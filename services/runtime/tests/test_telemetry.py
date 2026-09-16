from __future__ import annotations

from unittest.mock import patch

from strands.telemetry import tracer as tracer_module

from frogbot_runtime.telemetry import PrivateTracer, install_private_tracer


def test_private_tracer_does_not_forward_system_prompt_metadata() -> None:
    tracer = object.__new__(PrivateTracer)
    with patch.object(
        tracer_module.Tracer, "start_agent_span", return_value="span"
    ) as start:
        result = tracer.start_agent_span(
            messages=[], agent_name="FroggyBot", system_prompt="private prompt"
        )

    assert result == "span"
    assert "system_prompt" not in start.call_args.kwargs


def test_private_tracer_is_installed_process_wide() -> None:
    previous = tracer_module._tracer_instance
    try:
        tracer_module._tracer_instance = None
        install_private_tracer()
        assert isinstance(tracer_module._tracer_instance, PrivateTracer)
    finally:
        tracer_module._tracer_instance = previous
