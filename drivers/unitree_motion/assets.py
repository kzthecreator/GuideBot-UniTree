"""Read-only motion asset parsing and validation shared by runtime and tools."""
import hashlib
import json
import math
import re
from pathlib import Path

NAME_RE = re.compile(r"[A-Za-z0-9_]+\Z")
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
                or category not in {"basic", "reception", "presentation", "interaction", "elevator", "prosody", "semantic"}
                or priority not in {"P0", "P1", "P2"} or kind not in {"pose", "motion"}
                or (kind == "pose") != (category == "basic") or name in entries):
            raise ValueError(f"动作清单条目无效或重复: {name}")
        entries[name] = entry
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
    if "preview_confirmation" in meta and not errors:
        from .planning import confirmed_timing
        try:
            confirmed_timing(meta)
        except (ValueError, KeyError, TypeError) as error:
            errors.append(f"试播确认记录无效: {error}")
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
