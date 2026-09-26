from __future__ import annotations

import asyncio
import json

import pytest
from strands import tool
from strands.session import SnapshotSessionManager
from strands.storage import InMemoryStorage
from strands_harness import create_harness
from test_model import FakeModel, SequencedFakeModel

from heytim_runtime.streaming import stream_with_token_recovery
from model.load import (
    PreResponseFallbackModel,
    ResilientOpenRouterModel,
    increase_output_budget,
)
from model.usage import (
    LONG_RUN_CALL_LIMITS,
    ProviderCallLimitExceeded,
    ProviderCallLimits,
    UsageAccumulator,
    UsageTrackingModel,
)


def test_output_recovery_grows_with_a_ceiling_and_preserves_each_route_settings():
    primary = FakeModel("primary", [])
    fallback = FakeModel("fallback", [])
    primary.config["params"] = {
        "max_tokens": 4_096,
        "extra_body": {"reasoning": {"effort": "high"}},
    }
    fallback.config["params"] = {
        "max_tokens": 4_096,
        "extra_body": {"reasoning": {"effort": "low"}},
    }
    model = PreResponseFallbackModel(
        ResilientOpenRouterModel(primary),
        ResilientOpenRouterModel(fallback),
        fallback_name="fallback",
    )
    assert increase_output_budget(model)
    assert primary.config["params"]["max_tokens"] == 8_192
    assert increase_output_budget(model)
    assert primary.config["params"]["max_tokens"] == 16_384
    assert not increase_output_budget(model)
    assert fallback.config["params"]["extra_body"]["reasoning"]["effort"] == "low"


def test_reasoning_only_truncation_recovers_before_emitting_an_empty_answer():
    truncated = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"reasoningContent": {"text": "thinking"}}}},
        {"messageStop": {"stopReason": "max_tokens"}},
    ]
    complete = [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockDelta": {"delta": {"text": "Completed."}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    delegate = SequencedFakeModel([truncated, complete])
    delegate.config["params"] = {"max_tokens": 4_096}
    usage = UsageAccumulator()
    model = ResilientOpenRouterModel(
        UsageTrackingModel(delegate, usage, provider="test", model_id="test")
    )

    async def run():
        return [event async for event in model.stream([])]

    assert asyncio.run(run()) == complete
    assert delegate.config["params"]["max_tokens"] == 8_192
    assert usage.snapshot()["totals"]["modelDispatchCount"] == 2


def test_checkpoint_round_trip_preserves_completed_tool_receipts():
    async def run():
        storage = InMemoryStorage()
        session = SnapshotSessionManager(
            "turn", storage=storage, save_latest_on="trigger"
        )
        agent = create_harness(
            model=FakeModel("test", []),
            tools=[],
            builtin_tools=[],
            builtin_plugins=[],
            skills=False,
            memory=False,
            context_manager="auto",
            session=False,
            session_manager=session,
            agent_id="worker",
            caching=False,
            callback_handler=None,
        )
        history = [
            {"role": "user", "content": [{"text": "Do two actions"}]},
            {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "done", "name": "action", "input": {}}}
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "done",
                            "status": "success",
                            "content": [{"text": "receipt-123"}],
                        }
                    }
                ],
            },
        ]
        agent.messages[:] = history
        await session.save_snapshot(agent, is_latest=True)
        restored = create_harness(
            model=FakeModel("test", []),
            tools=[],
            builtin_tools=[],
            builtin_plugins=[],
            skills=False,
            memory=False,
            context_manager="auto",
            session=False,
            session_manager=SnapshotSessionManager(
                "turn", storage=storage, save_latest_on="trigger"
            ),
            agent_id="worker",
            caching=False,
            callback_handler=None,
        )
        assert restored.messages == history

    asyncio.run(run())


def test_truncated_tool_arguments_are_retried_before_any_action_executes():
    completed = []

    @tool
    def record_action(value: str = "default") -> str:
        """Record an external action using the supplied value."""
        completed.append(value)
        return "Action completed"

    def tool_response(raw_input, stop_reason):
        return [
            {"messageStart": {"role": "assistant"}},
            {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {"toolUseId": "action-1", "name": "record_action"}
                    },
                }
            },
            {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": raw_input}},
                }
            },
            {"contentBlockStop": {"contentBlockIndex": 0}},
            {"messageStop": {"stopReason": stop_reason}},
        ]

    delegate = SequencedFakeModel(
        [
            tool_response('{"value":"unfinished', "max_tokens"),
            tool_response('{"value":"intended"}', "tool_use"),
            [
                {"messageStart": {"role": "assistant"}},
                {
                    "contentBlockDelta": {
                        "contentBlockIndex": 0,
                        "delta": {"text": "Completed."},
                    }
                },
                {"messageStop": {"stopReason": "end_turn"}},
            ],
        ]
    )
    delegate.config["params"] = {"max_tokens": 4_096}
    agent = create_harness(
        model=ResilientOpenRouterModel(delegate),
        tools=[record_action],
        builtin_tools=[],
        builtin_plugins=[],
        skills=False,
        memory=False,
        context_manager="auto",
        session=False,
        caching=False,
        callback_handler=None,
    )

    async def run():
        return [
            event
            async for event in stream_with_token_recovery(agent, "Record the action")
        ]

    events = asyncio.run(run())
    tool_inputs = [
        event["event"]["contentBlockDelta"]["delta"]["toolUse"]["input"]
        for event in events
        if "toolUse"
        in event.get("event", {}).get("contentBlockDelta", {}).get("delta", {})
    ]
    assert tool_inputs == ['{"value":"intended"}']
    assert completed == ["intended"]
    assert delegate.calls == 3
    assert delegate.config["params"]["max_tokens"] == 8_192


