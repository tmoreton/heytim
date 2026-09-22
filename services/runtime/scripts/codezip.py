from __future__ import annotations

import argparse
import email.parser
import shutil
import sys
import tomllib
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = RUNTIME_ROOT.parents[1]
SOURCE_ROOT = RUNTIME_ROOT / "runtime"
LOCK_PATH = RUNTIME_ROOT / "uv.lock"
GENERATED_PATHS = (
    REPOSITORY_ROOT / "agentcore/.cache",
    REPOSITORY_ROOT / "agentcore/cdk/cdk.out",
    REPOSITORY_ROOT / "agentcore/HeyTim",
    REPOSITORY_ROOT / "agentcore/HeyTim.zip",
)
SOURCE_TOP_LEVEL = {
    "attachments-policy.json",
    "heytim_runtime",
    "group_context.py",
    "main.py",
    "model",
}
REQUIRED_ARCHIVE_PATHS = {
    "bedrock_agentcore/",
    "boto3/",
    "docx/",
    "heytim_runtime/",
    "httpx/",
    "mcp/",
    "model/",
    "openpyxl/",
    "pptx/",
    "reportlab/",
    "strands/",
    "strands_harness/",
}
FORBIDDEN_TOP_LEVEL = {
    ".agentcore.json",
    ".gitignore",
    ".pytest_cache",
    ".ruff_cache",
    "README.md",
    "contracts",
    "evals",
    "pyproject.toml",
    "scripts",
    "tests",
    "uv.lock",
    "vendor",
}


def _normalize_distribution(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def verify_source(root: Path = SOURCE_ROOT) -> None:
    actual = {
        item.name
        for item in root.iterdir()
        if item.name not in {".DS_Store", "__pycache__", ".pytest_cache", ".ruff_cache"}
    }
    unexpected = actual - SOURCE_TOP_LEVEL
    missing = SOURCE_TOP_LEVEL - actual
    if missing or unexpected:
        raise ValueError(
            f"CodeZip source boundary mismatch; missing={sorted(missing)}, "
            f"unexpected={sorted(unexpected)}"
        )
    if not (RUNTIME_ROOT / "pyproject.toml").is_file() or not LOCK_PATH.is_file():
        raise ValueError("CodeZip source must have a parent pyproject.toml and uv.lock")


def _distribution_metadata(
    names: list[str], reader: Callable[[str], bytes]
) -> dict[str, bytes]:
    return {
        name: reader(name) for name in names if name.endswith(".dist-info/METADATA")
    }


def _archive_members(path: Path) -> tuple[list[str], dict[str, bytes]]:
    if path.is_dir():
        names = [
            item.relative_to(path).as_posix()
            for item in path.rglob("*")
            if item.is_file()
        ]
        return names, _distribution_metadata(
            names, lambda name: (path / name).read_bytes()
        )
    with zipfile.ZipFile(path) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        return names, _distribution_metadata(names, archive.read)


def _locked_distributions(lock_path: Path = LOCK_PATH) -> set[tuple[str, str]]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    return {
        (_normalize_distribution(package["name"]), package["version"])
        for package in lock.get("package", [])
    }


def _packaged_distributions(metadata: dict[str, bytes]) -> set[tuple[str, str]]:
    parser = email.parser.BytesParser()
    packages = set()
    for content in metadata.values():
        document = parser.parsebytes(content)
        name = document.get("Name")
        version = document.get("Version")
        if name and version:
            packages.add((_normalize_distribution(name), version))
    return packages


def verify_archive(path: Path, lock_path: Path = LOCK_PATH) -> None:
    names, metadata = _archive_members(path)
    top_level = {PurePosixPath(name).parts[0] for name in names if name}
    forbidden = sorted(top_level & FORBIDDEN_TOP_LEVEL)
    if forbidden:
        raise ValueError(f"Development artifacts leaked into CodeZip: {forbidden}")
    caches = sorted(
        name
        for name in names
        if any(
            part in {"__pycache__", ".pytest_cache", ".ruff_cache"}
            for part in PurePosixPath(name).parts
        )
    )
    if caches:
        raise ValueError(f"Cache artifacts leaked into CodeZip: {caches[:10]}")

    missing = sorted(
        prefix
        for prefix in REQUIRED_ARCHIVE_PATHS
        if not any(name.startswith(prefix) for name in names)
    )
    for filename in ("main.py", "group_context.py", "attachments-policy.json"):
        if filename not in names:
            missing.append(filename)
    if missing:
        raise ValueError(f"Required runtime content is missing from CodeZip: {missing}")

    locked = _locked_distributions(lock_path)
    packaged = _packaged_distributions(metadata)
    unlocked = sorted(packaged - locked)
    if unlocked:
        raise ValueError(
            f"CodeZip contains distributions absent from uv.lock: {unlocked}"
        )


def generated_paths() -> Iterable[Path]:
    return (path for path in GENERATED_PATHS if path.exists())


def clean_generated(*, apply: bool) -> list[Path]:
    paths = list(generated_paths())
    if apply:
        for path in paths:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    return paths


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify and clean AgentCore CodeZip output"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("source", help="verify the production-only source boundary")
    archive = subparsers.add_parser(
        "archive", help="verify a packaged zip or staging directory"
    )
    archive.add_argument("path", type=Path)
    clean = subparsers.add_parser(
        "clean", help="list generated package output; remove only with --apply"
    )
    clean.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "source":
            verify_source()
            print(f"CodeZip source boundary verified: {SOURCE_ROOT}")
        elif args.command == "archive":
            verify_archive(args.path)
            print(f"CodeZip archive verified against uv.lock: {args.path}")
        else:
            paths = clean_generated(apply=args.apply)
            action = "Removed" if args.apply else "Would remove"
            for path in paths:
                print(f"{action}: {path}")
            if not paths:
                print("No generated package output found")
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"CodeZip check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
