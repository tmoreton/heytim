from __future__ import annotations

import json
from typing import Any

from pydantic import model_validator
from strands_tools.code_interpreter.models import CodeInterpreterInput

MAX_ENCODED_CODE_INTERPRETER_INPUT_CHARS = 256_000


class CompatibleCodeInterpreterInput(CodeInterpreterInput):
    """Keep the typed schema while accepting one provider-encoded JSON object."""

    @model_validator(mode="before")
    @classmethod
    def decode_object(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if len(value) > MAX_ENCODED_CODE_INTERPRETER_INPUT_CHARS:
            raise ValueError("code_interpreter_input exceeds the JSON input size limit")
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError) as exc:
            raise ValueError(
                "code_interpreter_input must be an object or valid JSON object"
            ) from exc
        if not isinstance(decoded, dict):
            raise TypeError("code_interpreter_input JSON must decode to an object")
        return decoded
