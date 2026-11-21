#!/usr/bin/env python3
"""Offline pose/motion inventory and human approval records."""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "assets/motion"
TOOLS = REPO / "tools/motion"
DRIVER = REPO / "drivers/unitree_motion"
NAME_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
JOINT_NAMES = (
    "left_shoulder_pitch", "left_shoulder_roll", "left_shoulder_yaw",
    "left_elbow", "left_wrist_roll", "left_wrist_pitch", "left_wrist_yaw",
    "right_shoulder_pitch", "right_shoulder_roll", "right_shoulder_yaw",
    "right_elbow", "right_wrist_roll", "right_wrist_pitch", "right_wrist_yaw",
)
STATUSES = {"draft", "tested", "approved"}


def catalog_entries(path):
    document = json.loads(path.read_text(encoding="utf-8"))
    if type(document) is not dict or document.get("schema_version") != 1 or type(document.get("actions")) is not list:
        raise ValueError("动作清单格式不正确")
    entries = {}
    for entry in document["actions"]:
        if type(entry) is not dict:
            raise ValueError("动作清单条目不是对象")
        name, category, priority, kind = (entry.get(key) for key in ("name", "category", "priority", "type"))
        if (type(name) is not str or not NAME_RE.fullmatch(name) or type(category) is not str
                or category not in {"basic", "reception", "presentation", "interaction", "elevator"}
                or priority not in {"P0", "P1", "P2"} or kind not in {"pose", "motion"}
                or (kind == "pose") != (category == "basic") or name in entries):
            raise ValueError(f"动作清单条目无效或重复: {name}")
        entries[name] = entry
    if len(entries) != 22:
        raise ValueError(f"预期22个动作，实际{len(entries)}个")
    return entries


def asset_path(entry, motions, poses):
    root = poses if entry["type"] == "pose" else motions
    return root / entry["category"] / f"{entry['name']}.dat"


