import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from shundo_hunter.feed_server import POKEXPERIENCE_SOURCE, SightingStore
from shundo_hunter.internal_feed import InternalFeedItem


def payload(message_id: str, species: str = "Bulbasaur", level: int = 25) -> dict:
    return {
        "guildId": "guild",
        "channelId": "channel",
        "channelName": "💯gen1",
        "messageId": message_id,
        "rawText": f"***{species}*** **CP637** **L{level}** ✨",
        "resolvedCoordinate": {
            "latitude": 40.758701 + int(message_id) / 100_000,
            "longitude": -111.876183,
            "url": f"https://pokedex100.com/{message_id}",
        },
    }


def pokexperience_payload(items: list[dict], message: str = "Test snapshot") -> dict:
    return {
        "type": "snapshot",
        "state": "synced",
        "message": message,
        "appRunning": True,
        "trusted": True,
        "items": items,
    }


def pokexperience_item(
    species: str,
    latitude: float,
    *,
    cp: int = 500,
    level: int = 20,
    remaining_minutes: int = 10,
) -> dict:
    return {
        "species": species,
        "latitude": latitude,
        "longitude": -111.8910,
        "cp": cp,
        "level": level,
        "city": "Salt Lake City",
        "gender": "male",
        "expiresAt": (
            datetime.now(timezone.utc) + timedelta(minutes=remaining_minutes)
        ).isoformat(),
    }


def pokexperience_metadata_payload(
    items: list[dict],
    *,
    scope: str = "fallback",
    generation: str = "test-generation",
    complete_catalog: bool = False,
) -> dict:
    return {
        "type": "metadata-snapshot",
        "scope": scope,
        "generation": generation,
        "completeForScope": True,
        "completeCatalog": complete_catalog,
        "catalogRowsInspected": len(items),
        "catalogPagesScanned": 10,
        "state": "synced",
        "message": "Metadata-only test snapshot",
        "appRunning": True,
        "trusted": True,
        "items": items,
    }


