from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit
import math
import re
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from pxr import Usd, UsdGeom, UsdPhysics, UsdShade, Sdf, Gf


app = FastAPI()

# =========================
# 基础配置
# =========================

HTML_PATH = Path(__file__).resolve().with_name("index.html")

# Select a local USD file in the UI. No personal file path is embedded in the bundle.
ACTIVE_USD_PATH: Optional[Path] = None
SUPPORTED_USD_SUFFIXES = {".usd", ".usda", ".usdc"}

DEFAULT_MASS = 1.0
DEFAULT_LENGTH = 1.0
DEFAULT_INERTIA = 1.0
TOOL_PHYSICS_SCENE_PATH = Sdf.Path("/PhysicsScene")

MOTION_DIRECTION_ATTR = "userProperties:motionDirection"
MOTION_DIRECTION_CUSTOM_KEY = "motionDirection"


app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])


@app.middleware("http")
async def local_browser_only(request: Request, call_next):
    # Only the page served by this local process may edit a user's USD files.
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname not in {"127.0.0.1", "localhost"}:
        return JSONResponse({"detail": "Open SolverAdapt from its local /ui address."}, status_code=403)
    return await call_next(request)


# =========================
# 通用工具
# =========================

def get_usd_path() -> Path:
    if ACTIVE_USD_PATH is None:
        raise HTTPException(status_code=400, detail="Select a local USD file first.")
    return ACTIVE_USD_PATH


def validate_usd_path(path: Path) -> None:
    suffix = path.suffix.lower()

    if suffix not in SUPPORTED_USD_SUFFIXES:
        raise HTTPException(status_code=400, detail="Only .usd, .usda, and .usdc files are supported.")

    if not path.exists():
        raise HTTPException(status_code=404, detail=f"USD file not found: {path}")

    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")


def to_json_safe(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, str):
        return value

    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(v) for v in value]

    try:
        if hasattr(value, "__len__") and hasattr(value, "__getitem__") and len(value) in {2, 3, 4}:
            return [to_json_safe(value[i]) for i in range(len(value))]
    except Exception:
        pass

    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}

    return str(value)


def safe_get(attr, default=None):
    if not attr:
        return default

    try:
        value = attr.Get()
    except Exception:
        return default

    if value is None:
        return default

    return to_json_safe(value)


def safe_float(value, default=None):
    if value is None:
        return default

    try:
        value = float(value)
    except Exception:
        return default

    return value if math.isfinite(value) else default


def open_stage_for_read() -> Usd.Stage:
    usd_path = get_usd_path()
    validate_usd_path(usd_path)

    stage = Usd.Stage.Open(str(usd_path))
    if not stage:
        raise HTTPException(status_code=400, detail=f"Could not open USD file: {usd_path}")

    stage.Load()
    return stage


def open_stage_for_overwrite() -> Usd.Stage:
    usd_path = get_usd_path()
    validate_usd_path(usd_path)

    stage = Usd.Stage.Open(str(usd_path))
    if not stage:
        raise HTTPException(status_code=400, detail=f"Could not open USD file: {usd_path}")

    stage.Load()
    stage.SetEditTarget(stage.GetRootLayer())
    return stage


# =========================
# 原生文件选择窗口
# =========================

@app.post("/api/usd/open-dialog")
def open_usd_file_dialog():
    """
    打开系统原生文件选择窗口。
    注意：窗口会出现在运行 FastAPI 的这台电脑上。
    """
    global ACTIVE_USD_PATH

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open the native file picker: {e}")

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    current_path = ACTIVE_USD_PATH
    initial_dir = str(current_path.parent) if current_path and current_path.exists() else str(Path.home())

    try:
        selected = filedialog.askopenfilename(
            title="Select a USD file",
            initialdir=initial_dir,
            filetypes=[
                ("USD files", "*.usd *.usda *.usdc"),
                ("All files", "*.*"),
            ],
        )
    finally:
        root.destroy()

    if not selected:
        return {
            "cancelled": True,
            "message": "File selection cancelled.",
            "active_usd_path": str(ACTIVE_USD_PATH) if ACTIVE_USD_PATH else None,
        }

    selected_path = Path(selected)
    validate_usd_path(selected_path)

    ACTIVE_USD_PATH = selected_path

    return {
        "cancelled": False,
        "message": "Active USD file changed.",
        "active_usd_path": str(ACTIVE_USD_PATH),
        "save_mode": "overwrite_original_usd",
    }


# =========================
# USD 读取
# =========================

def get_joint_type_and_drive_name(prim):
    if prim.IsA(UsdPhysics.RevoluteJoint):
        return "RevoluteJoint", "angular"

    if prim.IsA(UsdPhysics.PrismaticJoint):
        return "PrismaticJoint", "linear"

    if prim.IsA(UsdPhysics.SphericalJoint):
        return "SphericalJoint", "angular"

    if prim.IsA(UsdPhysics.FixedJoint):
        return "FixedJoint", None

    return None, None


def get_axis(prim, joint_type: Optional[str]) -> Optional[str]:
    try:
        if joint_type == "RevoluteJoint":
            axis = UsdPhysics.RevoluteJoint(prim).GetAxisAttr().Get()
            return str(axis) if axis is not None else None

        if joint_type == "PrismaticJoint":
            axis = UsdPhysics.PrismaticJoint(prim).GetAxisAttr().Get()
            return str(axis) if axis is not None else None
    except Exception:
        return None

    return None


def get_applied_drive_name(prim, suggested_drive_name: Optional[str]) -> Optional[str]:
    applied_schemas = prim.GetAppliedSchemas()

    for schema in applied_schemas:
        prefix = "PhysicsDriveAPI:"
        if schema.startswith(prefix):
            return schema.replace(prefix, "")

    return suggested_drive_name


def read_drive_attrs(prim, drive_name: Optional[str]) -> dict[str, Any]:
    if not drive_name:
        return {
            "drive_name": None,
            "target_position": None,
            "target_velocity": None,
            "stiffness": None,
            "damping": None,
            "max_force": None,
        }

    drive = UsdPhysics.DriveAPI(prim, drive_name)

    return {
        "drive_name": drive_name,
        "target_position": safe_get(drive.GetTargetPositionAttr(), 0.0),
        "target_velocity": safe_get(drive.GetTargetVelocityAttr(), 0.0),
        "stiffness": safe_get(drive.GetStiffnessAttr(), 0.0),
        "damping": safe_get(drive.GetDampingAttr(), 0.0),
        "max_force": safe_get(drive.GetMaxForceAttr(), 0.0),
    }


def read_limit_by_methods(api_obj) -> tuple[Optional[float], Optional[float]]:
    low = None
    high = None

    method_pairs = [
        ("GetLowerLimitAttr", "GetUpperLimitAttr"),
        ("GetLowAttr", "GetHighAttr"),
    ]

    for low_method, high_method in method_pairs:
        if hasattr(api_obj, low_method) and hasattr(api_obj, high_method):
            try:
                low_attr = getattr(api_obj, low_method)()
                high_attr = getattr(api_obj, high_method)()
                low = safe_float(safe_get(low_attr, None), None)
                high = safe_float(safe_get(high_attr, None), None)
                if low is not None or high is not None:
                    return low, high
            except Exception:
                pass

    return low, high


def read_joint_limits(prim, joint_type: Optional[str]) -> dict[str, Any]:
    lower = None
    upper = None
    source = None

    try:
        if joint_type == "RevoluteJoint":
            lower, upper = read_limit_by_methods(UsdPhysics.RevoluteJoint(prim))
            if lower is not None or upper is not None:
                source = "RevoluteJoint limit attrs"

        elif joint_type == "PrismaticJoint":
            lower, upper = read_limit_by_methods(UsdPhysics.PrismaticJoint(prim))
            if lower is not None or upper is not None:
                source = "PrismaticJoint limit attrs"
    except Exception:
        pass

    if lower is None or upper is None:
        for attr in prim.GetAttributes():
            name = attr.GetName()
            lname = name.lower()

            if lower is None and (
                "lowerlimit" in lname or lname.endswith(":low") or lname.endswith(":lower")
            ):
                value = safe_float(safe_get(attr, None), None)
                if value is not None:
                    lower = value
                    source = source or f"attribute scan: {name}"

            if upper is None and (
                "upperlimit" in lname or lname.endswith(":high") or lname.endswith(":upper")
            ):
                value = safe_float(safe_get(attr, None), None)
                if value is not None:
                    upper = value
                    source = source or f"attribute scan: {name}"

    return {
        "lower_limit": lower,
        "upper_limit": upper,
        "limit_source": source,
        "has_limit": lower is not None or upper is not None,
    }


def collect_xform_paths(stage: Usd.Stage) -> list[str]:
    paths = []

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Xform):
            paths.append(str(prim.GetPath()))

    return paths


