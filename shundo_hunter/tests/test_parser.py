import unittest

from shundo_hunter.internal_feed import BatchAssembler, parse_item

from shundo_hunter.parser import coordinates_from_text, coordinates_from_url, parse_relay_payload


class ParserTests(unittest.TestCase):
    def test_adjacent_integer_stats_are_not_coordinates(self):
        self.assertIsNone(coordinates_from_text("Weedle    6  75   Summerlin South"))
        self.assertIsNone(coordinates_from_text("SVG path 2.5,4.5"))

    def test_parses_reference_project_message(self):
        payload = {
            "guildId": "271392134169493505",
            "channelId": "1062013131834007563",
            "channelName": "💯gen1",
            "messageId": "123456789012345678",
            "rawText": "***Poochyena*** **CP329** **L17** ♂ ✨",
            "resolvedCoordinate": {
                "latitude": 43.550079,
                "longitude": -79.748105,
                "url": "https://pokedex100.com/example"
            }
        }
        sighting = parse_relay_payload(payload)
        self.assertIsNotNone(sighting)
        self.assertEqual(sighting.species, "Poochyena")
        self.assertEqual(sighting.cp, 329)
        self.assertEqual(sighting.level, 17)
        self.assertEqual(sighting.gender, "male")
        self.assertEqual(sighting.iv, 100)
        self.assertTrue(sighting.shiny_eligible)

    def test_parses_pokedex100_community_message(self):
        payload = {
            "guildId": "252776251708801024",
            "channelId": "259536527221063683",
            "channelName": "100community",
            "messageId": "123456789012345679",
            "rawText": "***Makuhita*** **CP397** **L17** ♀ ✨",
            "resolvedCoordinate": {
                "latitude": 40.876327,
                "longitude": -73.866205,
                "url": "https://coord.pokedex100.com/6/example",
            },
        }
        sighting = parse_relay_payload(payload)
        self.assertIsNotNone(sighting)
        self.assertEqual(sighting.species, "Makuhita")
        self.assertEqual(sighting.cp, 397)
        self.assertEqual(sighting.level, 17)
        self.assertEqual(sighting.gender, "female")
        self.assertEqual(sighting.iv, 100)

    def test_parses_pokedex100_rendered_discord_row(self):
        payload = {
            "guildId": "252776251708801024",
            "channelId": "259536527221063683",
            "channelName": "100community",
            "messageId": "123456789012345680",
            "rawText": (
                "SuperShipper6\nAPP\n — \n5:23 PM\n"
                "Friday, July 31, 2026 at 5:23 PM\n"
                " Spritzee  IV100 (A15/D15/S15) CP1073 L30 ♀ / "
                "(DSP in 24m) - Islington, London\n"
                "Click for Coords | Donor | Support Us"
            ),
            "resolvedCoordinate": {
                "latitude": 51.5462,
                "longitude": -0.1027,
                "url": "https://coord.pokedex100.com/6/example",
            },
        }
        sighting = parse_relay_payload(payload)
        self.assertIsNotNone(sighting)
        self.assertEqual(sighting.species, "Spritzee")
        self.assertEqual(sighting.cp, 1073)
        self.assertEqual(sighting.level, 30)

    def test_parses_pokex_private_coordinate_reply(self):
        payload = {
            "channelName": "💯gen1",
            "messageId": "private-reply-1",
            "rawText": "APP\nCoords\n Paras     29  843   Hégenheim  in 28 minutes @✨HighCP\n47.572918, 7.545373\nOnly you can see this",
        }
        sighting = parse_relay_payload(payload)
        self.assertIsNotNone(sighting)
        self.assertEqual(sighting.species, "Paras")
        self.assertEqual(sighting.level, 29)
        self.assertEqual(sighting.cp, 843)
        self.assertEqual((sighting.latitude, sighting.longitude), (47.572918, 7.545373))

    def test_rejects_non_hundo_message(self):
        payload = {
            "channelName": "wild-spawns",
            "messageId": "1",
            "rawText": "Pikachu IV 91 CP 400 at 40.1,-111.9"
        }
        self.assertIsNone(parse_relay_payload(payload))

    def test_parses_internal_ipogo_feed_item(self):
        line = (
            "HUNTER_FEED_ITEM_V12 storage=0000000159130000 index=0 count=1 "
            "pokemon=263 form=946 weather=0 cp=334 cpnil=0 iv=100 ivnil=0 "
            "level=23 levelnil=0 expirybits=41c80febcaa2d0e6 "
            "lonbits=4060f60d15869ba3 latbits=404167e9e29b5d03 replace=1"
        )
        item = parse_item(line)
        self.assertIsNotNone(item)
        self.assertEqual(item.species, "Zigzagoon")
        self.assertEqual(item.iv, 100)
        self.assertEqual(item.cp, 334)
        self.assertEqual(item.level, 23)
        self.assertTrue(item.replace)
        self.assertAlmostEqual(item.latitude, 34.81182510934925)
        self.assertAlmostEqual(item.longitude, 135.68909717836968)
        self.assertEqual(item.expires_at, "2026-08-02T19:52:53.272000+00:00")

    def test_internal_batch_requires_every_index_and_deduplicates(self):
        first = (
            "HUNTER_FEED_ITEM_V11 storage=0000000159130000 index=0 count=2 "
            "pokemon=263 form=946 weather=0 cp=334 cpnil=0 iv=100 ivnil=0 "
            "level=23 levelnil=0 expirybits=41c80febcaa2d0e6 "
            "lonbits=4060f60d15869ba3 latbits=404167e9e29b5d03 replace=1"
        )
        second = first.replace("index=0", "index=1").replace("pokemon=263", "pokemon=123")
        assembler = BatchAssembler()
        self.assertIsNone(assembler.accept(first))
        replace, batch = assembler.accept(second)
        self.assertTrue(replace)
        self.assertEqual([item.species for item in batch], ["Zigzagoon", "Scyther"])
        self.assertIsNone(assembler.accept(first))
        self.assertIsNone(assembler.accept(second))

    def test_rejects_link_only_discord_fragment(self):
        payload = {
            "channelName": "100community",
            "messageId": "link-only",
            "rawText": "Click for Coords | Donor | Support Us",
            "resolvedCoordinate": {
                "latitude": 40.758701,
                "longitude": -111.876183,
            },
        }
        self.assertIsNone(parse_relay_payload(payload))

    def test_extracts_google_maps_query(self):
        coordinate = coordinates_from_url(
            "https://maps.google.com/?q=40.758701,-111.876183"
        )
        self.assertEqual(coordinate, (40.758701, -111.876183))


if __name__ == "__main__":
    unittest.main()
