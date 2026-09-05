from __future__ import annotations

from typing import Any

from strands.telemetry import tracer as tracer_module


class PrivateTracer(tracer_module.Tracer):
    """Keep operational spans while excluding prompts from agent metadata."""

    def start_agent_span(self, *args: Any, **kwargs: Any):
        # Strands 1.54 treats system_prompt as a generic attribute here, outside
        # its sensitive-field redaction policy. The model span still records a
        # redacted system-instructions event for correlation.
        kwargs.pop("system_prompt", None)
        return super().start_agent_span(*args, **kwargs)


def install_private_tracer() -> None:
    """Install one process-wide tracer used by agents and event-loop helpers."""
    if isinstance(tracer_module._tracer_instance, PrivateTracer):
        return
    tracer_module._tracer_instance = PrivateTracer()
