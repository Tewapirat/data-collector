import csv
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import collector
from adapters import sungrow
from config import load_config
from pathlib import Path

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="Set RUN_LIVE_TESTS=1 to call the real Sungrow API",
)


@pytest.mark.asyncio
async def test_real_sungrow_endpoint_to_csv(tmp_path):
    config = load_config("config/sungrow-test.yaml")
    vendor_config = config["vendors"]["sungrow"]
    fetched_at = datetime.now(ZoneInfo("Asia/Bangkok"))

    data_path = Path("data/test")
    await collector._collect_vendor(
        brand="sungrow",
        vendor_config=vendor_config,
        fetched_at=fetched_at,
        data_root=data_path,
    )

    output = (
        data_path
        / "sungrow"
        / f"{fetched_at:%Y}"
        / f"{fetched_at:%m}"
        / f"sungrow_{fetched_at:%d_%H_%M_%S}.csv"
    )

    assert output.exists()

    with output.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)

    assert tuple(reader.fieldnames or []) == sungrow.SCHEMA
    assert rows
    assert all(row["plant_code"] for row in rows)

    print(f"CSV: {output}")
    print(f"Successful rows: {len(rows)}")
