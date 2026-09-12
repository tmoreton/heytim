from __future__ import annotations

import logging

from shared.agent_stream import ProgressCallback
from shared.time import utc_now_iso

from .support import table

logger = logging.getLogger(__name__)


def progress_updater(item_key: dict, lease_owner: str) -> ProgressCallback:
    def update(progress: list[str]) -> None:
        try:
            table.update_item(
                Key=item_key,
                UpdateExpression="SET activity = :activity, activityUpdatedAt = :updated",
                ConditionExpression="#status = :running AND leaseOwner = :owner",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":activity": progress,
                    ":updated": utc_now_iso(),
                    ":running": "RUNNING",
                    ":owner": lease_owner,
                },
            )
        except Exception:
            logger.exception(
                "Could not publish agent activity for %s", item_key.get("sk", "unknown")
            )

    return update
