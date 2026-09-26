"""Stable identity, packaged data and component contracts; no Maya dependency."""
import json
from pathlib import Path
import re
import math

DISPLAY_NAME = "自定义身体绑定"
VERSION = "1.3.2"
DATA_PATH = Path(__file__).parent / "data" / "body_v1.json"
RECIPE_PATH = DATA_PATH.with_name("body_v6.json")
COMPONENT_ORDER = ("controls", "skeleton", "drivers", "display")


def load_definition(segment_count=4, height=6.0, preserve_four=True):
    from .topology import compile_definition
    validate_dimensions(segment_count, height)
    recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
    if recipe["schema_version"] != 6 or recipe["version"] != VERSION:
        raise ValueError("Unsupported custom body rig recipe version")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if data["schema_version"] != 1 or data["version"] != "1.0.0":
        raise ValueError("Unsupported custom body rig template version")
    data = compile_definition(data, segment_count, height, VERSION, preserve_four=preserve_four)
    names = [node["name"] for node in data["nodes"]]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate template node names")
    return data


def validate_dimensions(segment_count, height):
    if type(segment_count) is not int or not 2 <= segment_count <= 64:
        raise ValueError("segment_count 必须为 2–64 的整数（骨骼与控制器数量相同）")
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(height) or height <= 0:
        raise ValueError("height 必须是大于零的有限数字，单位厘米")


def validate_options(namespace, on_conflict):
    if not isinstance(namespace, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", namespace):
        raise ValueError("命名空间须以字母或下划线开头，只能包含字母、数字、下划线")
    if on_conflict not in {"increment", "error"}:
        raise ValueError("on_conflict 必须为 increment 或 error")
