from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import codezip
from scripts.codezip import REQUIRED_ARCHIVE_PATHS, verify_archive, verify_source


def _archive(path: Path, *, forbidden: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("main.py", "")
        archive.writestr("group_context.py", "")
        archive.writestr("attachments-policy.json", "{}")
        for prefix in REQUIRED_ARCHIVE_PATHS:
            archive.writestr(f"{prefix}__init__.py", "")
        archive.writestr(
            "boto3-1.42.1.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: boto3\nVersion: 1.42.1\n",
        )
        if forbidden:
            archive.writestr(forbidden, "")


def test_production_source_boundary_is_allowlisted() -> None:
    verify_source()


def test_agentcore_package_is_dependency_complete_and_production_only() -> None:
    repository = Path(__file__).resolve().parents[3]
    runtime_name = "HeyTim"
    staging = repository / f"agentcore/{runtime_name}"
    archive = repository / f"agentcore/{runtime_name}.zip"
    preexisting = [path for path in (staging, archive) if path.exists()]
    if preexisting:
        pytest.fail(
            "Package integration test requires absent outputs and will not delete "
            f"preexisting paths: {preexisting}"
        )

    try:
        subprocess.run(
            [
                "agentcore",
                "package",
                "--directory",
                str(repository),
                "--runtime",
                runtime_name,
            ],
            cwd=repository,
            check=True,
            timeout=600,
        )
        verify_archive(archive)
    finally:
        if staging.is_dir():
            shutil.rmtree(staging)
        if archive.is_file():
            archive.unlink()


def test_archive_requires_locked_packages_and_production_content(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "runtime.zip"
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        'version = 1\n\n[[package]]\nname = "boto3"\nversion = "1.42.1"\n',
        encoding="utf-8",
    )
    _archive(archive_path)

    verify_archive(archive_path, lock_path)


def test_archive_rejects_development_content(tmp_path: Path) -> None:
    archive_path = tmp_path / "runtime.zip"
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text(
        'version = 1\n\n[[package]]\nname = "boto3"\nversion = "1.42.1"\n',
        encoding="utf-8",
    )
    _archive(archive_path, forbidden="tests/test_runtime.py")

    with pytest.raises(ValueError, match="Development artifacts"):
        verify_archive(archive_path, lock_path)


def test_generated_cleanup_is_previewed_before_it_is_applied(
    tmp_path: Path, monkeypatch
) -> None:
    generated_dir = tmp_path / "staging"
    generated_dir.mkdir()
    generated_file = tmp_path / "runtime.zip"
    generated_file.write_bytes(b"generated")
    monkeypatch.setattr(
        codezip,
        "GENERATED_PATHS",
        (generated_dir, generated_file),
    )

    assert codezip.clean_generated(apply=False) == [generated_dir, generated_file]
    assert generated_dir.exists() and generated_file.exists()

    assert codezip.clean_generated(apply=True) == [generated_dir, generated_file]
    assert not generated_dir.exists() and not generated_file.exists()
