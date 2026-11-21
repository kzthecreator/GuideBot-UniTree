import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "assets/motion"
BUILD_DIR = Path(os.environ.get("GUIDEBOT_MOTION_BUILD_DIR",
                                Path.home() / ".local/share/guidebot/deps/motion/build-reorganized"))
BINARY = BUILD_DIR / "motion_library_server"
SOCKET = "\0guidebot_motion_test_" + str(os.getpid())


@unittest.skipUnless(BINARY.is_file(), "build motion_library_server first")
class OfflineServerTest(unittest.TestCase):
    def test_approved_action_interrupt_status_and_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            catalog = json.loads((ROOT / "config/motion_catalog.json").read_text(encoding="utf-8"))
            motions = folder / "motions"
            poses = folder / "poses"
            metadata = folder / "metadata"
            metadata.mkdir()
            names = ["neutral", "greet_open", "invite_follow", "present_center"]
            for name in names:
                entry = next(item for item in catalog["actions"] if item["name"] == name)
                root = poses if entry["type"] == "pose" else motions
                path = root / entry["category"] / f"{name}.dat"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("1\n14\n1.0 " + " ".join(["0"] * 14) + "\n")
                meta = {
                    "schema_version": 2, "name": name, "category": entry["category"],
                    "robot_model": "G1-7DOF", "source": "teach_with_name",
                    "status": "approved", "verified_by": "offline test",
                    "verified_at": "2026-11-11T10:00:00+08:00",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "version": 1, "scenes": [entry["category"]], "label": name,
                    "description": "test fixture", "movement_context": "stationary",
                }
                (metadata / f"{name}.json").write_text(json.dumps(meta), encoding="utf-8")
            request = {
                "标签": "offline",
                "动作": dict(zip("abcd", names)),
                "时间": {key: 1 for key in "abcd"},
            }
            process = subprocess.Popen(
                [str(BINARY), "--offline-server", "--dir", str(motions),
                 "--socket-name", SOCKET[1:],
                 "--poses", str(poses),
                 "--metadata", str(metadata)], cwd=ROOT,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            def cleanup():
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=3)

            self.addCleanup(cleanup)

            def send(payload):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(1)
                    client.connect(SOCKET)
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
                    if time.monotonic() > deadline:
                        self.fail("offline server did not start")
                    time.sleep(0.02)
            self.assertEqual(status["ownership"], "released")
            self.assertFalse(send(request)["ok"])
            self.assertTrue(send({"接管": True})["ok"])
            deadline = time.monotonic() + 2
            while send({"状态": True})["status"]["ownership"] != "owned":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            self.assertTrue(send(request)["ok"])
            deadline = time.monotonic() + 2
            while send({"状态": True})["status"]["state"] != "running":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            self.assertTrue(send({"中断": True})["ok"])
            deadline = time.monotonic() + 4
            while True:
                status = send({"状态": True})["status"]
                if status["state"] == "paused":
                    break
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            self.assertEqual(status["checkpoint"]["label"], "offline")
            self.assertTrue(send({"恢复": True})["ok"])
            deadline = time.monotonic() + 2
            while send({"状态": True})["status"]["state"] != "running":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            self.assertTrue(send({"停止": True})["ok"])
            deadline = time.monotonic() + 3
            while True:
                status = send({"状态": True})["status"]
                if status["state"] == "idle":
                    break
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            self.assertIsNone(status["checkpoint"])
            self.assertTrue(send({"释放": True})["ok"])
            deadline = time.monotonic() + 2
            while send({"状态": True})["status"]["ownership"] != "released":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            self.assertFalse(send(request)["ok"])
            self.assertTrue(send({"退出": True})["ok"])
            process.wait(timeout=3)
            self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
