#!/usr/bin/env python3
"""Send action or waist commands to the local standing motion controller."""

import argparse
import getpass
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drivers.unitree_motion.client import request, SOCKET_NAME

from drivers.unitree_motion.paths import ASSETS as ROOT, BUILD, LIMITS


def preview_server_args(args, socket_name):
    command = [str(BUILD / "motion_library_server"), "--allow-preview",
               "--socket-name", socket_name[1:],
               "--limits", str(args.limits), "--catalog", str(args.catalog),
               "--dir", str(args.dir), "--poses", str(args.poses),
               "--metadata", str(args.metadata)]
    if args.offline:
        command.append("--offline-server")
    else:
        command.append("--auto-preview")
    return command


def preview_payload(args):
    if args.sequence_file is not None:
        if any(value is not None for value in (args.total_ms, args.timing_profile_json,
                args.duration_ms, args.hold_ms, args.transition_ms, args.weights_json, args.interpolation)):
            raise ValueError("组合文件不能与单动作试播参数混用")
        return {"组合试播": json.loads(args.sequence_file.read_text(encoding="utf-8"))}
    options = {"name": args.name}
    if args.total_ms is not None:
        options["total_ms"] = args.total_ms
    if args.timing_profile_json is not None:
        options["timing_profile"] = json.loads(args.timing_profile_json)
    if args.duration_ms is not None:
        options["duration_ms"] = args.duration_ms
    if args.hold_ms is not None:
        options["hold_ms"] = args.hold_ms
    if args.transition_ms is not None:
        options["transition_ms"] = args.transition_ms
    if args.weights_json is not None:
        options["weights"] = json.loads(args.weights_json)
    if args.interpolation is not None:
        options["interpolation"] = args.interpolation
    return {"试播": options} if len(options) > 1 else {"试播": args.name}


