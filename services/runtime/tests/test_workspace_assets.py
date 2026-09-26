from __future__ import annotations

import base64
import io
import uuid

import pytest
from PIL import Image, ImageDraw

from heytim_runtime import artifacts, workspace_assets


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def put_object(self, **request) -> None:
        self.objects[request["Key"]] = dict(request)

    def copy_object(self, **request) -> None:
        source = self.objects[request["CopySource"]["Key"]]
        self.objects[request["Key"]] = {
            **source,
            **request,
            "Body": source["Body"],
        }

    def get_object(self, **request) -> dict:
        stored = self.objects[request["Key"]]
        return {
            "Body": io.BytesIO(stored["Body"]),
            "ContentType": stored.get("ContentType"),
            "Metadata": stored.get("Metadata", {}),
        }


def _png_base64(label: str) -> str:
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 312, 172), outline="black", width=2)
    draw.text((24, 70), label, fill="black")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode()


CASES = [
    ("notes.txt", "Initial notes", "Revised notes"),
    ("plan.md", "# Initial plan\n\nFirst version.", "# Revised plan\n\nSecond version."),
    ("ledger.csv", "Date,Amount\n2026-09-01,10", "Date,Amount\n2026-09-01,12"),
    ("state.json", '{"cursor":"one"}', '{"cursor":"two"}'),
    ("view.html", "<h1>Initial</h1>", "<h1>Revised</h1>"),
    ("report.pdf", "# Initial report\n\nFirst version.", "# Revised report\n\nSecond version."),
    ("report.docx", "# Initial report\n\nFirst version.", "# Revised report\n\nSecond version."),
    ("ledger.xlsx", "Date,Amount\n2026-09-01,10", "Date,Amount\n2026-09-01,12"),
    ("briefing.pptx", "# Initial\n\n- First", "# Revised\n\n- Second"),
    ("chart.png", _png_base64("Initial"), _png_base64("Revised")),
]


def test_workspace_manifest_is_bound_to_the_current_bot(monkeypatch) -> None:
    actor = "a" * 64
    asset_id = "12345678-1234-4234-8234-123456789abc"
    item = {
        "id": asset_id,
        "assetKey": "finance/plaid-ledger",
        "name": "ledger.csv",
        "revision": 2,
        "objectKey": (
            f"users/{actor}/bots/finance/workspace/{asset_id}/revisions/2/ledger.csv"
        ),
    }
    monkeypatch.setattr(workspace_assets, "FILES_BUCKET_NAME", "files")

    parsed = workspace_assets.workspace_assets_from_payload(
        {"bot": {"id": "finance"}, "workspaceAssets": [item]}, actor
    )

    assert parsed[0]["assetKey"] == "finance/plaid-ledger"
    with pytest.raises(ValueError, match="metadata"):
        workspace_assets.workspace_assets_from_payload(
            {"bot": {"id": "another"}, "workspaceAssets": [item]}, actor
        )


@pytest.mark.parametrize(("filename", "initial", "revised"), CASES)
def test_each_workspace_format_stages_initial_and_follow_up_revisions(
    monkeypatch, filename: str, initial: str, revised: str
) -> None:
    actor = "a" * 64
    event = "12345678-1234-4234-8234-123456789abc"
    prefix = f"users/{actor}/bots/finance/artifacts/{event}"
    target = FakeS3()
    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    monkeypatch.setattr(workspace_assets, "FILES_BUCKET_NAME", "files")

    create = workspace_assets.workspace_asset_tools(prefix, [], client=target)[1]
    create("finance/monthly-ledger", filename, initial)
    first = next(
        item
        for key, item in target.objects.items()
        if key.startswith(prefix + "/") and "--" in key.rsplit("/", 1)[-1]
    )
    assert first["Metadata"]["workspace-asset-key"] == "finance/monthly-ledger"
    assert first["Metadata"]["workspace-expected-revision"] == "0"
    assert first["Body"]

    asset_id = str(uuid.uuid4())
    manifest = [{
        "id": asset_id,
        "assetKey": "finance/monthly-ledger",
        "name": filename,
        "revision": 1,
        "objectKey": (
            f"users/{actor}/bots/finance/workspace/{asset_id}/revisions/1/{filename}"
        ),
    }]
    revise = workspace_assets.workspace_asset_tools(prefix, manifest, client=target)[1]
    revise("finance/monthly-ledger", filename, revised)
    staged = [
        item
        for key, item in target.objects.items()
        if key.startswith(prefix + "/") and "--" in key.rsplit("/", 1)[-1]
    ]
    assert len(staged) == 2
    assert sorted(
        item["Metadata"]["workspace-expected-revision"] for item in staged
    ) == ["0", "1"]
    assert staged[0]["Metadata"]["workspace-asset-key"] == staged[1]["Metadata"][
        "workspace-asset-key"
    ]


def test_workspace_native_document_source_can_be_read_before_revision(
    monkeypatch,
) -> None:
    actor = "b" * 64
    event = "22345678-1234-4234-8234-123456789abc"
    prefix = f"users/{actor}/bots/writer/artifacts/{event}"
    asset_id = str(uuid.uuid4())
    source_key = (
        f"users/{actor}/bots/writer/workspace/{asset_id}/revisions/3/source.txt"
    )
    target = FakeS3()
    target.put_object(
        Bucket="files",
        Key=source_key,
        Body=b"# Existing report\n\nKeep this context.",
        ContentType="text/plain",
    )
    monkeypatch.setattr(artifacts, "FILES_BUCKET_NAME", "files")
    monkeypatch.setattr(workspace_assets, "FILES_BUCKET_NAME", "files")
    tools = workspace_assets.workspace_asset_tools(
        prefix,
        [{
            "id": asset_id,
            "assetKey": "reports/operating-review",
            "name": "Operating review.docx",
            "revision": 3,
            "objectKey": (
                f"users/{actor}/bots/writer/workspace/{asset_id}/revisions/3/"
                "Operating review.docx"
            ),
            "sourceObjectKey": source_key,
        }],
        client=target,
    )

    assert tools[0]("reports/operating-review").startswith("# Existing report")
