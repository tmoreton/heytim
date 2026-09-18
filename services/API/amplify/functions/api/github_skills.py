"""Read public GitHub SKILL.md files for a review-before-copy workflow."""

from __future__ import annotations

import base64
import binascii
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from shared.client_contract import (
    SKILL_DESCRIPTION_MAX_LENGTH,
    SKILL_INSTRUCTIONS_MAX_LENGTH,
    SKILL_NAME_MAX_LENGTH,
)

from .support import ApiError

_OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}[A-Za-z0-9])?\Z")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}\Z")
_REF = re.compile(r"[A-Za-z0-9._/-]{1,160}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_MAX_INDEX_BYTES = 3_000_000
_MAX_FILE_BYTES = 35_000
_MAX_RESULTS = 100


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _request, _fp, _code, _msg, _headers, _newurl):
        return None


def _github_json(path: str, *, limit: int = _MAX_INDEX_BYTES) -> Any:
    # URLs are assembled only from validated GitHub owner, repository, ref, path,
    # or blob SHA fields. Redirects are disabled so GitHub cannot hand us a new host.
    url = f"https://api.github.com{path}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "HeyTim-Skill-Importer",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=8) as response:  # nosec B310
            content = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ApiError(404, "GitHub repository or skill file was not found") from exc
        if exc.code in {403, 429}:
            raise ApiError(503, "GitHub is limiting requests. Try again shortly") from exc
        raise ApiError(502, "Could not read the GitHub repository") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(502, "Could not reach GitHub") from exc
    if len(content) > limit:
        raise ApiError(400, "This repository is too large. Paste a direct SKILL.md link")
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(502, "GitHub returned an invalid response") from exc


def _safe_path(path: str) -> str:
    parts = path.split("/")
    if (
        not path
        or len(path) > 500
        or any(part in {"", ".", ".."} for part in parts)
        or any(not re.fullmatch(r"[A-Za-z0-9._@+ -]+", part) for part in parts)
    ):
        raise ApiError(400, "The GitHub skill path is invalid")
    return path


def _repository(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 210:
        raise ApiError(400, "The GitHub repository is invalid")
    parts = value.split("/")
    if (
        len(parts) != 2
        or not _OWNER.fullmatch(parts[0])
        or not _REPO.fullmatch(parts[1])
        or parts[1] in {".", ".."}
    ):
        raise ApiError(400, "The GitHub repository is invalid")
    return parts[0], parts[1]


def _valid_ref(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_REF.fullmatch(value))
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _parse_url(value: Any) -> tuple[str, str, str | None, str | None, str | None]:
    if not isinstance(value, str) or len(value) > 800:
        raise ApiError(400, "Enter a GitHub repository or SKILL.md URL")
    parsed = urllib.parse.urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or "%" in parsed.path
    ):
        raise ApiError(400, "Use a plain https://github.com repository or SKILL.md URL")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        raise ApiError(400, "Enter a GitHub repository URL")
    owner, repo = _repository("/".join(parts[:2]))
    if len(parts) == 2:
        return owner, repo, None, None, None
    if len(parts) < 4 or parts[2] not in {"tree", "blob"} or not _valid_ref(parts[3]):
        raise ApiError(400, "Use a GitHub repository, folder, or SKILL.md link")
    kind, reference = parts[2:4]
    path = _safe_path("/".join(parts[4:])) if len(parts) > 4 else None
    if kind == "blob" and (not path or path.split("/")[-1] != "SKILL.md"):
        raise ApiError(400, "The GitHub link must point to SKILL.md")
    return owner, repo, reference, kind, path


def _source_url(owner: str, repo: str, reference: str, path: str) -> str:
    return (
        f"https://github.com/{owner}/{repo}/blob/"
        f"{urllib.parse.quote(reference, safe='/')}/{urllib.parse.quote(path, safe='/')}"
    )


