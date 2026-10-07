import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock, MagicMock, patch
import zlib

from shundo_hunter.encounter_vision import (SCHEMAS, VisionClient, VisionError, alert_identity,
    frame_unchanged, helper, tap_candidate, validate_result, verify_encounter)
from shundo_hunter.vision_opener import VisionOpener, safe_native_target


def result(scene="map"):
    return {"scene": scene, "species": "Charizard", "selection_evidence": "One visible Charizard sprite, unobscured and clear of map controls.",
            "candidate_count": 1, "target_box": {"x": .4, "y": .4, "width": .08, "height": .08}, "uncertainty": ""}


def encounter():
    value = result("encounter")
    value.pop("selection_evidence")
    value.update(cp=1234, iv=100, shiny_indicator="shiny_symbol",
                 shiny_evidence="Shiny symbol next to encounter name", iv_evidence="100%", target_box=None)
    return value


def frame():
    return {"pixelWidth": 1284, "pixelHeight": 2778, "cropTop": .16,
            "cropHeight": .66, "grid": [80]*9216, "image": "fake", "pid": 21}


EXPECTED = {"species": "Charizard", "cp": 1234}
LOCAL = {"scene": "encounter", "cp": 1234, "evidence": ["Charizard", "CP 1234", "100%"]}


