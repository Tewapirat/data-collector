"""Huawei FusionSolar API constants and shared data structures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LOGIN_PATH = "/thirdData/login"
DATA_PATH = "/thirdData/getKpiStationDay"
XSRF_NAME = "XSRF-TOKEN"
BASE_COLUMNS = ("no", "plant_name", "plant_code")


@dataclass(frozen=True)
class MetricDefinition:
    response_key: str
    column: str


METRICS = (
    MetricDefinition("PVYield", "pv_yield_kwh"),
    MetricDefinition("radiation_intensity", "global_irradiation_kwh_m2"),
)
SCHEMA = BASE_COLUMNS + tuple(metric.column for metric in METRICS) + (
    "fetched_at",
    "collect_time",
)


@dataclass(frozen=True)
class BatchResult:
    records: list[Any]
