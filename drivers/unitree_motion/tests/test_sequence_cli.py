from drivers.unitree_motion.paths import BUILD
import importlib.util
import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[3] / "assets/motion"
TOOL = Path(__file__).resolve().parents[3] / "tools/motion/motion_ctl.py"
spec = importlib.util.spec_from_file_location("motion_library", TOOL.with_name("motion_library.py"))
motion_library = importlib.util.module_from_spec(spec)
spec.loader.exec_module(motion_library)
ctl_spec = importlib.util.spec_from_file_location("motion_ctl", TOOL)
motion_ctl = importlib.util.module_from_spec(ctl_spec)
ctl_spec.loader.exec_module(motion_ctl)


class SequenceCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = ROOT / "config" / "motion_catalog.json"
        self.motions = self.root / "motions"
        self.poses = self.root / "poses"
        self.metadata = self.root / "metadata"
        self.metadata.mkdir()
        self.limits = self.root / "limits.json"
        self.sequence = self.root / "sequence.yaml"
        entries = motion_library.catalog_entries(self.catalog)
        for name, values in (("neutral", (0,)), ("greet_open", (0.02, 0.04, 0.02))):
            entry = entries[name]
            path = motion_library.asset_path(entry, self.motions, self.poses)
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = []
            for value in values:
                rows.append("0.5 " + str(value) + " " + " ".join(["0"] * 13))
            path.write_text(f"{len(values)}\n14\n" + "\n".join(rows) + "\n")
            points, errors, _ = motion_library.parse_motion(path)
            self.assertFalse(errors)
            meta = motion_library.metadata_for(entry, path, points)
            meta["status"] = "approved"
            meta["verified_by"] = "offline fixture"
            meta["verified_at"] = "2026-11-12T10:00:00+08:00"
            (self.metadata / f"{name}.json").write_text(json.dumps(meta))
        profile = {
            "schema_version": 1, "verified": True,
            "verified_by": "offline fixture", "verified_at": "2026-11-12T10:00:00+08:00",
            "joint_names": list(motion_library.JOINT_NAMES),
            "min_rad": [-1] * 14, "max_rad": [1] * 14,
        }
        self.limits.write_text(json.dumps(profile))
        self.sequence.write_text(yaml.safe_dump({
            "sequence_name": "greet_guest",
            "steps": [
                {"type": "pose", "name": "neutral", "hold_ms": 300},
                {"type": "motion", "name": "greet_open", "duration_ms": 1200,
                 "hold_ms": 800, "transition_ms": 400},
                {"type": "pose", "name": "neutral", "hold_ms": 300,
                 "transition_ms": 500},
            ],
        }), encoding="utf-8")

    def check(self):
        return subprocess.run([
            sys.executable, str(TOOL), "sequence", "--file", str(self.sequence), "--check",
            "--limits", str(self.limits), "--catalog", str(self.catalog),
            "--dir", str(self.motions), "--poses", str(self.poses),
            "--metadata", str(self.metadata),
        ], cwd=ROOT, capture_output=True, text=True, check=False)

    def check_preview(self, name="neutral"):
        return subprocess.run([
            str(BUILD / "motion_library_server"), "--check-preview", name,
            "--limits", str(self.limits), "--catalog", str(self.catalog),
            "--dir", str(self.motions), "--poses", str(self.poses),
            "--metadata", str(self.metadata),
        ], cwd=ROOT, capture_output=True, text=True, check=False)

    def test_preview_validates_draft_hash_and_joint_limits(self):
        path = self.metadata / "neutral.json"
        meta = json.loads(path.read_text())
        meta["status"] = "draft"
        meta["verified_by"] = meta["verified_at"] = ""
        path.write_text(json.dumps(meta))
        self.assertEqual(self.check_preview().returncode, 0)
        self.assertNotEqual(self.check().returncode, 0)
        profile = json.loads(self.limits.read_text())
        profile["verified"] = False
        self.limits.write_text(json.dumps(profile))
        unchecked = self.check_preview()
        self.assertEqual(unchecked.returncode, 0, unchecked.stderr)
        self.assertIn("joint limits unverified", unchecked.stdout)
        profile["verified"] = True
        profile["max_rad"] = [-0.1] * 14
        self.limits.write_text(json.dumps(profile))
        self.assertNotEqual(self.check_preview().returncode, 0)
        profile["max_rad"] = [1] * 14
        self.limits.write_text(json.dumps(profile))
        (self.poses / "basic" / "neutral.dat").write_text("1\n14\n0.5 " + " ".join(["0.01"] * 14) + "\n")
        self.assertNotEqual(self.check_preview().returncode, 0)

    def test_preview_check_uses_trial_duration(self):
        plans = []
        for duration in (1000, 5000):
            result = subprocess.run([
                sys.executable, str(TOOL), "preview", "greet_open", "--check",
                "--duration-ms", str(duration), "--weights-json", "[1, 1]",
                "--limits", str(self.limits), "--catalog", str(self.catalog),
                "--dir", str(self.motions), "--poses", str(self.poses),
                "--metadata", str(self.metadata),
            ], cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"core requested {duration / 1000:g} s", result.stdout)
            plans.append(result.stdout)
        self.assertIn("core planned 1 s", plans[0])
        self.assertIn("core planned 5 s", plans[1])

    def test_total_ms_uses_saved_profile_and_user_minimum(self):
        path = self.metadata / "greet_open.json"
        meta = json.loads(path.read_text())
        meta["timing_profile"] = {
            "phase_weights": {"transition": 1, "core": 4, "hold": 1},
            "minimum_total_ms": 12000, "frame_weights": [1, 3],
        }
        path.write_text(json.dumps(meta))
        for total, expected in ((6000, 12), (24000, 24)):
            self.sequence.write_text(yaml.safe_dump({
                "sequence_name": "timed", "steps": [
                    {"type": "motion", "name": "greet_open", "total_ms": total}],
            }))
            checked = self.check()
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn(f"{expected} s", checked.stdout)
            preview = subprocess.run([
                sys.executable, str(TOOL), "preview", "greet_open", "--check",
                "--total-ms", str(total), "--limits", str(self.limits),
                "--catalog", str(self.catalog), "--dir", str(self.motions),
                "--poses", str(self.poses), "--metadata", str(self.metadata),
            ], capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn(f"total planned {expected} s", preview.stdout)

    def test_total_ms_requires_profile_and_rejects_mixed_phase_times(self):
        for step in (
            {"type": "motion", "name": "greet_open", "total_ms": 6000},
            {"type": "motion", "name": "greet_open", "total_ms": 6000, "hold_ms": 100},
        ):
            self.sequence.write_text(yaml.safe_dump({"sequence_name": "invalid", "steps": [step]}))
            self.assertNotEqual(self.check().returncode, 0)

    def test_unsaved_profile_offline_preview_uses_uniform_timing(self):
        profile = {"phase_weights": {"transition": 1, "core": 2, "hold": 1},
                   "minimum_total_ms": 1000, "frame_weights": [1, 1]}
        result = subprocess.run([
            sys.executable, str(TOOL), "preview", "greet_open", "--offline", "--json-events",
            "--total-ms", "100", "--timing-profile-json", json.dumps(profile),
            "--limits", str(self.limits), "--catalog", str(self.catalog),
            "--dir", str(self.motions), "--poses", str(self.poses),
            "--metadata", str(self.metadata),
        ], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()
                  if line.startswith('{"event": "preview"')]
        running = next(event["preview"] for event in events if event["preview"]["state"] == "running")
        self.assertAlmostEqual(running["planned_seconds"], 1)
        self.assertAlmostEqual(running["planned_core_seconds"], running["planned_seconds"] / 2)
        self.assertEqual(events[-1]["ownership"], "released")
        self.assertNotIn("timing_profile", json.loads((self.metadata / "greet_open.json").read_text()))

    def combo_fixture(self):
        entries = motion_library.catalog_entries(self.catalog)
        path = motion_library.asset_path(entries["present_right"], self.motions, self.poses)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("1\n14\n0.3 0.03 " + " ".join(["0"] * 13) + "\n")
        points, errors, _ = motion_library.parse_motion(path)
        self.assertFalse(errors)
        motion_library.write_meta(self.metadata / "present_right.json", motion_library.metadata_for(
            entries["present_right"], path, points))
        for name in ("neutral", "greet_open", "present_right"):
            meta_path = self.metadata / f"{name}.json"
            meta = json.loads(meta_path.read_text())
            meta.update(status="draft", verified_by="", verified_at="")
            meta["timing_profile"] = {
                "phase_weights": {"transition": 1, "core": 2 if name == "greet_open" else 0, "hold": 1},
                "minimum_total_ms": 200, "frame_weights": [1, 3] if name == "greet_open" else [],
            }
            meta_path.write_text(json.dumps(meta))
        sequence = {"sequence_name": "fixture_combo", "steps": [
            {"type": entries[name]["type"], "name": name, "total_ms": 100}
            for name in ("neutral", "greet_open", "neutral", "present_right", "neutral")
        ]}
        self.sequence.write_text(json.dumps(sequence))

    def combo_command(self, mode, *extra):
        return [
            sys.executable, str(TOOL), "preview", "fixture_combo", "--sequence-file", str(self.sequence),
            mode, "--json-events", "--limits", str(self.limits), "--catalog", str(self.catalog),
            "--dir", str(self.motions), "--poses", str(self.poses), "--metadata", str(self.metadata), *extra,
        ]

    def run_combo(self, mode, *extra):
        return subprocess.run(self.combo_command(mode, *extra), capture_output=True, text=True, timeout=30)

    def test_combo_draft_actions_run_continuously_and_release_once(self):
        self.combo_fixture()
        before = {path.name: path.read_bytes() for path in self.metadata.glob("*.json")}
        checked = self.run_combo("--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertIn("total planned 1 s", checked.stdout)
        self.assertIn("return directly to startup pose", checked.stdout)
        result = self.run_combo("--offline")
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"event": "preview"')]
        self.assertEqual(events[-1]["ownership"], "released")
        self.assertEqual(events[-1]["preview"]["name"], "fixture_combo")
        indices = {event.get("active_step_index") for event in events}
        self.assertTrue(set(range(5)).issubset(indices), indices)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.metadata.glob("*.json")})

    def test_combo_rejects_missing_profile_before_any_execution(self):
        self.combo_fixture()
        path = self.metadata / "present_right.json"
        meta = json.loads(path.read_text())
        del meta["timing_profile"]
        path.write_text(json.dumps(meta))
        result = self.run_combo("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("saved timing profile", result.stderr)

    def test_combo_cancellation_exits_and_releases_offline_session(self):
        self.combo_fixture()
        sequence = json.loads(self.sequence.read_text())
        for step in sequence["steps"]:
            step["total_ms"] = 2000
        self.sequence.write_text(json.dumps(sequence))
        log_path = self.root / "combo-output.txt"
        with log_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(self.combo_command("--offline"), stdout=output,
                                       stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 8
                while True:
                    lines = log_path.read_text().splitlines()
                    events = [json.loads(line) for line in lines
                              if line.startswith('{"event": "preview"') and line.endswith('}')]
                    if any(event["preview"]["state"] == "running" for event in events):
                        break
                    self.assertIsNone(process.poll(), lines)
                    self.assertLess(time.monotonic(), deadline, lines)
                    time.sleep(0.05)
                process.send_signal(signal.SIGINT)
                _, errors = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 130, errors)
                self.assertIn("取消试播并释放控制权", errors)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)

    def test_play_style_preview_honors_requested_time_and_supports_single_frame(self):
        def check(name, interpolation=None):
            return subprocess.run([
                sys.executable, str(TOOL), "preview", name, "--check",
                "--duration-ms", "20",
                "--limits", str(self.limits), "--catalog", str(self.catalog),
                "--dir", str(self.motions), "--poses", str(self.poses),
                "--metadata", str(self.metadata),
            ] + (["--interpolation", interpolation] if interpolation is not None else []),
                cwd=ROOT, capture_output=True, text=True, check=False)

        removed = check("greet_open", "quintic")
        linear = check("greet_open", "linear")
        self.assertNotEqual(removed.returncode, 0)
        self.assertEqual(linear.returncode, 0, linear.stderr)
        self.assertIn("core requested 0.02 s, core planned 0.02 s", linear.stdout)
        self.assertIn("Play-style linear preview: 2 ms commands", linear.stdout)
        default = check("greet_open")
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stdout, linear.stdout)
        neutral = check("neutral", "linear")
        self.assertEqual(neutral.returncode, 0, neutral.stderr)

    def test_preview_one_command_completes_offline(self):
        meta_path = self.metadata / "neutral.json"
        meta = json.loads(meta_path.read_text())
        meta["status"] = "draft"
        meta["verified_by"] = meta["verified_at"] = ""
        meta_path.write_text(json.dumps(meta))
        profile = json.loads(self.limits.read_text())
        profile["verified"] = False
        self.limits.write_text(json.dumps(profile))
        result = subprocess.run([
            sys.executable, str(TOOL), "preview", "neutral", "--offline",
            "--limits", str(self.limits), "--catalog", str(self.catalog),
            "--dir", str(self.motions), "--poses", str(self.poses),
            "--metadata", str(self.metadata),
        ], cwd=ROOT, capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("试播完成：neutral", result.stdout)
        self.assertIn("joint limits unverified", result.stderr)
        self.assertEqual(json.loads(meta_path.read_text())["status"], "draft")

    def test_preview_status_reports_planned_core_seconds(self):
        result = subprocess.run([
            sys.executable, str(TOOL), "preview", "greet_open", "--offline",
            "--no-confirm", "--json-events", "--duration-ms", "3000",
            "--hold-ms", "100", "--limits", str(self.limits),
            "--catalog", str(self.catalog), "--dir", str(self.motions),
            "--poses", str(self.poses), "--metadata", str(self.metadata),
        ], cwd=ROOT, capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()
                  if line.startswith('{"event": "preview"')]
        running = next(event["preview"] for event in events
                       if event["preview"]["state"] == "running")
        self.assertAlmostEqual(running["planned_core_seconds"], 3.0)
        self.assertGreater(running["planned_seconds"], running["planned_core_seconds"])

    def test_linear_preview_reports_linear_core_and_releases_offline(self):
        result = subprocess.run([
            sys.executable, str(TOOL), "preview", "greet_open", "--offline",
            "--no-confirm", "--json-events", "--duration-ms", "20",
            "--interpolation", "linear", "--hold-ms", "100",
            "--limits", str(self.limits), "--catalog", str(self.catalog),
            "--dir", str(self.motions), "--poses", str(self.poses),
            "--metadata", str(self.metadata),
        ], cwd=ROOT, capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        events = [json.loads(line) for line in result.stdout.splitlines()
                  if line.startswith('{"event": "preview"')]
        running = next(event["preview"] for event in events
                       if event["preview"]["state"] == "running")
        self.assertAlmostEqual(running["planned_core_seconds"], 0.02)
        self.assertIn("上半身控制权已释放", result.stdout)

    def test_single_frame_motion_sequence_and_offline_preview(self):
        path = self.motions / "reception" / "greet_open.dat"
        path.write_text("1\n14\n0.3 0.08 " + " ".join(["0"] * 13) + "\n")
        entry = motion_library.catalog_entries(self.catalog)["greet_open"]
        points, errors, _ = motion_library.parse_motion(path)
        self.assertFalse(errors)
        meta = motion_library.metadata_for(entry, path, points)
        meta.update(status="approved", verified_by="offline fixture",
                    verified_at="2026-11-12T10:00:00+08:00")
        (self.metadata / "greet_open.json").write_text(json.dumps(meta))
        self.assertEqual(self.check_preview("greet_open").returncode, 0)
        self.assertEqual(self.check().returncode, 0)
        result = subprocess.run([
            sys.executable, str(TOOL), "preview", "greet_open", "--offline",
            "--no-confirm", "--transition-ms", "500", "--hold-ms", "100",
            "--limits", str(self.limits), "--catalog", str(self.catalog),
            "--dir", str(self.motions), "--poses", str(self.poses),
            "--metadata", str(self.metadata),
        ], cwd=ROOT, capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("试播完成：greet_open", result.stdout)

    def test_playback_confirmation_records_approval(self):
        meta_path = self.metadata / "neutral.json"
        meta = json.loads(meta_path.read_text())
        meta["status"] = "draft"
        meta["verified_by"] = meta["verified_at"] = ""
        meta_path.write_text(json.dumps(meta))
        args = SimpleNamespace(name="neutral", dir=self.motions, poses=self.poses,
                               metadata=self.metadata, catalog=self.catalog)
        motion_ctl.confirm_preview(args)
        confirmed = json.loads(meta_path.read_text())
        self.assertEqual(confirmed["status"], "approved")
        self.assertTrue(confirmed["verified_by"])
        self.assertTrue(confirmed["verified_at"])

    def test_yaml_sequence_plans_offline(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("3 steps", result.stdout)

    def test_unverified_limits_and_stale_motion_are_rejected(self):
        profile = json.loads(self.limits.read_text())
        profile["verified"] = False
        self.limits.write_text(json.dumps(profile))
        self.assertNotEqual(self.check().returncode, 0)
        profile["verified"] = True
        self.limits.write_text(json.dumps(profile))
        path = self.motions / "reception" / "greet_open.dat"
        path.write_text(path.read_text().replace("0.04", "0.05"))
        self.assertNotEqual(self.check().returncode, 0)

    def test_anchor_mismatch_and_disallowed_repeat_are_rejected(self):
        path = self.metadata / "greet_open.json"
        meta = json.loads(path.read_text())
        meta["entry_pose"][0] = 0.4
        path.write_text(json.dumps(meta))
        self.assertNotEqual(self.check().returncode, 0)
        meta["entry_pose"][0] = 0.02
        path.write_text(json.dumps(meta))
        sequence = yaml.safe_load(self.sequence.read_text())
        sequence["steps"][1]["repeat"] = 2
        self.sequence.write_text(yaml.safe_dump(sequence))
        self.assertNotEqual(self.check().returncode, 0)

    def test_offline_socket_sequence_interrupt_resume(self):
        process = subprocess.Popen([
            str(BUILD / "motion_library_server"), "--offline-server",
            "--limits", str(self.limits), "--catalog", str(self.catalog),
            "--dir", str(self.motions), "--poses", str(self.poses),
            "--metadata", str(self.metadata),
        ], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)

        self.addCleanup(cleanup)

        def send(payload):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect("\0g1_arm_motion_library")
                client.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode())
                client.shutdown(socket.SHUT_WR)
                return json.loads(client.makefile().readline())

        deadline = time.monotonic() + 3
        while True:
            try:
                status = send({"状态": True})["status"]
                break
            except PermissionError:
                self.skipTest("sandbox blocks local Unix socket connections")
            except OSError:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
        request = yaml.safe_load(self.sequence.read_text(encoding="utf-8"))
        self.assertEqual(status["ownership"], "released")
        self.assertFalse(send({"序列": request})["ok"])
        self.assertTrue(send({"接管": True})["ok"])
        deadline = time.monotonic() + 2
        while send({"状态": True})["status"]["ownership"] != "owned":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertFalse(send({"试播": "neutral"})["ok"])
        self.assertTrue(send({"序列": request})["ok"])
        deadline = time.monotonic() + 2
        while send({"状态": True})["status"]["state"] != "running":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        time.sleep(0.5)
        self.assertTrue(send({"中断": True})["ok"])
        deadline = time.monotonic() + 4
        while True:
            status = send({"状态": True})["status"]
            if status["state"] == "paused":
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertEqual(status["checkpoint"]["step_name"], "greet_open")
        self.assertTrue(send({"恢复": True})["ok"])
        deadline = time.monotonic() + 2
        while send({"状态": True})["status"]["state"] != "running":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertTrue(send({"停止": True})["ok"])
        deadline = time.monotonic() + 3
        while send({"状态": True})["status"]["state"] != "idle":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertTrue(send({"退出": True})["ok"])
        process.wait(timeout=3)
        self.assertEqual(process.returncode, 0)

    def test_preview_socket_plays_one_draft_pose_and_auto_releases(self):
        path = self.metadata / "neutral.json"
        meta = json.loads(path.read_text())
        meta["status"] = "draft"
        meta["verified_by"] = meta["verified_at"] = ""
        path.write_text(json.dumps(meta))
        profile = json.loads(self.limits.read_text())
        profile["verified"] = False
        self.limits.write_text(json.dumps(profile))
        process = subprocess.Popen([
            str(BUILD / "motion_library_server"), "--offline-server",
            "--allow-preview", "--limits", str(self.limits),
            "--catalog", str(self.catalog), "--dir", str(self.motions),
            "--poses", str(self.poses), "--metadata", str(self.metadata),
        ], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)

        self.addCleanup(cleanup)

        def send(payload):
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1)
                client.connect("\0g1_arm_motion_library")
                client.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode())
                client.shutdown(socket.SHUT_WR)
                return json.loads(client.makefile().readline())

        deadline = time.monotonic() + 3
        while True:
            try:
                send({"状态": True})
                break
            except PermissionError:
                self.skipTest("sandbox blocks local Unix socket connections")
            except OSError:
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
        self.assertFalse(send({"试播": "neutral"})["ok"])
        self.assertTrue(send({"接管": True})["ok"])
        deadline = time.monotonic() + 2
        while send({"状态": True})["status"]["ownership"] != "owned":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertFalse(send({"腰部角度": 0})["ok"])
        response = send({"试播": "neutral"})
        self.assertTrue(response["ok"])
        self.assertIn("joint limits unverified", response["warning"])
        deadline = time.monotonic() + 3
        while True:
            status = send({"状态": True})["status"]
            if status["preview"] and status["preview"]["state"] == "completed":
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertEqual(status["ownership"], "released")
        self.assertFalse(status["preview"]["joint_limits_verified"])
        self.assertTrue(send({"接管": True})["ok"])
        deadline = time.monotonic() + 2
        while send({"状态": True})["status"]["ownership"] != "owned":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.assertFalse(send({"试播": "neutral"})["ok"])
        self.assertTrue(send({"退出": True})["ok"])
        process.wait(timeout=3)
        self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