def pokexperience_metadata_item(
    species: str,
    *,
    cp: int = 500,
    level: int = 20,
    source_index: int = 0,
    remaining_minutes: int = 10,
) -> dict:
    return {
        "species": species,
        "cp": cp,
        "level": level,
        "city": "Salt Lake City",
        "country": "United States",
        "gender": "male",
        "sourceIndex": source_index,
        "expiresAt": (
            datetime.now(timezone.utc) + timedelta(minutes=remaining_minutes)
        ).isoformat(),
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SightingStore(Path(self.temp_dir.name) / "test.db")
        self.store.set_feed_source("discord")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_deduplicates_messages(self):
        first, inserted = self.store.add(payload("1"))
        duplicate, duplicate_inserted = self.store.add(payload("1"))
        self.assertTrue(inserted)
        self.assertFalse(duplicate_inserted)
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(self.store.stats()["received"], 1)

    def test_manual_coordinate_is_next_and_counts_toward_species_stats(self):
        self.store.add(payload("1", "Eevee", 40))
        manual = self.store.add_manual_sighting(
            "  Bulbasaur  ", "40.760800, -111.891000"
        )

        self.assertEqual(manual["species"], "Bulbasaur")
        self.assertEqual(manual["source"], "manual-entry")
        self.assertEqual(manual["queue_position"], 0)
        self.assertIsNotNone(manual["expires_at"])

        claimed = self.store.claim_next_target(30 * 60)
        self.assertEqual(claimed["id"], manual["id"])
        self.store.complete_hunt_target(claimed["id"], "checked")
        bulbasaur = next(
            row for row in self.store.stats()["species"] if row["species"] == "Bulbasaur"
        )
        self.assertEqual(bulbasaur["checked"], 1)

    def test_manual_coordinate_is_available_with_internal_feed_selected(self):
        self.store.set_feed_source("ipogo-internal")
        manual = self.store.add_manual_sighting(
            "Squirtle", "51.636073,-0.438103"
        )

        self.assertEqual(self.store.list(10)[0]["id"], manual["id"])
        self.assertEqual(self.store.source_status()["activeQueueCount"], 1)
        self.assertEqual(self.store.source_status()["feedSourceCounts"]["manual"], 1)
        self.assertEqual(self.store.claim_next_target(30 * 60)["id"], manual["id"])

    def test_manual_coordinate_rejects_bad_input(self):
        with self.assertRaisesRegex(ValueError, "Pokémon name"):
            self.store.add_manual_sighting(" ", "40.7608,-111.8910")
        with self.assertRaisesRegex(ValueError, "Coordinates must look"):
            self.store.add_manual_sighting("Bulbasaur", "Salt Lake City")

    def test_custom_queue_order_overrides_and_can_restore_automatic_ranking(self):
        low, _ = self.store.add(payload("1", "Squirtle", 10))
        middle, _ = self.store.add(payload("2", "Charmander", 20))
        high, _ = self.store.add(payload("3", "Eevee", 40))

        saved = self.store.save_queue_order([low["id"], middle["id"], high["id"]])
        self.assertTrue(saved["customOrder"])
        first = self.store.claim_next_target(30 * 60)
        self.assertEqual(first["id"], low["id"])
        self.store.complete_hunt_target(first["id"], "checked")

        reset = self.store.save_queue_order([])
        self.assertFalse(reset["customOrder"])
        second = self.store.claim_next_target(30 * 60)
        self.assertEqual(second["id"], high["id"])
        self.assertNotEqual(second["id"], middle["id"])

    def test_hunt_timing_settings_keep_defaults_and_persist_changes(self):
        self.assertEqual(
            self.store.hunt_settings(),
            {"dwellSeconds": 45.0, "recoveryFailureThreshold": 2, "hundoCooldownSeconds": 30.0},
        )
        saved = self.store.save_hunt_settings(80, 4, 25)
        self.assertEqual(saved, {"dwellSeconds": 80.0, "recoveryFailureThreshold": 4, "hundoCooldownSeconds": 25.0})
        self.assertEqual(self.store.hunt_settings(), saved)

    def test_hunt_timing_settings_reject_unsafe_values(self):
        with self.assertRaisesRegex(ValueError, "between 5 and 600"):
            self.store.save_hunt_settings(2, 2, 30)
        with self.assertRaisesRegex(ValueError, "between 1 and 20"):
            self.store.save_hunt_settings(45, 21, 30)
        with self.assertRaisesRegex(ValueError, "between 0 and 600"):
            self.store.save_hunt_settings(45, 2, 601)

    def test_adds_internal_ipogo_batch_with_real_expiry(self):
        item = InternalFeedItem(
            storage="0000000159130000",
            index=0,
            count=1,
            pokemon_id=7,
            species="Squirtle",
            form=181,
            weather=0,
            cp=567,
            iv=100,
            level=21,
            expires_at="2099-08-02T19:59:00+00:00",
            latitude=40.7608,
            longitude=-111.8910,
        )
        self.assertEqual(self.store.add_internal_batch([item]), 1)
        self.assertEqual(self.store.add_internal_batch([item]), 0)
        self.store.set_feed_source("ipogo-internal")
        row = self.store.list(1)[0]
        self.assertEqual(row["source"], "ipogo-internal-100iv")
        self.assertEqual(row["channel_name"], "iPogo 100 IV")
        self.assertEqual(row["species"], "Squirtle")
        self.assertEqual(row["expires_at"], item.expires_at)

    def test_hunter_discards_targets_without_enough_time_to_check(self):
        expires_soon = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
        item = InternalFeedItem(
            storage="0000000159130000",
            index=0,
            count=1,
            pokemon_id=7,
            species="Squirtle",
            form=181,
            weather=0,
            cp=567,
            iv=100,
            level=21,
            expires_at=expires_soon,
            latitude=40.7608,
            longitude=-111.8910,
        )
        self.store.add_internal_batch([item])
        self.store.set_feed_source("ipogo-internal")

        self.assertIsNone(self.store.claim_next_target(30 * 60, 75))
        self.assertEqual(self.store.list(10), [])

    def test_source_mode_only_claims_the_selected_feed(self):
        external, _ = self.store.add(payload("1", "Bulbasaur", 40))
        internal = InternalFeedItem(
            storage="0000000159130000",
            index=0,
            count=1,
            pokemon_id=7,
            species="Squirtle",
            form=181,
            weather=0,
            cp=567,
            iv=100,
            level=21,
            expires_at="2099-08-02T19:59:00+00:00",
            latitude=40.7608,
            longitude=-111.8910,
        )
        self.store.add_internal_batch([internal])
        source = self.store.set_feed_source("ipogo-internal")
        self.assertEqual(source["feedSourceMode"], "ipogo-internal")
        self.assertFalse(self.store.accepts_external_feed())
        claimed = self.store.claim_next_target(30 * 60)
        self.assertEqual(claimed["source"], "ipogo-internal-100iv")
        self.assertEqual(self.store.get_sighting(external["id"])["status"], "queued")

    def test_pokexperience_snapshot_is_source_isolated_and_reports_health(self):
        external, _ = self.store.add(payload("1", "Bulbasaur", 40))
        result = self.store.update_pokexperience_bridge(pokexperience_payload([
            pokexperience_item("Squirtle", 40.7608, cp=700, level=28),
        ]))
        self.assertEqual(result["inserted"], 1)
        self.assertTrue(result["pokexperienceBridgeConnected"])
        self.assertTrue(result["pokexperienceAppRunning"])

        status = self.store.set_feed_source("pokexperience")
        self.assertEqual(status["feedSourceMode"], "pokexperience")
        self.assertEqual(status["activeQueueCount"], 1)
        self.assertEqual(status["feedSourceCounts"]["pokexperience"], 1)
        claimed = self.store.claim_next_target(30 * 60)
        self.assertEqual(claimed["source"], POKEXPERIENCE_SOURCE)
        self.assertEqual(claimed["species"], "Squirtle")
        self.assertEqual(self.store.get_sighting(external["id"])["status"], "queued")

    def test_pokexperience_snapshot_replaces_missing_and_expired_targets(self):
        self.store.update_pokexperience_bridge(pokexperience_payload([
            pokexperience_item("Bulbasaur", 40.7608),
            pokexperience_item("Charmander", 40.7618),
        ]))
        self.store.set_feed_source("pokexperience")
        self.assertEqual(self.store.source_status()["activeQueueCount"], 2)

        result = self.store.update_pokexperience_bridge(pokexperience_payload([
            pokexperience_item("Charmander", 40.7618, cp=900),
            pokexperience_item("Expired", 40.7628, remaining_minutes=-1),
        ]))
        self.assertEqual(result["inserted"], 0)
        rows = self.store.list(10)
        self.assertEqual([row["species"] for row in rows], ["Charmander"])
        self.assertEqual(rows[0]["cp"], 900)

    def test_pokexperience_queue_uses_species_rank_then_level_then_cp(self):
        self.store.update_pokexperience_bridge(pokexperience_payload([
            pokexperience_item("Squirtle", 40.7608, cp=600, level=30),
            pokexperience_item("Squirtle", 40.7618, cp=900, level=30),
            pokexperience_item("Squirtle", 40.7628, cp=1200, level=20),
            pokexperience_item("Bulbasaur", 40.7638, cp=1500, level=40),
        ]))
        self.store.set_feed_source("pokexperience")
        self.store.save_preferences("all", ["Squirtle", "Bulbasaur"])

        first = self.store.claim_next_target(30 * 60)
        self.assertEqual(first["species"], "Squirtle")
        self.assertEqual(first["level"], 30)
        self.assertEqual(first["cp"], 900)
        self.store.complete_hunt_target(first["id"], "checked")

        second = self.store.claim_next_target(30 * 60)
        self.assertEqual(second["species"], "Squirtle")
        self.assertEqual(second["level"], 30)
        self.assertEqual(second["cp"], 600)

    def test_pokexperience_fallback_uses_highest_cp_before_level(self):
        self.store.update_pokexperience_bridge(pokexperience_payload([
            pokexperience_item("Squirtle", 40.7608, cp=500, level=20),
            pokexperience_item("Rhyhorn", 40.7618, cp=1533, level=35),
            pokexperience_item("Stonjourner", 40.7628, cp=2896, level=33),
        ]))
        self.store.set_feed_source("pokexperience")
        self.store.save_preferences("all", ["Squirtle"])

        visible_queue = self.store.list_queue()
        self.assertEqual(
            [row["species"] for row in visible_queue],
            ["Squirtle", "Stonjourner", "Rhyhorn"],
        )
        self.assertEqual([row["queue_rank"] for row in visible_queue], [0, 1, 2])

        preferred = self.store.claim_next_target(30 * 60)
        self.assertEqual(preferred["species"], "Squirtle")
        self.store.complete_hunt_target(preferred["id"], "checked")

        fallback = self.store.claim_next_target(30 * 60)
        self.assertEqual(fallback["species"], "Stonjourner")
        self.assertEqual(fallback["cp"], 2896)
        self.assertEqual(fallback["level"], 33)

    def test_pokexperience_lookahead_prepares_cp_first_fallbacks(self):
        self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload([
                pokexperience_metadata_item("Rhyhorn", cp=1533, level=35, source_index=0),
                pokexperience_metadata_item("Stonjourner", cp=2896, level=33, source_index=1),
                pokexperience_metadata_item("Excadrill", cp=2780, level=30, source_index=2),
            ])
        )
        self.store.set_feed_source("pokexperience")

        first_job = self.store.lease_pokexperience_resolution()
        second_job = self.store.lease_pokexperience_resolution()
        self.assertEqual(first_job["species"], "Stonjourner")
        self.assertEqual(second_job["species"], "Excadrill")

    def test_pokexperience_metadata_sync_does_not_invent_coordinates(self):
        result = self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload([
                pokexperience_metadata_item("Squirtle", cp=900, level=30),
            ])
        )
        self.assertEqual(result["inserted"], 1)
        self.store.set_feed_source("pokexperience")
        row = self.store.list(10)[0]
        self.assertIsNone(row["latitude"])
        self.assertIsNone(row["longitude"])
        self.assertEqual(row["coordinate_state"], "pending")
        self.assertEqual(row["city"], "Salt Lake City")
        status = self.store.pokexperience_status()
        self.assertEqual(status["pokexperienceCoordinatesPending"], 1)
        self.assertEqual(status["pokexperienceCoordinatesReady"], 0)

    def test_pokexperience_resolves_only_a_leased_target(self):
        self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload([
                pokexperience_metadata_item("Squirtle", cp=900, level=30),
            ])
        )
        self.store.set_feed_source("pokexperience")
        target = self.store.claim_next_target(30 * 60)
        self.store.queue_pokexperience_resolution(target["id"])
        job = self.store.lease_pokexperience_resolution()
        self.assertEqual(job["sightingId"], target["id"])

        with self.assertRaisesRegex(ValueError, "lease"):
            self.store.update_pokexperience_bridge({
                "type": "resolve-result",
                "jobId": job["jobId"],
                "leaseToken": "wrong-token",
                "latitude": 40.7608,
                "longitude": -111.8910,
            })
        self.store.update_pokexperience_bridge({
            "type": "resolve-result",
            "jobId": job["jobId"],
            "leaseToken": job["leaseToken"],
            "latitude": 40.7608,
            "longitude": -111.8910,
        })
        resolved = self.store.get_sighting(target["id"])
        self.assertEqual(resolved["coordinate_state"], "ready")
        self.assertAlmostEqual(resolved["latitude"], 40.7608)
        self.assertAlmostEqual(resolved["longitude"], -111.8910)

    def test_pokexperience_resolver_stops_after_two_item_lookahead(self):
        self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload([
                pokexperience_metadata_item("Squirtle", level=40, source_index=0),
                pokexperience_metadata_item("Bulbasaur", level=30, source_index=0),
                pokexperience_metadata_item("Charmander", level=20, source_index=0),
            ])
        )
        self.store.set_feed_source("pokexperience")
        for offset in (0.001, 0.002):
            job = self.store.lease_pokexperience_resolution()
            self.assertIsNotNone(job)
            self.store.update_pokexperience_bridge({
                "type": "resolve-result",
                "jobId": job["jobId"],
                "leaseToken": job["leaseToken"],
                "latitude": 40.7608 + offset,
                "longitude": -111.8910,
            })
        self.assertIsNone(self.store.lease_pokexperience_resolution())
        pending = [row for row in self.store.list(10) if row["coordinate_state"] == "pending"]
        self.assertEqual([row["species"] for row in pending], ["Charmander"])

    def test_pokexperience_metadata_prunes_only_its_completed_scope(self):
        self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload(
                [pokexperience_metadata_item("Squirtle")], scope="priority:squirtle"
            )
        )
        self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload(
                [pokexperience_metadata_item("Bulbasaur")], scope="fallback"
            )
        )
        self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload([], scope="priority:squirtle", generation="next")
        )
        self.store.set_feed_source("pokexperience")
        self.assertEqual([row["species"] for row in self.store.list(10)], ["Bulbasaur"])

    def test_complete_pokexperience_catalog_replaces_all_legacy_scopes(self):
        self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload(
                [pokexperience_metadata_item("Squirtle")], scope="priority:squirtle"
            )
        )
        result = self.store.update_pokexperience_bridge(
            pokexperience_metadata_payload(
                [pokexperience_metadata_item("Bulbasaur")],
                scope="catalog",
                generation="full-catalog",
                complete_catalog=True,
            )
        )
        self.store.set_feed_source("pokexperience")
        self.assertEqual([row["species"] for row in self.store.list(10)], ["Bulbasaur"])
        self.assertTrue(result["pokexperienceCatalogComplete"])
        self.assertEqual(result["pokexperienceCatalogRows"], 1)
        self.assertEqual(result["pokexperienceCatalogPages"], 10)

    def test_priority_names_are_canonicalized_and_catalog_is_searchable_before_spawn(self):
        preferences = self.store.save_preferences("all", ["Magicarp", "charizard"])
        self.assertEqual(preferences["rankedSpecies"], ["Magikarp", "Charizard"])
        catalog = {item["species"]: item for item in preferences["availableSpecies"]}
        self.assertIn("Magikarp", catalog)
        self.assertEqual(catalog["Magikarp"]["actionable"], 0)

    def test_persists_lifetime_and_species_stats(self):
        self.store.add(payload("1"))
        self.store.action("start")
        self.store.action("checked")
        self.store.add(payload("2"))
        self.store.action("start")
        self.store.action("shundo")

        stats = self.store.stats()
        self.assertEqual(stats["checked"], 2)
        self.assertEqual(stats["shundos"], 1)
        self.assertEqual(stats["species"][0]["species"], "Bulbasaur")
        self.assertEqual(stats["species"][0]["checked"], 2)
        self.assertEqual(stats["species"][0]["shundos"], 1)

    def test_heartbeat_marks_relay_connected(self):
        self.store.heartbeat("channel", "💯gen1", visible_message_count=12, new_candidate_count=3)
        status = self.store.status()
        self.assertTrue(status["relayConnected"])
        self.assertEqual(status["visibleMessages"], 12)
        self.assertEqual(status["candidatesSeen"], 3)

    def test_selected_species_rules_choose_ranked_target(self):
        bulbasaur, _ = self.store.add(payload("1", "Bulbasaur"))
        eevee, _ = self.store.add(payload("2", "Eevee"))
        preferences = self.store.save_preferences("selected", ["Eevee"])
        self.assertEqual(preferences["mode"], "selected")
        self.assertEqual(preferences["rankedSpecies"], ["Eevee"])

        status = self.store.action("start")
        self.assertEqual(status["currentTargetId"], eevee["id"])
        self.assertNotEqual(status["currentTargetId"], bulbasaur["id"])

    def test_manual_priority_overrides_species_allowlist(self):
        bulbasaur, _ = self.store.add(payload("1", "Bulbasaur"))
        self.store.add(payload("2", "Eevee"))
        self.store.save_preferences("selected", ["Eevee"])
        self.store.action("prioritize", bulbasaur["id"])

        status = self.store.action("start")
        self.assertEqual(status["currentTargetId"], bulbasaur["id"])

    def test_uses_discord_despawn_timer_when_expiring_targets(self):
        expiring = payload("1", "Squirtle")
        expiring["rawText"] += " (DSP in 0m)"
        sighting, _ = self.store.add(expiring)

        self.assertIsNotNone(sighting["expires_at"])
        self.store.expire_stale_sightings(30 * 60)
        with self.assertRaises(ValueError):
            self.store.get_sighting(sighting["id"])

    def test_queue_uses_species_rank_then_highest_level(self):
        low_squirtle, _ = self.store.add(payload("1", "Squirtle", 10))
        high_squirtle, _ = self.store.add(payload("2", "Squirtle", 35))
        high_bulbasaur, _ = self.store.add(payload("3", "Bulbasaur", 40))
        self.store.save_preferences("selected", ["Squirtle", "Bulbasaur"])

        first = self.store.claim_next_target(30 * 60)
        self.assertEqual(first["id"], high_squirtle["id"])
        self.store.complete_hunt_target(first["id"], "checked")

        second = self.store.claim_next_target(30 * 60)
        self.assertEqual(second["id"], low_squirtle["id"])
        self.store.complete_hunt_target(second["id"], "checked")

        third = self.store.claim_next_target(30 * 60)
        self.assertEqual(third["id"], high_bulbasaur["id"])

    def test_queue_falls_back_to_global_highest_level_after_priorities(self):
        preferred, _ = self.store.add(payload("1", "Squirtle", 10))
        low_fallback, _ = self.store.add(payload("2", "Charmander", 12))
        high_fallback, _ = self.store.add(payload("3", "Eevee", 40))
        self.store.save_preferences("all", ["Squirtle"])

        first = self.store.claim_next_target(30 * 60)
        self.assertEqual(first["id"], preferred["id"])
        self.store.complete_hunt_target(first["id"], "checked")

        second = self.store.claim_next_target(30 * 60)
        self.assertEqual(second["id"], high_fallback["id"])
        self.assertNotEqual(second["id"], low_fallback["id"])

    def test_internal_ipogo_queue_uses_highest_cp_not_highest_level(self):
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        low_cp_high_level = InternalFeedItem(
            storage="0000000159130000",
            index=0,
            count=2,
            pokemon_id=7,
            species="Squirtle",
            form=181,
            weather=0,
            cp=500,
            iv=100,
            level=35,
            expires_at=expires_at,
            latitude=40.7608,
            longitude=-111.8910,
        )
        high_cp_low_level = InternalFeedItem(
            storage="0000000159130000",
            index=1,
            count=2,
            pokemon_id=7,
            species="Squirtle",
            form=181,
            weather=0,
            cp=900,
            iv=100,
            level=20,
            expires_at=expires_at,
            latitude=40.7618,
            longitude=-111.8920,
        )
        self.store.add_internal_batch([low_cp_high_level, high_cp_low_level])
        self.store.set_feed_source("ipogo-internal")

        claimed = self.store.claim_next_target(30 * 60)
        self.assertEqual(claimed["cp"], 900)
        self.assertEqual(claimed["level"], 20)

    def test_future_species_can_be_ranked_before_it_has_a_sighting(self):
        preferences = self.store.save_preferences("selected", ["Ivysaur"])
        self.assertEqual(preferences["rankedSpecies"], ["Ivysaur"])
        self.assertIsNone(self.store.claim_next_target(30 * 60))

        ivysaur, _ = self.store.add(payload("1", "Ivysaur", 28))
        claimed = self.store.claim_next_target(30 * 60)
        self.assertEqual(claimed["id"], ivysaur["id"])

    def test_discards_current_target_left_by_interrupted_process(self):
        interrupted, _ = self.store.add(payload("1", "Squirtle", 35))
        claimed = self.store.claim_next_target(30 * 60)
        self.assertEqual(claimed["id"], interrupted["id"])

        self.assertEqual(self.store.discard_orphaned_current(), 1)
        with self.assertRaises(ValueError):
            self.store.get_sighting(interrupted["id"])
        self.assertIsNone(self.store.claim_next_target(30 * 60))


if __name__ == "__main__":
    unittest.main()
