"""Sungrow API constants and shared data structures."""
## ===========================================================
## เก็บข้อตกลงและค่าคงที่ของ Sungrow
## ===========================================================

from __future__ import annotations
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

LOGIN_PATH = "/login"
DATA_PATH = "/getDeviceRealTimeData"
LANGUAGE = "_en_US"
BASE_COLUMNS = ("no", "plant_name", "plant_code") ## ชื่อคอลัมน์ทั้งหมดใน CSV


class DeviceType(IntEnum):
    PLANT = 11

## ===========================================================
## mapping ระหว่าง Point ID, Response Key และชื่อคอลัมน์ CSV
## ===========================================================
@dataclass(frozen=True)
class PointDefinition:
    point_id: str
    response_key: str
    column: str

## ===========================================================
## metrics ที่ต้องการดึง เช่น daily yield และ irradiation
## ===========================================================
POINTS = (
    PointDefinition("83022", "p83022", "daily_yield_wh"),
    PointDefinition("83013", "p83013", "daily_irradiation_w_m2"),
)
SCHEMA = BASE_COLUMNS + tuple(point.column for point in POINTS) + (
    "fetched_at",
    "collect_time",
)


@dataclass(frozen=True)
class BatchResult:
    records: list[Any]
    failed_ps_keys: tuple[str, ...]


## ===========================================================
## แปลง plant code เป็น Sungrow ps_key 
## Ex : plant_code "1159162" จะได้ ps_key "1159162_11_0_0"
## ===========================================================
def make_ps_key(plant_code: str) -> str:
    return f"{plant_code}_{int(DeviceType.PLANT)}_0_0"


## ===========================================================
## แปลง ps_key กลับเป็น plant code พร้อมตรวจรูปแบบ 
## Ex : ps_key "1159162_11_0_0" จะได้ plant_code "1159162"
## ===========================================================
def plant_code_from_ps_key(ps_key: Any) -> str | None:
    if not isinstance(ps_key, str):
        return None
    suffix = f"_{int(DeviceType.PLANT)}_0_0"
    if not ps_key.endswith(suffix):
        return None
    return ps_key[: -len(suffix)] or None
