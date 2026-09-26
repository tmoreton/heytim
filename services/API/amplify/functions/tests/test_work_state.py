from __future__ import annotations

import unittest

from shared.work_state import is_claimable, is_in_flight, processing_summary


class WorkStateTests(unittest.TestCase):
    def test_in_flight_states_cover_execution_approval_and_input(self) -> None:
        for status in (
            "PENDING",
            "RUNNING",
            "WAITING",
            "NEEDS_INPUT",
            "AWAITING_APPROVAL",
            "AWAITING_DEVICE",
        ):
            self.assertTrue(is_in_flight(status))
        for status in ("COMPLETE", "ERROR", "CANCELLED", None):
            self.assertFalse(is_in_flight(status))

    def test_only_pending_or_expired_running_work_can_be_claimed(self) -> None:
        self.assertTrue(is_claimable("PENDING"))
        self.assertTrue(is_claimable("RUNNING"))
        self.assertFalse(is_claimable("WAITING"))
        self.assertFalse(is_claimable("AWAITING_DEVICE"))
        self.assertFalse(is_claimable("COMPLETE"))


class ProcessingSummaryTests(unittest.TestCase):
    def test_reports_newest_pending_or_running_reply(self) -> None:
        result = processing_summary(
            [
                {"status": "WAITING", "authorName": "Last bot"},
                {"status": "RUNNING", "authorName": "Working bot"},
                {"status": "COMPLETE", "authorName": "Earlier bot"},
            ]
        )

        self.assertEqual(
            result, {"processing": True, "processingBotName": "Working bot"}
        )

    def test_waiting_and_approval_states_are_not_shown_as_processing(self) -> None:
        self.assertEqual(
            processing_summary(
                [
                    {"status": "WAITING"},
                    {"status": "AWAITING_APPROVAL"},
                    {"status": "AWAITING_DEVICE"},
                ]
            ),
            {"processing": False},
        )

    def test_name_is_optional_for_direct_turns(self) -> None:
        self.assertEqual(
            processing_summary([{"status": "PENDING"}]), {"processing": True}
        )


if __name__ == "__main__":
    unittest.main()