def test_long_run_budget_is_cumulative_and_does_not_relax_provider_subcaps():
    usage = UsageAccumulator(limits=LONG_RUN_CALL_LIMITS)
    for _ in range(LONG_RUN_CALL_LIMITS.provider_tool_calls):
        usage.observe_tool("provider", "read")
    with pytest.raises(ProviderCallLimitExceeded):
        usage.observe_tool("provider", "read")
    assert (
        usage.snapshot()["totals"]["toolCallCount"]
        == LONG_RUN_CALL_LIMITS.provider_tool_calls
    )

    images = UsageAccumulator(limits=LONG_RUN_CALL_LIMITS)
    for _ in range(LONG_RUN_CALL_LIMITS.image_calls):
        images.observe_tool("openrouter", "generate_image")
    with pytest.raises(ProviderCallLimitExceeded, match="image-generation"):
        images.observe_tool("openrouter", "generate_image")

    small = UsageAccumulator(
        limits=ProviderCallLimits(model_calls=2, provider_tool_calls=2, image_calls=1)
    )
    for _ in range(2):
        small.reserve_model("provider", "model")
    with pytest.raises(ProviderCallLimitExceeded, match="model-call"):
        small.reserve_model("provider", "fallback")
    assert small.snapshot()["totals"]["modelDispatchCount"] == 2


@pytest.mark.parametrize(
    "scenario", ["many_tools", "repeated_truncation", "transient_model_failure"]
)
def test_generic_80_step_task_survives_slices_and_recovery_without_replaying_actions(
    scenario,
):
    completed = []
    checkpoints = []

    @tool
    def complete_step(step: int) -> str:
        """Perform the next step of a long task."""
        assert step not in completed, "An external action was replayed"
        assert step == len(completed)
        usage.observe_tool("test-provider", "complete_step")
        completed.append(step)
        return f"Completed step {step}"

    class LongTaskModel(FakeModel):
        def __init__(self):
            super().__init__("test", [])
            self.config.update(
                {"context_window_limit": 200_000, "params": {"max_tokens": 4_096}}
            )
            self.recovered = set()

        async def stream(self, *_args, **_kwargs):
            step = len(completed)
            self.calls += 1
            if (
                scenario == "transient_model_failure"
                and step == 20
                and step not in self.recovered
            ):
                self.recovered.add(step)
                raise TimeoutError("temporary model timeout before response")
            yield {"messageStart": {"role": "assistant"}}
            if (
                scenario == "repeated_truncation"
                and step > 0
                and step % 13 == 0
                and step not in self.recovered
            ):
                self.recovered.add(step)
                yield {
                    "contentBlockDelta": {
                        "contentBlockIndex": 0,
                        "delta": {"text": "Continuing the task."},
                    }
                }
                yield {"messageStop": {"stopReason": "max_tokens"}}
            elif step == 80:
                yield {
                    "contentBlockDelta": {
                        "contentBlockIndex": 0,
                        "delta": {"text": "All 80 steps completed."},
                    }
                }
                yield {"messageStop": {"stopReason": "end_turn"}}
            else:
                yield {
                    "contentBlockStart": {
                        "contentBlockIndex": 0,
                        "start": {
                            "toolUse": {
                                "toolUseId": f"step-{step}",
                                "name": "complete_step",
                            }
                        },
                    }
                }
                yield {
                    "contentBlockDelta": {
                        "contentBlockIndex": 0,
                        "delta": {"toolUse": {"input": json.dumps({"step": step})}},
                    }
                }
                yield {"contentBlockStop": {"contentBlockIndex": 0}}
                yield {"messageStop": {"stopReason": "tool_use"}}

    usage = UsageAccumulator(limits=LONG_RUN_CALL_LIMITS)
    delegate = LongTaskModel()
    agent = create_harness(
        model=ResilientOpenRouterModel(
            UsageTrackingModel(delegate, usage, provider="test", model_id="test")
        ),
        tools=[complete_step],
        builtin_tools=[],
        builtin_plugins=[],
        skills=False,
        memory=False,
        context_manager="auto",
        session=False,
        caching=False,
        callback_handler=None,
    )

    async def checkpoint(current):
        assert current is agent
        checkpoints.append(list(completed))

    async def run():
        return [
            event
            async for event in stream_with_token_recovery(
                agent,
                "Complete the long task.",
                turn_slice_size=8,
                checkpoint=checkpoint,
            )
        ]

    events = asyncio.run(run())
    assert completed == list(range(80))
    assert len(checkpoints) >= 10
    assert all(items == list(range(len(items))) for items in checkpoints)
    assert any(
        event.get("event", {}).get("messageStop", {}).get("stopReason") == "end_turn"
        for event in events
    )
    assert usage.snapshot()["totals"]["toolCallCount"] == 80
    assert usage.snapshot()["totals"]["modelDispatchCount"] == delegate.calls
    assert (
        delegate.calls
        == {"many_tools": 81, "repeated_truncation": 87, "transient_model_failure": 82}[
            scenario
        ]
    )
