import tempfile
import unittest
from pathlib import Path
from shundo_hunter.phone_helper import xcode_command


class PhoneHelperTests(unittest.TestCase):
    def test_pinned_device_and_single_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            plan = Path(folder) / "Hunter.xctestrun"
            plan.touch()
            command = xcode_command(folder, "test-phone")
            self.assertEqual(command[0], "/usr/bin/xcodebuild")
            self.assertIn("id=test-phone", command)
            self.assertIn(str(plan), command)
            self.assertNotIn("build-for-testing", command)

    def test_missing_or_ambiguous_plan_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                xcode_command(folder, "test-phone")
            (Path(folder) / "One.xctestrun").touch()
            (Path(folder) / "Two.xctestrun").touch()
            with self.assertRaises(RuntimeError):
                xcode_command(folder, "test-phone")