def parse_motion(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        count, joints = int(lines[0]), int(lines[1])
    except (OSError, UnicodeError, IndexError, ValueError) as error:
        return [], [f"动作文件头或文件读取失败: {error}"], []
    if not 1 <= count <= 10000 or joints != 14 or len(lines) != count + 2:
        return [], ["动作点数、关节数或行数不匹配"], []
    points, errors, warnings = [], [], []
    for number, line in enumerate(lines[2:], 3):
        try:
            values = [float(value) for value in line.split()]
        except ValueError:
            errors.append(f"第{number}行包含非数字值")
            continue
        if len(values) not in (14, 15) or not all(math.isfinite(value) for value in values):
            errors.append(f"第{number}行列数或数值无效")
            continue
        duration, angles = (values[0], values[1:]) if len(values) == 15 else (0.3, values)
        if not 0 < duration <= 30 or any(abs(angle) > 2 * math.pi for angle in angles):
            errors.append(f"第{number}行时长或角度超出校验范围")
        if len(values) == 14:
            warnings.append(f"第{number}行旧格式，默认0.3秒")
        points.append((duration, angles))
    return points, errors, warnings


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timing(points):
    times = [0]
    for duration, _ in points[1:]:
        times.append(times[-1] + int(math.floor(duration * 1000 + 0.5)))
    return times


def validate_timing_profile(profile, frames):
    fields = {"phase_weights", "minimum_total_ms", "frame_weights"}
    if type(profile) is not dict or set(profile) != fields:
        raise ValueError("完整时间配置字段无效")
    phases = profile["phase_weights"]
    if type(phases) is not dict or set(phases) != {"transition", "core", "hold"}:
        raise ValueError("完整动作比例须包含transition、core、hold")
    for key in ("transition", "core", "hold"):
        value = phases[key]
        positive = key == "transition" or (key == "core" and frames > 1)
        if (type(value) not in (int, float) or not math.isfinite(value) or
                not 0 <= value <= 10000 or (0 < value < 0.000001) or (positive and value == 0)):
            raise ValueError("非零比例须在0.000001到10000之间；入口与多帧核心不能为0")
    if frames == 1 and phases["core"] != 0:
        raise ValueError("单帧动作的核心比例须为0")
    if type(profile["minimum_total_ms"]) is not int or not 1 <= profile["minimum_total_ms"] <= 600000:
        raise ValueError("最短总时长须为1到600000的整数毫秒")
    weights = profile["frame_weights"]
    if type(weights) is not list or len(weights) != (frames - 1 if frames >= 3 else 0) or any(
            type(value) not in (int, float) or not math.isfinite(value) or
            not 0.05 <= value <= 20 for value in weights):
        raise ValueError("仅三帧及以上可设置帧间比例，每项须在0.05到20之间")
    return dict(profile, phase_weights=dict(phases), frame_weights=list(weights))


def save_timing_profile(name, profile, entries, motions, poses, metadata,
                       expected_sha256, expected_version, confirm_by=None):
    result, errors, _ = inspect(name, entries, motions, poses, metadata)
    if errors:
        raise ValueError("; ".join(errors))
    points, meta = result
    if meta["sha256"] != expected_sha256 or meta["version"] != expected_version:
        raise ValueError("动作或时间配置已变化，请重新载入")
    profile = validate_timing_profile(profile, len(points))
    changed = meta.get("timing_profile") != profile
    if changed:
        meta = dict(meta, timing_profile=profile, version=meta["version"] + 1,
                    status="draft", verified_by="", verified_at="")
    path = metadata / f"{name}.json"
    if confirm_by:
        meta = dict(meta, status="approved", verified_by=confirm_by,
                    verified_at=datetime.now().astimezone().isoformat(timespec="seconds"))
    if changed or confirm_by:
        write_meta(path, meta)
    return meta, changed


def metadata_for(entry, path, points, old=None):
    old = old or {}
    return {
        "schema_version": 3, "file_format_version": 1,
        "name": entry["name"], "category": entry["category"], "type": entry["type"],
        "label": old.get("label", entry["name"]),
        "description": old.get("description", ""),
        "robot_model": "G1-7DOF", "source": "teach_with_name",
        "version": old.get("version", 0) + 1, "status": "draft",
        "movement_context": "stationary", "scenes": old.get("scenes", [entry["category"]]),
        "notes": old.get("notes", ""), "sha256": checksum(path),
        "verified_by": "", "verified_at": "",
        "joint_count": 14, "joint_names": list(JOINT_NAMES),
        "keyframe_times_ms": timing(points), "nominal_duration_ms": timing(points)[-1],
        "entry_pose": points[0][1], "exit_pose": points[-1][1],
        "loopable": old.get("loopable", False),
        "interruptible": old.get("interruptible", True),
        "allowed_robot_modes": ["standing"],
        "safety": old.get("safety", {
            "max_velocity_rad_s": 0.4,
            "max_acceleration_rad_s2": 0.8,
            "joint_limits_profile": "config/arm_joint_limits.json",
        }),
    }


def validate_metadata(path, entry, asset, points):
    if not path.is_file():
        return None, ["缺少元数据"]
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return None, [f"元数据读取失败: {error}"]
    if type(meta) is not dict:
        return None, ["元数据必须是对象"]
    errors = []
    if "timing_profile" in meta:
        try:
            validate_timing_profile(meta["timing_profile"], len(points))
        except ValueError as error:
            errors.append(str(error))
    schema = meta.get("schema_version")
    if schema not in (2, 3):
        errors.append("schema_version必须是2或3")
    for key, expected in (("name", entry["name"]), ("category", entry["category"]),
                          ("robot_model", "G1-7DOF"), ("source", "teach_with_name")):
        if meta.get(key) != expected:
            errors.append(f"{key}与清单不符")
    if type(meta.get("version")) is not int or meta.get("version", 0) < 1:
        errors.append("version必须是正整数")
    if type(meta.get("status")) is not str or meta.get("status") not in STATUSES:
        errors.append("status无效")
    if meta.get("movement_context") != "stationary":
        errors.append("当前控制器只允许stationary")
    if type(meta.get("scenes")) is not list or not meta.get("scenes") or not all(type(x) is str and x for x in meta.get("scenes", [])):
        errors.append("scenes必须是非空字符串列表")
    for key in ("label", "description", "notes", "verified_by", "verified_at"):
        if type(meta.get(key)) is not str:
            errors.append(f"{key}必须是字符串")
    if meta.get("status") == "approved" and (not meta.get("verified_by") or not meta.get("verified_at")):
        errors.append("approved缺少验收人或时间")
    if meta.get("sha256") != checksum(asset):
        errors.append("动作文件SHA-256不匹配，须重新验收")
    if schema == 3:
        if meta.get("type") != entry["type"] or meta.get("file_format_version") != 1:
            errors.append("type或file_format_version无效")
        if meta.get("joint_count") != 14 or meta.get("joint_names") != list(JOINT_NAMES):
            errors.append("关节数量或顺序无效")
        if meta.get("keyframe_times_ms") != timing(points) or meta.get("nominal_duration_ms") != timing(points)[-1]:
            errors.append("关键帧时间或标称时长与文件不符")
        if meta.get("entry_pose") != points[0][1] or meta.get("exit_pose") != points[-1][1]:
            errors.append("首尾姿态锚点与文件不符")
        if type(meta.get("loopable")) is not bool or type(meta.get("interruptible")) is not bool:
            errors.append("loopable或interruptible必须是布尔值")
        if meta.get("allowed_robot_modes") != ["standing"]:
            errors.append("allowed_robot_modes当前只允许standing")
        safety = meta.get("safety")
        if type(safety) is not dict:
            errors.append("缺少safety安全约束")
        else:
            for key, ceiling in (("max_velocity_rad_s", 0.4), ("max_acceleration_rad_s2", 0.8)):
                value = safety.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= ceiling:
                    errors.append(f"{key}必须在(0,{ceiling}]内")
            if safety.get("joint_limits_profile") != "config/arm_joint_limits.json":
                errors.append("joint_limits_profile无效")
    return meta, errors


def inspect(name, entries, motions, poses, metadata):
    entry = entries[name]
    path = asset_path(entry, motions, poses)
    if not path.is_file():
        return None, ["动作文件不存在"], []
    points, errors, warnings = parse_motion(path)
    if not errors and entry["type"] == "pose" and len(points) != 1:
        errors.append("pose必须恰好1帧")
    if errors:
        return (points, None), errors, warnings
    meta, meta_errors = validate_metadata(metadata / f"{name}.json", entry, path, points)
    if meta and meta.get("schema_version") == 2:
        warnings.append("v2元数据只供旧四段接口使用，Sequence要求v3；运行refresh-meta升级")
    return (points, meta), meta_errors, warnings


def write_meta(path, meta, create=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x" if create else "w", encoding="utf-8") as stream:
        json.dump(meta, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def confirm_metadata(path, meta, verified_by):
    if meta.get("schema_version") != 3:
        raise ValueError("只能确认v3动作元数据")
    if meta["status"] != "approved":
        meta = dict(meta)
        meta["status"] = "approved"
        meta["verified_by"] = verified_by
        meta["verified_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        write_meta(path, meta)
    return meta


def save_timing(name, weights, entries, motions, poses, metadata, confirm_by=None):
    if name not in entries or entries[name]["type"] != "motion":
        raise ValueError("仅动态动作可以编辑帧间比例")
    path = asset_path(entries[name], motions, poses)
    points, errors, _ = parse_motion(path)
    if errors or len(points) < 2:
        raise ValueError("动作文件无效: " + "; ".join(errors))
    meta_path = metadata / f"{name}.json"
    old, errors = validate_metadata(meta_path, entries[name], path, points)
    if errors:
        raise ValueError("元数据无效: " + "; ".join(errors))
    if not isinstance(weights, list) or len(weights) != len(points) - 1 or any(
            type(value) not in (int, float) or not math.isfinite(value) or
            not 0.05 <= value <= 20 for value in weights):
        raise ValueError("比例数量须等于帧间段数，且每项在0.05到20之间")
    total_ms = timing(points)[-1]
    weight_sum = sum(weights)
    durations_ms = [round(total_ms * value / weight_sum) for value in weights[:-1]]
    durations_ms.append(total_ms - sum(durations_ms))
    if any(not 10 <= value <= 30000 for value in durations_ms):
        raise ValueError("保存后的某段时长超出10到30000毫秒，请缩小比例差异")
    updated = [(points[0][0], points[0][1])] + [
        (duration / 1000, points[index + 1][1])
        for index, duration in enumerate(durations_ms)]
    if timing(updated) == timing(points):
        if confirm_by:
            old = confirm_metadata(meta_path, old, confirm_by)
        return old, False
    payload = f"{len(updated)}\n14\n" + "".join(
        f"{duration:.6f} " + " ".join(f"{angle:.6f}" for angle in angles) + "\n"
        for duration, angles in updated)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{name}.", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(payload)
        shutil.copy2(path, path.with_suffix(".dat.bak"))
        shutil.copy2(meta_path, meta_path.with_suffix(".json.bak"))
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    updated_meta = metadata_for(entries[name], path, updated, old)
    if confirm_by:
        updated_meta["status"] = "approved"
        updated_meta["verified_by"] = confirm_by
        updated_meta["verified_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    write_meta(meta_path, updated_meta)
    return updated_meta, True


def main():
    parser = argparse.ArgumentParser(description="G1姿态/动作库离线管理，不连接机器人")
    parser.add_argument("--dir", type=Path, default=ROOT / "motions", help="动态动作目录")
    parser.add_argument("--poses", type=Path, default=ROOT / "poses")
    parser.add_argument("--metadata", type=Path, default=ROOT / "metadata")
    parser.add_argument("--catalog", type=Path, default=ROOT / "config/motion_catalog.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    validate = commands.add_parser("validate")
    validate.add_argument("name", nargs="?")
    init = commands.add_parser("init-meta")
    init.add_argument("name")
    init.add_argument("--label")
    init.add_argument("--description", default="")
    refresh = commands.add_parser("refresh-meta")
    refresh.add_argument("name")
    edit = commands.add_parser("edit-meta")
    edit.add_argument("name")
    edit.add_argument("--label")
    edit.add_argument("--description")
    edit.add_argument("--notes")
    edit.add_argument("--loopable", choices=("true", "false"))
    edit.add_argument("--interruptible", choices=("true", "false"))
    edit.add_argument("--max-velocity-rad-s", type=float)
    edit.add_argument("--max-acceleration-rad-s2", type=float)
    edit.add_argument("--scene", action="append", help="可重复指定，覆盖适用场景列表")
    tested = commands.add_parser("mark-tested")
    tested.add_argument("name")
    approve = commands.add_parser("approve")
    approve.add_argument("name")
    approve.add_argument("--verified-by", required=True)
    approve.add_argument("--verified-at", help="ISO-8601验收时间；默认使用当前本机时间")
    approve.add_argument("--confirm-physical-test", action="store_true")
    args = parser.parse_args()
    try:
        entries = catalog_entries(args.catalog)
        if args.command in ("list", "validate"):
            names = entries if args.command == "list" or args.name is None else [args.name]
            if any(name not in entries for name in names):
                raise ValueError("动作名不在清单中")
            failed = False
            for name in names:
                result, errors, warnings = inspect(name, entries, args.dir, args.poses, args.metadata)
                status = result[1].get("status", "missing") if result and result[1] else "missing"
                entry = entries[name]
                print(f"{'FAIL' if errors else 'OK  '} {name} [{entry['type']}, {entry['priority']}, {status}]")
                for message in errors + warnings:
                    print("  " + message)
                failed |= bool(errors)
            if len(names) == len(entries):
                expected = {asset_path(entry, args.dir, args.poses) for entry in entries.values()}
                extras = set(args.dir.rglob("*.dat")) | set(args.poses.rglob("*.dat"))
                extras -= expected
                extras |= {path for path in args.metadata.glob("*.json") if path.stem not in entries}
                for path in sorted(extras):
                    print(f"FAIL 未登记文件: {path}")
                failed |= bool(extras)
            return int(failed)

        if args.name not in entries:
            raise ValueError("动作名不在清单中")
        entry = entries[args.name]
        path = asset_path(entry, args.dir, args.poses)
        points, errors, _ = parse_motion(path)
        if errors or (entry["type"] == "pose" and len(points) != 1):
            raise ValueError("动作文件无效: " + "; ".join(errors))
        meta_path = args.metadata / f"{args.name}.json"
        if args.command == "init-meta":
            meta = metadata_for(entry, path, points)
            if args.label is not None:
                meta["label"] = args.label
            meta["description"] = args.description
            write_meta(meta_path, meta, create=True)
        else:
            meta, errors = validate_metadata(meta_path, entry, path, points)
            if meta is None:
                raise ValueError("请先运行init-meta")
            if args.command == "refresh-meta":
                meta = metadata_for(entry, path, points, meta)
            else:
                if errors:
                    raise ValueError("; ".join(errors))
                if args.command == "edit-meta":
                    fields = ("label", "description", "notes", "loopable", "interruptible",
                              "max_velocity_rad_s", "max_acceleration_rad_s2", "scene")
                    if all(getattr(args, key) is None for key in fields):
                        raise ValueError("至少指定一个要修改的字段")
                    for key in ("label", "description", "notes"):
                        value = getattr(args, key)
                        if value is not None:
                            meta[key] = value
                    for key in ("loopable", "interruptible"):
                        value = getattr(args, key)
                        if value is not None:
                            meta[key] = value == "true"
                    for key, ceiling in (("max_velocity_rad_s", 0.4),
                                         ("max_acceleration_rad_s2", 0.8)):
                        value = getattr(args, key)
                        if value is not None:
                            if not math.isfinite(value) or not 0 < value <= ceiling:
                                raise ValueError(f"{key}必须在(0,{ceiling}]内")
                            meta["safety"][key] = value
                    if args.scene is not None:
                        if not all(scene.strip() for scene in args.scene):
                            raise ValueError("scene不能为空")
                        meta["scenes"] = args.scene
                    meta["version"] += 1
                    meta["status"] = "draft"
                    meta["verified_by"] = meta["verified_at"] = ""
                elif args.command == "mark-tested":
                    if meta["status"] != "draft" or meta.get("schema_version") != 3:
                        raise ValueError("只能将v3 draft标记为tested")
                    meta["status"] = "tested"
                elif args.command == "approve":
                    if meta["status"] != "tested" or not args.confirm_physical_test:
                        raise ValueError("需先完成线下真机测试并显式确认")
                    verified_at = args.verified_at or datetime.now().astimezone().isoformat(timespec="seconds")
                    try:
                        stamp = datetime.fromisoformat(verified_at)
                    except ValueError as error:
                        raise ValueError("verified-at须为ISO-8601时间") from error
                    if not args.verified_by.strip() or stamp.tzinfo is None:
                        raise ValueError("验收人不能为空，时间须含时区")
                    meta["status"] = "approved"
                    meta["verified_by"] = args.verified_by.strip()
                    meta["verified_at"] = verified_at
            write_meta(meta_path, meta)
        print(f"已更新 {meta_path}")
        if args.command == "approve":
            print(f"验收时间: {meta['verified_at']}")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