class EvidenceTests(unittest.TestCase):
    def test_identity_only_does_not_prove_shundo(self):
        identity = {k: encounter()[k] for k in ("scene", "species", "cp", "uncertainty")}
        self.assertEqual(verify_encounter(identity, EXPECTED, LOCAL, require_shundo=False), 1234)
        with self.assertRaises(VisionError):
            verify_encounter(identity, EXPECTED, LOCAL)
    def test_map_selection_has_no_shiny_or_iv_requirements(self):
        self.assertNotIn("iv", SCHEMAS["locate"]["properties"])
        self.assertNotIn("shiny_indicator", SCHEMAS["locate"]["properties"])
        beldum = {**result(), "species": "Beldum", "selection_evidence": "One Beldum sprite left of the central PokéStop and above-left of the avatar.",
                  "target_box": {"x": .276, "y": .631, "width": .065, "height": .042}}
        self.assertAlmostEqual(tap_candidate(beldum, {"species": "Beldum"}, frame())[0], .3085)
        with self.assertRaises(VisionError):
            verify_encounter(beldum, {"species": "Beldum"}, LOCAL)

    def test_stage_schemas_cannot_be_interchanged(self):
        with self.assertRaises(VisionError):
            validate_result(encounter(), "locate")
        with self.assertRaises(VisionError):
            validate_result(result(), "verify")

    def test_selection_commentary_does_not_bypass_ambiguity(self):
        for update in ({"uncertainty": "Two possible Beldum sprites"}, {"candidate_count": 2}, {"selection_evidence": ""}):
            with self.subTest(update=update), self.assertRaises(VisionError):
                tap_candidate({**result(), **update}, EXPECTED, frame())

    def test_alert_uses_actual_species_not_queued_target(self):
        self.assertEqual(alert_identity("Shundo Pikachu appeared! CP 300", EXPECTED), {"species": "Pikachu", "cp": 300})

    def test_unknown_ambiguous_or_test_alert_rejected(self):
        for text in ("Shundo", "Shundo Pikachu Charizard", "Test Shundo Charizard", "Not a shundo Charizard", "Hundo Charizard"):
            with self.subTest(text=text), self.assertRaises(VisionError):
                alert_identity(text, EXPECTED)

    def test_cp_is_only_an_additional_constraint(self):
        self.assertEqual(alert_identity("Shundo Charizard", EXPECTED)["cp"], 1234)
        self.assertIsNone(alert_identity("Shundo Pikachu", EXPECTED)["cp"])

    def test_normalized_map_point(self):
        x, y = tap_candidate(result(), EXPECTED, frame())
        self.assertAlmostEqual(x, .44)
        self.assertAlmostEqual(y, .16+.44*.66)

    def test_ambiguous_or_wrong_species_never_tapped(self):
        for update in ({"candidate_count": 2}, {"species": "Pikachu"}, {"scene": "encounter"}, {"uncertainty": "occluded"}, {"target_box": None}):
            with self.subTest(update=update), self.assertRaises(VisionError):
                tap_candidate({**result(), **update}, EXPECTED, frame())

    def test_invalid_box_and_protected_regions(self):
        for box in ({"x": float("nan"), "y": .3, "width": .1, "height": .1},
                    {"x": -.1, "y": .3, "width": .1, "height": .1},
                    {"x": .98, "y": .3, "width": .1, "height": .1},
                    {"x": .01, "y": .3, "width": .04, "height": .04},
                    {"x": .4, "y": .97, "width": .02, "height": .02},
                    {"x": .4, "y": .3, "width": .5, "height": .1}):
            with self.subTest(box=box), self.assertRaises(VisionError):
                tap_candidate({**result(), "target_box": box}, EXPECTED, frame())

    def test_schema_not_just_json(self):
        for update in ({"candidate_count": True}, {"iv": 101}, {"scene": "click"}, {"uncertainty": "x"*601}, {"cp": "1234"}):
            with self.subTest(update=update), self.assertRaises(VisionError):
                validate_result({**result(), **update})

    def test_stale_geometry_global_change_and_local_change(self):
        original = frame()
        self.assertTrue(frame_unchanged(original, frame(), result()["target_box"]))
        for modified in (dict(frame(), pixelWidth=1000), dict(frame(), grid=[255]*9216)):
            self.assertFalse(frame_unchanged(original, modified, result()["target_box"]))
        modified = frame()
        for y in range(38, 47):
            for x in range(38, 47):
                modified["grid"][y*96+x] = 200
        self.assertFalse(frame_unchanged(original, modified, result()["target_box"]))

    def test_shundo_requires_local_iv_and_explicit_shiny(self):
        self.assertEqual(verify_encounter(encounter(), EXPECTED, LOCAL), 1234)
        for update in ({"iv": None}, {"iv_evidence": ""}, {"shiny_indicator": "none"}, {"shiny_evidence": ""}, {"cp": 1235}, {"species": "Pikachu"}):
            with self.subTest(update=update), self.assertRaises(VisionError):
                verify_encounter({**encounter(), **update}, EXPECTED, LOCAL)
        with self.assertRaises(VisionError):
            verify_encounter(encounter(), EXPECTED, {**LOCAL, "evidence": ["Charizard", "CP 1234"]})

    def test_name_and_cp_need_local_corroboration(self):
        for update in ({"cp": 4}, {"scene": "uncertain"}, {"evidence": ["Pikachu", "100%"]}):
            with self.subTest(update=update), self.assertRaises(VisionError):
                verify_encounter(encounter(), EXPECTED, {**LOCAL, **update})

    def test_native_control_and_dialog_guards(self):
        safe_native_target('<App><XCUIElementTypeButton x="0" y="0" width="20" height="20" visible="true"/></App>', 200, 400)
        for xml in ('<App><XCUIElementTypeAlert visible="true"/></App>',
                    '<App><XCUIElementTypeButton x="190" y="390" width="20" height="20"/></App>',
                    '<App><XCUIElementTypeButton/></App>', 'bad xml'):
            with self.subTest(xml=xml), self.assertRaises(VisionError):
                safe_native_target(xml, 200, 400)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"vision.json"
        self.client = VisionClient(self.path)
        self.client.opener = MagicMock()

    def tearDown(self):
        self.temp.cleanup()

    def test_default_makes_no_network_request(self):
        with self.assertRaises(VisionError):
            self.client.analyze("locate", frame(), EXPECTED)
        self.client.opener.open.assert_not_called()

    def test_consent_and_key_required(self):
        with self.assertRaises(VisionError):
            self.client.configure({"enabled": True})
        with patch("shundo_hunter.encounter_vision.helper", return_value={"configured": False}), self.assertRaises(VisionError):
            self.client.configure({"enabled": True, "consent": True})

    def test_secret_not_persisted_or_returned(self):
        key = "sk-" + "testkey"*4
        with patch("shundo_hunter.encounter_vision.helper", return_value={"configured": True}):
            status = self.client.configure({"enabled": True, "consent": True, "apiKey": key})
        self.assertNotIn(key, self.path.read_text())
        self.assertNotIn(key, json.dumps(status))
        self.assertEqual(set(json.loads(self.path.read_text())), {"enabled", "consent", "model"})

    def test_request_is_cropped_scoped_and_not_stored(self):
        self.client.config.update(enabled=True, consent=True)
        self.client.key_available = True
        output = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(result())}]}]}
        self.client.opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(output).encode()
        with patch("shundo_hunter.encounter_vision.helper", return_value=b"sk-not-real"):
            self.client.analyze("locate", frame(), EXPECTED)
        request = self.client.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        body = json.loads(request.data)
        self.assertFalse(body["store"])
        self.assertEqual(body["text"]["format"]["schema"], SCHEMAS["locate"])
        self.assertNotIn("VERIFY ONLY:", body["instructions"])
        self.assertNotIn("sk-not-real", request.data.decode())
        self.assertEqual(body["input"][0]["content"][1]["image_url"], "data:image/png;base64,fake")

    def test_malformed_incomplete_and_refusal_responses(self):
        self.client.config.update(enabled=True, consent=True)
        self.client.key_available = True
        for output in ([], {"status": "incomplete"}, {"status": "completed", "output": [None]},
                       {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal"}]}]}):
            self.client.opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(output).encode()
            with self.subTest(output=output), patch("shundo_hunter.encounter_vision.helper", return_value=b"sk-test"), self.assertRaises(VisionError):
                self.client.analyze("locate", frame(), EXPECTED)


class OpenerTests(unittest.TestCase):
    def setUp(self):
        self.guard = Mock()
        self.guard.lock = threading.RLock()
        self.guard.operation_lock = threading.RLock()
        self.guard.active = self.guard.protected = True
        self.guard.event = {}
        self.guard.screen_recovery = None
        self.guard.stop_event.is_set.return_value = False
        self.guard.power.poll.return_value = None
        self.guard.hunt.status.return_value = {"huntState": "shundo", "huntWorkerAlive": False}
        self.guard.controller.session_id = "test-session"
        self.guard.controller._request.side_effect = self.request
        self.client = Mock()
        self.client.status.return_value = {"visionConfigured": True}
        self.opener = VisionOpener(self.guard, self.client)
        self.opener.deadline = float("inf")
        self.opener._capture = Mock(return_value=(frame(), {"scene": "uncertain"}))

    @staticmethod
    def request(method, path, *args):
        if path.endswith("/size"):
            return {"value": {"width": 428, "height": 926}}
        if path.endswith("/source"):
            return {"value": "<App/>"}
        return {"value": None}

    def actions(self):
        return [c for c in self.guard.controller._request.call_args_list if c.args[0] == "POST" and c.args[1].endswith("/actions")]

    def test_one_tap_durably_consumed_and_no_second_tap(self):
        self.opener._tap(0, frame(), frame(), result(), EXPECTED)
        self.assertTrue(self.guard.event["tapConsumed"])
        self.guard._save.assert_called_once()
        with self.assertRaises(VisionError):
            self.opener._tap(0, frame(), frame(), result(), EXPECTED)
        self.assertEqual(len(self.actions()), 1)
        self.assertEqual([a["type"] for a in self.actions()[0].args[2]["actions"][0]["actions"]], ["pointerMove", "pointerDown", "pause", "pointerUp"])

    def test_uncertain_delivery_does_not_restore_tap_budget(self):
        def request(method, path, *args):
            if path.endswith("/actions"):
                raise OSError("timeout")
            return self.request(method, path, *args)
        self.guard.controller._request.side_effect = request
        with self.assertRaises(OSError):
            self.opener._tap(0, frame(), frame(), result(), EXPECTED)
        self.assertTrue(self.guard.event["tapConsumed"])
        with self.assertRaises(VisionError):
            self.opener._tap(0, frame(), frame(), result(), EXPECTED)
        self.assertEqual(len(self.actions()), 1)

    def test_changed_screen_or_process_never_taps(self):
        for modified in (dict(frame(), pid=22), dict(frame(), grid=[255]*9216)):
            with self.subTest(pid=modified["pid"]), self.assertRaises(VisionError):
                self.opener._tap(0, frame(), modified, result(), EXPECTED)
        self.assertEqual(self.actions(), [])

    def test_encounter_appearing_just_before_tap_blocks_it(self):
        self.opener._capture.return_value = (frame(), LOCAL)
        with self.assertRaises(VisionError):
            self.opener._tap(0, frame(), frame(), result(), EXPECTED)
        self.assertEqual(self.actions(), [])

    def test_cancel_during_ai_call_prevents_action(self):
        def cancel(*args):
            self.opener.cancel()
            return result()
        self.client.analyze.side_effect = cancel
        self.opener._run(0, EXPECTED, False)
        self.assertEqual(self.actions(), [])
        self.assertTrue(self.guard.protected)
        self.assertFalse(self.opener.busy)

    def test_wrong_encounter_left_open_without_exit_or_retry(self):
        self.opener._capture.side_effect = [(frame(), {"scene": "uncertain"})]*3 + [(frame(), LOCAL)]
        self.client.analyze.side_effect = [result(), {**encounter(), "species": "Pikachu"}]
        self.opener._run(0, EXPECTED, False)
        self.assertEqual(len(self.actions()), 1)
        self.assertEqual(self.guard.state, "attention")
        self.assertFalse(self.opener.verified)
        self.assertTrue(self.guard.protected)

    def test_full_flow_one_tap_three_requests_and_readonly_hold(self):
        self.opener._capture.side_effect = [(frame(), {"scene": "uncertain"})]*3 + [(frame(), LOCAL)]*3
        self.client.analyze.side_effect = [result(), encounter(), encounter()]
        self.opener._run(0, EXPECTED, False)
        self.assertEqual(len(self.actions()), 1)
        self.assertEqual(self.client.analyze.call_count, 3)
        self.assertTrue(self.opener.verified)
        self.assertEqual(self.guard.state, "holding")
        self.guard.controller.throw_once.assert_not_called()

    def test_supervised_requires_confirmation_and_unprotected_idle_state(self):
        for status, protected, confirmed in (("idle", False, False), ("running", False, True), ("shundo", False, True), ("idle", True, True)):
            self.guard.hunt.status.return_value = {"huntState": status, "huntWorkerAlive": False, "ipogoPrepared": False}
            self.guard.protected = protected
            with self.subTest(status=status, protected=protected, confirmed=confirmed), self.assertRaises(VisionError):
                self.opener.start(species="Beldum", supervised=True, confirmed=confirmed)
        self.assertIsNone(self.opener.thread)

    def test_supervised_cannot_be_used_with_real_alert(self):
        with self.assertRaises(VisionError):
            self.opener.start(event=Mock(), target=EXPECTED, supervised=True, confirmed=True)

    def test_supervised_hold_has_no_shundo_claim_or_stats_calls(self):
        self.opener.supervised = True
        self.guard.event = {"mode": "supervised"}
        self.guard.hunt.status.return_value = {"huntState": "idle", "huntWorkerAlive": False, "ipogoPrepared": False}
        self.opener._capture.side_effect = [(frame(), {"scene": "uncertain"})]*3 + [(frame(), LOCAL)]*3
        identity = {k: encounter()[k] for k in ("scene", "species", "cp", "uncertainty")}
        self.client.analyze.side_effect = [result(), identity, identity]
        self.opener._run(0, EXPECTED, False)
        self.assertEqual(len(self.actions()), 1)
        self.assertEqual([c.args[0] for c in self.client.analyze.call_args_list], ["locate", "identity"])
        self.assertFalse(self.opener.verified)
        self.assertEqual(self.guard.state, "holding")
        self.assertIn("NOT verified", self.guard.detail)
        self.guard.hunt.store.complete_hunt_target.assert_not_called()

    def test_production_shundo_requires_real_proof_even_after_supervised_support(self):
        self.opener._capture.side_effect = [(frame(), {"scene": "uncertain"})]*3 + [(frame(), LOCAL)]
        ordinary = {**encounter(), "iv": None, "shiny_indicator": "none"}
        self.client.analyze.side_effect = [result(), ordinary]
        self.opener._run(0, EXPECTED, False)
        self.assertFalse(self.opener.verified)
        self.assertEqual(self.guard.state, "attention")

    def test_readonly_test_never_taps_or_claims_shundo(self):
        self.client.analyze.return_value = result()
        self.opener._run(0, EXPECTED, True)
        self.assertEqual(self.actions(), [])
        self.assertFalse(self.opener.verified)
        self.assertEqual(self.opener.stage, "test-complete")

    def test_stale_alert_and_missing_species_do_not_start(self):
        for text, at in (("Shundo Charizard", datetime.now(timezone.utc)-timedelta(seconds=45)), ("Shundo", datetime.now(timezone.utc))):
            event = Mock(message=text, received_at=at.isoformat())
            with self.assertRaises(VisionError):
                self.opener.start(event=event, target=EXPECTED)
        self.assertIsNone(self.opener.thread)


class NativeFrameTests(unittest.TestCase):
    def test_crop_and_fingerprint_share_top_left_orientation(self):
        executable = Path(__file__).resolve().parents[2]/"build/shundo-hunter/VisionSupport"
        if not executable.is_file():
            self.skipTest("Native helper not built")
        # Synthetic grayscale PNG: top half black, lower half white.
        def chunk(kind, data):
            return struct.pack(">I", len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data)&0xffffffff)
        pixels = b"".join(b"\0"+bytes([0 if y < 400 else 255])*400 for y in range(800))
        png = b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB", 400, 800, 8, 0, 0, 0, 0))+chunk(b"IDAT", zlib.compress(pixels))+chunk(b"IEND", b"")
        sampled = helper("frame", png)
        self.assertEqual(sampled["pixelWidth"], 400)
        self.assertEqual(sampled["pixelHeight"], 800)
        self.assertAlmostEqual(sampled["cropTop"], .16)
        self.assertLess(sum(sampled["grid"][:96])/96, 10)
        self.assertGreater(sum(sampled["grid"][-96:])/96, 245)


if __name__ == "__main__":
    unittest.main()
