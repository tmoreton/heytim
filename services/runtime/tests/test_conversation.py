from heytim_runtime.conversation import (
    CONTEXT_COMPRESSION_THRESHOLD,
    conversation_manager,
)


def test_tool_heavy_history_is_compacted_early() -> None:
    manager = conversation_manager()

    assert CONTEXT_COMPRESSION_THRESHOLD == 0.20
    assert manager._compression_threshold == 0.20
    assert manager.summary_ratio == 0.5
    assert manager.preserve_recent_messages == 10
