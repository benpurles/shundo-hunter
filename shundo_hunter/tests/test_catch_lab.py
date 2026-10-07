import base64
import unittest
from unittest.mock import Mock, patch

from shundo_hunter.catch_lab import CatchLab, CatchLabError


class CatchLabTests(unittest.TestCase):
    def lab(self):
        lab = CatchLab(lambda: True)
        lab.screen_reader = Mock(return_value={"scene": "encounter", "cp": 135, "cooldownSeconds": 0, "evidence": ["Golett", "CP 135"]})
        lab._start_observer = Mock()
        lab._request = Mock(side_effect=lambda method, path, payload=None: {
            "/status": {"value": {"ready": True}},
            "/wda/activeAppInfo": {"value": {"bundleId": lab.BUNDLE_ID}},
            "/session": {"value": {"sessionId": "test-session"}},
            "/session/test-session/window/size": {"value": {"width": 428, "height": 926}},
            "/screenshot": {"value": base64.b64encode(b"\x89PNG\r\n\x1a\nfake-test-data").decode()},
        }.get(path, {"value": None}))
        return lab

    def payload(self, preview):
        return {"token": preview["token"], "start": [0.5, 0.85], "end": [0.5, 0.4],
                "confirmedOrdinaryRegularBall": True}

    def test_preview_never_launches_or_touches_phone(self):
        lab = self.lab()
        preview = lab.inspect()
        self.assertTrue(preview["image"].startswith("data:image/png;base64,"))
        posts = [call for call in lab._request.call_args_list if call.args[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].args[1], "/session")
        caps = posts[0].args[2]["capabilities"]["alwaysMatch"]
        self.assertNotIn("bundleId", caps)
        self.assertFalse(caps["shouldTerminateApp"])
        self.assertFalse(lab.status()["autoCatchEnabled"])

    def test_active_hunt_prevents_preview_and_throw(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        lab.can_test = lambda: False
        with self.assertRaises(CatchLabError):
            lab.throw_once(payload)
        with self.assertRaises(CatchLabError):
            lab.inspect()
        self.assertFalse(any(call.args[1].endswith("/actions") for call in lab._request.call_args_list))

    def test_confirmation_is_mandatory(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        payload["confirmedOrdinaryRegularBall"] = False
        with self.assertRaisesRegex(CatchLabError, "Confirm"):
            lab.throw_once(payload)

    def test_uncertain_preview_blocks_throw(self):
        lab = self.lab()
        lab.screen_reader.return_value = {"scene": "uncertain", "cp":None}
        payload = self.payload(lab.inspect())
        with self.assertRaisesRegex(CatchLabError, "not a recognized"):
            lab.throw_once(payload)

    def test_fresh_cooldown_blocks_throw(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        lab.screen_reader.return_value = {"scene":"encounter","cp":135,"cooldownSeconds":50}
        with self.assertRaisesRegex(CatchLabError, "active cooldown"):
            lab.throw_once(payload)
        self.assertFalse(any(call.args[1].endswith("/actions") for call in lab._request.call_args_list))

    def test_changed_encounter_blocks_throw(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        lab.screen_reader.return_value = {"scene":"encounter","cp":999,"cooldownSeconds":0}
        with self.assertRaisesRegex(CatchLabError, "Encounter changed"):
            lab.throw_once(payload)

    def test_unreadable_frame_retries_only_observation(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        lab.screen_reader.side_effect = [
            {"scene":"uncertain","cp":None},
            {"scene":"encounter","cp":135,"cooldownSeconds":0},
        ]
        lab.throw_once(payload)
        self.assertEqual(len([c for c in lab._request.call_args_list if c.args[1].endswith("/actions")]),1)

    def test_persistently_unreadable_screen_never_throws(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        lab.screen_reader.return_value = {"scene":"uncertain","cp":None}
        with self.assertRaisesRegex(CatchLabError,"Encounter changed"):
            lab.throw_once(payload)
        self.assertFalse(any(c.args[1].endswith("/actions") for c in lab._request.call_args_list))

    def test_calibration_duration_bounded(self):
        for duration in (True,119,601,200.1,"240"):
            lab = self.lab()
            payload = dict(self.payload(lab.inspect()), durationMs=duration)
            with self.assertRaisesRegex(CatchLabError, "duration"):
                lab.throw_once(payload)
        lab = self.lab()
        lab.throw_once(dict(self.payload(lab.inspect()),durationMs=240))
        actions = [c for c in lab._request.call_args_list if c.args[1].endswith("/actions")][0].args[2]["actions"][0]["actions"]
        self.assertEqual(actions[3]["duration"],240)

    def test_one_throw_only_and_no_claim_of_capture(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        status = lab.throw_once(payload)
        self.assertEqual(status["catchLabState"], "attempt-unverified")
        self.assertFalse(status["autoCatchEnabled"])
        with self.assertRaisesRegex(CatchLabError, "already used"):
            lab.throw_once(payload)
        posts = [call for call in lab._request.call_args_list if call.args[1].endswith("/actions")]
        self.assertEqual(len(posts), 1)

    def test_expired_preview(self):
        lab = self.lab()
        with patch("shundo_hunter.catch_lab.time.monotonic", return_value=10):
            payload = self.payload(lab.inspect())
        with patch("shundo_hunter.catch_lab.time.monotonic", return_value=41):
            with self.assertRaisesRegex(CatchLabError, "expired"):
                lab.throw_once(payload)

    def test_foreground_switch_prevents_throw(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        lab._request = Mock(return_value={"value": {"bundleId": "com.apple.Preferences"}})
        with self.assertRaisesRegex(CatchLabError, "No other app"):
            lab.throw_once(payload)
        self.assertEqual(lab._request.call_count, 1)

    def test_out_of_range_nonfinite_or_boolean_points_rejected(self):
        for point in ([0, float("nan")], [True, 0.8], [2, 0.8], [0.5], None):
            lab = self.lab()
            payload = dict(self.payload(lab.inspect()), start=point)
            with self.assertRaises(CatchLabError):
                lab.throw_once(payload)

    def test_transport_failure_is_unknown_not_a_retry(self):
        lab = self.lab()
        payload = self.payload(lab.inspect())
        original = lab._request.side_effect
        def fail_action(method, path, payload=None):
            if path.endswith("/actions"):
                raise CatchLabError("connection lost")
            return original(method, path, payload)
        lab._request.side_effect = fail_action
        with self.assertRaises(CatchLabError):
            lab.throw_once(payload)
        self.assertIn("unknown", lab.status()["catchLabDetail"])
        with self.assertRaisesRegex(CatchLabError, "already used"):
            lab.throw_once(payload)
