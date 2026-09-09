from __future__ import annotations

import json
from typing import Any

from pydantic import model_validator
from strands_tools.browser.models import BrowserInput

MAX_ENCODED_BROWSER_INPUT_CHARS = 64_000


class CompatibleBrowserInput(BrowserInput):
    """Preserve the browser action schema while accepting one JSON-encoded object."""

    @model_validator(mode="before")
    @classmethod
    def decode_object(cls, value: Any) -> Any:
        # Some providers encode nested tool objects as strings. Decode only the
        # declared browser input, once; never infer actions or repair broken JSON.
        if not isinstance(value, str):
            return value
        if len(value) > MAX_ENCODED_BROWSER_INPUT_CHARS:
            raise ValueError("browser_input exceeds the JSON input size limit")
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError) as exc:
            raise ValueError(
                "browser_input must be an object or valid JSON object"
            ) from exc
        if not isinstance(decoded, dict):
            raise TypeError("browser_input JSON must decode to an object")
        return decoded
