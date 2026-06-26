"""Opt-in end-to-end test against the real Huawei FusionSolar API."""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import collector
from adapters import huawei
from config import load_config

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Set RUN_LIVE_TESTS=1 to call the real Huawei API",
)

BANGKOK = ZoneInfo("Asia/Bangkok")


@pytest.mark.asyncio
async def test_real_huawei_endpoint_to_csv(tmp_path: Path) -> None:
    config = load_config("config/huawei-test.yaml")
    vendor_config = config["vendors"]["huawei"]
    fetched_at = datetime.now(BANGKOK)
    data_path = Path("data/test")

    await collector._collect_vendor(
        brand="huawei",
        vendor_config=vendor_config,
        fetched_at=fetched_at,
        data_root=data_path,
    )

    output = (
        data_path
        / "huawei"
        / f"{fetched_at:%Y}"
        / f"{fetched_at:%m}"
        / f"huawei_{fetched_at:%d_%H_%M_%S}.csv"
    )
    assert output.exists(), (
        "Huawei returned no successful rows; inspect collector logs for login, "
        "XSRF, station, or current-day KPI errors"
    )

    with output.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)

    assert tuple(reader.fieldnames or []) == huawei.SCHEMA
    assert rows
    assert all(row["plant_name"] for row in rows)
    assert all(row["plant_code"] for row in rows)
    assert all(row["no"] for row in rows)
    assert all(row["pv_yield_kwh"] for row in rows)
    assert all(row["fetched_at"] for row in rows)
    assert all(row["collect_time"] for row in rows)
    assert all(
        row["plant_code"].startswith("NE=")
        for row in rows
    )

    print(f"CSV: {output}")
    print(f"Successful rows: {len(rows)}")
