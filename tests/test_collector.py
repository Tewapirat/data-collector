import csv
import multiprocessing
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import collector

FETCHED_AT = datetime(2026, 6, 23, 7, 0, tzinfo=ZoneInfo("Asia/Bangkok"))
SCHEMA = ("plant_name", "plant_code", "metric")


def row(code: str = "P1") -> dict[str, object]:
    return {"plant_name": "Plant", "plant_code": code, "metric": 10}


def append_row_worker(data_root: str, code: str) -> None:
    collector.append_rows(
        "vendor",
        [row(code)],
        SCHEMA,
        FETCHED_AT,
        data_root=Path(data_root),
    )


def test_csv_header_written_once_and_rows_append(tmp_path: Path) -> None:
    expected_path = tmp_path / "vendor" / "2026" / "06" / "vendor_23_07_00_00.csv"
    first = collector.append_rows(
        "vendor",
        [row("P1")],
        SCHEMA,
        FETCHED_AT,
        data_root=tmp_path,
    )
    second = collector.append_rows(
        "vendor",
        [row("P2")],
        SCHEMA,
        FETCHED_AT,
        data_root=tmp_path,
    )

    assert first == second
    assert first == expected_path
    with first.open(encoding="utf-8", newline="") as source:
        contents = list(csv.reader(source))
    assert contents == [
        list(SCHEMA),
        ["Plant", "P1", "10"],
        ["Plant", "P2", "10"],
    ]


def test_csv_write_uses_per_file_lock(monkeypatch, tmp_path: Path) -> None:
    if collector.fcntl is None:
        pytest.skip("fcntl is unavailable on this runtime")
    operations: list[int] = []

    def record_lock(lock_file, operation):
        operations.append(operation)

    monkeypatch.setattr(collector.fcntl, "flock", record_lock)

    path = collector.append_rows(
        "vendor",
        [row()],
        SCHEMA,
        FETCHED_AT,
        data_root=tmp_path,
    )

    assert operations == [collector.fcntl.LOCK_EX, collector.fcntl.LOCK_UN]
    assert (
        tmp_path / ".locks" / "vendor" / "2026" / "06" / f"{path.name}.lock"
    ).exists()


def test_csv_write_waits_for_existing_file_lock(tmp_path: Path) -> None:
    if collector.fcntl is None:
        pytest.skip("fcntl is unavailable on this runtime")
    path = tmp_path / "vendor" / "2026" / "06" / "vendor_23_07_00_00.csv"
    path.parent.mkdir(parents=True)
    lock_path = tmp_path / ".locks" / "vendor" / "2026" / "06" / f"{path.name}.lock"
    lock_path.parent.mkdir(parents=True)

    with lock_path.open("a", encoding="utf-8") as lock_file:
        collector.fcntl.flock(lock_file, collector.fcntl.LOCK_EX)
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=append_row_worker,
            args=(str(tmp_path), "P1"),
        )
        process.start()
        time.sleep(0.25)
        assert process.is_alive()
        assert not path.exists()
        collector.fcntl.flock(lock_file, collector.fcntl.LOCK_UN)

    process.join(timeout=5)
    assert process.exitcode == 0
    with path.open(encoding="utf-8", newline="") as source:
        contents = list(csv.reader(source))
    assert contents == [list(SCHEMA), ["Plant", "P1", "10"]]


def test_csv_write_fails_clearly_when_file_locking_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(collector, "fcntl", None)

    with pytest.raises(RuntimeError, match="CSV file locking requires fcntl"):
        collector.append_rows(
            "vendor",
            [row()],
            SCHEMA,
            FETCHED_AT,
            data_root=tmp_path,
        )


