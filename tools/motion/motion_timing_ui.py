#!/usr/bin/env python3
"""Local timing editor and supervised one-shot preview launcher."""

import argparse
from collections import deque
from datetime import datetime
import errno
import getpass
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import motion_library as library

from drivers.unitree_motion.paths import ASSETS as ROOT, BUILD, LIMITS
PAGE = Path(__file__).with_suffix(".html")


class App:
    def __init__(self):
        self.entries = library.catalog_entries(ROOT / "config/motion_catalog.json")
        self.lock = threading.Lock()
        self.process = None
        self.stopping = False
        self.state = {"running": False, "phase": "idle", "planned_seconds": None,
                      "planned_core_seconds": None, "requested_core_seconds": None,
                      "message": "", "success": False, "eligible": False}
        self.tested = None
        self.cancelled = False

    def inventory(self):
        self.entries = library.catalog_entries(ROOT / "config/motion_catalog.json")
        items = []
        for name, entry in self.entries.items():
            path = library.asset_path(entry, ROOT / "motions", ROOT / "poses")
            item = {"name": name, "type": entry["type"], "category": entry["category"],
                    "recorded": path.is_file(), "available": False, "profile_saved": False}
            if item["recorded"]:
                try:
                    detail = self.detail(name)
                    item.update(available=True, profile_saved=detail["profile_saved"],
                                minimum_total_ms=detail["timing_profile"]["minimum_total_ms"])
                except (OSError, ValueError) as error:
                    item["error"] = str(error)
            else:
                item["error"] = "未录制：动作文件不存在，请先使用 teach_with_name 录制"
            items.append(item)
        return items

    def detail(self, name):
        self.entries = library.catalog_entries(ROOT / "config/motion_catalog.json")
        if type(name) is not str or name not in self.entries:
            raise ValueError("动作名不在清单中")
        result, errors, warnings = library.inspect(
            name, self.entries, ROOT / "motions", ROOT / "poses", ROOT / "metadata")
        if errors:
            raise ValueError("; ".join(errors))
        points, meta = result
        intervals = [round(value * 1000) for value, _ in points[1:]]
        mean = sum(intervals) / len(intervals) if intervals else 1
        profile = meta.get("timing_profile", {
            "phase_weights": {"transition": 1, "core": 2 if intervals else 0, "hold": 1},
            "minimum_total_ms": 3000,
            "frame_weights": [value / mean for value in intervals] if len(points) >= 3 else [],
        })
        return {"name": name, "type": self.entries[name]["type"],
                "category": self.entries[name]["category"], "status": meta["status"],
                "sha256": meta["sha256"], "version": meta["version"], "frames": len(points),
                "timing_profile": profile, "profile_saved": "timing_profile" in meta,
                "intervals_ms": intervals, "nominal_ms": sum(intervals),
                "warnings": warnings, "label": meta.get("label", name),
                "description": meta.get("description", ""),
                "gesture_group": meta.get("gesture_group", "prosody" if self.entries[name]["category"]=="prosody" else "semantic"),
                "confirmed_total_ms": meta.get("preview_confirmation", {}).get("total_ms")}

    def preview(self, payload):
        name = payload.get("name")
        detail = self.detail(name)
        if payload.get("sha256") != detail["sha256"] or payload.get("version") != detail["version"]:
            raise ValueError("动作或时间配置已变化，请重新载入")
        profile = library.validate_timing_profile(payload.get("timing_profile"), detail["frames"])
        total = self.check_int(payload.get("total_ms"), 1, 600000, "高层请求总时长")
        offline = payload.get("offline", False)
        if type(offline) is not bool:
            raise ValueError("离线选项无效")
        binary = BUILD / "motion_library_server"
        if not binary.is_file():
            raise ValueError("请先构建 motion_library_server")
        cmd = [sys.executable, str(Path(__file__).with_name("motion_ctl.py")), "preview", name,
               "--no-confirm", "--json-events", "--total-ms", str(total),
               "--timing-profile-json", json.dumps(profile)]
        if offline:
            cmd.append("--offline")
        signature = (name, detail["sha256"], detail["version"], profile, total)
        requested_core = max(total, profile["minimum_total_ms"]) / 1000 * \
            profile["phase_weights"]["core"] / sum(profile["phase_weights"].values())
        self.launch(cmd, signature, offline, requested_core=requested_core)

    def simple_payload(self, payload):
        detail = self.detail(payload.get("name"))
        # Keep the phase/frame distribution and the user-selected lower bound.
        # Runtime may stretch it to fit the planned speech window.
        profile = json.loads(json.dumps(detail["timing_profile"]))
        profile["minimum_total_ms"] = self.check_int(payload.get("minimum_total_ms", profile["minimum_total_ms"]), 1, 600000, "最短总时长")
        return dict(payload, timing_profile=profile)

    def simple_preview(self, payload):
        self.preview(self.simple_payload(payload))

    def confirm_available(self, payload):
        payload = self.simple_payload(payload)
        name = payload.get("name")
        detail = self.detail(name)
        total = self.check_int(payload.get("total_ms"), 1, 600000, "本次试播总时长")
        profile = library.validate_timing_profile(payload["timing_profile"], detail["frames"])
        signature = (name, payload.get("sha256"), payload.get("version"), profile, total)
        with self.lock:
            if (self.stopping or self.state["running"] or self.cancelled
                    or not self.state.get("eligible") or self.tested != signature):
                raise ValueError("请先按当前动作和时长完成真机试播，再确认可用")
            # Confirm this lower bound/distribution, without fixing runtime duration.
            saved_profile = json.loads(json.dumps(profile))
            actual_total = max(total, profile["minimum_total_ms"])
            from tools.motion.confirm_motion import confirm
            meta = confirm(ROOT, self.entries, name, payload.get("sha256"),
                           payload.get("version"), saved_profile, actual_total, getpass.getuser())
            self.tested = None
            self.state["eligible"] = False
        return {"confirmed": True, "enabled": True, "status": meta["status"],
                "message": "已确认可用，自动加入 LLM 动作列表"}

    def combo_plan(self, payload):
        steps = payload.get("steps")
        if type(steps) is not list or not 1 <= len(steps) <= 64:
            raise ValueError("组合须包含1到64个动作")
        sequence = {"sequence_name": "web_combo", "steps": []}
        planned_steps = []
        for index, step in enumerate(steps):
            if type(step) is not dict or set(step) != {"name", "total_ms"}:
                raise ValueError("组合步骤须包含动作名和总时长")
            detail = self.detail(step["name"])
            if not detail["profile_saved"]:
                raise ValueError(f"第{index + 1}步 {detail['name']} 尚未保存比例与最短时间")
            total = self.check_int(step["total_ms"], 1, 600000, f"第{index + 1}步总时长")
            minimum = detail["timing_profile"]["minimum_total_ms"]
            sequence["steps"].append({"type": detail["type"], "name": detail["name"], "total_ms": total})
            planned_steps.append({"name": detail["name"], "total_ms": total,
                                  "minimum_total_ms": minimum, "planned_ms": max(total, minimum)})
        return {"sequence": sequence, "steps": planned_steps,
                "requested_ms": sum(step["total_ms"] for step in planned_steps),
                "planned_ms": sum(step["planned_ms"] for step in planned_steps)}

    def preview_combo(self, payload):
        plan = self.combo_plan(payload)
        offline = payload.get("offline", False)
        if type(offline) is not bool:
            raise ValueError("离线选项无效")
        path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="g1-combo-",
                                             suffix=".json", delete=False) as stream:
                path = Path(stream.name)
                json.dump(plan["sequence"], stream, ensure_ascii=False)
            cmd = [sys.executable, str(Path(__file__).with_name("motion_ctl.py")), "preview", "web_combo",
                   "--sequence-file", str(path), "--no-confirm", "--json-events"]
            if offline:
                cmd.append("--offline")
            self.launch(cmd, None, offline, mode="combo", steps=plan["steps"], cleanup_path=path)
        except Exception:
            if path is not None:
                path.unlink(missing_ok=True)
            raise
        return plan

    def launch(self, cmd, signature, offline, requested_core=None,
               mode="single", steps=None, cleanup_path=None):
        if not (BUILD / "motion_library_server").is_file():
            raise ValueError("请先构建 motion_library_server")
        with self.lock:
            if self.stopping:
                raise ValueError("网页服务正在关闭")
            if self.state["running"]:
                raise ValueError("已有试播正在执行")
            self.tested = None
            self.cancelled = False
            self.state = {"running": True, "phase": "starting", "planned_seconds": None,
                          "planned_core_seconds": None,
                          "requested_core_seconds": requested_core,
                          "mode": mode, "steps": steps or [], "active_step_index": None,
                          "message": "正在启动试播", "success": False, "eligible": False}
            log_dir = Path.home()/".local/state/guidebot/motion-previews"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir/(datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".log")
            self.state["log_path"] = str(log_path)
            try:
                self.process = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE,
                                                stderr=subprocess.STDOUT, text=True,
                                                bufsize=1, start_new_session=True,
                                                env=dict(os.environ, PYTHONUNBUFFERED="1"))
            except OSError:
                self.state["running"] = False
                raise
            threading.Thread(target=self.watch, args=(self.process, signature, offline, cleanup_path, log_path), daemon=True).start()

    def watch(self, process, signature, offline, cleanup_path=None, log_path=None):
        lines = deque(maxlen=40)
        log = Path(log_path).open("w", encoding="utf-8") if log_path else None
        for line in process.stdout:
            if log is not None:
                log.write(line)
                log.flush()
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = None
            with self.lock:
                if event and event.get("event") == "preview":
                    preview = event["preview"]
                    self.state["phase"] = preview.get("state", "running")
                    self.state["planned_seconds"] = preview.get("planned_seconds")
                    self.state["planned_core_seconds"] = preview.get("planned_core_seconds")
                    self.state["active_step_index"] = event.get("active_step_index")
                    self.state["message"] = preview.get("error") or self.state["phase"]
                else:
                    lines.append(line)
                    self.state["message"] = line
        code = process.wait()
        if log is not None:
            log.write(f"\n[EXIT] code={code}\n")
            log.close()
        errors = [line for line in lines if any(marker in line.lower() for marker in
                  ("试播失败", "error:", "runtimeerror", "traceback", "[rejected]", "[error]", "failed to"))]
        failure = errors[-1] if errors else (lines[-1] if lines else "未收到执行状态")
        with self.lock:
            self.state["exit_code"] = code
            self.state["recent_output"] = list(lines)
            success = code == 0 and self.state["phase"] == "completed" and not self.cancelled
            self.state.update(running=False, success=success, eligible=success and not offline and signature is not None,
                              phase="completed" if success else "failed",
                              message="试播完成，控制权已释放" if success else
                                      (f"试播失败（退出码 {code}）：{failure}"))
            if success and not offline and signature is not None:
                self.tested = signature
            self.process = None
        if cleanup_path is not None:
            cleanup_path.unlink(missing_ok=True)

    def cancel(self):
        with self.lock:
            if not self.state["running"] or self.process is None:
                return
            self.cancelled = True
            os.killpg(self.process.pid, signal.SIGINT)
            self.state["message"] = "正在取消并释放控制权"
            self.state["eligible"] = False
            self.tested = None

    def save(self, payload):
        name = payload.get("name")
        detail = self.detail(name)
        profile = library.validate_timing_profile(payload.get("timing_profile"), detail["frames"])
        total = self.check_int(payload.get("total_ms"), 1, 600000, "高层请求总时长")
        with self.lock:
            if self.stopping:
                raise ValueError("网页服务正在关闭")
            if self.state["running"]:
                raise ValueError("试播运行时不能保存")
            confirmed = self.tested == (name, payload.get("sha256"), payload.get("version"), profile, total)
            meta, changed = library.save_timing_profile(
                name, profile, self.entries, ROOT / "motions", ROOT / "poses", ROOT / "metadata",
                payload.get("sha256"), payload.get("version"), getpass.getuser() if confirmed else None)
            self.tested = None
        return {"changed": changed, "confirmed": confirmed and meta["status"] == "approved",
                "status": meta["status"]}

    @staticmethod
    def check_int(value, low, high, label):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"{label}须为{low}到{high}的整数毫秒")
        return value

