import asyncio
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from adapters import huawei

BANGKOK = ZoneInfo("Asia/Bangkok")
FETCHED_AT = datetime(2026, 6, 23, 7, 0, tzinfo=BANGKOK)
TARGET_TIME_MS = 1782147600000


def plants(count: int, prefix: str = "NE=") -> list[dict[str, str]]:
    return [
        {"name": f"Plant {index}", "code": f"{prefix}{index}"}
        for index in range(count)
    ]


def record(
    code: str,
    *,
    collect_time: int = TARGET_TIME_MS,
    pv_yield=52.92,
    irradiation=6.829,
) -> dict[str, object]:
    data = {"PVYield": pv_yield}
    if irradiation is not None:
        data["radiation_intensity"] = irradiation
    return {
        "collectTime": collect_time,
        "stationCode": code,
        "dataItemMap": data,
    }


def huawei_config() -> dict[str, object]:
    return {
        "base_url": "https://sg5.fusionsolar.huawei.com",
        "batch_size": 100,
        "max_concurrency": 3,
        "accounts": [],
    }


def make_adapter(
    config: dict[str, object] | None = None,
) -> huawei.HuaweiAdapter:
    return huawei.HuaweiAdapter(
        config or huawei_config(),
        FETCHED_AT,
        asyncio.Semaphore(3),
    )


def test_collect_time_is_bangkok_midnight_epoch_ms() -> None:
    assert huawei.collect_time_ms(FETCHED_AT) == TARGET_TIME_MS
    assert (
        huawei.iso_collect_time(TARGET_TIME_MS)
        == "2026-06-23T00:00:00+07:00"
    )


def test_chunking_respects_100_station_limit() -> None:
    batches = huawei.chunked(plants(201), 100)
    assert [len(batch) for batch in batches] == [100, 100, 1]


def test_maps_out_of_order_records_by_station_code() -> None:
    configured = plants(2)
    result = huawei.BatchResult(
        records=[
            record("NE=1", pv_yield=20),
            record("NE=0", pv_yield=10),
        ]
    )

    rows = make_adapter().map_records("acc", configured, result)

    assert [row["plant_code"] for row in rows] == ["NE=0", "NE=1"]
    assert [row["pv_yield_kwh"] for row in rows] == [
        Decimal("10"),
        Decimal("20"),
    ]
    assert rows[0]["global_irradiation_kwh_m2"] == Decimal("6.829")
    assert rows[0]["fetched_at"] == FETCHED_AT.isoformat()
    assert rows[0]["collect_time"] == "2026-06-23T00:00:00+07:00"
    assert rows[0]["no"] == 1
    assert list(rows[0]) == list(huawei.SCHEMA)


def test_missing_optional_irradiation_becomes_empty_value() -> None:
    configured = [{"name": "Plant", "code": "NE=1"}]
    rows = make_adapter().map_records(
        "acc",
        configured,
        huawei.BatchResult(records=[record("NE=1", irradiation=None)]),
    )

    assert rows[0]["pv_yield_kwh"] == Decimal("52.92")
    assert rows[0]["global_irradiation_kwh_m2"] is None


def test_missing_null_and_empty_metrics_are_recorded_as_none() -> None:
    configured = plants(3)
    rows = make_adapter().map_records(
        "acc",
        configured,
        huawei.BatchResult(
            records=[
                record("NE=0", pv_yield=None),
                record("NE=1", irradiation=None),
                record("NE=2", pv_yield="", irradiation=""),
            ]
        ),
    )

    assert [row["plant_code"] for row in rows] == ["NE=0", "NE=1", "NE=2"]
    assert rows[0]["pv_yield_kwh"] is None
    assert rows[1]["global_irradiation_kwh_m2"] is None
    assert rows[2]["pv_yield_kwh"] is None
    assert rows[2]["global_irradiation_kwh_m2"] is None


def test_filters_other_dates_and_logs_missing_station(caplog) -> None:
    configured = [{"name": "Plant", "code": "NE=1"}]
    previous_day = TARGET_TIME_MS - 86_400_000

    rows = make_adapter().map_records(
        "acc",
        configured,
        huawei.BatchResult(records=[record("NE=1", collect_time=previous_day)]),
    )

    assert rows == []
    assert "missing station station_code=NE=1" in caplog.text


def test_omits_malformed_duplicate_and_unexpected_records(caplog) -> None:
    configured = [{"name": "Plant", "code": "NE=1"}]
    result = huawei.BatchResult(
        records=[
            record("NE=1"),
            record("NE=1"),
            record("NE=unexpected"),
            record("NE=bad", pv_yield="not-a-number"),
            "invalid",
        ]
    )

    rows = make_adapter().map_records("acc", configured, result)

    assert [row["plant_code"] for row in rows] == ["NE=1"]
    assert "duplicate station response station_code=NE=1" in caplog.text
    assert "unexpected station response station_code=NE=unexpected" in caplog.text
    assert "malformed record type=str" in caplog.text


@pytest.mark.asyncio
async def test_accounts_use_distinct_clients_and_batches_do_not_mix() -> None:
    created_clients = []
    observed_batches = []

    class RecordingClient:
        def __init__(self):
            self.account_id = None

        async def login(self, account):
            self.account_id = account["id"]

        async def fetch_batch(self, batch, collect_time_ms):
            observed_batches.append(
                (self.account_id, tuple(plant["code"] for plant in batch))
            )
            return huawei.BatchResult(
                records=[record(plant["code"]) for plant in batch]
            )

    def factory(session):
        client = RecordingClient()
        created_clients.append(client)
        return client

    config = {
        **huawei_config(),
        "batch_size": 2,
        "accounts": [
            {
                "id": "a1",
                "username": "u1",
                "system_code": "s1",
                "plants": plants(3, "A"),
            },
            {
                "id": "a2",
                "username": "u2",
                "system_code": "s2",
                "plants": plants(2, "B"),
            },
        ],
    }
    adapter = huawei.HuaweiAdapter(
        config,
        FETCHED_AT,
        asyncio.Semaphore(3),
        client_factory=factory,
    )

    rows = await adapter.fetch()

    assert len(created_clients) == 2
    assert sorted(observed_batches) == [
        ("a1", ("A0", "A1")),
        ("a1", ("A2",)),
        ("a2", ("B0", "B1")),
    ]
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_login_and_batch_failures_are_isolated() -> None:
    class FailingClient:
        def __init__(self):
            self.account_id = None

        async def login(self, account):
            self.account_id = account["id"]
            if self.account_id == "bad-login":
                raise RuntimeError("authentication failed")

        async def fetch_batch(self, batch, collect_time_ms):
            if batch[0]["code"] == "NE=2":
                raise RuntimeError("batch failed")
            return huawei.BatchResult(
                records=[record(plant["code"]) for plant in batch]
            )

    config = {
        **huawei_config(),
        "batch_size": 2,
        "accounts": [
            {
                "id": "good",
                "username": "u",
                "system_code": "s",
                "plants": plants(4),
            },
            {
                "id": "bad-login",
                "username": "u",
                "system_code": "s",
                "plants": plants(1, "X"),
            },
        ],
    }
    adapter = huawei.HuaweiAdapter(
        config,
        FETCHED_AT,
        asyncio.Semaphore(2),
        client_factory=lambda session: FailingClient(),
    )

    rows = await adapter.fetch()

    assert [row["plant_code"] for row in rows] == ["NE=0", "NE=1"]
