import threading
import unittest

from shundo_hunter.notification_service import (
    MARKER,
    WORLD_SCAN_MARKER,
    NotificationWatcher,
    WorldScanWatcher,
)


class NotificationWatcherTests(unittest.TestCase):
    def setUp(self):
        self.watcher = NotificationWatcher(executable="/usr/bin/false")

    def test_ignores_unmarked_log_lines(self):
        self.assertIsNone(self.watcher._handle_line("ordinary iPogo log line"))
        self.assertEqual(self.watcher.checkpoint(), 0)

    def test_records_and_classifies_marker(self):
        event = self.watcher._handle_line(
            f"PokmonGO: {MARKER} A Shundo Slowpoke appeared nearby"
        )
        self.assertIsNotNone(event)
        self.assertTrue(event.is_hundo)
        self.assertTrue(event.is_shundo)
        self.assertEqual(event.sequence, 1)
        self.assertIn("Slowpoke", event.text)

    def test_checkpoint_excludes_old_alerts(self):
        self.watcher._handle_line(f"{MARKER} old Shundo")
        checkpoint = self.watcher.checkpoint()
        self.assertIsNone(self.watcher.wait_for_shundo(checkpoint, 0.01))
        self.watcher._handle_line(f"{MARKER} Hundo only")
        self.assertIsNone(self.watcher.wait_for_shundo(checkpoint, 0.01))
        self.watcher._handle_line(f"{MARKER} new SHUNDO")
        self.assertEqual(self.watcher.wait_for_shundo(checkpoint, 0.01).sequence, 3)

    def test_classifies_regular_hundo_without_calling_it_shundo(self):
        event = self.watcher._handle_line(f"{MARKER} A Hundo Squirtle appeared nearby")
        self.assertTrue(event.is_hundo)
        self.assertFalse(event.is_shundo)

    def test_records_native_mac_notification_text(self):
        event = self.watcher.record_external("Pokémon GO Hundo Squirtle appeared nearby")
        self.assertEqual(event.sequence, 1)
        self.assertTrue(event.is_hundo)
        self.assertFalse(event.is_shundo)

    def test_app_name_does_not_trigger_false_shundo(self):
        event = self.watcher.record_external(
            "iPhone notification · Shundo Hunter · Apple · System Settings"
        )
        self.assertIsNone(event)
        self.assertEqual(self.watcher.checkpoint(), 0)

    def test_ignores_hunter_pause_notification_that_mentions_no_hundo_and_ipogo(self):
        event = self.watcher.record_external(
            "Script Editor · Shundo Hunter paused · No Hundo alert arrived for Machop after iPogo was refreshed"
        )
        self.assertIsNone(event)
        self.assertEqual(self.watcher.checkpoint(), 0)

    def test_cancel_ends_wait(self):
        cancel = threading.Event()
        cancel.set()
        self.assertIsNone(self.watcher.wait_for_shundo(0, 5, cancel))


class WorldScanWatcherTests(unittest.TestCase):
    def setUp(self):
        self.watcher = WorldScanWatcher(executable="/usr/bin/false")

    def test_parses_bounded_world_array_marker(self):
        event = self.watcher._handle_line(
            f"PokmonGO: {WORLD_SCAN_MARKER} wild=17 nearby=3 gyms=2 stops=9"
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "pokestops")
        self.assertEqual(event.count, 9)
        self.assertGreater(event.received_monotonic, 0)
        snapshot = self.watcher.status()["lastWorldScanSnapshot"]
        self.assertEqual(snapshot["spawnCount"], 20)
        self.assertEqual(snapshot["gyms"], 2)

    def test_ignores_unknown_kind_and_unmarked_lines(self):
        self.assertIsNone(self.watcher._handle_line("ordinary map activity"))
        self.assertIsNone(self.watcher._handle_line(f"{WORLD_SCAN_MARKER} bad data"))
        self.assertEqual(self.watcher.checkpoint(), 0)

    def test_checkpoint_scopes_events(self):
        self.watcher._handle_line(
            f"{WORLD_SCAN_MARKER} wild=0 nearby=0 gyms=0 stops=0"
        )
        checkpoint = self.watcher.checkpoint()
        self.watcher._handle_line(
            f"{WORLD_SCAN_MARKER} wild=12 nearby=1 gyms=4 stops=8"
        )
        events = self.watcher.events_after(checkpoint)
        self.assertEqual(len(events), 4)
        self.assertEqual(
            {event.kind: event.count for event in events},
            {"wild-pokemon": 12, "nearby-pokemon": 1, "gyms": 4, "pokestops": 8},
        )


if __name__ == "__main__":
    unittest.main()
