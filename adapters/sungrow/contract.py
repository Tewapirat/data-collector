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
    METEO = 5

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
PLANT_POINTS = (
    PointDefinition("83022", "p83022", "daily_yield_wh"),
)
METEO_POINT = PointDefinition("2001", "p2001", "daily_irradiation_wh_m2")
SLOPE_METEO_POINT = PointDefinition(
    "2005",
    "p2005",
    "slope_daily_irradiation_wh_m2",
)
METEO_POINTS = (METEO_POINT, SLOPE_METEO_POINT)
POINTS = PLANT_POINTS + METEO_POINTS
SCHEMA = BASE_COLUMNS + (
    PLANT_POINTS[0].column,
    METEO_POINT.column,
    SLOPE_METEO_POINT.column,
    "meteo_name",
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