def scan_github_skills(value: dict) -> dict:
    owner, repo, reference, kind, selected_path = _parse_url(value.get("url"))
    api_root = f"/repos/{owner}/{repo}"
    if reference is None:
        metadata = _github_json(api_root, limit=100_000)
        reference = metadata.get("default_branch") if isinstance(metadata, dict) else None
        if not _valid_ref(reference):
            raise ApiError(502, "GitHub did not provide a valid default branch")
    if kind == "blob":
        path = _safe_path(selected_path or "")
        file = _github_json(
            f"{api_root}/contents/{urllib.parse.quote(path, safe='/')}"
            f"?ref={urllib.parse.quote(reference, safe='')}",
            limit=100_000,
        )
        if not isinstance(file, dict) or file.get("type") != "file":
            raise ApiError(400, "This link does not point to a skill file")
        candidates = [{"path": path, "sha": file.get("sha"), "size": file.get("size")}]
    else:
        tree = _github_json(
            f"{api_root}/git/trees/{urllib.parse.quote(reference, safe='')}?recursive=1"
        )
        if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
            raise ApiError(502, "GitHub did not provide a file list")
        if tree.get("truncated"):
            raise ApiError(400, "This repository has too many files. Paste a direct SKILL.md link")
        candidates = [item for item in tree["tree"] if isinstance(item, dict)]
    prefix = selected_path.rstrip("/") + "/" if kind == "tree" and selected_path else ""
    results = []
    for item in candidates:
        path, sha, size = item.get("path"), item.get("sha"), item.get("size")
        if (
            item.get("type") not in {None, "blob"}
            or not isinstance(path, str)
            or not path.startswith(prefix)
            or path.split("/")[-1] != "SKILL.md"
            or not isinstance(sha, str)
            or not _SHA.fullmatch(sha)
            or not isinstance(size, int)
            or size > _MAX_FILE_BYTES
            or size <= 0
        ):
            continue
        results.append(
            {
                "name": path.split("/")[-2] if "/" in path else repo,
                "path": path,
                "blobSha": sha,
                "sourceUrl": _source_url(owner, repo, reference, path),
            }
        )
    results.sort(key=lambda item: item["path"].lower())
    if not results:
        raise ApiError(404, "No supported SKILL.md files were found at this link")
    return {
        "repository": f"{owner}/{repo}",
        "reference": reference,
        "skills": results[:_MAX_RESULTS],
        "moreAvailable": len(results) > _MAX_RESULTS,
    }


def _frontmatter(text: str, path: str) -> tuple[str, str, str, list[str]]:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ApiError(400, "SKILL.md needs name and description frontmatter")
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() == "---")
    except StopIteration as exc:
        raise ApiError(400, "SKILL.md frontmatter is incomplete") from exc
    fields: dict[str, str] = {}
    current: str | None = None
    block_scalar = False
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if match:
            current = match.group(1)
            fields[current] = match.group(2).strip()
            block_scalar = fields[current] in {">", ">-", "|", "|-"}
        elif current and block_scalar and line.startswith((" ", "\t")):
            fields[current] += " " + line.strip()
    def scalar(key: str) -> str:
        raw = fields.get(key, "").strip()
        if raw.startswith((">", "|")) and " " in raw:
            raw = raw.split(" ", 1)[1]
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
            raw = raw[1:-1]
        return raw.strip()
    name, description = scalar("name"), scalar("description")
    instructions = "\n".join(lines[end + 1 :]).strip()
    if not name or len(name) > SKILL_NAME_MAX_LENGTH:
        raise ApiError(400, f"{path}: skill name is missing or too long")
    if not description or len(description) > SKILL_DESCRIPTION_MAX_LENGTH:
        raise ApiError(400, f"{path}: skill description is missing or too long")
    if not instructions or len(instructions) > SKILL_INSTRUCTIONS_MAX_LENGTH:
        raise ApiError(400, f"{path}: skill instructions are missing or too long")
    warnings = []
    if re.search(r"\]\((?!https?://|mailto:|#)[^)]+\)", instructions, re.IGNORECASE) or re.search(
        r"\b(?:scripts|references|assets)/[\w./-]+", instructions
    ):
        warnings.append("This skill refers to other files. Only SKILL.md is copied; adapt those steps before using it.")
    if scalar("disable-model-invocation").lower() == "true":
        warnings.append("The source marks this for manual use. Review when your bot should activate it.")
    return name, description, instructions, warnings


def preview_github_skill(value: dict) -> dict:
    owner, repo = _repository(value.get("repository"))
    path = _safe_path(value.get("path")) if isinstance(value.get("path"), str) else ""
    sha = value.get("blobSha")
    reference = value.get("reference")
    if path.split("/")[-1] != "SKILL.md" or not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ApiError(400, "Select a valid SKILL.md file")
    if not _valid_ref(reference):
        raise ApiError(400, "The GitHub reference is invalid")
    blob = _github_json(f"/repos/{owner}/{repo}/git/blobs/{sha}", limit=100_000)
    if (
        not isinstance(blob, dict)
        or blob.get("encoding") != "base64"
        or blob.get("sha") != sha
        or not isinstance(blob.get("content"), str)
        or not isinstance(blob.get("size"), int)
        or blob["size"] > _MAX_FILE_BYTES
    ):
        raise ApiError(400, "This skill file cannot be imported")
    try:
        data = base64.b64decode(
            re.sub(r"[\r\n\t ]", "", blob["content"]), validate=True
        )
        if len(data) > _MAX_FILE_BYTES or len(data) != blob["size"]:
            raise ValueError("file size mismatch")
        text = data.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ApiError(400, "This skill file is not valid UTF-8 text") from exc
    name, description, instructions, warnings = _frontmatter(text, path)
    return {
        "name": name,
        "description": description,
        "instructions": instructions,
        "sourceUrl": _source_url(owner, repo, reference, path),
        "warnings": warnings,
    }
