import asyncio
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from adapters import sungrow

FETCHED_AT = datetime(2026, 6, 23, 7, 0, tzinfo=ZoneInfo("Asia/Bangkok"))


def plants(count: int, prefix: str = "P") -> list[dict[str, str]]:
    return [
        {"name": f"Plant {index}", "code": f"{prefix}{index}"}
        for index in range(count)
    ]


def sungrow_record(
    code: str,
    *,
    daily_yield: object = "4147700.0",
    device_time: str = "20260616150000",
) -> dict[str, object]:
    return {
        "device_point": {
            "ps_key": f"{code}_11_0_0",
            "p83022": daily_yield,
            "device_time": device_time,
        }
    }


def meteo_record(
    code: str,
    *,
    irradiation: object = "5718.2808",
    device_time: str = "20260616150500",
    device_name: str = "Meteo Station1",
) -> dict[str, object]:
    return {
        "device_point": {
            "ps_key": f"{code}_5_1_1",
            "p2001": irradiation,
            "device_time": device_time,
            "device_name": device_name,
        }
    }


def sungrow_config() -> dict[str, object]:
    return {
        "base_url": "https://gateway.isolarcloud.com.hk/openapi",
        "app_key": "app-key",
        "access_key": "access-key",
        "sys_code": "sys-code",
        "batch_size": 50,
        "max_concurrency": 2,
        "accounts": [],
    }


class StubClient:
    async def login(self, account):
        return "token"

    async def fetch_batch(self, token, batch):
        return sungrow.BatchResult(
            records=[sungrow_record(plant["code"]) for plant in batch],
            failed_ps_keys=(),
        )


def make_adapter(
    client=None,
    config: dict[str, object] | None = None,
) -> sungrow.SungrowAdapter:
    return sungrow.SungrowAdapter(
        client or StubClient(),
        config or sungrow_config(),
        FETCHED_AT,
    )


def test_sungrow_chunking_uses_one_batch_at_or_below_limit() -> None:
    configured = plants(3)
    assert sungrow.chunked(configured, 3) == [configured]
    assert sungrow.chunked(configured, 10) == [configured]


def test_sungrow_chunking_splits_at_50_plant_limit() -> None:
    batches = sungrow.chunked(plants(101), 50)
    assert [len(batch) for batch in batches] == [50, 50, 1]


def test_sungrow_maps_out_of_order_response_by_code() -> None:
    configured = plants(2)
    records = [
        sungrow_record("P1", daily_yield="20"),
        sungrow_record("P0", daily_yield="10"),
    ]

    rows = make_adapter().map_records(
        "acc",
        configured,
        sungrow.BatchResult(records=records, failed_ps_keys=()),
        {
            "P0": meteo_record("P0")["device_point"],
            "P1": meteo_record("P1", irradiation="6000")["device_point"],
        },
    )

    assert [row["plant_code"] for row in rows] == ["P0", "P1"]
    assert [row["daily_yield_wh"] for row in rows] == [
        Decimal("10"),
        Decimal("20"),
    ]
    assert rows[0]["daily_irradiation_wh_m2"] == Decimal("5718.2808")
    assert rows[0]["meteo_name"] == "Meteo Station1"
    assert rows[0]["collect_time"] == "2026-06-16T15:05:00+07:00"
    assert rows[0]["no"] == 1
    assert list(rows[0]) == list(sungrow.SCHEMA)


def test_sungrow_missing_null_and_empty_metrics_are_recorded_as_none() -> None:
    configured = plants(3)
    missing_metric = sungrow_record("P0")
    del missing_metric["device_point"]["p83022"]

    rows = make_adapter().map_records(
        "acc",
        configured,
        sungrow.BatchResult(
            records=[
                missing_metric,
                sungrow_record("P1", daily_yield=None),
                sungrow_record("P2"),
            ],
            failed_ps_keys=(),
        ),
    )

    assert [row["plant_code"] for row in rows] == ["P0", "P1", "P2"]
    assert rows[0]["daily_yield_wh"] is None
    assert rows[1]["daily_yield_wh"] is None
    assert rows[2]["daily_irradiation_wh_m2"] is None


def test_sungrow_meteo_mapping_is_merged_by_ps_key() -> None:
    configured = [
        {
            "name": "Plant 0",
            "code": "P0",
            "meteo": {"ps_key": "P0_5_7_1", "name": "Meteo A"},
        },
        {
            "name": "Plant 1",
            "code": "P1",
            "meteo": {"ps_key": "P1_5_8_1", "name": "Meteo B"},
        },
    ]
    adapter = make_adapter(config=sungrow_config())

    rows = adapter.map_records(
        "acc",
        configured,
        sungrow.BatchResult(
            records=[sungrow_record("P0"), sungrow_record("P1")],
            failed_ps_keys=(),
        ),
        adapter._index_meteo_records(
            "acc",
            [
                {
                    "device_point": {
                        "ps_key": "P1_5_8_1",
                        "p2001": "20.5",
                        "device_time": "20260616150600",
                        "device_name": "Meteo B",
                    }
                },
                {
                    "device_point": {
                        "ps_key": "P0_5_7_1",
                        "p2001": "10.75",
                        "device_time": "20260616150500",
                        "device_name": "Meteo A",
                    }
                },
            ],
            {
                plant["meteo"]["ps_key"]: plant["code"]
                for plant in configured
            },
        ),
    )

    assert [row["daily_irradiation_wh_m2"] for row in rows] == [
        Decimal("10.75"),
        Decimal("20.5"),
    ]
    assert [row["meteo_name"] for row in rows] == ["Meteo A", "Meteo B"]


