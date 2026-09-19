from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MAX_SOURCE_CHARS = 500_000


@dataclass(frozen=True)
class ContentBlock:
    kind: str
    text: str
    level: int = 0


def validate_content(content: str) -> str:
    if not isinstance(content, str):
        raise TypeError("content must be a string")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized or len(normalized) > MAX_SOURCE_CHARS:
        raise ValueError(f"content must be between 1 and {MAX_SOURCE_CHARS} characters")
    return normalized


def markdown_blocks(content: str) -> list[ContentBlock]:
    lines = validate_content(content).split("\n")
    blocks: list[ContentBlock] = []
    paragraph: list[str] = []
    code: list[str] = []
    in_code = False

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(ContentBlock("paragraph", " ".join(paragraph)))
            paragraph.clear()

    def flush_code() -> None:
        if code:
            blocks.append(ContentBlock("code", "\n".join(code)))
            code.clear()

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.lstrip().startswith("```"):
            if in_code:
                flush_code()
                in_code = False
            else:
                flush_paragraph()
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue
        if not line.strip():
            flush_paragraph()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            blocks.append(
                ContentBlock("heading", heading.group(2).strip(), len(heading.group(1)))
            )
            continue
        bullet = re.match(r"^\s*[-*+]\s+(.+)$", line)
        if bullet:
            flush_paragraph()
            blocks.append(ContentBlock("bullet", bullet.group(1).strip()))
            continue
        numbered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if numbered:
            flush_paragraph()
            blocks.append(ContentBlock("number", numbered.group(1).strip()))
            continue
        paragraph.append(line.strip())

    flush_paragraph()
    flush_code()
    return blocks


def document_title(filename: str) -> str:
    title = Path(filename).stem.replace("_", " ").replace("-", " ").strip()
    return title or "HeyTim document"
