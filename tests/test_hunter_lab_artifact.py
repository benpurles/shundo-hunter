import unittest

import hunter_lab_artifact as lab
import build_hunter_lab_clone as clone
import build_hunter_lab_v2 as live_feed


class HunterLabArtifactTests(unittest.TestCase):
    def gold_like_binary(self) -> bytearray:
        size = max(item.offset + len(item.expected) for item in lab.INVARIANTS) + 64
        binary = bytearray(size)
        for invariant in lab.INVARIANTS:
            binary[invariant.offset:invariant.offset + len(invariant.expected)] = invariant.expected
        return binary

    def test_invariants_accept_matching_binary_without_hash_gate(self):
        report = lab.verify_fbl(bytes(self.gold_like_binary()), require_gold_hash=False)
        self.assertEqual(len(report["invariants"]), len(lab.INVARIANTS))

    def test_rejects_nil_source_information_patch(self):
        binary = self.gold_like_binary()
        binary[0x132C3C:0x132C44] = lab.FAILED_NIL_SOURCE_PATCH
        with self.assertRaisesRegex(RuntimeError, "sourceInformation"):
            lab.verify_fbl(bytes(binary), require_gold_hash=False)

    def test_rejects_legacy_framework_load_path(self):
        binary = self.gold_like_binary()
        binary.extend(lab.FORBIDDEN_LOAD_PATH)
        with self.assertRaisesRegex(RuntimeError, "ShundoBridge"):
            lab.verify_fbl(bytes(binary), require_gold_hash=False)

    def test_rejects_changed_proven_slice(self):
        binary = self.gold_like_binary()
        binary[0x2574DC] ^= 0xFF
        with self.assertRaisesRegex(RuntimeError, "notification logger"):
            lab.verify_fbl(bytes(binary), require_gold_hash=False)

    def test_lab_identity_is_separate_from_production(self):
        self.assertNotEqual(clone.LAB_BUNDLE_ID, "com.nianticlabs.pokemongo")
        self.assertTrue(clone.LAB_BUNDLE_ID.endswith(".hunterlab"))
        self.assertTrue(int(clone.LAB_BUILD) >= 5000)

    def test_live_feed_lab_forces_all_levels(self):
        self.assertGreaterEqual(int(live_feed.LAB_BUILD), 5015)
        self.assertEqual(live_feed.FEED_LEVEL_SELECTION, 0x139714)
        self.assertEqual(live_feed.FEED_LEVEL_SELECTION_ORIGINAL, 0x9A960016)
        self.assertEqual(live_feed.FEED_LEVEL_ALL, 0xAA1F03F6)

    def test_resigning_allows_only_code_signature_bytes(self):
        header = bytearray(32 + 16 + 64)
        header[0:4] = (0xFEEDFACF).to_bytes(4, "little")
        header[16:20] = (1).to_bytes(4, "little")
        header[20:24] = (16).to_bytes(4, "little")
        header[32:36] = (0x1D).to_bytes(4, "little")
        header[36:40] = (16).to_bytes(4, "little")
        header[40:44] = (48).to_bytes(4, "little")
        header[44:48] = (64).to_bytes(4, "little")
        self.assertEqual(lab.macho_code_signature_range(bytes(header)), (48, 64))


if __name__ == "__main__":
    unittest.main()
