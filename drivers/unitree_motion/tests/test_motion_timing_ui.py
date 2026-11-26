import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3] / "assets/motion"
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools/motion"))
import motion_library as library
import motion_timing_ui as timing_ui


class TimingProfileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "config/motion_catalog.json").write_bytes(
            (ROOT / "config/motion_catalog.json").read_bytes())
        self.entries = library.catalog_entries(self.root / "config/motion_catalog.json")
        self.profile = {
            "phase_weights": {"transition": 1, "core": 4, "hold": 1},
            "minimum_total_ms": 12000, "frame_weights": [1, 3],
        }
        self.path = self.root / "motions/reception/B_Open_Hold.dat"
        self.path.parent.mkdir(parents=True)
        row = "0.3 " + " ".join(["0"] * 14) + "\n"
        self.path.write_text("3\n14\n" + row * 3)
        points, errors, _ = library.parse_motion(self.path)
        self.assertFalse(errors)
        self.meta_path = self.root / "metadata/B_Open_Hold.json"
        library.write_meta(self.meta_path, library.metadata_for(
            self.entries["B_Open_Hold"], self.path, points))
        self.root_patch = patch.object(timing_ui, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.app = timing_ui.App()

    def payload(self):
        detail = self.app.detail("B_Open_Hold")
        return {"name": "B_Open_Hold", "sha256": detail["sha256"],
                "version": detail["version"], "timing_profile": copy.deepcopy(self.profile),
                "total_ms": 6000, "offline": False}

    def test_unrecorded_prosody_visible_but_preview_save_and_combo_rejected(self):
        items = {item["name"]: item for item in self.app.inventory()}
        prosody = [item for item in items.values() if item["category"] == "prosody"]
        self.assertEqual(len(prosody), sum(e["category"]=="prosody" for e in self.entries.values()))
        self.assertTrue(items["B_Open_Hold"]["available"])
        for item in prosody:
            self.assertFalse(item["recorded"])
            self.assertFalse(item["available"])
            self.assertFalse(item["profile_saved"])
            with self.assertRaisesRegex(ValueError, "动作文件不存在"):
                self.app.detail(item["name"])
            with self.assertRaises(ValueError):
                self.app.preview({"name": item["name"]})
            with self.assertRaises(ValueError):
                self.app.save({"name": item["name"]})
            with self.assertRaises(ValueError):
                self.app.combo_plan({"steps": [{"name": item["name"], "total_ms": 6000}]})

    def test_recorded_prosody_metadata_timing_and_existing_preview_command(self):
        name = "B_Down_Beat"
        path = self.root / "motions/prosody" / (name + ".dat")
        path.parent.mkdir(parents=True)
        path.write_bytes(self.path.read_bytes())
        item = next(item for item in self.app.inventory() if item["name"] == name)
        self.assertTrue(item["recorded"])
        self.assertFalse(item["available"])  # Metadata is still missing.
        points, _, _ = library.parse_motion(path)
        library.write_meta(self.root / "metadata" / (name + ".json"),
                           library.metadata_for(self.entries[name], path, points))
        detail = self.app.detail(name)
        self.assertEqual(detail["category"], "prosody")
        self.assertEqual(detail["frames"], 3)
        payload = dict(self.payload(), name=name, sha256=detail["sha256"], version=detail["version"])
        before = path.read_bytes()
        self.app.save(payload)
        detail = self.app.detail(name)
        self.assertEqual(detail["timing_profile"], self.profile)
        self.assertEqual(path.read_bytes(), before)
        payload["version"] = detail["version"]
        with patch.object(Path, "is_file", return_value=True), patch.object(self.app, "launch") as launch:
            self.app.preview(payload)
        command = launch.call_args[0][0]
        self.assertIn("motion_ctl.py", command[1])
        self.assertEqual(command[2:4], ["preview", name])
        self.assertTrue(next(item for item in self.app.inventory() if item["name"] == name)["available"])

    def test_save_reload_preserves_exact_ratios_and_does_not_change_recording(self):
        before = self.path.read_bytes()
        result = self.app.save(self.payload())
        self.assertTrue(result["changed"])
        self.assertFalse(result["confirmed"])
        detail = self.app.detail("B_Open_Hold")
        self.assertEqual(detail["timing_profile"], self.profile)
        self.assertEqual(detail["version"], 2)
        self.assertEqual(detail["status"], "draft")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.app.save(self.payload())["changed"])

    def test_profile_edit_invalidates_approval_and_stale_save_is_rejected(self):
        payload = self.payload()
        self.app.tested = ("B_Open_Hold", payload["sha256"], payload["version"],
                           payload["timing_profile"], payload["total_ms"])
        self.assertTrue(self.app.save(payload)["confirmed"])
        with self.assertRaises(ValueError):
            self.app.save(payload)
        updated = self.payload()
        updated["timing_profile"]["minimum_total_ms"] += 1000
        self.assertFalse(self.app.save(updated)["confirmed"])
        meta = json.loads(self.meta_path.read_text())
        self.assertEqual(meta["status"], "draft")
        self.assertEqual(meta["verified_by"], "")

    def test_modified_profile_cannot_reuse_previous_physical_confirmation(self):
        payload = self.payload()
        self.app.tested = ("B_Open_Hold", payload["sha256"], payload["version"],
                           copy.deepcopy(payload["timing_profile"]), payload["total_ms"])
        payload["timing_profile"]["phase_weights"]["hold"] = 2
        self.assertFalse(self.app.save(payload)["confirmed"])

    def test_only_three_or_more_frames_have_editable_frame_weights(self):
        for frames in (1, 2):
            profile = copy.deepcopy(self.profile)
            if frames == 1:
                profile["phase_weights"]["core"] = 0
            with self.assertRaises(ValueError):
                library.validate_timing_profile(profile, frames)
            profile["frame_weights"] = []
            self.assertEqual(library.validate_timing_profile(profile, frames), profile)

    def test_invalid_profiles_do_not_overwrite_metadata(self):
        before = self.meta_path.read_bytes()
        for key, invalid in (("transition", 0), ("core", -1), ("hold", float("nan"))):
            payload = self.payload()
            payload["timing_profile"]["phase_weights"][key] = invalid
            with self.assertRaises(ValueError):
                self.app.save(payload)
        payload = self.payload()
        payload["timing_profile"]["minimum_total_ms"] = True
        with self.assertRaises(ValueError):
            self.app.save(payload)
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_combo_uses_saved_profiles_minima_and_preserves_duplicate_order(self):
        self.app.save(self.payload())
        before = self.meta_path.read_bytes()
        plan = self.app.combo_plan({"steps": [
            {"name": "B_Open_Hold", "total_ms": 6000},
            {"name": "B_Open_Hold", "total_ms": 24000},
        ]})
        self.assertEqual([step["planned_ms"] for step in plan["steps"]], [12000, 24000])
        self.assertEqual(plan["requested_ms"], 30000)
        self.assertEqual(plan["planned_ms"], 36000)
        self.assertEqual([step["total_ms"] for step in plan["sequence"]["steps"]], [6000, 24000])
        self.assertEqual(self.meta_path.read_bytes(), before)

    def test_combo_rejects_empty_oversized_unknown_and_unsaved_actions(self):
        for steps in ([], [{"name": "B_Open_Hold", "total_ms": 1}] * 65,
                      [{"name": "B_Open_Hold", "total_ms": 6000}],
                      [{"name": "missing", "total_ms": 6000}]):
            with self.assertRaises(ValueError):
                self.app.combo_plan({"steps": steps})
        self.app.save(self.payload())
        for duration in (True, 0, 600001, 1.5):
            with self.assertRaises(ValueError):
                self.app.combo_plan({"steps": [{"name": "B_Open_Hold", "total_ms": duration}]})

    def test_combo_launch_uses_one_sequence_and_does_not_confirm_individual_actions(self):
        self.app.save(self.payload())
        with patch.object(self.app, "launch") as launch:
            self.app.preview_combo({"steps": [{"name": "B_Open_Hold", "total_ms": 6000}], "offline": True})
        args, kwargs = launch.call_args
        self.assertIsNone(args[1])
        self.assertEqual(kwargs["mode"], "combo")
        path = kwargs["cleanup_path"]
        self.addCleanup(path.unlink, missing_ok=True)
        self.assertEqual(json.loads(path.read_text())["steps"][0]["name"], "B_Open_Hold")
        self.assertIn("--offline", args[0])
        self.assertIn("--sequence-file", args[0])
        class Finished:
            stdout = [json.dumps({"event": "preview", "preview": {"state": "completed",
                       "planned_seconds": 12}, "active_step_index": None})]
            def wait(self):
                return 0
        self.app.state = {"running": True}
        self.app.watch(Finished(), None, False, path)
        self.assertTrue(self.app.state["success"])
        self.assertFalse(self.app.state["eligible"])
        self.assertIsNone(self.app.tested)
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
