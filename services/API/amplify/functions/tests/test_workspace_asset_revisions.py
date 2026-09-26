from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from worker_test_case import WorkerTestCase


class ConditionalCheckFailedException(Exception):
    pass


class RevisionTable:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}
        self.meta = SimpleNamespace(
            client=SimpleNamespace(
                exceptions=SimpleNamespace(
                    ConditionalCheckFailedException=ConditionalCheckFailedException
                )
            )
        )

    def get_item(self, *, Key: dict, **_kwargs) -> dict:
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def put_item(self, *, Item: dict, ConditionExpression=None, **_kwargs) -> None:
        key = (Item["pk"], Item["sk"])
        if ConditionExpression is not None and key in self.items:
            raise ConditionalCheckFailedException
        self.items[key] = dict(Item)

    def delete_item(self, *, Key: dict, **_kwargs) -> None:
        self.items.pop((Key["pk"], Key["sk"]), None)

    def update_item(self, **kwargs) -> None:
        key = (kwargs["Key"]["pk"], kwargs["Key"]["sk"])
        values = kwargs["ExpressionAttributeValues"]
        if key[1].startswith("WORKSPACE#"):
            item = self.items.get(key, {"pk": key[0], "sk": key[1]})
            item["entity"] = "WORKSPACE"
            item["fileCount"] = item.get("fileCount", 0) + values[":files"]
            item["totalBytes"] = item.get("totalBytes", 0) + values[":bytes"]
            if (
                item["fileCount"] < 0
                or item["fileCount"] > 50
                or item["totalBytes"] < 0
                or item["totalBytes"] > 100_000_000
            ):
                raise ConditionalCheckFailedException
            self.items[key] = item
            return
        item = self.items.get(key)
        if item is None or item.get("revision") != values[":next"] - 1:
            raise ConditionalCheckFailedException
        item.update({
            "workspaceVersion": values[":workspaceVersion"],
            "objectKey": values[":objectKey"],
            "name": values[":name"],
            "size": values[":size"],
            "kind": values[":kind"],
            "format": values[":format"],
            "contentType": values[":contentType"],
            "checksum": values[":checksum"],
            "revision": values[":next"],
            "updatedAt": values[":updatedAt"],
            "sourceObjectKey": values[":sourceObjectKey"],
        })
        self.items[key] = item


class RevisionS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def stage(
        self,
        prefix: str,
        filename: str,
        body: bytes,
        asset_key: str,
        expected_revision: int,
        *,
        source: bytes | None = None,
    ) -> None:
        file_id = str(uuid.uuid4())
        object_key = f"{prefix}/{file_id}--{filename}"
        metadata = {
            "heytim-purpose": "workspace-asset",
            "workspace-asset-key": asset_key,
            "workspace-expected-revision": str(expected_revision),
            "workspace-sha256": hashlib.sha256(body).hexdigest(),
        }
        if source is not None:
            source_key = f"{prefix}/workspace-sources/{file_id}.source"
            self.objects[source_key] = {
                "Key": source_key,
                "Body": source,
                "Size": len(source),
                "Metadata": {},
                "LastModified": datetime.now(UTC),
            }
            metadata["workspace-source-key"] = source_key
        self.objects[object_key] = {
            "Key": object_key,
            "Body": body,
            "Size": len(body),
            "Metadata": metadata,
            "LastModified": datetime.now(UTC),
        }

    def list_objects_v2(self, **request) -> dict:
        contents = [
            {
                "Key": key,
                "Size": item["Size"],
                "LastModified": item["LastModified"],
            }
            for key, item in sorted(self.objects.items())
            if key.startswith(request["Prefix"])
        ]
        return {"Contents": contents, "IsTruncated": False}

    def head_object(self, **request) -> dict:
        item = self.objects[request["Key"]]
        return {"Metadata": item.get("Metadata", {})}

    def get_object(self, **request) -> dict:
        return {"Body": io.BytesIO(self.objects[request["Key"]]["Body"])}

    def copy_object(self, **request) -> None:
        source = self.objects[request["CopySource"]["Key"]]
        self.objects[request["Key"]] = {
            "Key": request["Key"],
            "Body": source["Body"],
            "Size": len(source["Body"]),
            "Metadata": request.get("Metadata", {}),
            "LastModified": datetime.now(UTC),
        }

    def delete_object(self, **request) -> None:
        self.objects.pop(request["Key"], None)


