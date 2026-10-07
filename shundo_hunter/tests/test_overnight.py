from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from shundo_hunter.overnight import OvernightGuard
from shundo_hunter.hunt_service import USBNotificationDetector
from shundo_hunter.notification_service import NotificationWatcher, MARKER


class DirectAlertsTests(unittest.TestCase):
    def setUp(self):
        self.watcher = NotificationWatcher(executable="/usr/bin/false")
        self.detector = USBNotificationDetector(watcher=self.watcher)
        self.detector.set_alert_source("direct")
        self.watcher.state = "listening"
        self.watcher.banner_heartbeat = time.monotonic()

    def tearDown(self):
        self.detector.close()

    def test_live_process_is_not_alert_proof(self):
        self.assertFalse(self.detector.status()["unattendedReady"])
        self.assertTrue(self.detector.status()["huntReady"])

    def test_stale_or_disconnected_reader_cannot_start_without_proof(self):
        self.watcher.banner_heartbeat = time.monotonic()-9
        self.assertFalse(self.detector.status()["huntReady"])
        self.watcher.stop()
        self.assertFalse(self.detector.status()["huntReady"])

    def test_plain_device_log_is_not_healthy_banner_transport(self):
        self.watcher.use_phone_banners=False
        self.assertFalse(self.detector.status()["huntReady"])

    def test_mac_heartbeat_cannot_stop_or_verify_direct_stream(self):
        result = self.detector.update_mac_bridge({"type": "notification", "state": "listening", "trusted": True, "title": "Hundo Pikachu"})
        self.assertFalse(result["accepted"])
        self.assertEqual(self.watcher.state, "listening")
        self.assertEqual(self.watcher.checkpoint(), 0)
        self.assertFalse(self.detector.status()["unattendedReady"])

    def test_only_direct_hundo_proves_source_and_restart_clears_it(self):
        self.watcher.record_external("Hundo Pikachu")
        self.assertFalse(self.detector.status()["unattendedReady"])
        self.watcher._handle_line(f"{MARKER} Shiny Pikachu")
        self.assertFalse(self.detector.status()["unattendedReady"])
        self.watcher._handle_line(f"{MARKER} Hundo Pikachu")
        self.assertTrue(self.detector.status()["unattendedReady"])
        self.watcher.stop()
        self.assertFalse(self.detector.status()["unattendedReady"])
        self.assertIsNone(self.watcher.status()["directAlertProof"])

    def test_old_reader_cannot_prove_new_stream(self):
        self.watcher._handle_line(f"{MARKER} Hundo Pikachu", process=object())
        self.assertFalse(self.detector.status()["unattendedReady"])


class OvernightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "hold.json"
        self.hunt = Mock()
        self.hunt.status.return_value = {"huntState": "idle", "huntWorkerAlive": False, "ipogoPrepared": False}
        self.device = Mock()
        self.device.status.return_value = {}
        self.device.refresh.return_value = {"phoneConnected": True, "phoneUdid": "test-udid", "phoneNativeWifi": True}
        self.guard = OvernightGuard(self.hunt, self.device, self.path)
        self.guard.controller = Mock()
        self.power = Mock()
        self.power.poll.return_value = None

    def tearDown(self):
        self.guard.close()
        self.temp.cleanup()

    def begin(self):
        with patch("shundo_hunter.overnight.subprocess.Popen", return_value=self.power) as spawn:
            self.guard.begin(True)
            self.assertNotIn("-d", spawn.call_args.args[0])
            self.assertIn("-i", spawn.call_args.args[0])

    def test_requires_operator_auto_lock_confirmation(self):
        with self.assertRaisesRegex(RuntimeError, "Auto-Lock"):
            self.guard.begin(False)
        self.guard.controller.start_helper.assert_not_called()

    def test_health_reconnect_keeps_location_and_requires_new_alert_proof(self):
        self.begin()
        self.hunt.status.return_value={"huntState":"paused","huntPhase":"paused-alerts","huntWorkerAlive":True,"ipogoPrepared":True}
        self.hunt.detector.status.return_value={"checkpoint":0}
        self.hunt.detector.watcher.events_after.return_value=[]
        self.guard.controller._request.return_value={"value":{"screenLocked":False}}
        order=Mock()
        order.attach_mock(self.hunt.detector.watcher.stop,"revoke_proof")
        order.attach_mock(self.guard.controller.close,"close")
        order.attach_mock(self.guard.controller.start_helper,"start")
        order.attach_mock(self.hunt.detector.watcher.start,"watch")
        self.guard.reconnect_for_health()
        self.assertEqual([call[0] for call in order.mock_calls],["revoke_proof","close","start","watch"])
        self.device.set_location.assert_not_called()
        self.device.restart_ipogo.assert_not_called()

    def test_health_reconnect_cannot_touch_locked_manual_or_protected_phone(self):
        self.begin();self.guard.controller.start_helper.reset_mock()
        self.hunt.status.return_value={"huntState":"paused","huntPhase":"paused-alerts","huntWorkerAlive":True,"ipogoPrepared":True}
        self.hunt.detector.status.return_value={"checkpoint":0}
        self.hunt.detector.watcher.events_after.return_value=[]
        self.guard.controller._request.return_value={"value":{"screenLocked":True}}
        with self.assertRaisesRegex(RuntimeError,"locked"):self.guard.reconnect_for_health()
        self.guard.protected=True
        with self.assertRaises(RuntimeError):self.guard.reconnect_for_health()
        self.guard.protected=False;self.hunt.status.return_value["huntPhase"]="paused"
        with self.assertRaises(RuntimeError):self.guard.reconnect_for_health()
        self.guard.controller.close.assert_not_called()
        self.guard.controller.start_helper.assert_not_called()

    def test_health_reconnect_pending_shundo_is_noop(self):
        self.begin();self.guard.controller.start_helper.reset_mock()
        self.hunt.status.return_value={"huntState":"paused","huntPhase":"paused-alerts","huntWorkerAlive":True,"ipogoPrepared":True}
        self.hunt.detector.status.return_value={"checkpoint":0}
        self.hunt.detector.watcher.events_after.return_value=[SimpleNamespace(is_shundo=True)]
        with self.assertRaisesRegex(RuntimeError,"Shundo"):self.guard.reconnect_for_health()
        self.guard.controller.close.assert_not_called()
        self.guard.controller.start_helper.assert_not_called()

    def test_recovery_yields_to_real_hundo_without_consuming_it(self):
        from shundo_hunter.screen_recovery import RecoveryCancelled
        self.begin()
        self.hunt.detector.status.return_value={"checkpoint":11}
        event=SimpleNamespace(is_hundo=True,is_shundo=False)
        self.hunt.detector.watcher.events_after.return_value=[event]
        self.guard.screen_recovery._capture=Mock(side_effect=lambda check:check())
        with patch.object(self.guard.vision.client,"status",return_value={"visionConfigured":True}):
            with self.assertRaisesRegex(RecoveryCancelled,"Hundo/Shundo"):
                self.guard.recover_hunt_screen("probe",lambda:None,probe=True)
        self.hunt.detector.watcher.events_after.assert_called_once_with(11)
        self.hunt.detector.poll.assert_not_called()

    def test_resumed_cleanup_ignores_hundo_but_shundo_always_preempts(self):
        from shundo_hunter.screen_recovery import RecoveryCancelled
        self.begin()
        self.guard.screen_recovery.resume_pending=True
        self.guard.screen_recovery.next_probe=time.monotonic()+100
        self.hunt.detector.status.return_value={"checkpoint":11}
        self.hunt.detector.watcher.events_after.return_value=[SimpleNamespace(is_hundo=True,is_shundo=False)]
        self.guard.screen_recovery.run=Mock(side_effect=lambda reason,check:check())
        with patch.object(self.guard.vision.client,"status",return_value={"visionConfigured":True}):
            self.guard.recover_hunt_screen("resume",lambda:None,probe=True,after_hundo=True)
            self.guard.screen_recovery.run.assert_called_once()
            self.hunt.detector.watcher.events_after.return_value=[SimpleNamespace(is_hundo=True,is_shundo=True)]
            with self.assertRaises(RecoveryCancelled):
                self.guard.recover_hunt_screen("resume",lambda:None,probe=True,after_hundo=True)
        self.hunt.detector.poll.assert_not_called()

    def test_setup_never_claims_automatic_opening_and_never_throws(self):
        self.begin()
        self.assertFalse(self.guard.status()["overnightAutomaticOpeningReady"])
        self.assertTrue(self.guard.status()["overnightMacAwake"])
        self.guard.controller.start_helper.assert_called_once_with(self.device.executable, "test-udid", native_wifi=True, session_seconds=43200)
        self.guard.controller.throw_once.assert_not_called()

    def test_uncertain_scene_cannot_be_called_held(self):
        self.begin()
        self.guard._read = Mock(return_value={"scene": "uncertain", "cp": None})
        with patch("shundo_hunter.overnight.time.sleep"), self.assertRaisesRegex(RuntimeError, "matching"):
            self.guard.protect_open_encounter()
        self.assertFalse(self.guard.protected)

    def test_matching_open_encounter_locks_actions_and_persists(self):
        self.begin()
        self.guard._read = Mock(return_value={"scene": "encounter", "cp": 135})
        with patch("shundo_hunter.overnight.time.sleep"):
            status = self.guard.protect_open_encounter()
        self.assertEqual(status["overnightState"], "holding")
        self.assertIn("NOT verified", status["overnightDetail"])
        with self.assertRaisesRegex(RuntimeError, "locked"):
            self.guard.require_unprotected()
        recovered = OvernightGuard(self.hunt, self.device, self.path)
        try:
            self.assertTrue(recovered.protected)
            self.assertFalse(recovered.active)
            self.assertEqual(recovered.state, "attention")
        finally:
            recovered.close()

    def test_shundo_hold_failure_remains_locked_without_open_or_throw(self):
        self.begin()
        self.hunt.status.return_value["huntState"] = "shundo"
        self.device.set_location.side_effect = RuntimeError("disconnected")
        self.guard.on_shundo({"latitude": 1, "longitude": 2}, SimpleNamespace(message="Shundo", received_at="now"))
        self.assertTrue(self.guard.protected)
        self.assertEqual(self.guard.state, "attention")
        self.guard.controller._request.assert_not_called()
        self.guard.controller.throw_once.assert_not_called()

    def test_release_changes_no_phone_location_or_encounter(self):
        self.begin()
        self.guard.protected = True
        self.guard.release()
        self.assertFalse(self.guard.protected)
        self.device.set_location.assert_not_called()
        self.device.clear_location.assert_not_called()
        self.hunt.start.assert_not_called()
        self.power.terminate.assert_called_once()

    def test_malformed_journal_fails_closed(self):
        self.path.write_text("not valid JSON")
        recovered = OvernightGuard(self.hunt, self.device, self.path)
        try:
            self.assertTrue(recovered.protected)
        finally:
            recovered.close()

    def test_cannot_resume_with_dead_power_assertion(self):
        self.begin()
        self.power.poll.return_value = 0
        with self.assertRaisesRegex(RuntimeError, "needs attention"):
            self.guard.require_hunt_ready()


if __name__ == "__main__":
    unittest.main()
