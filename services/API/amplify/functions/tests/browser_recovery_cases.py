"""Regression cases for expired browser handoffs and AWS Stop conflicts."""


class BrowserRecoveryCases:
    def failed_handoff(self, status="OPENING", **changes):
        self.service.open()
        return self.service.store.write(
            self.record(), status=status, operation="close" if status == "RESUMING" else "open",
            operationUntil=0, resumeState="COMPLETE", resumedTurnId="old-turn", **changes,
        )

    def test_ended_open_and_close_are_reopenable_without_get_mutations(self):
        for status in ("OPENING", "RESUMING"):
            with self.subTest(status=status):
                self.failed_handoff(status)
                self.dp.get_browser_session.return_value["status"] = "TERMINATED"
                before = self.record()
                view = self.service.get()
                self.assertEqual(view["status"], "expired")
                self.assertNotIn("resumedTurnId", view)
                self.assertEqual(before, self.record())
                opened = self.service.open()
                self.assertEqual(opened["status"], "human_control")
                self.assertIsNone(self.record()["resumedTurnId"])
                self.enqueue.assert_not_called()
                self.dp.get_browser_session.return_value["status"] = "READY"

    def test_expired_operation_alone_does_not_recover_live_or_unknown_session(self):
        self.failed_handoff()
        for remote in ("READY", "CREATING", "UNKNOWN"):
            self.dp.get_browser_session.return_value["status"] = remote
            self.assertEqual(self.service.get()["status"], "opening")
            self.assertTrue(self.service.get()["recoveryRequired"])
            self.assert_error(409, self.service.open)
        self.dp.get_browser_session.side_effect = TimeoutError("private endpoint")
        with self.assertRaises(TimeoutError):
            self.service.open()
        self.assertEqual(self.record()["status"], "OPENING")

    def test_missing_remote_session_can_recover_but_unknown_start_cannot(self):
        self.failed_handoff()
        self.dp.get_browser_session.side_effect = self.dp.exceptions.ResourceNotFoundException()
        self.assertEqual(self.service.get()["status"], "expired")
        self.service.store.write(self.record(), sessionId=None)
        self.assertEqual(self.service.get()["status"], "opening")
        self.assert_error(409, self.service.open)

    def test_recovery_never_bypasses_active_operation_or_uncertain_resume(self):
        self.failed_handoff()
        self.dp.get_browser_session.return_value["status"] = "TERMINATED"
        self.service.store.write(self.record(), operationUntil=self.now + 45)
        self.assertFalse(self.service.get()["recoveryRequired"])
        self.assert_error(409, self.service.open)
        for resume in ("WAIT_PROFILE", "ENQUEUEING", "UNCERTAIN"):
            self.service.store.write(self.record(), operationUntil=0, resumeState=resume)
            self.assert_error(409, self.service.open)
        self.enqueue.assert_not_called()

    def test_recovery_checks_remote_ownership(self):
        self.failed_handoff()
        self.dp.get_browser_session.return_value.update(name="another-bot", status="TERMINATED")
        self.assert_error(403, self.service.get)
        self.assert_error(403, self.service.open)

    def test_stop_conflict_is_success_only_when_termination_confirmed(self):
        self.service.open()
        self.service.resume(True, self.enqueue)
        self.dp.stop_browser_session.side_effect = self.dp.exceptions.ConflictException()
        self.assert_error(503, self.service.close)
        self.assertIsNotNone(self.record()["sessionId"])
        self.dp.get_browser_session.return_value["status"] = "TERMINATED"
        view = self.service.close()
        self.assertEqual(view["status"], "closed")
        self.assertTrue(view["hasSavedLogin"])
        self.cp.delete_browser_profile.assert_not_called()

    def test_stop_conflict_with_unknown_remote_state_keeps_cleanup_reference(self):
        self.service.open()
        self.dp.stop_browser_session.side_effect = self.dp.exceptions.ConflictException()
        self.dp.get_browser_session.side_effect = TimeoutError()
        self.assert_error(503, self.service.close)
        self.assertEqual(self.record()["sessionId"], "session1")

    def test_failed_new_open_does_not_inherit_previous_resume_receipt(self):
        self.service.open()
        self.service.resume(False, self.enqueue)
        self.dp.update_browser_stream.side_effect = TimeoutError()
        self.assert_error(503, self.service.open)
        self.assertIsNone(self.record()["resumedTurnId"])
        self.assertIsNone(self.record()["resumeState"])