APP = App()


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/":
                body = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/api/motions":
                self.reply(200, {"items": APP.inventory()})
            elif url.path == "/api/motion":
                self.reply(200, APP.detail(parse_qs(url.query).get("name", [""])[0]))
            elif url.path == "/api/status":
                with APP.lock:
                    self.reply(200, dict(APP.state))
            else:
                self.reply(404, {"error": "页面不存在"})
        except (OSError, ValueError) as error:
            self.reply(400, {"error": str(error)})

    def do_POST(self):
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{self.headers.get('Host')}":
            self.reply(403, {"error": "来源不允许"})
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.reply(415, {"error": "只接受JSON"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 65536:
                raise ValueError("请求过大")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("请求必须是对象")
            if self.path == "/api/simple-preview":
                APP.simple_preview(payload)
                result = {"started": True}
            elif self.path == "/api/confirm":
                result = APP.confirm_available(payload)
            elif self.path == "/api/preview":
                APP.preview(payload)
                result = {"started": True}
            elif self.path == "/api/combo-plan":
                result = APP.combo_plan(payload)
            elif self.path == "/api/combo-preview":
                result = APP.preview_combo(payload)
            elif self.path == "/api/cancel":
                APP.cancel()
                result = {"cancelled": True}
            elif self.path == "/api/save":
                result = APP.save(payload)
            elif self.path == "/api/shutdown":
                with APP.lock:
                    if APP.state["running"]:
                        raise ValueError("请先取消试播，再关闭网页服务")
                    APP.stopping = True
                self.reply(200, {"stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                self.reply(404, {"error": "接口不存在"})
                return
            self.reply(200, result)
        except (ValueError, OSError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(description="本机动作试播与确认窗口")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        url = f"http://127.0.0.1:{args.port}"
        try:
            with urllib.request.urlopen(url + "/api/status", timeout=1) as response:
                status = json.load(response)
            if isinstance(status, dict) and "running" in status and "phase" in status:
                print(f"动作时间轴已在运行：{url}（本次未启动新进程）")
                return
        except (OSError, ValueError, urllib.error.URLError):
            pass
        parser.error(f"端口 {args.port} 已被其他程序占用；可用 --port 指定其他端口")
    print(f"Motion timing editor: http://127.0.0.1:{server.server_port}", flush=True)
    previous_handlers = {}
    def stop_on_signal(signum, _frame):
        raise KeyboardInterrupt
    for signum in (signal.SIGTERM, signal.SIGHUP):
        previous_handlers[signum] = signal.signal(signum, stop_on_signal)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        APP.cancel()
        with APP.lock:
            process = APP.process
        if process is not None:
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                print("试播进程未及时退出，请检查其控制权状态", file=sys.stderr)
    finally:
        server.server_close()
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    main()