def test_main_exits_when_collector_lock_is_already_held(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    if collector.fcntl is None:
        pytest.skip("fcntl is unavailable on this runtime")
    monkeypatch.chdir(tmp_path)
    lock_path = tmp_path / "logs" / "collector.lock"
    lock_path.parent.mkdir()

    async def fail_if_run():
        raise AssertionError("run should not be called")

    monkeypatch.setattr(collector, "run", fail_if_run)

    with lock_path.open("a", encoding="utf-8") as lock_file:
        collector.fcntl.flock(lock_file, collector.fcntl.LOCK_EX)
        try:
            assert collector.main() == 0
        finally:
            collector.fcntl.flock(lock_file, collector.fcntl.LOCK_UN)

    assert "collector already running; exiting" in caplog.text


def test_header_mismatch_fails_without_modifying_file(tmp_path: Path) -> None:
    path = tmp_path / "vendor" / "2026" / "06" / "vendor_23_07_00_00.csv"
    path.parent.mkdir(parents=True)
    original = "plant_name,wrong\nPlant,old\n"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="CSV header mismatch"):
        collector.append_rows(
            "vendor",
            [row()],
            SCHEMA,
            FETCHED_AT,
            data_root=tmp_path,
        )

    assert path.read_text(encoding="utf-8") == original


def test_row_key_order_mismatch_fails_before_write(tmp_path: Path) -> None:
    wrong_order = {"plant_code": "P1", "plant_name": "Plant", "metric": 10}
    with pytest.raises(ValueError, match="row 0 schema mismatch"):
        collector.append_rows(
            "vendor",
            [wrong_order],
            SCHEMA,
            FETCHED_AT,
            data_root=tmp_path,
        )
    assert not (tmp_path / "vendor").exists()


def test_no_rows_do_not_create_or_modify_file(tmp_path: Path) -> None:
    assert (
        collector.append_rows(
            "vendor",
            [],
            SCHEMA,
            FETCHED_AT,
            data_root=tmp_path,
        )
        is None
    )
    assert list(tmp_path.rglob("*")) == []


def test_decimal_values_are_written_exactly(tmp_path: Path) -> None:
    schema = ("plant_name", "plant_code", "metric")
    path = collector.append_rows(
        "sungrow",
        [
            {
                "plant_name": "Plant",
                "plant_code": "P1",
                "metric": Decimal("5718.2808"),
            }
        ],
        schema,
        FETCHED_AT,
        data_root=tmp_path,
    )

    with path.open(encoding="utf-8", newline="") as source:
        contents = list(csv.reader(source))
    assert contents[1][2] == "5718.2808"


def test_none_metric_is_written_as_empty_csv_field(tmp_path: Path) -> None:
    schema = ("plant_name", "plant_code", "metric")
    path = collector.append_rows(
        "huawei",
        [{"plant_name": "Plant", "plant_code": "NE=1", "metric": None}],
        schema,
        FETCHED_AT,
        data_root=tmp_path,
    )

    with path.open(encoding="utf-8", newline="") as source:
        contents = list(csv.reader(source))
    assert contents[1][2] == ""


@pytest.mark.asyncio
async def test_vendor_failure_does_not_block_other_vendor(
    monkeypatch, tmp_path: Path
) -> None:
    async def failed_fetch(config, fetched_at):
        raise RuntimeError("vendor down")

    async def successful_fetch(config, fetched_at):
        return [row()]

    monkeypatch.setattr(
        collector,
        "ADAPTERS",
        {
            "bad": SimpleNamespace(fetch=failed_fetch, SCHEMA=SCHEMA),
            "good": SimpleNamespace(fetch=successful_fetch, SCHEMA=SCHEMA),
        },
    )
    monkeypatch.setattr(
        collector,
        "load_config",
        lambda path: {
            "vendors": {
                "bad": {"accounts": []},
                "good": {"accounts": []},
            }
        },
    )

    await collector.run(config_path="unused", data_root=tmp_path)

    files = list((tmp_path / "good").rglob("*.csv"))
    assert len(files) == 1
    assert not (tmp_path / "bad").exists()
