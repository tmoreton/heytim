"""Keep large tool results readable and export data without model transcription."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import re
import uuid
from typing import Any

import boto3
from botocore.config import Config
from strands import tool
from strands.hooks import AfterToolCallEvent
from strands.plugins import hook
from strands.vended_plugins.context_offloader import ContextOffloader

from .artifacts import FILES_BUCKET_NAME, MAX_ARTIFACT_SOURCE_BYTES, _valid_prefix

MAX_RESULT_BYTES = 8_000_000
PAGE_CHARS = 3_200
RESULT_INSTRUCTIONS = (
    "Large tool results are saved in full. Use retrieve_offloaded_content with its "
    "nextOffset to read further; never refetch provider data just to work around a "
    "preview. For requested CSV/JSON exports, call export_tool_result with the saved "
    "references and a records_path such as /transactions. This exports the actual "
    "records directly without copying them into tool arguments. Include all provider "
    "pages exactly once; an offloaded reference contains only the page fetched. Use "
    "asset_key when the file should be retained in the workspace for later use."
)


class ResultStorage:
    """Opaque references bound to one authorized turn, retained across interrupts."""

    def __init__(self, prefix: str | None, *, client: Any = None):
        if prefix is not None and not _valid_prefix(prefix):
            raise ValueError("Tool result scope is invalid")
        self.prefix = (
            prefix.replace("/artifacts/", "/tool-results/") if prefix else None
        )
        self.scope = hashlib.sha256(
            (self.prefix or uuid.uuid4().hex).encode()
        ).hexdigest()[:24]
        self.client = (
            (
                client
                or boto3.client(
                    "s3",
                    config=Config(
                        connect_timeout=3,
                        read_timeout=20,
                        retries={"total_max_attempts": 3, "mode": "standard"},
                    ),
                )
            )
            if prefix
            else None
        )
        self._local: dict[str, tuple[bytes, str]] = {}

    async def store(
        self, key: str, content: bytes, content_type: str = "text/plain"
    ) -> str:
        if len(content) > MAX_RESULT_BYTES:
            raise ValueError("Tool result is too large to store")
        reference = f"result_{self.scope}_{uuid.uuid4().hex}"
        if self.client is None:
            self._local[reference] = (content, content_type)
        else:
            await asyncio.to_thread(
                self.client.put_object,
                Bucket=FILES_BUCKET_NAME,
                Key=f"{self.prefix}/{reference}",
                Body=content,
                ContentType=content_type,
            )
        return reference

    async def retrieve(self, reference: str) -> tuple[bytes, str]:
        if not isinstance(reference, str) or not re.fullmatch(
            rf"result_{self.scope}_[a-f0-9]{{32}}", reference
        ):
            raise ValueError("Tool result reference is outside this turn")
        if self.client is None:
            return self._local[reference]

        def read():
            response = self.client.get_object(
                Bucket=FILES_BUCKET_NAME,
                Key=f"{self.prefix}/{reference}",
            )
            with response["Body"] as stream:
                body = stream.read(MAX_RESULT_BYTES + 1)
            if len(body) > MAX_RESULT_BYTES:
                raise ValueError("Stored tool result is too large")
            return body, response.get("ContentType", "text/plain")

        return await asyncio.to_thread(read)


def _readable(text: str) -> str:
    try:
        value = json.loads(text)
    except ValueError, RecursionError:
        return text
    return (
        json.dumps(value, ensure_ascii=False, indent=2)
        if isinstance(value, (dict, list))
        else text
    )


def _records(value: Any, path: str) -> list[dict]:
    if path:
        if not path.startswith("/"):
            raise ValueError(
                "records_path must be a JSON pointer such as /transactions"
            )
        for part in path[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(value, dict) or key not in value:
                raise ValueError("records_path was not found in the saved result")
            value = value[key]
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("records_path must select an array of records")
    return value


def _csv_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    # Prevent provider-controlled strings from becoming spreadsheet formulas.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class ToolResultOffloader(ContextOffloader):
    def __init__(
        self, storage: ResultStorage, *, save_artifact=None, save_workspace=None
    ):
        self.results = storage
        self.save_artifact = save_artifact
        self.save_workspace = save_workspace
        super().__init__(storage=storage, max_result_tokens=1_500, preview_tokens=500)
        if save_artifact is None:
            self._tools = [
                item for item in self.tools if item.tool_name != "export_tool_result"
            ]

    @hook
    async def _handle_tool_result(self, event: AfterToolCallEvent) -> None:
        if event.tool_use.get("name") == "retrieve_offloaded_content":
            return
        summaries = []
        for block in event.result.get("content", []):
            try:
                value = (
                    block.get("json")
                    if "json" in block
                    else json.loads(block.get("text", ""))
                )
            except ValueError, TypeError, RecursionError:
                continue
            if isinstance(value, dict):
                summaries.append(
                    {
                        key: {"records": len(item)}
                        if isinstance(item, list)
                        else {"keys": list(item)[:10]}
                        if isinstance(item, dict)
                        else item[:120]
                        if isinstance(item, str)
                        else item
                        for key, item in list(value.items())[:20]
                    }
                )
        await super()._handle_tool_result(event)
        for block in event.result.get("content", []):
            text = block.get("text", "")
            if text.startswith("[Offloaded:"):
                summary = json.dumps(summaries, ensure_ascii=False)
                text = text.replace(
                    "pattern: regex or keyword", "pattern: literal text"
                ).replace(
                    "Retrieve full content (omit pattern/line_range) as a last resort.",
                    "Follow nextOffset to read subsequent pages without refetching provider data.",
                )
                block["text"] = (
                    text
                    + "\nSaved JSON structure: "
                    + summary[:1_200]
                    + "\n"
                    + RESULT_INSTRUCTIONS
                )

    @tool
    async def retrieve_offloaded_content(
        self,
        reference: str,
        offset: int = 0,
        max_chars: int = PAGE_CHARS,
        line_range: dict[str, int] | None = None,
        pattern: str | None = None,
        context_lines: int = 0,
    ) -> str | dict:
        """Read a bounded page of a saved result, including single-line JSON.

        Follow nextOffset until null, keeping any filters unchanged. JSON is formatted
        into lines first. Optional line_range has 1-based start/end; pattern is literal
        text (not regex), with context_lines surrounding each match. offset is a character
        offset within the selected text. For CSV/JSON exports use export_tool_result.
        """
        if (
            type(offset) is not int
            or offset < 0
            or type(max_chars) is not int
            or not 1 <= max_chars <= PAGE_CHARS
        ):
            raise ValueError(
                f"offset must be nonnegative and max_chars must be 1–{PAGE_CHARS}"
            )
        body, content_type = await self.results.retrieve(reference)
        if not (content_type.startswith("text/") or content_type == "application/json"):
            if offset or line_range or pattern or context_lines:
                raise ValueError("Binary results cannot be paged as text")
            return self._decode_full_content(body, content_type, reference)
        text = _readable(body.decode("utf-8"))
        if line_range is not None or pattern is not None:
            lines = text.splitlines()
            start, end = 1, len(lines)
            if line_range is not None:
                start, end = line_range.get("start"), line_range.get("end")
                if (
                    type(start) is not int
                    or type(end) is not int
                    or not 1 <= start <= end
                    or start > len(lines)
                ):
                    raise ValueError("line_range must select existing lines")
                end = min(end, len(lines))
            indices = set(range(start - 1, end))
            if pattern is not None:
                if not isinstance(pattern, str) or not pattern or len(pattern) > 200:
                    raise ValueError(
                        "pattern must be literal text up to 200 characters"
                    )
                if type(context_lines) is not int or not 0 <= context_lines <= 10:
                    raise ValueError("context_lines must be between 0 and 10")
                matches = [
                    i for i in indices if pattern.casefold() in lines[i].casefold()
                ]
                indices = {
                    j
                    for i in matches
                    for j in range(
                        max(start - 1, i - context_lines),
                        min(end, i + context_lines + 1),
                    )
                }
            text = "\n".join(f"{i + 1}| {lines[i]}" for i in sorted(indices))
        if offset > len(text):
            raise ValueError("offset exceeds the selected result length")
        end = min(len(text), offset + max_chars)
        while True:
            page = {
                "reference": reference,
                "text": text[offset:end],
                "offset": offset,
                "nextOffset": end if end < len(text) else None,
                "totalChars": len(text),
            }
            encoded = json.dumps(page, ensure_ascii=False)
            # The context manager counts the serialized tool envelope. Escaped
            # quotes, control characters, and Unicode can cost much more than
            # their raw character count; keep those pages below its threshold too.
            if len(json.dumps(encoded)) <= 4_000 or end - offset <= 1:
                return encoded
            end = offset + max(1, (end - offset) // 2)

    @tool
    async def export_tool_result(
        self,
        references: list[str],
        filename: str,
        records_path: str = "",
        asset_key: str = "",
    ) -> str:
        """Export saved JSON records directly to a requested CSV or JSON file.

        Pass each provider page's reference exactly once, in order. records_path is a
        JSON pointer to its rows, e.g. /transactions; empty means the root array.
        All fields are retained; nested values become JSON cells in CSV. asset_key
        saves a durable workspace file for later charts; reuse it for later revisions.
        This uses saved results and makes no provider calls. It does not fetch missing pages.
        """
        if (
            not isinstance(references, list)
            or not 1 <= len(references) <= 100
            or any(not isinstance(ref, str) for ref in references)
        ):
            raise ValueError("references must contain 1–100 saved result references")
        if len(set(references)) != len(references):
            raise ValueError("Each result reference must be included exactly once")
        if not isinstance(filename, str) or not filename.lower().endswith(
            (".csv", ".json")
        ):
            raise ValueError("filename must end in .csv or .json")
        rows = []
        total_bytes = 0
        for reference in references:
            body, content_type = await self.results.retrieve(reference)
            total_bytes += len(body)
            if total_bytes > MAX_RESULT_BYTES:
                raise ValueError("Selected results are too large for one export")
            if not (
                content_type.startswith("text/") or content_type == "application/json"
            ):
                raise ValueError("Only JSON records can be exported")
            rows.extend(_records(json.loads(body), records_path))
        if filename.lower().endswith(".json"):
            content = json.dumps(rows, ensure_ascii=False, indent=2)
        else:
            fields = list(dict.fromkeys(key for row in rows for key in row))
            if not fields:
                raise ValueError("No records are available to export as CSV")
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            writer.writerow([_csv_cell(key) for key in fields])
            writer.writerows(
                [_csv_cell(row.get(key)) for key in fields] for row in rows
            )
            content = output.getvalue()
        if len(content.encode("utf-8")) > MAX_ARTIFACT_SOURCE_BYTES:
            raise ValueError("Export is too large for one file; select fewer pages")
        if asset_key:
            if self.save_workspace is None:
                raise ValueError("Durable workspace storage is unavailable")
            result = await asyncio.to_thread(
                self.save_workspace, asset_key, filename, content
            )
        else:
            if self.save_artifact is None:
                raise ValueError("Artifact storage is unavailable")
            result = await asyncio.to_thread(self.save_artifact, filename, content)
        return f"Exported {len(rows)} records. {result}"
