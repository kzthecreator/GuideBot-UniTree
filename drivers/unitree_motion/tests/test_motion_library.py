import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "tools/motion/motion_library.py"
spec = importlib.util.spec_from_file_location("motion_library", SCRIPT)
motion_library = importlib.util.module_from_spec(spec)
spec.loader.exec_module(motion_library)


class MotionLibraryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.motions = self.root / "motions"
        self.poses = self.root / "poses"
        self.metadata = self.root / "metadata"
        self.catalog = self.root / "catalog.json"
        source = PROJECT_ROOT / "assets/motion/config/motion_catalog.json"
        self.catalog.write_bytes(source.read_bytes())

    def motion(self, name="neutral", row=None):
        path = self.poses / "basic" / f"{name}.dat" if name == "neutral" else self.motions / "reception" / f"{name}.dat"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1\n14\n" + (row or "0.3 " + " ".join(["0"] * 14)) + "\n", encoding="utf-8")
        return path

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--dir", str(self.motions), "--poses", str(self.poses), "--metadata",
             str(self.metadata), "--catalog", str(self.catalog), *args],
            capture_output=True, text=True, check=False,
        )

    def test_inventory_has_22_actions_and_missing_are_visible(self):
        result = self.cli("list")
        self.assertEqual(len([line for line in result.stdout.splitlines() if line.startswith("FAIL")]), 22)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("elevator_button_prepose", result.stdout)

    def test_draft_tested_approved_and_hash_invalidation(self):
        path = self.motion()
        self.assertEqual(self.cli("init-meta", "neutral").returncode, 0)
        meta_path = self.metadata / "neutral.json"
        self.assertEqual(json.loads(meta_path.read_text())["status"], "draft")
        self.assertNotEqual(self.cli("init-meta", "neutral").returncode, 0)
        self.assertNotEqual(self.cli("approve", "neutral", "--verified-by", "tester",
                                     "--verified-at", "2026-11-11T10:00:00+08:00",
                                     "--confirm-physical-test").returncode, 0)
        self.assertEqual(self.cli("mark-tested", "neutral").returncode, 0)
        self.assertEqual(self.cli("approve", "neutral", "--verified-by", "tester",
                                  "--verified-at", "2026-11-11T10:00:00+08:00",
                                  "--confirm-physical-test").returncode, 0)
        self.assertEqual(self.cli("validate", "neutral").returncode, 0)
        path.write_text(path.read_text().replace("0.3", "0.4"), encoding="utf-8")
        self.assertNotEqual(self.cli("validate", "neutral").returncode, 0)
        self.assertEqual(self.cli("refresh-meta", "neutral").returncode, 0)
        meta = json.loads(meta_path.read_text())
        self.assertEqual(meta["status"], "draft")
        self.assertEqual(meta["version"], 2)

    def test_bad_motion_and_malformed_metadata(self):
        self.motion(row="0.3 nan " + " ".join(["0"] * 13))
        self.assertNotEqual(self.cli("init-meta", "neutral").returncode, 0)
        self.motion()
        self.assertEqual(self.cli("init-meta", "neutral").returncode, 0)
        meta_path = self.metadata / "neutral.json"
        meta_path.write_text(json.dumps({"status": [], "movement_context": {}}))
        result = self.cli("validate", "neutral")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    def test_approve_uses_current_timezone_aware_time_when_omitted(self):
        self.motion()
        self.assertEqual(self.cli("init-meta", "neutral").returncode, 0)
        self.assertEqual(self.cli("mark-tested", "neutral").returncode, 0)
        before = datetime.now(timezone.utc)
        result = self.cli("approve", "neutral", "--verified-by", "tester",
                          "--confirm-physical-test")
        after = datetime.now(timezone.utc)
        self.assertEqual(result.returncode, 0, result.stderr)
        meta = json.loads((self.metadata / "neutral.json").read_text())
        stamp = datetime.fromisoformat(meta["verified_at"])
        self.assertIsNotNone(stamp.tzinfo)
        self.assertLessEqual(before.timestamp() - 1, stamp.timestamp())
        self.assertLessEqual(stamp.timestamp(), after.timestamp())
        self.assertIn(meta["verified_at"], result.stdout)

    def test_extra_file_detected(self):
        self.motion("orphan")
        result = self.cli("list")
        self.assertIn("未登记文件", result.stdout)

    def test_single_frame_motion_is_valid_target(self):
        self.motion("greet_open")
        result = self.cli("init-meta", "greet_open")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.cli("validate", "greet_open").returncode, 0)
        meta = json.loads((self.metadata / "greet_open.json").read_text())
        self.assertEqual(meta["keyframe_times_ms"], [0])
        self.assertEqual(meta["nominal_duration_ms"], 0)
        self.assertEqual(meta["entry_pose"], meta["exit_pose"])
        confirmed = motion_library.confirm_metadata(
            self.metadata / "greet_open.json", meta, "tester")
        self.assertEqual(confirmed["status"], "approved")
        self.assertEqual(self.cli("validate", "greet_open").returncode, 0)

    def test_timing_save_changes_ratios_and_resets_approval(self):
        path = self.motion("greet_open")
        zero = " ".join(["0"] * 14)
        path.write_text(f"3\n14\n0.3 {zero}\n0.3 {zero}\n0.3 {zero}\n", encoding="utf-8")
        self.assertEqual(self.cli("init-meta", "greet_open").returncode, 0)
        entries = motion_library.catalog_entries(self.catalog)
        meta, changed = motion_library.save_timing(
            "greet_open", [1, 3], entries, self.motions, self.poses, self.metadata)
        self.assertTrue(changed)
        self.assertEqual(meta["status"], "draft")
        self.assertEqual(meta["keyframe_times_ms"], [0, 150, 600])
        self.assertEqual(meta["nominal_duration_ms"], 600)
        self.assertEqual(self.cli("validate", "greet_open").returncode, 0)
        self.assertTrue(path.with_suffix(".dat.bak").is_file())
        self.assertEqual(self.cli("mark-tested", "greet_open").returncode, 0)
        self.assertEqual(self.cli("approve", "greet_open", "--verified-by", "tester",
                                  "--confirm-physical-test").returncode, 0)
        meta, changed = motion_library.save_timing(
            "greet_open", [3, 1], entries, self.motions, self.poses, self.metadata)
        self.assertTrue(changed)
        self.assertEqual(meta["status"], "draft")
        self.assertEqual(meta["version"], 3)
        self.assertEqual(meta["verified_by"], "")

    def test_timing_save_rejects_invalid_ratio_without_modifying_file(self):
        path = self.motion("greet_open")
        zero = " ".join(["0"] * 14)
        path.write_text(f"3\n14\n0.3 {zero}\n0.3 {zero}\n0.3 {zero}\n", encoding="utf-8")
        self.assertEqual(self.cli("init-meta", "greet_open").returncode, 0)
        original = path.read_bytes()
        with self.assertRaises(ValueError):
            motion_library.save_timing(
                "greet_open", [0.05, 20], motion_library.catalog_entries(self.catalog),
                self.motions, self.poses, self.metadata)
        self.assertEqual(path.read_bytes(), original)

    def test_single_frame_motion_has_no_editable_timing(self):
        path = self.motion("greet_open")
        self.assertEqual(self.cli("init-meta", "greet_open").returncode, 0)
        with self.assertRaises(ValueError):
            motion_library.save_timing(
                "greet_open", [], motion_library.catalog_entries(self.catalog),
                self.motions, self.poses, self.metadata)
        self.assertFalse(path.with_suffix(".dat.bak").exists())

    def test_unchanged_timing_can_be_confirmed_after_preview(self):
        path = self.motion("greet_open")
        zero = " ".join(["0"] * 14)
        path.write_text(f"2\n14\n0.3 {zero}\n0.3 {zero}\n", encoding="utf-8")
        self.assertEqual(self.cli("init-meta", "greet_open").returncode, 0)
        entries = motion_library.catalog_entries(self.catalog)
        meta, changed = motion_library.save_timing(
            "greet_open", [1], entries, self.motions, self.poses,
            self.metadata, confirm_by="tester")
        self.assertFalse(changed)
        self.assertEqual(meta["status"], "approved")
        self.assertEqual(meta["version"], 1)
        self.assertEqual(self.cli("validate", "greet_open").returncode, 0)


if __name__ == "__main__":
    unittest.main()
