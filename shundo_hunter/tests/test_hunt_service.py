from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from shundo_hunter.feed_server import SightingStore
from shundo_hunter.hunt_service import (
    HuntCoordinator,
    HuntError,
    ManualNotificationDetector,
    USBNotificationDetector,
)
from shundo_hunter.notification_service import (
    NotificationEvent as SourceNotificationEvent,
    WorldScanEvent as SourceWorldScanEvent,
)


def payload(message_id: str, species: str = "Bulbasaur") -> dict:
    return {
        "guildId": "guild",
        "channelId": "channel",
        "channelName": "100community",
        "messageId": message_id,
        "rawText": f"***{species}*** **CP637** **L25** ✨",
        "resolvedCoordinate": {
            "latitude": 40.75 + int(message_id) / 100_000,
            "longitude": -111.88,
            "url": f"https://pokedex100.com/{message_id}",
        },
    }


class FakeDevice:
    def __init__(self, connected: bool = True):
        self.connected = connected
        self.locations: list[tuple[float, float]] = []
        self.hunt_locations: list[tuple[float, float]] = []
        self.location_event = threading.Event()
        self.restarts: list[tuple[float, float] | None] = []

    def status(self) -> dict:
        return {
            "phoneConnected": self.connected,
            "phoneUdid": "phone-udid" if self.connected else None,
            "phoneLastError": None if self.connected else "No paired USB iPhone detected",
        }

    def refresh(self) -> dict:
        return self.status()

    def set_location(self, latitude: float, longitude: float) -> dict:
        if not self.connected:
            raise RuntimeError("Phone disconnected")
        self.locations.append((latitude, longitude))
        self.location_event.set()
        return {**self.status(), "phoneLocationDelivery": "continuous-1hz"}

    def set_hunt_location(self, latitude: float, longitude: float) -> dict:
        result = self.set_location(latitude, longitude)
        self.hunt_locations.append((latitude, longitude))
        return {**result, "phoneLocationDelivery": "walking-loop-1hz"}

    def restart_ipogo(self) -> dict:
        if not self.connected:
            raise RuntimeError("Phone disconnected")
        self.restarts.append(self.locations[-1] if self.locations else None)
        return {**self.status(), "ipogoLastRestartAt": "now"}


class FakeWatcher:
    def __init__(self):
        self.sequence = 0
        self.events: list[SourceNotificationEvent] = []
        self.started_udid: str | None = None

    def start(self, udid: str):
        self.started_udid = udid

    def checkpoint(self):
        return self.sequence

    def events_after(self, checkpoint: int):
        return [event for event in self.events if event.sequence > checkpoint]

    def emit(self, text: str, is_shundo: bool, is_hundo: bool | None = None):
        self.sequence += 1
        event = SourceNotificationEvent(
            self.sequence,
            "now",
            text,
            is_shundo if is_hundo is None else is_hundo,
            is_shundo,
        )
        self.events.append(event)
        return event

    def status(self):
        return {
            "notificationWatcherState": "listening",
            "notificationWatcherLastError": None,
            "notificationSequence": self.sequence,
        }

    def close(self):
        pass


class FakeWorldWatcher:
    KIND_NAMES = {
        1: "nearby-pokemon",
        2: "wild-pokemon",
        3: "gyms",
        4: "pokestops",
    }

    def __init__(self):
        self.sequence = 0
        self.events: list[SourceWorldScanEvent] = []
        self.started_udid: str | None = None

    def start(self, udid: str):
        self.started_udid = udid

    def checkpoint(self):
        return self.sequence

    def events_after(self, checkpoint: int):
        return [event for event in self.events if event.sequence > checkpoint]

    def emit(self, kind_code: int, count: int):
        self.sequence += 1
        event = SourceWorldScanEvent(
            sequence=self.sequence,
            received_at="now",
            received_monotonic=time.monotonic(),
            kind=self.KIND_NAMES[kind_code],
            kind_code=kind_code,
            count=count,
        )
        self.events.append(event)
        return event

    def status(self):
        return {
            "worldScanWatcherState": "listening",
            "worldScanWatcherLastError": None,
            "worldScanSequence": self.sequence,
            "lastWorldScanEvent": self.events[-1].as_dict() if self.events else None,
        }

    def close(self):
        pass


class BridgeDependentDetector(ManualNotificationDetector):
    def __init__(self):
        super().__init__()
        self.ready = True

    def status(self):
        result = super().status()
        result.update({"requiresMacBridge": True, "unattendedReady": self.ready})
        return result


class AlertWithOfflineSampleDetector(BridgeDependentDetector):
    """Returns one real alert while the same cycle reports bridge loss."""

    def poll(self, target_id: int):
        event = super().poll(target_id)
        if event is not None:
            self.ready = False
        return event


def wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for hunt state")


class HuntCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SightingStore(Path(self.temp_dir.name) / "test.db")
        self.store.set_feed_source("discord")
        self.device = FakeDevice()
        self.detector = ManualNotificationDetector()
        self.coordinators: list[HuntCoordinator] = []

    def tearDown(self):
        for coordinator in self.coordinators:
            coordinator.close()
        self.temp_dir.cleanup()

    def coordinator(self, **kwargs) -> HuntCoordinator:
        kwargs.setdefault("ipogo_refresh_confirmed_interval", 999)
        kwargs.setdefault("ipogo_refresh_visit_interval", 999)
        kwargs.setdefault("ipogo_recovery_timeout_threshold", 999)
        kwargs.setdefault("ipogo_clean_start", False)
        kwargs.setdefault("hundo_cooldown_seconds", 0)
        kwargs.setdefault("shundo_alarm", lambda: None)
        coordinator = HuntCoordinator(
            self.store,
            self.device,
            self.detector,
            idle_poll_seconds=0.05,
            notifier=lambda _title, _message: None,
            **kwargs,
        )
        self.coordinators.append(coordinator)
        return coordinator

    def test_screen_recovery_runs_after_restart_without_replacing_location_service(self):
        coordinator = self.coordinator(ipogo_restart_settle_seconds=0)
        guard = Mock(protected=False)
        coordinator.encounter_guard = guard
        coordinator._prepared = True
        coordinator._hunt_state = "running"
        self.assertTrue(coordinator._restart_ipogo_session("test", 1))
        self.assertEqual(len(self.device.restarts), 1)
        guard.recover_hunt_screen.assert_called_once()
        self.assertEqual(guard.recover_hunt_screen.call_args.args[0], "After iPogo refresh")
        guard.recover_hunt_screen.call_args.args[1]()
        coordinator.encounter_guard = None

    def test_screen_recovery_failure_pauses_without_advancing_target(self):
        coordinator = self.coordinator()
        coordinator.encounter_guard = Mock()
        coordinator.encounter_guard.recover_hunt_screen.side_effect = RuntimeError("Unknown popup")
        coordinator._prepared = True
        coordinator._hunt_state = "running"
        self.assertFalse(coordinator._recover_screen("test", 7))
        self.assertEqual(coordinator.status()["huntState"], "paused")
        self.assertEqual(self.device.locations, [])
        coordinator.encounter_guard = None

    def test_screen_recovery_preemption_yields_before_world_poll(self):
        from shundo_hunter.screen_recovery import RecoveryCancelled
        coordinator = self.coordinator()
        coordinator.encounter_guard = Mock()
        coordinator.encounter_guard.recover_hunt_screen.side_effect = RecoveryCancelled("Shundo pending")
        self.assertEqual(coordinator._recover_screen("test", 7, probe=True), "interrupted")
        coordinator.encounter_guard = None

    def test_health_retry_is_worker_request_not_parallel_restart(self):
        c=self.coordinator()
        c._prepared=True;c._hunt_state="paused";c._phase="paused-world"
        c._health_retryable_pause=True;c._current_target={"id":7}
        c._worker=Mock();c._worker.is_alive.return_value=True
        with patch.object(c.detector,"status",return_value={"unattendedReady":True}):
            self.assertFalse(c.health_retry(8))
            self.assertTrue(c.health_retry(7))
        self.assertEqual(self.device.restarts,[])
        self.assertTrue(c._retry_world_recovery_requested)
        self.assertEqual(c._phase,"retrying-world")
        c._worker=None

    def test_walking_hunt_can_start_before_hundo_but_pauses_on_reader_failure(self):
        self.store.add(payload("1"))
        c=self.coordinator(dwell_seconds=5)
        original=self.detector.status
        ready=[True]
        def status():
            return {**original(),"requiresAlertReadiness":True,"huntReady":ready[0],
                    "unattendedReady":False,"alertSource":"direct"}
        with patch.object(self.detector,"status",side_effect=status):
            c.prepare();c.start()
            wait_for(lambda:c.status()["huntPhase"]=="dwelling")
            self.assertTrue(self.device.hunt_locations)
            self.assertEqual(c.status()["huntNotificationsConfirmedThisRun"],0)
            self.assertFalse(c.status()["notificationWatcher"]["unattendedReady"])
            ready[0]=False
            wait_for(lambda:c.status()["huntPhase"]=="paused-alerts")
            c.unprepare()

    def test_unverified_walking_check_still_times_out_bad_coordinates(self):
        target,_=self.store.add(payload("1"))
        c=self.coordinator(dwell_seconds=.15)
        original=self.detector.status
        with patch.object(self.detector,"status",side_effect=lambda:{**original(),"requiresAlertReadiness":True,"huntReady":True,"unattendedReady":False}):
            c.prepare();c.start()
            wait_for(lambda:self.store.get_sighting(target["id"])["completion_reason"]=="timeout-no-alert")
            self.assertEqual(c.status()["huntNotificationsConfirmedThisRun"],0)
            c.unprepare()

    def test_health_retry_cannot_resume_operator_pause_unverified_or_protected(self):
        c=self.coordinator();c._prepared=True;c._health_retryable_pause=True
        c._current_target={"id":7};c._worker=Mock();c._worker.is_alive.return_value=True
        for phase,ready,protected in [("paused",True,False),("paused-world",False,False),("paused-world",True,True)]:
            c._hunt_state="paused";c._phase=phase
            c.encounter_guard=Mock(protected=protected)
            with patch.object(c.detector,"status",return_value={"unattendedReady":ready}):
                self.assertFalse(c.health_retry(7))
        c._worker=None;c.encounter_guard=None

    def test_only_read_only_observation_failure_is_auto_recoverable(self):
        from shundo_hunter.screen_recovery import ObservationUnavailable, VisionError
        c=self.coordinator();c.encounter_guard=Mock()
        for error,expected in [(ObservationUnavailable("read failed"),True),(VisionError("Unknown dialog"),False)]:
            c.encounter_guard.recover_hunt_screen.side_effect=error
            c._prepared=True;c._hunt_state="running"
            self.assertFalse(c._recover_screen("test",7))
            self.assertEqual(c.status()["healthRetryablePause"],expected)
        c.encounter_guard=None

    def test_shundo_arriving_after_queued_retry_blocks_actual_restart(self):
        c=self.coordinator();c._prepared=True;c._hunt_state="running"
        watcher=Mock();watcher.events_after.return_value=[Mock(is_shundo=True)]
        c.detector=Mock(watcher=watcher)
        c.detector.status.return_value={"checkpoint":0}
        self.assertFalse(c._restart_ipogo_session("health recovery",7))
        self.assertEqual(self.device.restarts,[])
        c.detector.poll.assert_not_called()
        self.assertEqual(c._phase,"paused-world")

    def test_protected_encounter_blocks_actual_restart(self):
        c=self.coordinator();c.encounter_guard=Mock(protected=True)
        self.assertFalse(c._restart_ipogo_session("health recovery",7))
        self.assertEqual(self.device.restarts,[])
        c.encounter_guard=None

    def test_preventive_ipogo_refresh_runs_before_next_target_and_preserves_spoof(self):
        first, _ = self.store.add(payload("1", "Bulbasaur"))
        second, _ = self.store.add(payload("2", "Charmander"))
        third, _ = self.store.add(payload("3", "Squirtle"))
        self.store.save_preferences("all", ["Bulbasaur", "Charmander", "Squirtle"])
        coordinator = self.coordinator(
            dwell_seconds=1.0,
            ipogo_refresh_confirmed_interval=2,
            ipogo_restart_settle_seconds=0.05,
        )
        coordinator.prepare()
        coordinator.start()

        wait_for(lambda: coordinator.status()["currentTargetId"] == first["id"] and coordinator.status()["huntPhase"] == "dwelling")
        self.detector.inject(kind="hundo", message="Hundo Bulbasaur")
        wait_for(lambda: coordinator.status()["currentTargetId"] == second["id"] and coordinator.status()["huntPhase"] == "dwelling")
        self.detector.inject(kind="hundo", message="Hundo Charmander")
        wait_for(lambda: len(self.device.restarts) == 1)
        self.assertEqual(self.device.restarts[0], self.device.locations[-1])
        wait_for(
            lambda: coordinator.status()["currentTargetId"] == third["id"]
            and coordinator.status()["huntPhase"] == "dwelling"
        )
        status = coordinator.status()
        self.assertEqual(status["ipogoRefreshesThisRun"], 1)
        self.assertTrue(status["ipogoAwaitingWorldProof"])

    def test_completed_map_load_budget_counts_timeouts_and_restarts_before_next_target(self):
        first, _ = self.store.add(payload("1", "Bulbasaur"))
        second, _ = self.store.add(payload("2", "Charmander"))
        third, _ = self.store.add(payload("3", "Squirtle"))
        self.store.save_preferences("all", ["Bulbasaur", "Charmander", "Squirtle"])
        coordinator = self.coordinator(
            dwell_seconds=0.08,
            ipogo_refresh_confirmed_interval=999,
            ipogo_refresh_visit_interval=2,
            ipogo_recovery_timeout_threshold=999,
            ipogo_restart_settle_seconds=0.05,
        )
        coordinator.prepare()
        coordinator.start()

        wait_for(lambda: self.store.get_sighting(first["id"])["status"] == "checked")
        wait_for(lambda: self.store.get_sighting(second["id"])["status"] == "checked")
        wait_for(lambda: len(self.device.restarts) == 1)
        self.assertEqual(self.device.restarts[0], self.device.locations[-1])
        wait_for(
            lambda: coordinator.status()["currentTargetId"] == third["id"]
            and coordinator.status()["huntPhase"] == "dwelling"
        )
        self.assertEqual(coordinator.status()["ipogoVisitsSinceRefresh"], 1)

    def test_default_memory_budget_is_fourteen_completed_map_loads(self):
        coordinator = HuntCoordinator(
            self.store,
            self.device,
            self.detector,
            notifier=lambda _title, _message: None,
            shundo_alarm=lambda: None,
        )
        self.coordinators.append(coordinator)

        status = coordinator.status()
        self.assertEqual(status["ipogoRefreshConfirmedInterval"], 14)
        self.assertEqual(status["ipogoRefreshVisitInterval"], 14)
        self.assertTrue(status["ipogoCleanStartEnabled"])

    def test_new_hunt_establishes_clean_ipogo_memory_baseline_at_first_location(self):
        target, _ = self.store.add(payload("1", "Bulbasaur"))
        coordinator = HuntCoordinator(
            self.store,
            self.device,
            self.detector,
            dwell_seconds=1,
            idle_poll_seconds=0.05,
            ipogo_refresh_confirmed_interval=999,
            ipogo_refresh_visit_interval=999,
            ipogo_recovery_timeout_threshold=999,
            ipogo_restart_settle_seconds=0.05,
            notifier=lambda _title, _message: None,
            shundo_alarm=lambda: None,
        )
        self.coordinators.append(coordinator)
        coordinator.prepare()
        coordinator.start()

        wait_for(lambda: len(self.device.restarts) == 1)
        self.assertEqual(self.device.restarts[0], self.device.locations[-1])
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")
        status = coordinator.status()
        self.assertEqual(status["currentTargetId"], target["id"])
        self.assertEqual(status["ipogoRefreshesThisRun"], 1)
        self.assertEqual(status["ipogoVisitsSinceRefresh"], 1)
        self.assertTrue(status["ipogoAwaitingWorldProof"])

    def test_empty_queue_requests_feed_refill_and_resumes_new_target(self):
        first, _ = self.store.add(payload("1", "Bulbasaur"))
        coordinator = self.coordinator(dwell_seconds=1.0)
        refill_requested = threading.Event()

        def refill() -> None:
            self.store.add(payload("2", "Charmander"))
            refill_requested.set()
            coordinator.notify_targets_available()

        coordinator.set_queue_refill_requester(refill)
        coordinator.prepare()
        coordinator.start()
        wait_for(
            lambda: coordinator.status()["currentTargetId"] == first["id"]
            and coordinator.status()["huntPhase"] == "dwelling"
        )
        self.detector.inject(kind="hundo", message="Hundo Bulbasaur")
        wait_for(refill_requested.is_set)
        wait_for(
            lambda: (coordinator.status().get("currentTarget") or {}).get("species")
            == "Charmander"
        )

    def test_two_timeouts_refresh_ipogo_and_advance_to_different_target(self):
        first, _ = self.store.add(payload("1", "Bulbasaur"))
        second, _ = self.store.add(payload("2", "Charmander"))
        third, _ = self.store.add(payload("3", "Squirtle"))
        self.store.save_preferences("all", ["Bulbasaur", "Charmander", "Squirtle"])
        coordinator = self.coordinator(
            dwell_seconds=0.08,
            ipogo_recovery_timeout_threshold=2,
            ipogo_restart_settle_seconds=0.05,
            ipogo_recovery_dwell_seconds=0.3,
        )
        coordinator.prepare()
        coordinator.start()

        wait_for(lambda: self.store.get_sighting(first["id"])["status"] == "checked")
        wait_for(lambda: len(self.device.restarts) == 1)
        self.assertEqual(self.store.get_sighting(second["id"])["status"], "checked")
        wait_for(lambda: coordinator.status()["currentTargetId"] == third["id"])
        self.detector.inject(kind="hundo", message="Hundo Squirtle")
        wait_for(lambda: self.store.get_sighting(third["id"])["status"] == "checked")
        wait_for(lambda: coordinator.status()["ipogoRefreshState"] == "verified")

        status = coordinator.status()
        self.assertEqual(status["ipogoRefreshesThisRun"], 1)
        self.assertEqual(status["ipogoRefreshState"], "verified")
        self.assertEqual(status["ipogoConsecutiveTimeouts"], 0)

    def test_screen_probes_never_replenish_bad_coordinate_timer(self):
        first,_=self.store.add(payload("1","Bulbasaur"))
        second,_=self.store.add(payload("2","Charmander"))
        self.store.save_preferences("all",["Bulbasaur","Charmander"])
        coordinator=self.coordinator(dwell_seconds=.08)
        guard=Mock()
        guard.recover_hunt_screen.side_effect=lambda reason,check,probe=False,after_hundo=False: time.sleep(.025)
        coordinator.encounter_guard=guard
        coordinator.prepare();coordinator.start()
        wait_for(lambda: self.store.get_sighting(second["id"])["status"]=="checked")
        self.assertEqual(self.store.get_sighting(first["id"])["completion_reason"],"timeout-no-alert")
        self.assertEqual(coordinator.status()["huntState"],"running")
        self.assertEqual(coordinator.status()["huntTimeoutsThisRun"],2)

    def test_coordinate_deadline_cancels_slow_screen_cleanup_then_advances(self):
        first,_=self.store.add(payload("1","Bulbasaur"))
        second,_=self.store.add(payload("2","Charmander"))
        self.store.save_preferences("all",["Bulbasaur","Charmander"])
        coordinator=self.coordinator(dwell_seconds=.08)
        guard=Mock()
        def cleanup(reason,check,probe=False,after_hundo=False):
            while True:
                check()
                time.sleep(.005)
        guard.recover_hunt_screen.side_effect=cleanup
        coordinator.encounter_guard=guard
        coordinator.prepare();coordinator.start()
        wait_for(lambda: self.store.get_sighting(second["id"])["status"]=="checked")
        self.assertEqual(self.store.get_sighting(first["id"])["completion_reason"],"timeout-no-alert")
        self.assertEqual(coordinator.status()["huntState"],"running")

    def test_bad_coordinate_after_refresh_does_not_pause_or_lock_hunt(self):
        first, _ = self.store.add(payload("1", "Bulbasaur"))
        second, _ = self.store.add(payload("2", "Charmander"))
        third, _ = self.store.add(payload("3", "Squirtle"))
        self.store.save_preferences("all", ["Bulbasaur", "Charmander", "Squirtle"])
        coordinator = self.coordinator(
            dwell_seconds=0.08,
            ipogo_recovery_timeout_threshold=2,
            ipogo_restart_settle_seconds=0.05,
            ipogo_recovery_dwell_seconds=0.08,
        )
        coordinator.prepare()
        coordinator.start()

        wait_for(lambda: self.store.get_sighting(first["id"])["status"] == "checked")
        wait_for(lambda: len(self.device.restarts) == 1)
        self.assertEqual(self.store.get_sighting(second["id"])["status"], "checked")
        wait_for(lambda: self.store.get_sighting(third["id"])["status"] == "checked")
        wait_for(lambda: coordinator.status()["huntPhase"] == "waiting")
        self.assertEqual(coordinator.status()["huntState"], "running")
        self.assertFalse(coordinator.status()["ipogoRecoveryTargetLocked"])

    def test_start_requires_connected_phone_and_explicit_preparation(self):
        self.store.add(payload("1"))
        coordinator = self.coordinator(dwell_seconds=0.1)

        with self.assertRaisesRegex(HuntError, "Prepare"):
            coordinator.start()

        coordinator.prepare()
        self.device.connected = False
        with self.assertRaisesRegex(HuntError, "No paired USB"):
            coordinator.start()

        status = coordinator.status()
        self.assertTrue(status["ipogoPrepared"])
        self.assertFalse(status["huntWorkerAlive"])

    def test_timing_configuration_updates_defaults_and_locks_during_hunt(self):
        self.store.add(payload("1", "Bulbasaur"))
        coordinator = self.coordinator(dwell_seconds=45)
        status = coordinator.configure_timing(80, 4, 25)
        self.assertEqual(status["huntDwellSeconds"], 80)
        self.assertEqual(status["ipogoRecoveryTimeoutThreshold"], 4)
        self.assertEqual(status["huntHundoCooldownSeconds"], 25)

        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")
        with self.assertRaisesRegex(HuntError, "Stop the hunt"):
            coordinator.configure_timing(30, 3, 10)

    def test_prepare_requires_a_connected_phone(self):
        self.device.connected = False
        coordinator = self.coordinator()
        with self.assertRaisesRegex(HuntError, "No paired USB"):
            coordinator.prepare()
        self.assertFalse(coordinator.status()["ipogoPrepared"])

    def test_runs_ranked_targets_and_checks_only_after_each_dwell(self):
        bulbasaur, _ = self.store.add(payload("1", "Bulbasaur"))
        eevee, _ = self.store.add(payload("2", "Eevee"))
        self.store.save_preferences("all", ["Eevee", "Bulbasaur"])
        coordinator = self.coordinator(dwell_seconds=0.18)
        coordinator.prepare()
        coordinator.start()

        wait_for(lambda: len(self.device.locations) == 1)
        self.assertEqual(self.device.locations[0][0], eevee["latitude"])
        self.assertEqual(self.device.hunt_locations[0][0], eevee["latitude"])
        self.assertEqual(self.store.stats()["checked"], 0)

        wait_for(lambda: self.store.stats()["checked"] >= 1)
        wait_for(lambda: len(self.device.locations) == 2)
        self.assertEqual(self.device.locations[1][0], bulbasaur["latitude"])
        self.assertEqual(self.device.hunt_locations[1][0], bulbasaur["latitude"])
        wait_for(lambda: self.store.stats()["checked"] == 2)
        wait_for(lambda: coordinator.status()["huntPhase"] == "waiting")

        self.assertEqual(coordinator.status()["huntCheckedThisRun"], 2)
        self.assertEqual(coordinator.status()["huntTimeoutsThisRun"], 2)
        self.assertEqual(self.store.get_sighting(eevee["id"])["completion_reason"], "timeout-no-alert")
        self.assertIn("No iPogo alert", self.store.get_sighting(eevee["id"])["completion_message"])

    def test_pause_freezes_dwell_and_skip_remains_responsive(self):
        target, _ = self.store.add(payload("1"))
        coordinator = self.coordinator(dwell_seconds=1.0)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        coordinator.pause()
        wait_for(lambda: coordinator.status()["huntState"] == "paused")
        remaining = coordinator.status()["huntSecondsRemaining"]
        time.sleep(0.2)
        self.assertEqual(self.store.stats()["checked"], 0)
        self.assertEqual(coordinator.status()["huntSecondsRemaining"], remaining)

        coordinator.skip()
        wait_for(lambda: self.store.get_sighting(target["id"])["status"] == "skipped")
        status = coordinator.status()
        self.assertEqual(status["huntSkippedThisRun"], 1)
        self.assertEqual(status["ipogoVisitsSinceRefresh"], 0)
        self.assertEqual(status["ipogoConsecutiveTimeouts"], 0)
        self.assertEqual(status["ipogoRefreshesThisRun"], 0)
        self.assertEqual(self.store.stats()["checked"], 0)

    def test_manual_skips_do_not_trigger_visit_or_failure_refresh(self):
        first, _ = self.store.add(payload("1", "Bulbasaur"))
        second, _ = self.store.add(payload("2", "Charmander"))
        third, _ = self.store.add(payload("3", "Squirtle"))
        self.store.save_preferences("all", ["Bulbasaur", "Charmander", "Squirtle"])
        coordinator = self.coordinator(
            dwell_seconds=1.0,
            ipogo_refresh_visit_interval=2,
            ipogo_recovery_timeout_threshold=2,
            ipogo_restart_settle_seconds=0.05,
        )
        coordinator.prepare()
        coordinator.start()

        wait_for(lambda: coordinator.status()["currentTargetId"] == first["id"])
        coordinator.skip()
        wait_for(lambda: coordinator.status()["currentTargetId"] == second["id"])
        coordinator.skip()
        wait_for(lambda: coordinator.status()["currentTargetId"] == third["id"])

        status = coordinator.status()
        self.assertEqual(status["huntSkippedThisRun"], 2)
        self.assertEqual(status["ipogoVisitsSinceRefresh"], 1)
        self.assertEqual(status["ipogoConsecutiveTimeouts"], 0)
        self.assertEqual(status["ipogoRefreshesThisRun"], 0)
        self.assertEqual(self.device.restarts, [])

    def test_notification_bridge_loss_pauses_without_advancing_target(self):
        target, _ = self.store.add(payload("1", "Bulbasaur"))
        detector = BridgeDependentDetector()
        coordinator = HuntCoordinator(
            self.store,
            self.device,
            detector,
            dwell_seconds=1.0,
            idle_poll_seconds=0.05,
            ipogo_clean_start=False,
            notifier=lambda _title, _message: None,
        )
        self.coordinators.append(coordinator)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        detector.ready = False
        wait_for(lambda: coordinator.status()["huntPhase"] == "paused-alerts")

        status = coordinator.status()
        self.assertEqual(status["huntState"], "paused")
        self.assertEqual(self.store.get_sighting(target["id"])["status"], "current")
        self.assertEqual(status["huntCheckedThisRun"], 0)

    def test_alert_is_processed_before_simultaneous_offline_health_sample(self):
        target, _ = self.store.add(payload("1", "Bulbasaur"))
        detector = AlertWithOfflineSampleDetector()
        coordinator = HuntCoordinator(
            self.store,
            self.device,
            detector,
            dwell_seconds=1.0,
            idle_poll_seconds=0.05,
            ipogo_clean_start=False,
            notifier=lambda _title, _message: None,
        )
        self.coordinators.append(coordinator)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        detector.inject(kind="hundo", message="Hundo Bulbasaur appeared")
        wait_for(lambda: self.store.get_sighting(target["id"])["status"] == "checked")

        completed = self.store.get_sighting(target["id"])
        self.assertEqual(completed["completion_reason"], "hundo-notification")
        self.assertEqual(coordinator.status()["huntNotificationsConfirmedThisRun"], 1)

    def test_paused_alert_monitor_recovers_and_consumes_pending_alert(self):
        target, _ = self.store.add(payload("1", "Charmander"))
        detector = BridgeDependentDetector()
        coordinator = HuntCoordinator(
            self.store,
            self.device,
            detector,
            dwell_seconds=1.0,
            idle_poll_seconds=0.05,
            ipogo_clean_start=False,
            notifier=lambda _title, _message: None,
        )
        self.coordinators.append(coordinator)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        detector.ready = False
        wait_for(lambda: coordinator.status()["huntPhase"] == "paused-alerts")
        detector.inject(kind="hundo", message="Hundo Charmander appeared")
        detector.ready = True

        wait_for(
            lambda: (
                self.store.get_sighting(target["id"])["completion_reason"] == "hundo-notification"
                and coordinator.status()["huntNotificationsConfirmedThisRun"] == 1
            ),
            timeout=4.0,
        )
        self.assertEqual(coordinator.status()["huntNotificationsConfirmedThisRun"], 1)

    def test_manual_shundo_signal_stops_hunt(self):
        target, _ = self.store.add(payload("1", "Charmander"))
        alarms: list[str] = []
        coordinator = self.coordinator(
            dwell_seconds=1.0,
            shundo_alarm=lambda: alarms.append("played"),
        )
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        coordinator.inject_notification(kind="shundo", message="Shundo Charmander nearby")
        wait_for(lambda: coordinator.status()["huntState"] == "shundo")

        status = coordinator.status()
        self.assertEqual(status["huntPhase"], "shundo")
        self.assertEqual(status["currentTargetId"], target["id"])
        self.assertFalse(status["huntWorkerAlive"])
        completed = self.store.get_sighting(target["id"])
        self.assertEqual(completed["status"], "shundo")
        self.assertEqual(completed["completion_reason"], "shundo-notification")
        self.assertIsNotNone(completed["notification_received_at"])
        self.assertEqual(status["huntNotificationsConfirmedThisRun"], 1)
        self.assertEqual(status["huntLastNotificationProof"]["action"], "hunt-stopped")
        self.assertEqual(self.store.stats()["shundos"], 1)
        self.assertEqual(alarms, ["played"])

    def test_regular_hundo_signal_advances_without_waiting_for_timeout(self):
        first, _ = self.store.add(payload("1", "Squirtle"))
        coordinator = self.coordinator(dwell_seconds=5.0)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        coordinator.inject_notification(kind="hundo", message="Hundo confirmed nearby")
        wait_for(lambda: self.store.get_sighting(first["id"])["status"] == "checked")
        wait_for(lambda: coordinator.status()["huntPhase"] == "waiting")

        status = coordinator.status()
        completed = self.store.get_sighting(first["id"])
        self.assertEqual(status["huntCheckedThisRun"], 1)
        self.assertEqual(status["huntNotificationsConfirmedThisRun"], 1)
        self.assertTrue(status["notificationObservedSincePrepare"])
        self.assertEqual(status["huntLastNotificationProof"]["action"], "advanced")
        self.assertEqual(completed["completion_reason"], "hundo-notification")
        self.assertEqual(completed["completion_message"], "Hundo confirmed nearby")
        self.assertIsNotNone(completed["notification_received_at"])

    def test_hundo_cleanup_retains_proof_without_double_counting_or_moving(self):
        from shundo_hunter.screen_recovery import RecoveryCancelled
        first,_=self.store.add(payload("1","Squirtle"))
        c=self.coordinator(dwell_seconds=5)
        guard=Mock()
        attempts=[]
        def cleanup(reason,check,probe=False,after_hundo=False):
            check()
            if after_hundo:
                self.assertEqual(len(self.device.locations),1)
                attempts.append(1)
                if len(attempts)==1:raise RecoveryCancelled("transient interruption")
        guard.recover_hunt_screen.side_effect=cleanup
        c.encounter_guard=guard
        c.prepare();c.start()
        wait_for(lambda:c.status()["huntPhase"]=="dwelling")
        c.inject_notification(kind="hundo",message="Hundo Squirtle")
        wait_for(lambda:self.store.get_sighting(first["id"])["status"]=="checked")
        self.assertEqual(len(attempts),2)
        self.assertEqual(c.status()["huntNotificationsConfirmedThisRun"],1)
        self.assertEqual(c.status()["huntCheckedThisRun"],1)

    def test_shundo_arriving_during_post_hundo_cleanup_wins_before_advance(self):
        from shundo_hunter.screen_recovery import RecoveryCancelled
        first,_=self.store.add(payload("1","Squirtle"))
        self.store.add(payload("2","Charmander"))
        self.store.save_preferences("all",["Squirtle","Charmander"])
        c=self.coordinator(dwell_seconds=5)
        guard=Mock()
        def cleanup(reason,check,probe=False,after_hundo=False):
            check()
            if after_hundo:
                c.inject_notification(kind="shundo",message="Shundo Squirtle")
                raise RecoveryCancelled("Shundo pending")
        guard.recover_hunt_screen.side_effect=cleanup
        c.encounter_guard=guard
        c.prepare();c.start()
        wait_for(lambda:c.status()["huntPhase"]=="dwelling")
        c.inject_notification(kind="hundo",message="Hundo Squirtle")
        wait_for(lambda:c.status()["huntState"]=="shundo")
        self.assertEqual(self.store.get_sighting(first["id"])["status"],"shundo")
        self.assertEqual(len(self.device.locations),1)
        self.assertEqual(c.status()["huntNotificationsConfirmedThisRun"],1)
        guard.latch_shundo.assert_called_once()

    def test_hundo_cooldown_holds_location_before_next_check(self):
        first, _ = self.store.add(payload("1", "Squirtle"))
        second, _ = self.store.add(payload("2", "Charmander"))
        self.store.save_preferences("all", ["Squirtle", "Charmander"])
        coordinator = self.coordinator(
            dwell_seconds=5.0,
            hundo_cooldown_seconds=0.3,
        )
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        confirmed_at = time.monotonic()
        coordinator.inject_notification(kind="hundo", message="Hundo confirmed nearby")
        wait_for(lambda: self.store.get_sighting(first["id"])["status"] == "checked")
        wait_for(lambda: coordinator.status()["huntPhase"] == "cooldown")
        cooldown_status = coordinator.status()
        self.assertEqual(len(self.device.locations), 1)
        self.assertGreater(cooldown_status["huntSecondsRemaining"], 0)
        self.assertEqual(cooldown_status["huntLastNotificationProof"]["action"], "cooldown")

        wait_for(
            lambda: coordinator.status()["currentTargetId"] == second["id"]
            and coordinator.status()["huntPhase"] == "dwelling"
        )
        self.assertGreaterEqual(time.monotonic() - confirmed_at, 0.25)
        self.assertEqual(len(self.device.locations), 2)
        self.assertEqual(
            coordinator.status()["huntLastNotificationProof"]["action"],
            "advanced-after-cooldown",
        )

    def test_pausing_freezes_hundo_cooldown(self):
        first, _ = self.store.add(payload("1", "Squirtle"))
        second, _ = self.store.add(payload("2", "Charmander"))
        self.store.save_preferences("all", ["Squirtle", "Charmander"])
        coordinator = self.coordinator(
            dwell_seconds=5.0,
            hundo_cooldown_seconds=0.4,
        )
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")
        coordinator.inject_notification(kind="hundo", message="Hundo confirmed nearby")
        wait_for(lambda: coordinator.status()["huntPhase"] == "cooldown")

        coordinator.pause()
        paused_remaining = coordinator.status()["huntSecondsRemaining"]
        time.sleep(0.45)
        self.assertEqual(coordinator.status()["huntSecondsRemaining"], paused_remaining)
        self.assertEqual(len(self.device.locations), 1)

        coordinator.start()
        wait_for(
            lambda: coordinator.status()["currentTargetId"] == second["id"]
            and coordinator.status()["huntPhase"] == "dwelling"
        )
        self.assertEqual(self.store.get_sighting(first["id"])["status"], "checked")
        self.assertEqual(len(self.device.locations), 2)

    def test_shundo_stops_immediately_even_with_hundo_cooldown(self):
        target, _ = self.store.add(payload("1", "Charmander"))
        alarms: list[str] = []
        coordinator = self.coordinator(
            dwell_seconds=5.0,
            hundo_cooldown_seconds=5.0,
            shundo_alarm=lambda: alarms.append("played"),
        )
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        detected_at = time.monotonic()
        coordinator.inject_notification(kind="shundo", message="Shundo Charmander nearby")
        wait_for(lambda: coordinator.status()["huntState"] == "shundo")

        self.assertLess(time.monotonic() - detected_at, 0.5)
        self.assertEqual(self.store.get_sighting(target["id"])["status"], "shundo")
        self.assertEqual(coordinator.status()["huntPhase"], "shundo")
        self.assertEqual(alarms, ["played"])

    def test_expires_stale_sightings_before_selection(self):
        stale, _ = self.store.add(payload("1", "Oldmon"))
        fresh, _ = self.store.add(payload("2", "Freshmon"))
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        with self.store.lock, self.store._connect() as connection:
            connection.execute(
                "UPDATE sightings SET received_at=? WHERE id=?", (old_time, stale["id"])
            )

        coordinator = self.coordinator(dwell_seconds=0.2, max_sighting_age_seconds=30)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: len(self.device.locations) == 1)

        self.assertEqual(self.device.locations[0][0], fresh["latitude"])
        with self.assertRaises(ValueError):
            self.store.get_sighting(stale["id"])

    def test_start_discards_orphaned_current_and_selects_fresh_queue_target(self):
        orphaned, _ = self.store.add(payload("1", "OldSquirtle"))
        fresh, _ = self.store.add(payload("2", "FreshSquirtle"))
        with self.store.lock, self.store._connect() as connection:
            connection.execute("UPDATE sightings SET status='current' WHERE id=?", (orphaned["id"],))

        coordinator = self.coordinator(dwell_seconds=0.2)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: len(self.device.locations) == 1)

        self.assertEqual(self.device.locations[0][0], fresh["latitude"])
        with self.assertRaises(ValueError):
            self.store.get_sighting(orphaned["id"])

    def test_restoring_real_location_stops_worker_and_expires_current_target(self):
        target, _ = self.store.add(payload("1", "Squirtle"))
        coordinator = self.coordinator(dwell_seconds=5.0)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        status = coordinator.stop_for_real_location()
        wait_for(lambda: not coordinator.status()["huntWorkerAlive"])

        self.assertEqual(status["huntState"], "idle")
        self.assertFalse(status["ipogoPrepared"])
        with self.assertRaises(ValueError):
            self.store.get_sighting(target["id"])

    def test_status_exposes_ui_contract_and_unprepare_stops_worker(self):
        self.store.add(payload("1"))
        coordinator = self.coordinator(dwell_seconds=1.0)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntWorkerAlive"])

        expected = {
            "huntPhase",
            "huntMessage",
            "huntSecondsRemaining",
            "ipogoPrepared",
            "notificationWatcherState",
            "currentTargetId",
        }
        self.assertTrue(expected.issubset(coordinator.status()))

        coordinator.unprepare()
        wait_for(lambda: not coordinator.status()["huntWorkerAlive"])
        status = coordinator.status()
        self.assertEqual(status["huntPhase"], "unprepared")
        self.assertFalse(status["ipogoPrepared"])

    def test_usb_detector_scopes_device_markers_to_active_target(self):
        watcher = FakeWatcher()
        detector = USBNotificationDetector(watcher)
        target = {"id": 42}
        watcher.emit("old Shundo", True)
        detector.start("phone-udid")
        detector.begin_target(target)
        self.assertIsNone(detector.poll(42))

        watcher.emit("A regular Hundo appeared", False, True)
        event = detector.poll(42)
        self.assertIsNotNone(event)
        self.assertTrue(event.is_hundo)
        self.assertFalse(event.is_shundo)

        watcher.emit("A Shundo appeared", True)
        event = detector.poll(42)
        self.assertTrue(event.is_shundo)
        self.assertEqual(watcher.started_udid, "phone-udid")

    def test_usb_detector_accepts_mac_mirrored_hundo(self):
        watcher = FakeWatcher()
        watcher.record_external = lambda text: watcher.emit(text, False, True)
        detector = USBNotificationDetector(watcher)
        detector.begin_target({"id": 7})

        result = detector.update_mac_bridge({
            "type": "notification",
            "state": "listening",
            "trusted": True,
            "appName": "Pokémon GO",
            "title": "Hundo nearby",
            "body": "Squirtle appeared nearby",
        })
        event = detector.poll(7)

        self.assertTrue(result["accepted"])
        self.assertTrue(event.is_hundo)
        self.assertFalse(event.is_shundo)
        self.assertEqual(detector.status()["macBridgeState"], "listening")
        self.assertTrue(detector.status()["unattendedReady"])

    def test_usb_detector_uses_live_mac_bridge_when_usb_fallback_stops(self):
        watcher = FakeWatcher()
        watcher.status = lambda: {
            "notificationWatcherState": "stopped",
            "notificationWatcherLastError": "USB stream ended",
            "notificationSequence": watcher.sequence,
        }
        detector = USBNotificationDetector(watcher)
        detector.update_mac_bridge({
            "type": "status",
            "state": "listening",
            "trusted": True,
        })

        status = detector.status()
        self.assertEqual(status["state"], "listening")
        self.assertEqual(status["usbWatcherState"], "stopped")
        self.assertTrue(status["macBridgeReady"])
        self.assertTrue(status["unattendedReady"])

    def test_usb_detector_accepts_fresh_hundo_when_species_labels_differ(self):
        watcher = FakeWatcher()
        detector = USBNotificationDetector(watcher)
        detector.begin_target({"id": 9, "species": "Charmander"})

        watcher.emit("Hundo Bulbasaur appeared nearby", False, True)
        event = detector.poll(9)

        self.assertIsNotNone(event)
        self.assertIn("Bulbasaur", event.message)
        self.assertIn("Bulbasaur", detector.status()["lastUnmatchedEvent"]["message"])
        self.assertEqual(detector.status()["acceptedSpeciesMismatchCount"], 1)

    def test_usb_detector_accepts_gender_label_variant_as_fresh_hundo_proof(self):
        watcher = FakeWatcher()
        detector = USBNotificationDetector(watcher)
        detector.begin_target({"id": 10, "species": "Nidoran-m"})

        watcher.emit("Hundo Nidoran♂ appeared nearby", False, True)
        event = detector.poll(10)

        self.assertIsNotNone(event)
        self.assertTrue(event.is_hundo)
        self.assertIn("Nidoran♂", event.message)

    def test_world_scan_requires_fresh_populated_scanner_evidence(self):
        watcher = FakeWatcher()
        world = FakeWorldWatcher()
        detector = USBNotificationDetector(
            watcher,
            world,
            world_signal_minimum_delay_seconds=0,
            world_notification_grace_seconds=0,
        )
        detector.begin_target({"id": 11, "species": "Pidove"})

        world.emit(2, 0)
        world.emit(2, 13)
        evidence = detector.poll_world(11)

        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["spawnCount"], 13)
        self.assertTrue(evidence["resetObserved"])
        self.assertIsNone(detector.poll_world(11))

    def test_world_scan_can_use_two_corroborating_arrays_without_reset(self):
        watcher = FakeWatcher()
        world = FakeWorldWatcher()
        detector = USBNotificationDetector(
            watcher,
            world,
            world_signal_minimum_delay_seconds=0,
            world_notification_grace_seconds=0,
        )
        detector.begin_target({"id": 12})

        world.emit(2, 9)
        self.assertIsNone(detector.poll_world(12))
        world.emit(4, 5)
        evidence = detector.poll_world(12)

        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["counts"]["wild-pokemon"], 9)
        self.assertEqual(evidence["counts"]["pokestops"], 5)

    def test_coordinator_advances_on_world_loaded_without_hundo(self):
        target, _ = self.store.add(payload("71", "Pidove"))
        watcher = FakeWatcher()
        world = FakeWorldWatcher()
        detector = USBNotificationDetector(
            watcher,
            world,
            world_signal_minimum_delay_seconds=0,
            world_notification_grace_seconds=0,
        )
        detector.update_mac_bridge({
            "type": "status",
            "state": "listening",
            "trusted": True,
        })
        coordinator = HuntCoordinator(
            self.store,
            self.device,
            detector,
            dwell_seconds=5,
            idle_poll_seconds=0.02,
            ipogo_clean_start=False,
            ipogo_refresh_confirmed_interval=999,
            ipogo_refresh_visit_interval=999,
            ipogo_recovery_timeout_threshold=2,
            notifier=lambda _title, _message: None,
        )
        self.coordinators.append(coordinator)
        coordinator.prepare()
        coordinator.start()
        wait_for(lambda: coordinator.status()["huntPhase"] == "dwelling")

        world.emit(1, 0)
        world.emit(1, 6)
        wait_for(
            lambda: self.store.get_sighting(target["id"])["completion_reason"]
            == "world-loaded-no-hundo"
            and coordinator.status()["huntWorldReadySkipsThisRun"] == 1
        )

        status = coordinator.status()
        self.assertEqual(status["huntWorldReadySkipsThisRun"], 1)
        self.assertEqual(status["huntTimeoutsThisRun"], 0)
        self.assertEqual(status["ipogoConsecutiveTimeouts"], 0)


if __name__ == "__main__":
    unittest.main()
