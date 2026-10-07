import unittest
from unittest.mock import Mock, patch
from shundo_hunter.catch_screen import classify
from shundo_hunter.catch_lab import CatchLab


def line(text, y=0.4, confidence=1):
    return {"text": text, "y": y, "confidence": confidence}


class CatchScreenTests(unittest.TestCase):
    def test_real_encounter_layout(self):
        result = classify([line("AR", .046), line("Golett", .31), line("CP 135", .31), line("158", .95)])
        self.assertEqual(result["scene"], "encounter")
        self.assertEqual(result["cp"], 135)
        self.assertFalse(result["captureVerified"])

    def test_cp_alone_is_not_encounter(self):
        self.assertEqual(classify([line("CP 135")])["scene"], "uncertain")

    def test_notification_banner_cannot_confirm_capture(self):
        result = classify([line("Gotcha! Golett was caught!", .08)])
        self.assertEqual(result["scene"], "uncertain")

    def test_reward_panel_needs_corrobating_cues(self):
        self.assertEqual(classify([line("POKEMON CAUGHT"), line("TOTAL 100 XP"), line("OK", .8)])["scene"], "caught")
        self.assertEqual(classify([line("POKEMON CAUGHT"), line("TOTAL")])["scene"], "uncertain")

    def test_low_confidence_catch_does_not_count(self):
        self.assertEqual(classify([line("Gotcha! Golett was caught!", confidence=.2)])["scene"], "uncertain")

    def test_cooldown_formats(self):
        self.assertEqual(classify([line("Est. CD: 00:50", .145)])["cooldownSeconds"], 50)
        self.assertEqual(classify([line("Est. CD: 01:02:03")])["cooldownSeconds"], 3723)

    def test_flee_message_not_capture(self):
        self.assertEqual(classify([line("The wild Golett fled!")])["scene"], "fled")

    def test_observer_requires_two_frames_and_never_throws(self):
        lab = CatchLab(lambda: True)
        lab.attempt = {"id": "a", "cp":135,"samples":0}
        lab._read_scene = Mock(return_value={"scene":"caught","evidence":["POKEMON CAUGHT","TOTAL 100 XP","OK"]})
        lab._request = Mock()
        stop = Mock()
        stop.wait.return_value = False
        stop.is_set.return_value = False
        with patch("shundo_hunter.catch_lab.time.monotonic", side_effect=[0,3,3,6,6]):
            lab._observe_result(stop,"a")
        self.assertEqual(lab._read_scene.call_count,2)
        self.assertTrue(lab.status()["catchLabAttempt"]["captureVerified"])
        lab._request.assert_not_called()

    def test_observer_disconnect_stays_uncertain(self):
        lab = CatchLab(lambda: True)
        lab.attempt = {"id":"a","cp":135,"samples":0}
        lab._read_scene = Mock(side_effect=RuntimeError("offline"))
        stop = Mock()
        stop.wait.return_value = False
        stop.is_set.return_value = False
        lab._observe_result(stop,"a")
        self.assertFalse(lab.status()["catchLabAttempt"]["captureVerified"])
        self.assertEqual(lab.status()["catchLabAttempt"]["result"],"uncertain")
