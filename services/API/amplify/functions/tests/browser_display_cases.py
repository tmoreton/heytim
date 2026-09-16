"""Display cases using the shared browser session fixture."""
import json
from unittest.mock import patch


class BrowserDisplayCases:
    def test_mobile_open_configures_same_session_then_disables_automation(self):
        self.service.open()
        session = self.record()["sessionId"]
        order = []
        self.dp.update_browser_stream.side_effect = lambda **kw: order.append(kw["streamUpdate"]["automationStreamUpdate"]["streamStatus"])
        with patch.object(self.module, "prepare_browser", side_effect=lambda *_args: order.append("prepare")) as prepare:
            view = self.service.open(display="mobile", url="https://example.com/a?b=c#section")
        self.assertEqual(order, ["ENABLED", "prepare", "DISABLED"])
        self.assertEqual(prepare.call_args.args[1]["sessionId"], session)
        self.assertEqual(self.dp.start_browser_session.call_count, 1)
        self.assertEqual(view["viewport"], {"width": 1440, "height": 900})
        self.assertFalse(view["mobileSiteSupported"])
        self.assertNotIn("example.com", json.dumps(self.table.writes))

    def test_failed_browser_setup_never_signs_or_leaves_automation_enabled(self):
        with patch.object(self.module, "prepare_browser", side_effect=TimeoutError("secret")):
            self.assert_error(503, lambda: self.service.open(display="mobile"))
        self.assertEqual(self.dp.update_browser_stream.call_args.kwargs["streamUpdate"]["automationStreamUpdate"]["streamStatus"], "DISABLED")
        self.signer.assert_not_called()
        self.assertNotIn("secret", json.dumps(self.table.writes))

    def test_new_mobile_browser_loads_extension_and_correct_viewport(self):
        extension = [{"location": {"s3": {"bucket": "test", "prefix": "extension.zip"}}}]
        with patch.object(self.module, "extension_configuration", return_value=extension), patch.object(self.module, "prepare_browser"):
            view = self.service.open(display="mobile")
        self.assertEqual(self.dp.start_browser_session.call_args.kwargs["extensions"], extension)
        self.assertEqual(self.dp.start_browser_session.call_args.kwargs["viewPort"], {"width": 390, "height": 780})
        self.assertTrue(view["mobileSiteSupported"])
        self.assertEqual(view["viewport"], {"width": 390, "height": 780})

    def test_invalid_navigation_never_creates_browser(self):
        for url in ["javascript:alert(1)", "file:///secret", "https://localhost", "http://169.254.169.254", "https://me:secret@example.com", "https://example.com\\@localhost", False]:
            self.assert_error(400, lambda url=url: self.service.open(url=url))
        self.assert_error(400, lambda: self.service.open(display="other"))
        self.dp.start_browser_session.assert_not_called()