def confirm_preview(args):
    meta_path = args.metadata / f"{args.name}.json"
    if not meta_path.is_absolute():
        meta_path = ROOT / meta_path
    status = json.loads(meta_path.read_text(encoding="utf-8"))["status"]
    if status == "approved":
        print("动作已在动作库中，无需重复确认")
        return
    common = [sys.executable, str(Path(__file__).with_name("motion_library.py")),
              "--dir", str(args.dir), "--poses", str(args.poses),
              "--metadata", str(args.metadata), "--catalog", str(args.catalog)]
    if status == "draft":
        tested = subprocess.run(common + ["mark-tested", args.name],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        if tested.returncode:
            raise RuntimeError(tested.stderr.strip() or "无法记录试播结果")
    elif status != "tested":
        raise RuntimeError("动作元数据状态无效")
    approved = subprocess.run(
        common + ["approve", args.name, "--verified-by", getpass.getuser(),
                  "--confirm-physical-test"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if approved.returncode:
        raise RuntimeError(approved.stderr.strip() or "无法确认动作")
    print(f"动作已确认并录入动作库：{args.name}")


def preview_once(args):
    check = subprocess.run(
        [str(BUILD / "motion_library_server"), "--check-preview-request", "-",
         "--limits", str(args.limits), "--catalog", str(args.catalog),
         "--dir", str(args.dir), "--poses", str(args.poses),
         "--metadata", str(args.metadata)],
        input=json.dumps(preview_payload(args), ensure_ascii=False),
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    print(check.stdout or check.stderr, end="",
          file=sys.stdout if check.returncode == 0 else sys.stderr)
    if args.check or check.returncode != 0:
        return check.returncode

    socket_name = "\0g1_arm_motion_library_" + uuid.uuid4().hex
    process = subprocess.Popen(
        preview_server_args(args, socket_name), cwd=ROOT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"试播服务端已退出，退出码 {process.returncode}")
            try:
                status = request(socket_name, {"状态": True})["status"]
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("等待试播服务端启动超时")
                time.sleep(0.1)

        time.sleep(0.65)
        status = request(socket_name, {"状态": True})["status"]
        if status["ownership"] != "released":
            raise RuntimeError("试播服务端未处于已释放状态")
        request(socket_name, {"接管": True})
        deadline = time.monotonic() + 15
        while status["ownership"] != "owned":
            if process.poll() is not None:
                raise RuntimeError(f"接管时服务端退出，退出码 {process.returncode}")
            if time.monotonic() >= deadline:
                raise RuntimeError("接管未在 15 秒内完成")
            time.sleep(0.25)
            status = request(socket_name, {"状态": True})["status"]
            if status["ownership"] == "released":
                raise RuntimeError("接管被服务端拒绝；检查服务端日志")

        result = request(socket_name, preview_payload(args))
        if result.get("warning"):
            print("注意：" + result["warning"], file=sys.stderr)
        preview_started = time.monotonic()
        deadline = preview_started + 300
        last_event = None
        while True:
            if process.poll() is not None:
                raise RuntimeError(f"试播过程中服务端退出，退出码 {process.returncode}")
            status = request(socket_name, {"状态": True})["status"]
            preview = status.get("preview") or {}
            if preview.get("planned_seconds", 0) > 0:
                deadline = max(deadline, preview_started + preview["planned_seconds"] + 120)
            event = (preview.get("state"), status.get("ownership"),
                     preview.get("planned_seconds"), preview.get("error"), status.get("active_step_index"))
            if args.json_events and event != last_event:
                print(json.dumps({"event": "preview", "preview": preview,
                                  "active_step_index": status.get("active_step_index"),
                                  "ownership": status.get("ownership")},
                                 ensure_ascii=False), flush=True)
            last_event = event
            if preview.get("state") in {"rejected", "cancelled"}:
                raise RuntimeError("试播未完成：" + (preview.get("error") or preview["state"]))
            if preview.get("state") == "completed" and status["ownership"] == "released":
                print(f"试播完成：{args.name}；上半身控制权已释放")
                if not args.offline and not args.no_confirm and args.timing_profile_json is None and args.sequence_file is None:
                    try:
                        answer = input("确认这个动作可用并录入动作库？[y/N]: ").strip().lower()
                    except EOFError:
                        answer = ""
                    if answer in {"y", "yes", "是"}:
                        confirm_preview(args)
                    else:
                        print("未确认；动作文件已保留，可再次试播")
                return 0
            if time.monotonic() >= deadline:
                raise RuntimeError("试播等待超时")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n正在取消试播并释放控制权...", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"试播失败：{error}", file=sys.stderr)
        return 1
    finally:
        if process.poll() is None:
            try:
                status = request(socket_name, {"状态": True})["status"]
                if status["ownership"] == "owned":
                    request(socket_name, {"释放": True})
                deadline = time.monotonic() + 30
                while status["ownership"] != "released" and time.monotonic() < deadline:
                    time.sleep(0.1)
                    status = request(socket_name, {"状态": True})["status"]
                request(socket_name, {"退出": True})
                process.wait(timeout=10)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description="向本机 G1 上半身控制进程发送指令")
    commands = parser.add_subparsers(dest="command", required=True)
    action = commands.add_parser("action", help="发送四段动作标签")
    source = action.add_mutually_exclusive_group(required=True)
    source.add_argument("--json", help="完整 JSON 标签")
    source.add_argument("--file", type=Path, help="包含 JSON 标签的文件")
    sequence = commands.add_parser("sequence", help="发送 YAML 高层动作序列")
    sequence.add_argument("--file", type=Path, required=True, help="Sequence YAML 文件")
    sequence.add_argument("--check", action="store_true", help="只做离线规划校验，不连接机器人")
    sequence.add_argument("--limits", type=Path, default=LIMITS)
    sequence.add_argument("--catalog", type=Path, default=ROOT / "config/motion_catalog.json")
    sequence.add_argument("--dir", type=Path, default=ROOT / "motions")
    sequence.add_argument("--poses", type=Path, default=ROOT / "poses")
    sequence.add_argument("--metadata", type=Path, default=ROOT / "metadata")
    preview = commands.add_parser("preview", help="单次试播或复查一个已录制动作")
    preview.add_argument("name", help="动作清单中的名称，如 B_Neutral_Rest")
    preview.add_argument("--sequence-file", type=Path, help="组合试播的 Sequence JSON 文件；全组只接管和释放一次")
    preview_mode = preview.add_mutually_exclusive_group()
    preview_mode.add_argument("--check", action="store_true", help="只做离线校验，不连接机器人")
    preview_mode.add_argument("--offline", action="store_true", help="离线演练完整流程，不连接机器人")
    preview_mode.add_argument("--send", action="store_true", help="发送给已运行的试播服务端")
    preview.add_argument("--limits", type=Path, default=LIMITS)
    preview.add_argument("--catalog", type=Path, default=ROOT / "config/motion_catalog.json")
    preview.add_argument("--dir", type=Path, default=ROOT / "motions")
    preview.add_argument("--poses", type=Path, default=ROOT / "poses")
    preview.add_argument("--metadata", type=Path, default=ROOT / "metadata")
    preview.add_argument("--duration-ms", type=int, help="本次试播的动作核心总时长")
    preview.add_argument("--total-ms", type=int, help="入口、核心、保持的完整总时长，按已保存比例规划")
    preview.add_argument("--timing-profile-json", help="本次未保存的比例配置 JSON；试播不会自动确认元数据")
    preview.add_argument("--hold-ms", type=int, help="本次试播的末帧保持时长")
    preview.add_argument("--transition-ms", type=int, help="本次试播的入口过渡时长")
    preview.add_argument("--weights-json", help="本次试播各帧间权重的 JSON 数组")
    preview.add_argument("--interpolation", choices=("linear",),
                         help="仅支持原版 play 线性插值；默认已启用，无需指定")
    preview.add_argument("--no-confirm", action="store_true", help="非交互试播，不更新确认状态")
    preview.add_argument("--json-events", action="store_true", help="向标准输出发送试播状态事件")
    answer = commands.add_parser("answer", help="暂停后执行回答手势，保留原讲解断点")
    answer_source = answer.add_mutually_exclusive_group(required=True)
    answer_source.add_argument("--json", help="回答动作 JSON 标签")
    answer_source.add_argument("--file", type=Path, help="回答动作 JSON 文件")
    waist = commands.add_parser("waist", help="更新腰部目标角度")
    waist.add_argument("--deg", type=float, required=True, help="相对启动角度，单位度")
    commands.add_parser("interrupt", help="减速暂停并保留动作断点")
    commands.add_parser("resume", help="回答完成后接续动作")
    commands.add_parser("status", help="查询控制器状态和动作断点")
    commands.add_parser("stop", help="减速取消当前动作，清除断点")
    commands.add_parser("release", help="回到本次接管前姿态并交还上半身控制；等 status= released 后再导航")
    commands.add_parser("acquire", help="机器人停稳后重新接管上半身；等 status= owned 后再播放")
    commands.add_parser("quit", help="退出控制进程并释放上半身控制")
    args = parser.parse_args()

    try:
        if args.command in {"action", "answer"}:
            text = args.json if args.json is not None else args.file.read_text(encoding="utf-8")
            parsed = json.loads(text)
            payload = parsed if args.command == "action" else {"回答动作": parsed}
        elif args.command == "sequence":
            try:
                import yaml
            except ImportError as error:
                raise ValueError("YAML序列需要安装PyYAML") from error
            parsed = yaml.safe_load(args.file.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("序列YAML顶层必须是对象")
            if args.check:
                result = subprocess.run(
                    [str(BUILD / "motion_library_server"), "--check-sequence", "-",
                     "--limits", str(args.limits), "--catalog", str(args.catalog),
                     "--dir", str(args.dir), "--poses", str(args.poses),
                     "--metadata", str(args.metadata)],
                    input=json.dumps(parsed, ensure_ascii=False), text=True,
                    cwd=ROOT, capture_output=True, check=False,
                )
                print(result.stdout or result.stderr, end="", file=sys.stdout if result.returncode == 0 else sys.stderr)
                return result.returncode
            payload = {"序列": parsed}
        elif args.command == "preview":
            if not args.send:
                return preview_once(args)
            payload = preview_payload(args)
        elif args.command == "waist":
            payload = {"腰部角度": args.deg}
        elif args.command == "stop":
            payload = {"停止": True}
        elif args.command == "interrupt":
            payload = {"中断": True}
        elif args.command == "resume":
            payload = {"恢复": True}
        elif args.command == "status":
            payload = {"状态": True}
        elif args.command == "release":
            payload = {"释放": True}
        elif args.command == "acquire":
            payload = {"接管": True}
        else:
            payload = {"退出": True}
        result = request(SOCKET_NAME, payload)
        if result.get("ok"):
            if args.command == "status":
                print(json.dumps(result["status"], ensure_ascii=False, indent=2))
            else:
                print("指令已入队；用 status 查询执行状态")
                if result.get("warning"):
                    print("注意：" + result["warning"], file=sys.stderr)
            return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"发送失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
