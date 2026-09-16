from __future__ import annotations

import os

from strands.agent.conversation_manager import SummarizingConversationManager

CONTEXT_COMPRESSION_THRESHOLD = float(
    os.environ.get("FROGBOT_CONTEXT_COMPRESSION_THRESHOLD", "0.20")
)
if not 0.1 <= CONTEXT_COMPRESSION_THRESHOLD <= 0.9:
    raise ValueError(
        "FROGBOT_CONTEXT_COMPRESSION_THRESHOLD must be between 0.1 and 0.9"
    )


def conversation_manager() -> SummarizingConversationManager:
    """Compact older, tool-pair-safe history before provider requests get large."""
    return SummarizingConversationManager(
        summary_ratio=0.5,
        preserve_recent_messages=10,
        proactive_compression={
            "compression_threshold": CONTEXT_COMPRESSION_THRESHOLD
        },
    )
