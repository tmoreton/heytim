from __future__ import annotations

import unittest

from shared.work_state import is_claimable, is_in_flight


class WorkStateTests(unittest.TestCase):
    def test_in_flight_states_cover_execution_approval_and_input(self) -> None:
        for status in (
            "PENDING",
            "RUNNING",
            "WAITING",
            "NEEDS_INPUT",
            "AWAITING_APPROVAL",
        ):
            self.assertTrue(is_in_flight(status))
        for status in ("COMPLETE", "ERROR", "CANCELLED", None):
            self.assertFalse(is_in_flight(status))

    def test_only_pending_or_expired_running_work_can_be_claimed(self) -> None:
        self.assertTrue(is_claimable("PENDING"))
        self.assertTrue(is_claimable("RUNNING"))
        self.assertFalse(is_claimable("WAITING"))
        self.assertFalse(is_claimable("COMPLETE"))


if __name__ == "__main__":
    unittest.main()