def find_nearest_xform_ancestor(path_str: str, xform_paths: set[str]) -> Optional[str]:
    path = str(path_str)

    while path:
        if path in xform_paths:
            return path

        if "/" not in path.strip("/"):
            if path == "/":
                return "/" if "/" in xform_paths else None
            return None

        path = path.rsplit("/", 1)[0]
        if path == "":
            path = "/"

    return None


def bbox_volume(size: Optional[list[float]]) -> float:
    if not size:
        return 0.0

    sx = abs(safe_float(size[0], 0.0) or 0.0)
    sy = abs(safe_float(size[1], 0.0) or 0.0)
    sz = abs(safe_float(size[2], 0.0) or 0.0)
    return sx * sy * sz


def get_joint_controlled_xform_path(
    stage: Usd.Stage,
    joint_prim,
    joint_info: dict[str, Any],
    xform_paths: set[str],
) -> Optional[str]:
    """
    一个 Joint 只归属到一个可编辑 Xform。

    当前这类柜子 USD 的 Joint 通常直接放在 drawer Xform 下面，例如：
        /root/E_drawer1_5/PrismaticJoint_cabinet_1_down
        /root/E_drawer2_8/PrismaticJoint_cabinet_1_up
    因此优先使用 Joint 的父级 Xform。

    如果父级不可用，再从 body0/body1 里选候选。body0/body1 顺序在不同导出器中不稳定，
    所以不能固定认为 body1 一定是抽屉。候选中优先选择 bbox 体积较小的刚体，通常更像抽屉而不是柜体。
    """
    parent_path = str(joint_prim.GetPath().GetParentPath())
    parent_xform = find_nearest_xform_ancestor(parent_path, xform_paths)
    if parent_xform and parent_xform != "/":
        return parent_xform

    candidates = []

    for relation_name in ["body0_targets", "body1_targets"]:
        for target in joint_info.get(relation_name) or []:
            found = find_nearest_xform_ancestor(str(target), xform_paths)
            if not found or found == "/":
                continue

            bbox = get_path_bbox_metrics(stage, found)
            volume = bbox_volume(bbox.get("size") if bbox else None)
            candidates.append({
                "relation": relation_name,
                "path": found,
                "volume": volume,
            })

    unique: dict[str, dict[str, Any]] = {}
    for item in candidates:
        path = item["path"]
        if path not in unique or item["volume"] < unique[path]["volume"]:
            unique[path] = item

    valid = [item for item in unique.values() if item["volume"] > 1e-9]
    if valid:
        return min(valid, key=lambda item: item["volume"])["path"]

    for relation_name in ["body1_targets", "body0_targets"]:
        for target in joint_info.get(relation_name) or []:
            found = find_nearest_xform_ancestor(str(target), xform_paths)
            if found:
                return found

    return parent_xform


def get_bbox_metrics(stage: Usd.Stage, prim) -> dict[str, Any]:
    try:
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            [
                UsdGeom.Tokens.default_,
                UsdGeom.Tokens.render,
                UsdGeom.Tokens.proxy,
            ],
            useExtentsHint=True,
        )

        bbox = bbox_cache.ComputeWorldBound(prim)
        box = bbox.ComputeAlignedBox()

        min_pt = box.GetMin()
        max_pt = box.GetMax()

        size = [
            abs(safe_float(max_pt[0] - min_pt[0], 0.0) or 0.0),
            abs(safe_float(max_pt[1] - min_pt[1], 0.0) or 0.0),
            abs(safe_float(max_pt[2] - min_pt[2], 0.0) or 0.0),
        ]

        center = [
            safe_float((min_pt[0] + max_pt[0]) / 2.0, 0.0),
            safe_float((min_pt[1] + max_pt[1]) / 2.0, 0.0),
            safe_float((min_pt[2] + max_pt[2]) / 2.0, 0.0),
        ]

        approx_length = max(size)
        if approx_length is None or approx_length <= 1e-6:
            approx_length = DEFAULT_LENGTH

        return {
            "bbox_size": size,
            "bbox_center": center,
            "approx_length": approx_length,
            "bbox_source": "UsdGeom.BBoxCache world bound",
        }

    except Exception as e:
        return {
            "bbox_size": None,
            "bbox_center": None,
            "approx_length": DEFAULT_LENGTH,
            "bbox_source": f"default because BBox failed: {e}",
        }


# =========================
# Joint 自适应侧视角预览
# =========================