@pytest.mark.asyncio
async def test_sungrow_meteo_failed_ps_key_is_not_used() -> None:
    class MeteoClient:
        async def fetch_meteo_batch(self, token, batch):
            return sungrow.BatchResult(
                records=[
                    {
                        "device_point": {
                            "ps_key": "P0_5_7_1",
                            "p2001": "10.75",
                            "device_time": "20260616150500",
                            "device_name": "Meteo A",
                        }
                    }
                ],
                failed_ps_keys=("P0_5_7_1",),
            )

    adapter = sungrow.SungrowAdapter(
        MeteoClient(),
        sungrow_config(),
        FETCHED_AT,
    )

    records = await adapter.fetch_meteo_records(
        "acc",
        "token",
        [
            {
                "name": "Plant 0",
                "code": "P0",
                "meteo": {"ps_key": "P0_5_7_1", "name": "Meteo A"},
            }
        ],
    )

    assert records == {}


@pytest.mark.asyncio
async def test_account_batches_never_mix_accounts_and_login_once() -> None:
    login_calls: list[str] = []
    observed_batches: list[tuple[str, ...]] = []

    class RecordingClient:
        async def login(self, account):
            login_calls.append(account["id"])
            return f"token-{account['id']}"

        async def fetch_batch(self, token, batch):
            observed_batches.append(tuple(plant["code"] for plant in batch))
            return sungrow.BatchResult(
                records=[
                    sungrow_record(plant["code"]) for plant in reversed(batch)
                ],
                failed_ps_keys=(),
            )

    config = {
        **sungrow_config(),
        "batch_size": 2,
        "max_concurrency": 4,
        "accounts": [
            {
                "id": "a1",
                "username": "u1",
                "password": "p1",
                "plants": plants(3, "A"),
            },
            {
                "id": "a2",
                "username": "u2",
                "password": "p2",
                "plants": plants(2, "B"),
            },
        ],
    }

    rows = await make_adapter(RecordingClient(), config).fetch()

    assert sorted(login_calls) == ["a1", "a2"]
    assert len(login_calls) == 2
    assert sorted(observed_batches) == [("A0", "A1"), ("A2",), ("B0", "B1")]
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_login_and_batch_failures_are_isolated() -> None:
    class FailingClient:
        async def login(self, account):
            if account["id"] == "bad-login":
                raise RuntimeError("authentication failed")
            return "token"

        async def fetch_batch(self, token, batch):
            if batch[0]["code"] == "P2":
                raise RuntimeError("batch failed")
            return sungrow.BatchResult(
                records=[sungrow_record(plant["code"]) for plant in batch],
                failed_ps_keys=(),
            )

    config = {
        **sungrow_config(),
        "batch_size": 2,
        "accounts": [
            {
                "id": "good",
                "username": "u",
                "password": "p",
                "plants": plants(4),
            },
            {
                "id": "bad-login",
                "username": "u",
                "password": "p",
                "plants": plants(1, "X"),
            },
        ],
    }

    rows = await make_adapter(FailingClient(), config).fetch()

    assert [row["plant_code"] for row in rows] == ["P0", "P1"]


@pytest.mark.asyncio
async def test_shared_vendor_semaphore_limits_all_accounts() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(2)

    async def track():
        nonlocal active, peak
        async with semaphore:
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1

    class ConcurrentClient:
        async def login(self, account):
            await track()
            return "token"

        async def fetch_batch(self, token, batch):
            await track()
            return sungrow.BatchResult(
                records=[sungrow_record(plant["code"]) for plant in batch],
                failed_ps_keys=(),
            )

    config = {
        **sungrow_config(),
        "batch_size": 1,
        "accounts": [
            {
                "id": f"a{index}",
                "username": "u",
                "password": "p",
                "plants": plants(3, f"{index}-"),
            }
            for index in range(3)
        ],
    }

    await make_adapter(ConcurrentClient(), config).fetch()

    assert peak == 2


def test_sungrow_omits_failed_missing_and_malformed_plants(caplog) -> None:
    configured = plants(4)
    result = sungrow.BatchResult(
        records=[
            sungrow_record("P0"),
            sungrow_record("P1", daily_yield=None),
            sungrow_record("P2", device_time="invalid"),
            {"device_point": {"ps_key": "invalid-key"}},
        ],
        failed_ps_keys=("P3_11_0_0",),
    )

    rows = make_adapter().map_records("acc", configured, result)

    assert [row["plant_code"] for row in rows] == ["P0", "P1"]
    assert "API failed ps_key=P3_11_0_0" in caplog.text
    assert "malformed plant plant_code=P2" in caplog.text


def test_sungrow_failed_ps_key_is_omitted_even_if_record_is_present() -> None:
    configured = [{"name": "Plant", "code": "P0"}]
    result = sungrow.BatchResult(
        records=[sungrow_record("P0")],
        failed_ps_keys=("P0_11_0_0",),
    )

    assert make_adapter().map_records("acc", configured, result) == []