class WorkspaceAssetRevisionTests(WorkerTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.revision_table = RevisionTable()
        self.revision_s3 = RevisionS3()
        self.table_patch = patch.object(
            self.artifacts, "table", self.revision_table
        ).start()
        self.s3_patch = patch.object(self.artifacts, "s3", self.revision_s3).start()
        self.addCleanup(patch.stopall)

    def test_each_supported_type_creates_then_revises_one_logical_asset(self) -> None:
        cases = {
            "notes.txt": (b"initial", b"revised"),
            "plan.md": (b"# Initial", b"# Revised"),
            "ledger.csv": (b"Amount\n10", b"Amount\n12"),
            "state.json": (b'{"v":1}', b'{"v":2}'),
            "view.html": (b"<p>one</p>", b"<p>two</p>"),
            "report.pdf": (b"%PDF-initial", b"%PDF-revised"),
            "report.docx": (b"PK-docx-initial", b"PK-docx-revised"),
            "ledger.xlsx": (b"PK-xlsx-initial", b"PK-xlsx-revised"),
            "briefing.pptx": (b"PK-pptx-initial", b"PK-pptx-revised"),
            "chart.png": (b"\x89PNG\r\n\x1ainitial", b"\x89PNG\r\n\x1arevised"),
        }
        for filename, (initial, revised) in cases.items():
            with self.subTest(filename=filename):
                self.revision_table.items.clear()
                self.revision_s3.objects.clear()
                asset_key = "recurring/" + filename.rsplit(".", 1)[-1]
                event_one = "12345678-1234-4234-8234-123456789abc"
                prefix_one = (
                    f"users/{'a' * 64}/bots/finance/artifacts/{event_one}"
                )
                self.revision_s3.stage(
                    prefix_one, filename, initial, asset_key, 0
                )
                first = self.artifacts._collect_artifacts(
                    prefix_one, "USER#owner", {"botId": "finance"}
                )

                event_two = "22345678-1234-4234-8234-123456789abc"
                prefix_two = (
                    f"users/{'a' * 64}/bots/finance/artifacts/{event_two}"
                )
                self.revision_s3.stage(
                    prefix_two, filename, revised, asset_key, 1
                )
                second = self.artifacts._collect_artifacts(
                    prefix_two, "USER#owner", {"botId": "finance"}
                )

                self.assertEqual(first[0]["id"], second[0]["id"])
                self.assertEqual(second[0]["revision"], 2)
                workspace_items = [
                    item
                    for item in self.revision_table.items.values()
                    if item.get("entity") == "WORKSPACE_FILE"
                ]
                aliases = [
                    item
                    for item in self.revision_table.items.values()
                    if item.get("entity") == "FILE"
                    and item.get("source") == "workspace"
                ]
                self.assertEqual(len(workspace_items), 1)
                self.assertEqual(len(aliases), 1)
                self.assertEqual(workspace_items[0]["revision"], 2)
                revision_keys = [
                    key
                    for key in self.revision_s3.objects
                    if "/workspace/" in key and key.endswith(filename)
                ]
                self.assertEqual(len(revision_keys), 2)

    def test_native_source_is_promoted_with_the_same_revision(self) -> None:
        event = "32345678-1234-4234-8234-123456789abc"
        prefix = f"users/{'a' * 64}/bots/writer/artifacts/{event}"
        self.revision_s3.stage(
            prefix,
            "report.docx",
            b"PK-document",
            "reports/monthly",
            0,
            source=b"# Monthly report\n\nEditable source.",
        )

        result = self.artifacts._collect_artifacts(
            prefix, "USER#owner", {"botId": "writer"}
        )[0]

        self.assertEqual(result["revision"], 1)
        source_key = result["sourceObjectKey"]
        self.assertIn("/revisions/1/", source_key)
        self.assertTrue(source_key.endswith("/source.txt"))
        self.assertEqual(
            self.revision_s3.objects[source_key]["Body"],
            b"# Monthly report\n\nEditable source.",
        )

    def test_retry_with_identical_content_is_idempotent(self) -> None:
        body = b"Date,Amount\n2026-09-25,42"
        prefixes = [
            f"users/{'a' * 64}/bots/finance/artifacts/42345678-1234-4234-8234-123456789abc",
            f"users/{'a' * 64}/bots/finance/artifacts/52345678-1234-4234-8234-123456789abc",
        ]
        self.revision_s3.stage(
            prefixes[0], "ledger.csv", body, "finance/ledger", 0
        )
        first = self.artifacts._collect_artifacts(
            prefixes[0], "USER#owner", {"botId": "finance"}
        )[0]
        self.revision_s3.stage(
            prefixes[1], "ledger.csv", body, "finance/ledger", 0
        )
        retry = self.artifacts._collect_artifacts(
            prefixes[1], "USER#owner", {"botId": "finance"}
        )[0]

        self.assertEqual(retry["id"], first["id"])
        self.assertEqual(retry["revision"], 1)
        self.assertEqual(
            len([
                item
                for item in self.revision_table.items.values()
                if item.get("entity") == "WORKSPACE_FILE"
            ]),
            1,
        )