def vec3(value: Any, default: Optional[list[float]] = None) -> list[float]:
    if default is None:
        default = [0.0, 0.0, 0.0]

    if value is None:
        return list(default)

    if isinstance(value, str):
        nums = re.findall(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?", value)
        if len(nums) >= 3:
            parsed = [safe_float(nums[i], None) for i in range(3)]
            if all(v is not None for v in parsed):
                return [float(parsed[0]), float(parsed[1]), float(parsed[2])]

    try:
        x = safe_float(value[0], None)
        y = safe_float(value[1], None)
        z = safe_float(value[2], None)

        if x is None or y is None or z is None:
            return list(default)

        return [
            x,
            y,
            z,
        ]
    except Exception:
        return list(default)


def vec_add(a: list[float], b: list[float]) -> list[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def vec_sub(a: list[float], b: list[float]) -> list[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def vec_mul(a: list[float], s: float) -> list[float]:
    return [a[0] * s, a[1] * s, a[2] * s]


def vec_dot(a: list[float], b: list[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec_cross(a: list[float], b: list[float]) -> list[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def vec_len(a: list[float]) -> float:
    return math.sqrt(max(vec_dot(a, a), 0.0))


def vec_norm(a: list[float], fallback: Optional[list[float]] = None) -> list[float]:
    length = vec_len(a)
    if length <= 1e-9:
        return list(fallback or [0.0, 0.0, 1.0])
    return [a[0] / length, a[1] / length, a[2] / length]


def axis_to_vector(axis: Optional[str]) -> list[float]:
    if not axis:
        return [1.0, 0.0, 0.0]

    key = str(axis).upper()
    if key.endswith("X"):
        return [1.0, 0.0, 0.0]
    if key.endswith("Y"):
        return [0.0, 1.0, 0.0]
    if key.endswith("Z"):
        return [0.0, 0.0, 1.0]

    return [1.0, 0.0, 0.0]


def parse_motion_direction(value: Optional[str]) -> tuple[Optional[str], Optional[list[float]]]:
    """
    解析工具层面的运动方向。
    注意：USD Physics 原生 axis 仍然只保留 X/Y/Z；+/- 方向保存在自定义属性里，
    不再把 -Y 这种值写入 Joint axis。
    """
    if value is None:
        return None, None

    key = str(value).strip().lower()
    if not key or key == "auto":
        return None, None

    mapping: dict[str, tuple[str, list[float]]] = {
        "x": ("X", [1.0, 0.0, 0.0]),
        "+x": ("X", [1.0, 0.0, 0.0]),
        "-x": ("X", [-1.0, 0.0, 0.0]),
        "y": ("Y", [0.0, 1.0, 0.0]),
        "+y": ("Y", [0.0, 1.0, 0.0]),
        "-y": ("Y", [0.0, -1.0, 0.0]),
        "z": ("Z", [0.0, 0.0, 1.0]),
        "+z": ("Z", [0.0, 0.0, 1.0]),
        "-z": ("Z", [0.0, 0.0, -1.0]),
    }

    return mapping.get(key, (None, None))


def normalize_motion_direction(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    key = str(value).strip().lower()
    if not key or key == "auto":
        return None

    if key in {"x", "+x"}:
        return "+X"
    if key == "-x":
        return "-X"
    if key in {"y", "+y"}:
        return "+Y"
    if key == "-y":
        return "-Y"
    if key in {"z", "+z"}:
        return "+Z"
    if key == "-z":
        return "-Z"

    return None


def parse_motion_axis_sign(value: Optional[str]) -> tuple[Optional[str], int, Optional[str]]:
    """
    将 UI 的 +/-X/Y/Z 转换成 USD 可写入的真实结构。
    USD Physics Joint.axis 只支持 X/Y/Z；正负方向通过有符号 targetPosition
    和有符号 limit 表达。
    """
    normalized = normalize_motion_direction(value)
    if normalized is None:
        return None, 1, None

    axis_token = normalized[-1]
    sign = -1 if normalized.startswith("-") else 1
    return axis_token, sign, normalized


def get_joint_axis_schema(prim, joint_type: Optional[str]):
    if joint_type == "RevoluteJoint":
        return UsdPhysics.RevoluteJoint(prim)

    if joint_type == "PrismaticJoint":
        return UsdPhysics.PrismaticJoint(prim)

    return None


def read_limit_range_for_write(prim, joint_type: Optional[str], target_position: float) -> float:
    limit_attrs = read_joint_limits(prim, joint_type)
    values = [abs(float(target_position))]

    for key in ["lower_limit", "upper_limit"]:
        value = safe_float(limit_attrs.get(key), None)
        if value is not None:
            values.append(abs(value))

    range_value = max(values) if values else 0.0
    return range_value if math.isfinite(range_value) else 0.0


def is_lower_limit_attr_name(name: str) -> bool:
    lname = name.lower()
    return "lowerlimit" in lname or lname.endswith(":low") or lname.endswith(":lower")


def is_upper_limit_attr_name(name: str) -> bool:
    lname = name.lower()
    return "upperlimit" in lname or lname.endswith(":high") or lname.endswith(":upper")


def write_joint_limit_attrs(joint_prim, joint_schema, lower: float, upper: float) -> list[str]:
    """
    Write both the USD schema limit attrs and any existing limit-like attrs.

    Some assets use schema attrs such as physics:lowerLimit/physics:upperLimit,
    while others carry older or tool-authored low/high style attrs. Updating only
    one pair can make the UI read the old value back after save.
    """
    written: list[str] = []

    attr_pairs = [
        ("CreateLowerLimitAttr", lower),
        ("CreateUpperLimitAttr", upper),
    ]

    for method_name, value in attr_pairs:
        try:
            if hasattr(joint_schema, method_name):
                attr = getattr(joint_schema, method_name)()
                attr.Set(float(value))
                written.append(attr.GetName())
        except Exception:
            pass

    for attr in joint_prim.GetAttributes():
        try:
            name = attr.GetName()
            if is_lower_limit_attr_name(name):
                attr.Set(float(lower))
                written.append(name)
            elif is_upper_limit_attr_name(name):
                attr.Set(float(upper))
                written.append(name)
        except Exception:
            pass

    # Ensure the standard USD Physics attrs exist even if the schema helper did
    # not expose CreateLowerLimitAttr/CreateUpperLimitAttr in the local USD build.
    for name, value in [
        ("physics:lowerLimit", lower),
        ("physics:upperLimit", upper),
    ]:
        try:
            attr = joint_prim.CreateAttribute(name, Sdf.ValueTypeNames.Float, custom=False)
            attr.Set(float(value))
            written.append(name)
        except Exception:
            pass

    return sorted(set(written))


def collect_joint_limit_attr_debug(joint_prim) -> list[dict[str, Any]]:
    debug = []

    if not joint_prim or not joint_prim.IsValid():
        return debug

    for attr in joint_prim.GetAttributes():
        try:
            name = attr.GetName()
            if not (is_lower_limit_attr_name(name) or is_upper_limit_attr_name(name)):
                continue

            debug.append({
                "name": name,
                "value": safe_get(attr, None),
                "type": str(attr.GetTypeName()),
                "has_authored_value": bool(attr.HasAuthoredValueOpinion()),
            })
        except Exception as e:
            debug.append({
                "name": str(getattr(attr, "GetName", lambda: "-")()),
                "error": str(e),
            })

    return debug


def floats_match(left: Any, right: Any, eps: float = 1e-6) -> bool:
    left_value = safe_float(left, None)
    right_value = safe_float(right, None)

    if left_value is None or right_value is None:
        return left_value is None and right_value is None

    return abs(left_value - right_value) <= eps


def write_signed_joint_axis_target_and_limit(
    stage: Usd.Stage,
    joint_prim,
    joint_info: dict[str, Any],
    joint_type: Optional[str],
    motion_direction: Optional[str],
    target_position: float,
    manual_lower_limit: Optional[float] = None,
    manual_upper_limit: Optional[float] = None,
    use_manual_limit: bool = False,
) -> tuple[float, Optional[float], Optional[float], Optional[str], Optional[str], bool, list[str]]:
    """
    真正写回 USD Joint 的 axis / targetPosition / limit。

    例：
    - motion_direction=-Y, target_position=90
      => axis=Y, targetPosition=-90, limit=-range~0
    - motion_direction=+Y, target_position=90
      => axis=Y, targetPosition=90, limit=0~range
    """
    axis_token, sign, normalized = parse_motion_axis_sign(motion_direction)
    _, desired_world_vec = parse_motion_direction(normalized)

    joint_schema = get_joint_axis_schema(joint_prim, joint_type)
    if joint_schema is None:
        raise HTTPException(status_code=400, detail=f"Motion direction cannot be written for this joint type: {joint_type}")

    if axis_token is None and not use_manual_limit:
        return float(target_position), None, None, get_axis(joint_prim, joint_type), None, False, []

    if desired_world_vec is not None:
        axis_token, sign, _ = choose_local_axis_for_world_direction(
            stage=stage,
            joint_prim=joint_prim,
            joint_info=joint_info,
            desired_world_vec=desired_world_vec,
        )

    if axis_token is not None:
        joint_schema.CreateAxisAttr().Set(axis_token)

    signed_target_position = sign * abs(float(target_position)) if axis_token is not None else float(target_position)

    if use_manual_limit:
        if manual_lower_limit is None or manual_upper_limit is None:
            raise HTTPException(status_code=400, detail="Both lower and upper limits are required for a manual limit.")

        signed_lower = float(manual_lower_limit)
        signed_upper = float(manual_upper_limit)

        if not math.isfinite(signed_lower) or not math.isfinite(signed_upper):
            raise HTTPException(status_code=400, detail="Lower and upper limits must be valid numbers.")

        if signed_lower >= signed_upper:
            raise HTTPException(status_code=400, detail="The lower limit must be less than the upper limit.")

        target_outside_limit = signed_target_position < signed_lower or signed_target_position > signed_upper
    else:
        target_outside_limit = False
        range_value = read_limit_range_for_write(joint_prim, joint_type, signed_target_position)

        if range_value <= 0:
            signed_lower = 0.0
            signed_upper = 0.0
        elif sign < 0:
            signed_lower = -range_value
            signed_upper = 0.0
        else:
            signed_lower = 0.0
            signed_upper = range_value

    written_limit_attrs = write_joint_limit_attrs(joint_prim, joint_schema, signed_lower, signed_upper)

    return signed_target_position, signed_lower, signed_upper, axis_token, normalized, target_outside_limit, written_limit_attrs


def read_motion_direction_from_usd(prim) -> Optional[str]:
    """
    从 USD Joint 上读取本工具保存的运动方向。
    优先读 userProperties:motionDirection，其次读 customData["motionDirection"]。
    """
    try:
        attr = prim.GetAttribute(MOTION_DIRECTION_ATTR)
        value = safe_get(attr, None)
        normalized = normalize_motion_direction(value)
        if normalized:
            return normalized
    except Exception:
        pass

    try:
        value = prim.GetCustomDataByKey(MOTION_DIRECTION_CUSTOM_KEY)
        normalized = normalize_motion_direction(value)
        if normalized:
            return normalized
    except Exception:
        pass

    return None


def write_motion_direction_to_usd(prim, motion_direction: Optional[str]) -> Optional[str]:
    """
    将运动方向写回 USD。
    - auto/None：清空本工具保存的运动方向，回到后端自动推断。
    - +/-X/Y/Z：写入自定义属性和 customData。
    不修改 UsdPhysics.PrismaticJoint.axis / RevoluteJoint.axis 的正负。
    """
    normalized = normalize_motion_direction(motion_direction)

    if normalized is None:
        try:
            attr = prim.GetAttribute(MOTION_DIRECTION_ATTR)
            if attr:
                attr.Clear()
        except Exception:
            pass

        try:
            prim.ClearCustomDataByKey(MOTION_DIRECTION_CUSTOM_KEY)
        except Exception:
            pass

        return None

    _, motion_vec = parse_motion_direction(normalized)
    if motion_vec is None:
        raise HTTPException(status_code=400, detail=f"Invalid motion direction: {motion_direction}")

    attr = prim.CreateAttribute(MOTION_DIRECTION_ATTR, Sdf.ValueTypeNames.String, custom=True)
    attr.Set(normalized)
    prim.SetCustomDataByKey(MOTION_DIRECTION_CUSTOM_KEY, normalized)

    return normalized


def best_perpendicular_vector(axis_vec: list[float]) -> list[float]:
    axis_vec = vec_norm(axis_vec, [1.0, 0.0, 0.0])
    candidates = [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    return min(candidates, key=lambda c: abs(vec_dot(axis_vec, c)))


def get_xformable_world_translation(prim) -> Optional[list[float]]:
    try:
        xformable = UsdGeom.Xformable(prim)
        matrix = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        t = matrix.ExtractTranslation()
        return [safe_float(t[0], 0.0) or 0.0, safe_float(t[1], 0.0) or 0.0, safe_float(t[2], 0.0) or 0.0]
    except Exception:
        return None


def rotate_vector_by_quat(vec: list[float], quat) -> list[float]:
    try:
        w = float(quat.GetReal())
        imag = quat.GetImaginary()
        q = [float(imag[0]), float(imag[1]), float(imag[2])]
    except Exception:
        return vec

    t = vec_mul(vec_cross(q, vec), 2.0)
    return vec_add(vec, vec_add(vec_mul(t, w), vec_cross(q, t)))


def get_quat_attr_vector(prim, attr_name: str, vec: list[float]) -> list[float]:
    try:
        attr = prim.GetAttribute(attr_name)
        quat = attr.Get() if attr else None
        if quat is None:
            return vec
        return rotate_vector_by_quat(vec, quat)
    except Exception:
        return vec


def transform_direction_by_prim_world(prim, direction: list[float]) -> Optional[list[float]]:
    try:
        xformable = UsdGeom.Xformable(prim)
        matrix = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        transformed = matrix.TransformDir(Gf.Vec3d(direction[0], direction[1], direction[2]))
        return vec_norm([float(transformed[0]), float(transformed[1]), float(transformed[2])], direction)
    except Exception:
        return None


def get_joint_axis_world_vector(stage: Usd.Stage, joint_prim, joint_info: dict[str, Any]) -> list[float]:
    """
    USD Joint.axis 是 Joint/刚体局部语义，不应直接当世界 X/Y/Z 画。
    这里优先用 body0 的世界变换和 localRot0 把 local axis 转成 world axis。
    如果没有 body0，则退回 joint prim 自身的 xform。
    """
    local_axis = axis_to_vector(joint_info.get("axis"))

    for target_path in joint_info.get("body0_targets") or []:
        body_prim = stage.GetPrimAtPath(str(target_path))
        if not body_prim or not body_prim.IsValid():
            continue

        axis_in_body = get_quat_attr_vector(joint_prim, "physics:localRot0", local_axis)
        world_axis = transform_direction_by_prim_world(body_prim, axis_in_body)
        if world_axis is not None:
            return world_axis

    world_axis = transform_direction_by_prim_world(joint_prim, local_axis)
    if world_axis is not None:
        return world_axis

    return local_axis


def get_local_axis_world_candidates(stage: Usd.Stage, joint_prim, joint_info: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []

    for axis_token, local_axis in [
        ("X", [1.0, 0.0, 0.0]),
        ("Y", [0.0, 1.0, 0.0]),
        ("Z", [0.0, 0.0, 1.0]),
    ]:
        world_axis = None

        for target_path in joint_info.get("body0_targets") or []:
            body_prim = stage.GetPrimAtPath(str(target_path))
            if not body_prim or not body_prim.IsValid():
                continue

            axis_in_body = get_quat_attr_vector(joint_prim, "physics:localRot0", local_axis)
            world_axis = transform_direction_by_prim_world(body_prim, axis_in_body)
            if world_axis is not None:
                break

        if world_axis is None:
            world_axis = transform_direction_by_prim_world(joint_prim, local_axis)

        candidates.append({
            "axis": axis_token,
            "local_axis": local_axis,
            "world_axis": world_axis or local_axis,
        })

    return candidates


def choose_local_axis_for_world_direction(
    stage: Usd.Stage,
    joint_prim,
    joint_info: dict[str, Any],
    desired_world_vec: list[float],
) -> tuple[str, int, list[float]]:
    desired = vec_norm(desired_world_vec, [1.0, 0.0, 0.0])
    candidates = get_local_axis_world_candidates(stage, joint_prim, joint_info)
    best = max(candidates, key=lambda item: abs(vec_dot(item["world_axis"], desired)))
    dot = vec_dot(best["world_axis"], desired)
    signed_multiplier = 1 if dot >= 0 else -1
    return best["axis"], signed_multiplier, vec_norm(best["world_axis"], axis_to_vector(best["axis"]))


def get_path_bbox_metrics(stage: Usd.Stage, path: Optional[str]) -> Optional[dict[str, Any]]:
    if not path:
        return None

    prim = stage.GetPrimAtPath(str(path))
    if not prim or not prim.IsValid():
        return None

    metrics = get_bbox_metrics(stage, prim)
    center = metrics.get("bbox_center")
    size = metrics.get("bbox_size")

    if center is None:
        return None

    return {
        "path": str(path),
        "center": vec3(center),
        "size": vec3(size),
        "approx_length": safe_float(metrics.get("approx_length"), DEFAULT_LENGTH) or DEFAULT_LENGTH,
    }


def average_points(points: list[list[float]]) -> Optional[list[float]]:
    if not points:
        return None

    count = float(len(points))
    return [
        sum(p[0] for p in points) / count,
        sum(p[1] for p in points) / count,
        sum(p[2] for p in points) / count,
    ]


def get_joint_anchor_center(stage: Usd.Stage, joint_prim, joint_info: dict[str, Any]) -> list[float]:
    # 优先使用 joint prim 自身的世界位置。
    world_t = get_xformable_world_translation(joint_prim)
    if world_t is not None and vec_len(world_t) > 1e-9:
        return world_t

    # 如果 joint 没有可用 transform，则使用 body0/body1 的中心点中点近似关节位置。
    centers = []
    for path in (joint_info.get("body0_targets") or []) + (joint_info.get("body1_targets") or []):
        info = get_path_bbox_metrics(stage, path)
        if info is not None:
            centers.append(info["center"])

    averaged = average_points(centers)
    if averaged is not None:
        return averaged

    return [0.0, 0.0, 0.0]


def choose_camera_offset_direction(motion_vec: list[float]) -> list[float]:
    """
    选择一个观察方向，使 motion_vec 尽量落在屏幕平面内。
    这样调 stiffness / damping 时，位移、回弹、过冲最明显。
    """
    motion_vec = vec_norm(motion_vec, [1.0, 0.0, 0.0])

    # 优先水平侧面，避免一上来就是俯视/仰视。
    candidates = [
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, -1.0],
        [-1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, -1.0, 0.0],
    ]

    return min(candidates, key=lambda c: abs(vec_dot(motion_vec, c)))


def choose_camera_up(offset_dir: list[float]) -> list[float]:
    offset_dir = vec_norm(offset_dir, [0.0, 0.0, 1.0])
    world_y_up = [0.0, 1.0, 0.0]

    if abs(vec_dot(offset_dir, world_y_up)) < 0.95:
        return world_y_up

    return [0.0, 0.0, 1.0]


def get_joint_motion_vector(
    joint_type: Optional[str],
    axis_vec: list[float],
    joint_center: list[float],
    controlled_center: list[float],
) -> tuple[list[float], str]:
    axis_vec = vec_norm(axis_vec, [1.0, 0.0, 0.0])

    if joint_type == "PrismaticJoint":
        return axis_vec, "linear_axis"

    if joint_type == "RevoluteJoint":
        lever = vec_sub(controlled_center, joint_center)
        if vec_len(lever) <= 1e-9:
            lever = best_perpendicular_vector(axis_vec)

        tangent = vec_cross(axis_vec, lever)
        if vec_len(tangent) <= 1e-9:
            tangent = best_perpendicular_vector(axis_vec)

        return vec_norm(tangent, [1.0, 0.0, 0.0]), "angular_tangent"

    if joint_type == "SphericalJoint":
        return best_perpendicular_vector(axis_vec), "spherical_approx"

    return [1.0, 0.0, 0.0], "fallback"


def get_joint_preview_view(stage: Usd.Stage, joint_prim, joint_info: dict[str, Any]) -> dict[str, Any]:
    """
    为每个 joint 生成独立预览相机。
    前端选择 joint 后，用这个 preview_view 设置 camera/lookAt，避免所有关节共用同一侧面。
    """
    controlled_path = joint_info.get("controlled_xform_path")
    controlled_bbox = get_path_bbox_metrics(stage, controlled_path)

    body1_bbox = None
    for path in joint_info.get("body1_targets") or []:
        body1_bbox = get_path_bbox_metrics(stage, path)
        if body1_bbox is not None:
            break

    body0_bbox = None
    for path in joint_info.get("body0_targets") or []:
        body0_bbox = get_path_bbox_metrics(stage, path)
        if body0_bbox is not None:
            break

    focus_bbox = controlled_bbox or body1_bbox or body0_bbox
    joint_center = get_joint_anchor_center(stage, joint_prim, joint_info)

    if focus_bbox is not None:
        target = focus_bbox["center"]
        bbox_size = focus_bbox["size"]
        approx_length = safe_float(focus_bbox.get("approx_length"), DEFAULT_LENGTH) or DEFAULT_LENGTH
    else:
        target = joint_center
        bbox_size = [DEFAULT_LENGTH, DEFAULT_LENGTH, DEFAULT_LENGTH]
        approx_length = DEFAULT_LENGTH

    axis_vec = get_joint_axis_world_vector(stage, joint_prim, joint_info)
    saved_motion_direction = joint_info.get("motion_direction")
    _, saved_motion_vec = parse_motion_direction(saved_motion_direction)

    if saved_motion_vec is not None:
        motion_vec = vec_norm(saved_motion_vec, axis_vec)
        motion_source = "USD userProperties:motionDirection"
    else:
        motion_vec, motion_source = get_joint_motion_vector(
            joint_type=joint_info.get("type"),
            axis_vec=axis_vec,
            joint_center=joint_center,
            controlled_center=target,
        )

    offset_dir = choose_camera_offset_direction(motion_vec)
    distance = max(approx_length * 2.8, DEFAULT_LENGTH * 2.0)
    camera_position = vec_add(target, vec_mul(offset_dir, distance))
    up = choose_camera_up(offset_dir)

    return {
        "mode": "adaptive_joint_side_view",
        "target": target,
        "camera_position": camera_position,
        "camera_up": up,
        "camera_distance": distance,
        "bbox_size": bbox_size,
        "joint_center": joint_center,
        "axis_vector": axis_vec,
        "motion_direction": saved_motion_direction,
        "motion_vector": motion_vec,
        "default_motion_vector": motion_vec,
        "motion_source": motion_source,
        "camera_offset_direction": offset_dir,
        "focus_path": focus_bbox["path"] if focus_bbox else None,
        "controlled_xform_path": controlled_path,
        "auto_focus_paths": [
            p for p in [
                controlled_path,
                *(joint_info.get("body0_targets") or []),
                *(joint_info.get("body1_targets") or []),
            ] if p
        ],
        "reason": "camera is chosen per joint so the joint motion vector stays visible in the screen plane",
    }


def read_one_mass_api(p) -> dict[str, Any]:
    result = {
        "has_mass_api": p.HasAPI(UsdPhysics.MassAPI),
        "mass": None,
        "diagonal_inertia": None,
        "center_of_mass": None,
    }

    if not result["has_mass_api"]:
        return result

    mass_api = UsdPhysics.MassAPI(p)

    mass_value = safe_float(safe_get(mass_api.GetMassAttr(), None), None)
    if mass_value is not None and mass_value > 0:
        result["mass"] = mass_value

    diag = safe_get(mass_api.GetDiagonalInertiaAttr(), None)
    if diag is not None:
        try:
            diag_list = [safe_float(v, None) for v in diag]
            diag_list = [v for v in diag_list if v is not None and v >= 0]
            if diag_list:
                result["diagonal_inertia"] = diag_list
        except Exception:
            pass

    com = safe_get(mass_api.GetCenterOfMassAttr(), None)
    if com is not None:
        try:
            result["center_of_mass"] = [safe_float(v, 0.0) for v in com]
        except Exception:
            pass

    return result


def read_gravity_from_scene_prim(prim) -> Optional[dict[str, Any]]:
    try:
        if not prim or not prim.IsValid() or not prim.IsA(UsdPhysics.Scene):
            return None

        scene = UsdPhysics.Scene(prim)
        magnitude = safe_float(safe_get(scene.GetGravityMagnitudeAttr(), None), None)
        direction = safe_get(scene.GetGravityDirectionAttr(), None)
        direction_vec = vec3(direction, [0.0, -1.0, 0.0]) if direction is not None else [0.0, -1.0, 0.0]

        return {
            "gravity": magnitude if magnitude is not None else 9.81,
            "gravity_direction": vec_norm(direction_vec, [0.0, -1.0, 0.0]),
            "gravity_source": f"UsdPhysics.Scene: {prim.GetPath()}",
        }
    except Exception:
        return None


def collect_gravity_scene_debug(stage: Usd.Stage) -> list[dict[str, Any]]:
    scenes = []

    for prim in stage.Traverse():
        try:
            if not prim.IsA(UsdPhysics.Scene):
                continue

            scene_info = read_gravity_from_scene_prim(prim) or {}
            attrs = []
            for attr in prim.GetAttributes():
                try:
                    name = attr.GetName()
                    lname = name.lower()
                    if "gravity" not in lname:
                        continue

                    attrs.append({
                        "name": name,
                        "value": safe_get(attr, None),
                        "type": str(attr.GetTypeName()),
                        "has_authored_value": bool(attr.HasAuthoredValueOpinion()),
                    })
                except Exception as e:
                    attrs.append({"error": str(e)})

            scenes.append({
                "path": str(prim.GetPath()),
                "gravity": scene_info.get("gravity"),
                "gravity_direction": scene_info.get("gravity_direction"),
                "attrs": attrs,
            })
        except Exception as e:
            scenes.append({"error": str(e)})

    return scenes


def read_stage_gravity(stage: Usd.Stage) -> dict[str, Any]:
    # Prefer the tool-authored root PhysicsScene so rereads reflect values saved
    # from this editor even when the USD also contains referenced/sub-layer scenes.
    preferred = read_gravity_from_scene_prim(stage.GetPrimAtPath(TOOL_PHYSICS_SCENE_PATH))
    if preferred is not None:
        return preferred

    for prim in stage.Traverse():
        try:
            result = read_gravity_from_scene_prim(prim)
            if result is not None:
                return result
        except Exception:
            pass

    return {
        "gravity": 9.81,
        "gravity_direction": [0.0, -1.0, 0.0],
        "gravity_source": "USD PhysicsScene not found; using USD default-like gravity",
    }


def read_attr_float_by_names(prim, names: list[str]) -> tuple[Optional[float], Optional[str]]:
    wanted = {name.lower() for name in names}

    for attr in prim.GetAttributes():
        attr_name = attr.GetName()
        short_name = attr_name.split(":")[-1].lower()
        if attr_name.lower() not in wanted and short_name not in wanted:
            continue

        value = safe_float(safe_get(attr, None), None)
        if value is not None:
            return value, f"{prim.GetPath()}.{attr_name}"

    return None, None


def read_physics_material_attrs_from_prim(prim) -> dict[str, Any]:
    result = {
        "static_friction": None,
        "dynamic_friction": None,
        "restitution": None,
        "density": None,
        "physics_material_source": None,
    }

    try:
        material_api = UsdPhysics.MaterialAPI(prim)
        values = [
            ("static_friction", material_api.GetStaticFrictionAttr()),
            ("dynamic_friction", material_api.GetDynamicFrictionAttr()),
            ("restitution", material_api.GetRestitutionAttr()),
            ("density", material_api.GetDensityAttr()),
        ]

        found_any = False
        for key, attr in values:
            value = safe_float(safe_get(attr, None), None)
            if value is not None:
                result[key] = value
                found_any = True

        if found_any:
            result["physics_material_source"] = f"UsdPhysics.MaterialAPI: {prim.GetPath()}"
            return result
    except Exception:
        pass

    attr_map = {
        "static_friction": ["staticFriction", "physics:staticFriction", "physxMaterial:staticFriction"],
        "dynamic_friction": ["dynamicFriction", "physics:dynamicFriction", "physxMaterial:dynamicFriction"],
        "restitution": ["restitution", "physics:restitution", "physxMaterial:restitution"],
        "density": ["density", "physics:density", "physxMaterial:density"],
    }

    for key, names in attr_map.items():
        value, source = read_attr_float_by_names(prim, names)
        if value is not None:
            result[key] = value
            result["physics_material_source"] = result["physics_material_source"] or f"attribute scan: {source}"

    return result


def merge_first_physics_material(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    for key in ["static_friction", "dynamic_friction", "restitution", "density"]:
        if base.get(key) is None and candidate.get(key) is not None:
            base[key] = candidate[key]

    if base.get("physics_material_source") is None and candidate.get("physics_material_source"):
        base["physics_material_source"] = candidate["physics_material_source"]

    return base


def prim_has_material_binding_api(prim) -> bool:
    try:
        return bool(prim.HasAPI(UsdShade.MaterialBindingAPI))
    except Exception:
        return False


def merge_bound_physics_material_without_warnings(base: dict[str, Any], prim) -> dict[str, Any]:
    stage = prim.GetStage()

    if prim_has_material_binding_api(prim):
        try:
            binding_result = UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial()
            material = binding_result[0] if isinstance(binding_result, tuple) else binding_result
            material_prim = material.GetPrim() if material else None
            if material_prim and material_prim.IsValid():
                base = merge_first_physics_material(base, read_physics_material_attrs_from_prim(material_prim))
        except Exception:
            pass

    try:
        rel = prim.GetRelationship("material:binding")
        targets = rel.GetTargets() if rel and rel.HasAuthoredTargets() else []
    except Exception:
        targets = []

    for target in targets:
        try:
            material_prim = stage.GetPrimAtPath(target)
        except Exception:
            material_prim = None
        if material_prim and material_prim.IsValid():
            base = merge_first_physics_material(base, read_physics_material_attrs_from_prim(material_prim))

    return base


def read_physics_material_from_prim_or_descendants(prim) -> dict[str, Any]:
    result = {
        "static_friction": None,
        "dynamic_friction": None,
        "restitution": None,
        "density": None,
        "physics_material_source": None,
    }

    for p in Usd.PrimRange(prim):
        result = merge_bound_physics_material_without_warnings(result, p)
        result = merge_first_physics_material(result, read_physics_material_attrs_from_prim(p))

        if result.get("static_friction") is not None and result.get("dynamic_friction") is not None:
            break

    if result["static_friction"] is None:
        result["static_friction"] = 0.0
    if result["dynamic_friction"] is None:
        result["dynamic_friction"] = 0.0
    if result["physics_material_source"] is None:
        result["physics_material_source"] = "USD physics material friction not found; using 0"

    return result


def validate_optional_non_negative(value: Optional[float], name: str) -> Optional[float]:
    if value is None:
        return None

    parsed = safe_float(value, None)
    if parsed is None or parsed < 0:
        raise HTTPException(status_code=400, detail=f"{name} must be a valid nonnegative number.")

    return float(parsed)


def validate_optional_vec3(value: Optional[list[float]], name: str) -> Optional[list[float]]:
    if value is None:
        return None

    if len(value) != 3:
        raise HTTPException(status_code=400, detail=f"{name} must contain exactly three numbers.")

    parsed = [safe_float(v, None) for v in value]
    if any(v is None for v in parsed):
        raise HTTPException(status_code=400, detail=f"{name} must contain three valid numbers.")

    return [float(v) for v in parsed if v is not None]


def write_mass_physics_attrs(
    xform_prim,
    mass: Optional[float],
    diagonal_inertia: Optional[list[float]],
) -> dict[str, Any]:
    saved = {
        "mass": None,
        "diagonal_inertia": None,
    }

    mass_value = validate_optional_non_negative(mass, "mass")
    inertia_value = validate_optional_vec3(diagonal_inertia, "diagonal_inertia")

    if mass_value is None and inertia_value is None:
        return saved

    if mass_value is not None and mass_value <= 0:
        raise HTTPException(status_code=400, detail="Mass must be greater than zero.")

    mass_api = UsdPhysics.MassAPI.Apply(xform_prim)

    if mass_value is not None:
        mass_api.CreateMassAttr().Set(float(mass_value))
        saved["mass"] = float(mass_value)

    if inertia_value is not None:
        mass_api.CreateDiagonalInertiaAttr().Set(Gf.Vec3f(*inertia_value))
        saved["diagonal_inertia"] = inertia_value

    return saved


def write_material_physics_attrs(
    xform_prim,
    static_friction: Optional[float],
    dynamic_friction: Optional[float],
    density: Optional[float],
) -> dict[str, Any]:
    saved = {
        "static_friction": None,
        "dynamic_friction": None,
        "density": None,
    }

    values = {
        "static_friction": validate_optional_non_negative(static_friction, "static_friction"),
        "dynamic_friction": validate_optional_non_negative(dynamic_friction, "dynamic_friction"),
        "density": validate_optional_non_negative(density, "density"),
    }

    if all(value is None for value in values.values()):
        return saved

    material_api = UsdPhysics.MaterialAPI.Apply(xform_prim)

    if values["static_friction"] is not None:
        material_api.CreateStaticFrictionAttr().Set(float(values["static_friction"]))
        saved["static_friction"] = float(values["static_friction"])

    if values["dynamic_friction"] is not None:
        material_api.CreateDynamicFrictionAttr().Set(float(values["dynamic_friction"]))
        saved["dynamic_friction"] = float(values["dynamic_friction"])

    if values["density"] is not None:
        material_api.CreateDensityAttr().Set(float(values["density"]))
        saved["density"] = float(values["density"])

    return saved


def get_or_create_physics_scenes(stage: Usd.Stage):
    scene_paths = []

    for prim in stage.Traverse():
        try:
            if prim.IsA(UsdPhysics.Scene):
                scene_paths.append(prim.GetPath())
        except Exception:
            pass

    if TOOL_PHYSICS_SCENE_PATH not in scene_paths:
        scene_paths.append(TOOL_PHYSICS_SCENE_PATH)

    scenes = []
    for scene_path in scene_paths:
        # Always author the PhysicsScene in the active edit target. If the composed
        # scene comes from a sublayer or reference, this creates an override in the
        # selected USD root layer so gravity edits actually persist there.
        scenes.append((UsdPhysics.Scene.Define(stage, scene_path), scene_path))

    return scenes


def write_one_gravity_scene(scene, gravity_value: Optional[float], normalized: Optional[list[float]]) -> dict[str, Any]:
    saved = {
        "gravity": None,
        "gravity_direction": None,
        "written_attrs": [],
    }

    prim = scene.GetPrim()

    if gravity_value is not None:
        scene.CreateGravityMagnitudeAttr().Set(float(gravity_value))
        saved["gravity"] = float(gravity_value)
        saved["written_attrs"].append("schema:gravityMagnitude")

        try:
            attr = prim.CreateAttribute("physics:gravityMagnitude", Sdf.ValueTypeNames.Float, custom=False)
            attr.Set(float(gravity_value))
            saved["written_attrs"].append("physics:gravityMagnitude")
        except Exception:
            pass

    if normalized is not None:
        scene.CreateGravityDirectionAttr().Set(Gf.Vec3f(*normalized))
        saved["gravity_direction"] = normalized
        saved["written_attrs"].append("schema:gravityDirection")

        try:
            attr = prim.CreateAttribute("physics:gravityDirection", Sdf.ValueTypeNames.Vector3f, custom=False)
            attr.Set(Gf.Vec3f(*normalized))
            saved["written_attrs"].append("physics:gravityDirection")
        except Exception:
            pass

    return saved


def write_gravity_attrs(
    stage: Usd.Stage,
    gravity: Optional[float],
    gravity_direction: Optional[list[float]],
) -> dict[str, Any]:
    saved = {
        "gravity": None,
        "gravity_direction": None,
        "gravity_scene_path": None,
        "gravity_scene_paths": [],
        "gravity_written_attrs": [],
    }

    gravity_value = validate_optional_non_negative(gravity, "gravity")
    direction_value = validate_optional_vec3(gravity_direction, "gravity_direction")

    if gravity_value is None and direction_value is None:
        return saved

    scenes = get_or_create_physics_scenes(stage)
    saved["gravity_scene_paths"] = [str(scene_path) for _, scene_path in scenes]
    saved["gravity_scene_path"] = saved["gravity_scene_paths"][0] if saved["gravity_scene_paths"] else None

    normalized = vec_norm(direction_value, [0.0, -1.0, 0.0]) if direction_value is not None else None

    for scene, _scene_path in scenes:
        scene_saved = write_one_gravity_scene(scene, gravity_value, normalized)
        if scene_saved["gravity"] is not None:
            saved["gravity"] = scene_saved["gravity"]
        if scene_saved["gravity_direction"] is not None:
            saved["gravity_direction"] = scene_saved["gravity_direction"]
        saved["gravity_written_attrs"].extend(
            f"{_scene_path}:{attr_name}" for attr_name in scene_saved["written_attrs"]
        )

    return saved


def read_mass_from_prim_or_descendants(prim) -> dict[str, Any]:
    """
    读取 MassAPI。
    1. 当前 Xform 有 MassAPI.mass：优先用当前 Xform 的 mass。
    2. 当前 Xform 没有 MassAPI.mass：累加子层级 mass。
    3. 都没有：默认 mass=1。
    """
    current = read_one_mass_api(prim)

    if current["mass"] is not None:
        return {
            "mass": current["mass"],
            "mass_source": "MassAPI on current Xform",
            "diagonal_inertia": current["diagonal_inertia"],
            "center_of_mass": current["center_of_mass"],
            "approx_inertia_from_mass_api": max(current["diagonal_inertia"]) if current["diagonal_inertia"] else None,
        }

    mass_values = []
    diagonal_inertia_values = []
    center_of_mass_values = []

    for child in Usd.PrimRange(prim):
        if child == prim:
            continue

        info = read_one_mass_api(child)

        if info["mass"] is not None:
            mass_values.append(info["mass"])

        if info["diagonal_inertia"]:
            diagonal_inertia_values.extend(info["diagonal_inertia"])

        if info["center_of_mass"] is not None and not center_of_mass_values:
            center_of_mass_values.append(info["center_of_mass"])

    if mass_values:
        mass = sum(mass_values)
        mass_source = "sum MassAPI from descendants"
    else:
        mass = DEFAULT_MASS
        mass_source = "default mass because MassAPI not found"

    return {
        "mass": mass,
        "mass_source": mass_source,
        "diagonal_inertia": diagonal_inertia_values if diagonal_inertia_values else None,
        "center_of_mass": center_of_mass_values[0] if center_of_mass_values else None,
        "approx_inertia_from_mass_api": max(diagonal_inertia_values) if diagonal_inertia_values else None,
    }


def get_physics_preview_metrics(stage: Usd.Stage, prim) -> dict[str, Any]:
    bbox = get_bbox_metrics(stage, prim)
    mass_info = read_mass_from_prim_or_descendants(prim)
    material_info = read_physics_material_from_prim_or_descendants(prim)
    gravity_info = read_stage_gravity(stage)
    volume = bbox_volume(bbox.get("bbox_size"))

    if str(mass_info.get("mass_source", "")).startswith("default mass"):
        density = safe_float(material_info.get("density"), None)
        if density is not None and density > 0 and volume > 1e-12:
            mass_info["mass"] = density * volume
            mass_info["mass_source"] = "UsdPhysics.MaterialAPI.density * BBox volume"

    mass = safe_float(mass_info.get("mass"), DEFAULT_MASS) or DEFAULT_MASS
    approx_length = safe_float(bbox.get("approx_length"), DEFAULT_LENGTH) or DEFAULT_LENGTH

    inertia_from_mass_api = safe_float(mass_info.get("approx_inertia_from_mass_api"), None)
    if inertia_from_mass_api is not None and inertia_from_mass_api > 1e-9:
        approx_inertia = inertia_from_mass_api
        inertia_source = "MassAPI diagonalInertia"
    else:
        approx_inertia = (1.0 / 3.0) * mass * approx_length * approx_length
        if approx_inertia <= 1e-9:
            approx_inertia = DEFAULT_INERTIA
        inertia_source = "approx: 1/3 * mass * approx_length^2"

    return {
        **bbox,
        **mass_info,
        **material_info,
        **gravity_info,
        "bbox_volume": volume,
        "approx_inertia": approx_inertia,
        "inertia_source": inertia_source,
    }


def collect_joints(stage: Usd.Stage, xform_paths: set[str]) -> list[dict[str, Any]]:
    joints = []

    for prim in stage.Traverse():
        joint_type, suggested_drive_name = get_joint_type_and_drive_name(prim)
        if not joint_type:
            continue

        joint = UsdPhysics.Joint(prim)

        body0_targets = [str(p) for p in joint.GetBody0Rel().GetTargets()]
        body1_targets = [str(p) for p in joint.GetBody1Rel().GetTargets()]

        drive_name = get_applied_drive_name(prim, suggested_drive_name)
        drive_attrs = read_drive_attrs(prim, drive_name)
        limit_attrs = read_joint_limits(prim, joint_type)
        axis = get_axis(prim, joint_type)
        motion_direction = read_motion_direction_from_usd(prim)

        joint_info = {
            "name": prim.GetName(),
            "path": str(prim.GetPath()),
            "type": joint_type,
            "axis": axis,
            "motion_direction": motion_direction,
            "body0_targets": body0_targets,
            "body1_targets": body1_targets,
            "drivable": drive_name is not None,
            **drive_attrs,
            **limit_attrs,
        }

        controlled_xform_path = get_joint_controlled_xform_path(
            stage=stage,
            joint_prim=prim,
            joint_info=joint_info,
            xform_paths=xform_paths,
        )
        joint_info["controlled_xform_path"] = controlled_xform_path
        joint_info["preview_view"] = get_joint_preview_view(stage, prim, joint_info)

        joints.append(joint_info)

    return joints


def collect_xforms(stage: Usd.Stage, joints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    joints_by_xform: dict[str, list[dict[str, Any]]] = {}

    for joint in joints:
        controlled_xform_path = joint.get("controlled_xform_path")
        if not controlled_xform_path:
            continue

        joints_by_xform.setdefault(controlled_xform_path, []).append(joint)

    xforms = []

    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Xform):
            continue

        xform_path = str(prim.GetPath())
        related_joints = joints_by_xform.get(xform_path, [])
        drivable_joints = [joint for joint in related_joints if joint.get("drivable")]

        preview_metrics = get_physics_preview_metrics(stage, prim)

        xforms.append({
            "name": prim.GetName(),
            "path": xform_path,
            "type": prim.GetTypeName(),
            "has_rigid_body": prim.HasAPI(UsdPhysics.RigidBodyAPI),
            "has_collision": prim.HasAPI(UsdPhysics.CollisionAPI),
            "has_mass": prim.HasAPI(UsdPhysics.MassAPI),
            "related_joint_count": len(related_joints),
            "drivable_joint_count": len(drivable_joints),
            "related_joints": related_joints,
            "drivable_joints": drivable_joints,
            **preview_metrics,
        })

    return xforms


# =========================
# API
# =========================

@app.get("/")
def index():
    return RedirectResponse(url=f"/ui?v={int(time.time())}", status_code=307)


@app.get("/ui")
def ui():
    if not HTML_PATH.exists():
        raise HTTPException(status_code=404, detail=f"HTML file not found: {HTML_PATH}")

    return FileResponse(
        path=str(HTML_PATH),
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }
    )


@app.get("/api/status")
def status():
    return {
        "message": "USD Xform Physics Editor API is running",
        "usd_path": str(ACTIVE_USD_PATH) if ACTIVE_USD_PATH else None,
        "html_path": str(HTML_PATH),
        "save_mode": "overwrite_original_usd",
    }


class SetUsdPathRequest(BaseModel):
    usd_path: str


@app.post("/api/usd/set-path")
def set_usd_path(req: SetUsdPathRequest):
    global ACTIVE_USD_PATH

    path = Path(req.usd_path).expanduser().resolve()
    validate_usd_path(path)

    ACTIVE_USD_PATH = path

    return {
        "message": "Active USD file changed.",
        "active_usd_path": str(ACTIVE_USD_PATH),
        "save_mode": "overwrite_original_usd",
    }


@app.get("/api/usd/scene")
def get_usd_scene():
    stage = open_stage_for_read()

    xform_paths = set(collect_xform_paths(stage))
    joints = collect_joints(stage, xform_paths)
    xforms = collect_xforms(stage, joints)

    editable_xforms = [xform for xform in xforms if xform["drivable_joint_count"] > 0]

    result = {
        "usd_path": str(get_usd_path()),
        "save_mode": "overwrite_original_usd",
        "xform_count": len(xforms),
        "joint_count": len(joints),
        "editable_xform_count": len(editable_xforms),
        "xforms": xforms,
        "editable_xforms": editable_xforms,
        "joints": joints,
    }

    return to_json_safe(result)


@app.get("/api/usd/joint-preview")
def get_usd_joint_preview(joint_path: str):
    stage = open_stage_for_read()

    xform_paths = set(collect_xform_paths(stage))
    joints = collect_joints(stage, xform_paths)

    for joint in joints:
        if joint.get("path") == joint_path:
            return to_json_safe(joint)

    raise HTTPException(status_code=404, detail=f"Joint not found: {joint_path}")


class XformDriveUpdateRequest(BaseModel):
    xform_path: str
    joint_path: str
    drive_name: Optional[str] = None

    target_position: float = 0.0
    target_velocity: float = 0.0
    stiffness: float = 20.0
    damping: float = 2.0
    max_force: float = 100000.0

    # 写回当前 Xform 的 MassAPI.mass
    mass: Optional[float] = None
    diagonal_inertia: Optional[list[float]] = None
    static_friction: Optional[float] = None
    dynamic_friction: Optional[float] = None
    density: Optional[float] = None
    gravity: Optional[float] = None
    gravity_direction: Optional[list[float]] = None

    # 写回 USD Joint 的真实运动/旋转方向。
    # USD 原生 axis 只支持 X/Y/Z；+/- 由有符号 targetPosition 和 limit 表达。
    motion_direction: Optional[str] = None

    # 手动写回 Joint limit。用于把 -90~0 改成 0~90，或修改范围。
    use_manual_limit: bool = False
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None


@app.post("/api/usd/xform-drive")
def update_xform_drive(req: XformDriveUpdateRequest):
    stage = open_stage_for_overwrite()

    xform_prim = stage.GetPrimAtPath(req.xform_path)
    if not xform_prim or not xform_prim.IsValid():
        raise HTTPException(status_code=404, detail=f"Xform not found: {req.xform_path}")

    joint_prim = stage.GetPrimAtPath(req.joint_path)
    if not joint_prim or not joint_prim.IsValid():
        raise HTTPException(status_code=404, detail=f"Joint not found: {req.joint_path}")

    xform_paths = set(collect_xform_paths(stage))
    joint_type, suggested_drive_name = get_joint_type_and_drive_name(joint_prim)
    if not joint_type:
        raise HTTPException(status_code=400, detail=f"This path is not a joint: {req.joint_path}")

    joint = UsdPhysics.Joint(joint_prim)
    joint_info = {
        "name": joint_prim.GetName(),
        "path": str(joint_prim.GetPath()),
        "type": joint_type,
        "axis": get_axis(joint_prim, joint_type),
        "motion_direction": read_motion_direction_from_usd(joint_prim),
        "body0_targets": [str(p) for p in joint.GetBody0Rel().GetTargets()],
        "body1_targets": [str(p) for p in joint.GetBody1Rel().GetTargets()],
    }

    controlled_xform_path = get_joint_controlled_xform_path(stage, joint_prim, joint_info, xform_paths)
    if controlled_xform_path != req.xform_path:
        raise HTTPException(
            status_code=400,
            detail=(
                f"The joint does not belong to the selected Xform; save cancelled."
                f" current_xform={req.xform_path}, "
                f"joint_controlled_xform={controlled_xform_path}, "
                f"joint={req.joint_path}"
            )
        )

    drive_name = req.drive_name or get_applied_drive_name(joint_prim, suggested_drive_name)
    if not drive_name:
        raise HTTPException(status_code=400, detail=f"This joint does not support a drive: {req.joint_path}")

    # 1. 写真实 Joint axis、Drive targetPosition、limit。
    (
        signed_target_position,
        saved_lower_limit,
        saved_upper_limit,
        saved_axis,
        normalized_motion_direction,
        target_outside_limit,
        written_limit_attrs,
    ) = (
        write_signed_joint_axis_target_and_limit(
            stage=stage,
            joint_prim=joint_prim,
            joint_info=joint_info,
            joint_type=joint_type,
            motion_direction=req.motion_direction,
            target_position=float(req.target_position),
            manual_lower_limit=req.lower_limit,
            manual_upper_limit=req.upper_limit,
            use_manual_limit=req.use_manual_limit,
        )
    )

    # 2. 写 Drive 参数
    drive = UsdPhysics.DriveAPI.Apply(joint_prim, drive_name)
    drive.CreateTargetPositionAttr().Set(float(signed_target_position))
    drive.CreateTargetVelocityAttr().Set(0.0)
    drive.CreateStiffnessAttr().Set(float(req.stiffness))
    drive.CreateDampingAttr().Set(float(req.damping))
    drive.CreateMaxForceAttr().Set(float(req.max_force))

    # 3. 写当前 Xform 的物理属性
    saved_mass_attrs = write_mass_physics_attrs(
        xform_prim=xform_prim,
        mass=req.mass,
        diagonal_inertia=req.diagonal_inertia,
    )
    saved_material_attrs = write_material_physics_attrs(
        xform_prim=xform_prim,
        static_friction=req.static_friction,
        dynamic_friction=req.dynamic_friction,
        density=req.density,
    )
    saved_gravity_attrs = write_gravity_attrs(
        stage=stage,
        gravity=req.gravity,
        gravity_direction=req.gravity_direction,
    )

    # 4. 保存工具层方向，供 UI 读取时知道 +Y/-Y 语义。
    saved_motion_direction = write_motion_direction_to_usd(joint_prim, normalized_motion_direction)
    _, saved_motion_vector = parse_motion_direction(saved_motion_direction)

    root_layer = stage.GetRootLayer()
    saved = root_layer.Save()
    if not saved:
        raise HTTPException(status_code=500, detail=f"Could not save USD file: {root_layer.identifier}")

    try:
        verify_stage = open_stage_for_read()
        verified_gravity = read_stage_gravity(verify_stage)
        verified_gravity_scenes = collect_gravity_scene_debug(verify_stage)
        verify_joint_prim = verify_stage.GetPrimAtPath(req.joint_path)
        verify_joint_type, _ = get_joint_type_and_drive_name(verify_joint_prim)
        verified_limit = read_joint_limits(verify_joint_prim, verify_joint_type)
        verified_limit_attrs = collect_joint_limit_attr_debug(verify_joint_prim)
    except Exception:
        verified_gravity = {}
        verified_gravity_scenes = []
        verified_limit = {}
        verified_limit_attrs = []

    if saved_gravity_attrs["gravity"] is not None and not floats_match(
        saved_gravity_attrs["gravity"], verified_gravity.get("gravity")
    ):
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Gravity differs after saving and rereading; another physics scene, layer, reference, or variant may override it.",
                "expected_gravity": saved_gravity_attrs["gravity"],
                "verified_gravity": verified_gravity.get("gravity"),
                "verified_gravity_source": verified_gravity.get("gravity_source"),
                "gravity_scene_path": saved_gravity_attrs["gravity_scene_path"],
                "gravity_scene_paths": saved_gravity_attrs["gravity_scene_paths"],
                "gravity_written_attrs": saved_gravity_attrs["gravity_written_attrs"],
                "verified_gravity_scenes": verified_gravity_scenes,
                "saved_usd": str(get_usd_path()),
            },
        )

    if req.use_manual_limit and (
        not floats_match(saved_lower_limit, verified_limit.get("lower_limit")) or
        not floats_match(saved_upper_limit, verified_limit.get("upper_limit"))
    ):
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Joint limits differ after saving and rereading; a stronger layer, reference, or variant may override them.",
                "expected_lower_limit": saved_lower_limit,
                "expected_upper_limit": saved_upper_limit,
                "verified_lower_limit": verified_limit.get("lower_limit"),
                "verified_upper_limit": verified_limit.get("upper_limit"),
                "verified_limit_source": verified_limit.get("limit_source"),
                "written_limit_attrs": written_limit_attrs,
                "verified_limit_attrs": verified_limit_attrs,
                "joint_path": req.joint_path,
                "saved_usd": str(get_usd_path()),
            },
        )

    result = {
        "message": "Drive, physics, joint axis, target, limits, and motion direction were saved to the selected USD file.",
        "input_usd": str(get_usd_path()),
        "saved_usd": str(get_usd_path()),
        "xform_path": req.xform_path,
        "joint_path": req.joint_path,
        "joint_type": joint_type,
        "drive_name": drive_name,
        "target_position": signed_target_position,
        "target_velocity": 0.0,
        "stiffness": req.stiffness,
        "damping": req.damping,
        "max_force": req.max_force,
        "mass": saved_mass_attrs["mass"],
        "diagonal_inertia": saved_mass_attrs["diagonal_inertia"],
        "static_friction": saved_material_attrs["static_friction"],
        "dynamic_friction": saved_material_attrs["dynamic_friction"],
        "density": saved_material_attrs["density"],
        "gravity": saved_gravity_attrs["gravity"],
        "gravity_direction": saved_gravity_attrs["gravity_direction"],
        "gravity_scene_path": saved_gravity_attrs["gravity_scene_path"],
        "gravity_scene_paths": saved_gravity_attrs["gravity_scene_paths"],
        "gravity_written_attrs": saved_gravity_attrs["gravity_written_attrs"],
        "verified_gravity": verified_gravity.get("gravity"),
        "verified_gravity_direction": verified_gravity.get("gravity_direction"),
        "verified_gravity_source": verified_gravity.get("gravity_source"),
        "verified_gravity_scenes": verified_gravity_scenes,
        "axis": saved_axis or get_axis(joint_prim, joint_type),
        "axis_world_vector": get_joint_axis_world_vector(
            stage,
            joint_prim,
            {**joint_info, "axis": saved_axis or get_axis(joint_prim, joint_type)},
        ),
        "use_manual_limit": req.use_manual_limit,
        "lower_limit": saved_lower_limit,
        "upper_limit": saved_upper_limit,
        "written_limit_attrs": written_limit_attrs,
        "verified_lower_limit": verified_limit.get("lower_limit"),
        "verified_upper_limit": verified_limit.get("upper_limit"),
        "verified_limit_source": verified_limit.get("limit_source"),
        "verified_limit_attrs": verified_limit_attrs,
        "target_outside_limit": target_outside_limit,
        "motion_direction": saved_motion_direction,
        "motion_vector": saved_motion_vector,
    }

    return to_json_safe(result)


if __name__ == "__main__":
    import os
    import socket
    import uvicorn

    def port_is_free(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex((host, port)) != 0

    host = "127.0.0.1"
    try:
        preferred_port = int(os.environ.get("USD_API_PORT", "8001"))
    except ValueError:
        preferred_port = 8001

    port = preferred_port
    while port <= preferred_port + 20 and not port_is_free(host, port):
        port += 1

    if port > preferred_port + 20:
        raise RuntimeError(f"Cannot find a free port from {preferred_port} to {preferred_port + 20}")

    if port != preferred_port:
        print(f"Port {preferred_port} is already in use; using http://{host}:{port}/ui instead.")
    else:
        print(f"Starting USD editor at http://{host}:{port}/ui")

    uvicorn.run(app, host=host, port=port, reload=False)
