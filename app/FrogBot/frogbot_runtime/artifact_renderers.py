from __future__ import annotations

from collections.abc import Callable

from .document_renderers import render_docx, render_pdf
from .presentation_renderer import render_pptx
from .spreadsheet_renderer import render_xlsx

Renderer = Callable[[str, str], bytes]

RENDERERS: dict[str, Renderer] = {
    ".pdf": render_pdf,
    ".docx": render_docx,
    ".xlsx": render_xlsx,
    ".pptx": render_pptx,
}


def render_native_artifact(filename: str, extension: str, content: str) -> bytes:
    renderer = RENDERERS.get(extension)
    if renderer is None:
        raise ValueError(f"No native renderer is configured for {extension}")
    return renderer(filename, content)
