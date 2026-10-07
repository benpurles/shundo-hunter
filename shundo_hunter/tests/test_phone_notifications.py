import time
import unittest
from unittest.mock import patch

from shundo_hunter.phone_notifications import PhoneBannerReader
from shundo_hunter.notification_service import NotificationWatcher


def snapshot(*texts, active=True, locked=False):
    return {"protocol": 1, "source": "iphone-banner", "gameActive": active, "screenLocked": locked,
            "banners": [{"sourceBundleId": "com.nianticlabs.pokemongo", "text": t} for t in texts]}


class PhoneBannerTests(unittest.TestCase):
    def setUp(self):
        self.reader = PhoneBannerReader()

    def test_existing_banner_is_not_fresh_proof(self):
        self.assertEqual(self.reader.consume(snapshot("Pokémon GO · A Hundo Litten appeared nearby!")), [])
        self.assertEqual(self.reader.consume(snapshot("Pokémon GO · A Hundo Litten appeared nearby!")), [])

    def test_new_hundo_then_shundo(self):
        self.reader.consume(snapshot())
        self.assertEqual(self.reader.consume(snapshot("Pokémon GO · now · A Hundo Litten appeared nearby!")), ["A Hundo Litten appeared nearby!"])
        self.assertEqual(self.reader.consume(snapshot("Pokémon GO · A Shundo Beldum appeared nearby!")), ["A Shundo Beldum appeared nearby!"])

    def test_relative_age_does_not_duplicate(self):
        self.reader.consume(snapshot())
        self.reader.consume(snapshot("Pokémon GO · now · A Hundo Litten appeared nearby!"))
        self.assertEqual(self.reader.consume(snapshot("Pokémon GO · 1m · A Hundo Litten appeared nearby!")), [])

    def test_observed_ios_banner_without_nearby(self):
        self.reader.consume(snapshot())
        self.assertEqual(self.reader.consume(snapshot(
            "POKÉMON GO, now, Pokémon GO, Hundo Nidoking appeared · Hundo Nidoking appeared"
        )), ["Hundo Nidoking appeared"])
        self.assertEqual(self.reader.consume(snapshot(
            "POKÉMON GO, 1m, Pokémon GO, Hundo Nidoking appeared"
        )), [])
        self.assertEqual(self.reader.consume(snapshot(
            "Pokémon GO · Shundo Beldum appeared"
        )), ["Shundo Beldum appeared"])

    def test_same_species_after_banner_disappears_is_new(self):
        self.reader.consume(snapshot())
        self.reader.consume(snapshot("A Hundo Litten appeared nearby!"))
        self.reader.consume(snapshot())
        self.assertEqual(len(self.reader.consume(snapshot("A Hundo Litten appeared nearby!"))), 1)

    def test_reconnect_baselines_old_banner(self):
        self.reader.consume(snapshot())
        self.reader.reset()
        self.assertEqual(self.reader.consume(snapshot("A Shundo Litten appeared nearby!")), [])

    def test_other_app_or_locked_phone_rejected(self):
        for data in [snapshot(locked=True), {**snapshot(), "screenLocked": None}, {**snapshot(), "source": "mac"}, {**snapshot(), "protocol": 0},
                     {**snapshot(), "banners": [{"sourceBundleId": "other.app", "text": "Hundo Litten appeared nearby"}]}]:
            with self.assertRaises(RuntimeError):
                self.reader.consume(data)

    def test_intentional_game_restart_does_not_disconnect_transport(self):
        self.reader.consume(snapshot())
        self.assertEqual(self.reader.consume(snapshot(active=False)), [])
        self.assertEqual(self.reader.consume(snapshot("Hundo Treecko appeared")), ["Hundo Treecko appeared"])

    def test_generic_notification_never_proves_hundo(self):
        self.reader.consume(snapshot())
        self.assertEqual(self.reader.consume(snapshot("Notification sent", "Shiny Litten appeared nearby", "Hundo loading")), [])

    def test_listener_records_real_reader_event_and_revokes_on_failure(self):
        watcher = NotificationWatcher()
        watcher.use_phone_banners = True
        with patch.object(PhoneBannerReader, "read", side_effect=[[], ["A Hundo Litten appeared nearby!"], RuntimeError("offline")]):
            watcher.start("test-device")
            until = time.monotonic()+2
            while time.monotonic()<until and not watcher.status()["directAlertProof"]:
                time.sleep(.02)
            self.assertEqual(watcher.status()["directAlertProof"]["source"], "iphone-banner")
            until = time.monotonic()+2
            while time.monotonic()<until and watcher.status()["notificationWatcherState"] != "error":
                time.sleep(.02)
            self.assertIsNone(watcher.status()["directAlertProof"])
            watcher.stop()
            self.assertEqual(watcher.status()["notificationWatcherState"], "stopped")

    def test_stale_heartbeat_cannot_be_ready(self):
        watcher = NotificationWatcher()
        watcher.use_phone_banners = True
        watcher.state = "listening"
        watcher.banner_heartbeat = time.monotonic()-20
        watcher.direct_proof = {"text": "A Hundo Litten appeared nearby"}
        self.assertEqual(watcher.status()["notificationWatcherState"], "error")
        self.assertIsNone(watcher.status()["directAlertProof"])


if __name__ == "__main__":
    unittest.main()
