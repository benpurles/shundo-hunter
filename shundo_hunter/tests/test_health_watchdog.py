import threading
import unittest
from unittest.mock import Mock

from shundo_hunter.health_watchdog import HealthWatchdog


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.g = Mock()
        self.g.active=True;self.g.protected=False
        self.g.stop_event=threading.Event()
        self.g.vision.busy=False;self.g.screen_recovery.busy=False
        self.g.controller.status.return_value={"catchLabState":"starting"}
        self.s={"huntState":"running","huntPhase":"dwelling","ipogoPrepared":True,
                "huntWorkerAlive":True,"currentTargetId":1,"huntCheckedThisRun":0,
                "huntDwellSeconds":120,"huntRunStartedAt":"run1",
                "notificationWatcher":{"state":"listening","unattendedReady":True}}
        self.g.hunt.status.side_effect=lambda:dict(self.s)
        self.g.hunt.detector.watcher.events_after.return_value=[]
        self.g.hunt.detector.status.return_value={"checkpoint":0}
        self.w=HealthWatchdog(self.g,lambda:self.now)

    def test_off_idle_manual_pause_and_protected_never_repair(self):
        for updates,active,protected in [({},False,False),({"ipogoPrepared":False},True,False),
            ({"huntState":"paused","huntPhase":"paused"},True,False),({},True,True)]:
            self.s.update(updates);self.g.active=active;self.g.protected=protected
            self.w.tick()
        self.g.reconnect_for_health.assert_not_called()
        self.g.hunt.health_retry.assert_not_called()
        self.g.hunt.health_pause.assert_not_called()

    def test_slow_coordinate_is_not_stall_until_budget_plus_grace(self):
        self.w.tick();self.now=140;self.w.tick()
        self.g.hunt.health_pause.assert_not_called()
        self.now=146;self.w.tick()
        self.g.hunt.health_pause.assert_called_once()
        self.g.hunt.health_retry.assert_not_called()
        self.assertEqual(self.w.state,"stalled")

    def test_cooldown_budget_and_waiting_feed_not_false_stalls(self):
        self.s.update(huntPhase="cooldown",huntHundoCooldownSeconds=300)
        self.w.tick();self.now=310;self.w.tick()
        self.g.hunt.health_pause.assert_not_called()
        self.s["huntPhase"]="waiting";self.w.tick();self.now=9000;self.w.tick()
        self.assertEqual(self.w.state,"waiting-feed")
        self.g.hunt.health_pause.assert_not_called()

    def test_unknown_screen_never_auto_retries_and_alerts_once(self):
        self.s.update(huntState="paused",huntPhase="paused-world",healthRetryablePause=False)
        self.w.tick();self.now=100;self.w.tick()
        self.g.hunt.health_retry.assert_not_called()
        self.g.hunt.notifier.assert_called_once()

    def test_transient_read_recovery_queues_only_worker_and_is_bounded(self):
        self.s.update(huntState="paused",huntPhase="paused-world",healthRetryablePause=True)
        self.w.tick();self.now=10;self.w.tick()
        self.assertEqual(self.g.hunt.health_retry.call_count,1)
        self.now=31;self.w.tick();self.now=100;self.w.tick()
        self.assertEqual(self.g.hunt.health_retry.call_count,2)
        self.assertEqual(self.w.state,"attention")
        self.g.device.restart_ipogo.assert_not_called()

    def test_hourly_limit_survives_progress_and_incident_reset(self):
        self.s.update(huntState="paused",huntPhase="paused-world",healthRetryablePause=True)
        for i in range(7):
            self.s["huntCheckedThisRun"]=i;self.now=i*100;self.w.tick()
        self.assertEqual(self.g.hunt.health_retry.call_count,6)
        self.assertEqual(self.w.state,"attention")

    def test_connection_grace_and_relaunch_backoff(self):
        self.g.controller.status.return_value={"catchLabState":"unavailable"}
        self.w.tick();self.now=19;self.w.tick()
        self.g.reconnect_for_health.assert_not_called()
        self.now=20;self.w.tick()
        self.g.reconnect_for_health.assert_called_once()
        self.now=60;self.w.tick()
        self.g.reconnect_for_health.assert_called_once()
        self.now=111;self.w.tick();self.now=220;self.w.tick()
        self.assertEqual(self.g.reconnect_for_health.call_count,2)
        self.assertEqual(self.w.state,"attention")

    def test_listening_without_proof_never_resumes_or_restarts(self):
        self.s["notificationWatcher"]["unattendedReady"]=False
        self.w.tick();self.now=70;self.w.tick()
        self.g.hunt.health_retry.assert_not_called()
        self.g.reconnect_for_health.assert_not_called()
        self.assertEqual(self.w.state,"attention")

    def test_busy_screen_work_prevents_parallel_controller_repair(self):
        self.s["notificationWatcher"]["state"]="error"
        self.g.screen_recovery.busy=True
        self.w.tick();self.now=50;self.w.tick()
        self.g.reconnect_for_health.assert_not_called()

    def test_pending_shundo_blocks_every_repair_without_consuming_it(self):
        self.g.hunt.detector.watcher.events_after.return_value=[Mock(is_shundo=True)]
        self.s.update(huntState="paused",huntPhase="paused-world",healthRetryablePause=True)
        self.w.tick()
        self.g.hunt.health_retry.assert_not_called()
        self.g.reconnect_for_health.assert_not_called()
        self.g.hunt.detector.poll.assert_not_called()
        self.assertEqual(self.w.state,"attention")

    def test_dead_worker_is_attention_not_healthy_or_auto_started(self):
        self.s["huntWorkerAlive"]=False
        self.w.tick()
        self.assertEqual(self.w.state,"attention")
        self.g.hunt.health_retry.assert_not_called()
        self.g.reconnect_for_health.assert_not_called()

    def test_stopped_reader_uses_bounded_reconnection_not_endless_proof_wait(self):
        self.s["notificationWatcher"].update(state="stopped",unattendedReady=False)
        self.w.tick();self.now=21;self.w.tick()
        self.g.reconnect_for_health.assert_called_once()

    def test_connected_reader_without_first_hundo_does_not_pause_walking_hunt(self):
        self.s["notificationWatcher"].update(huntReady=True,unattendedReady=False)
        self.w.tick();self.now=100;self.w.tick()
        self.g.hunt.health_pause.assert_not_called()
        self.g.reconnect_for_health.assert_not_called()
        self.assertEqual(self.w.state,"awaiting-alert")


if __name__ == '__main__':unittest.main()
