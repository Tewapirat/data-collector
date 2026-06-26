import csv
from pathlib import Path

import pytest

import collector
from adapters import sungrow
from config import load_config


@pytest.mark.asyncio
async def test_sungrow_config_to_collector_csv_flow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "plants.yaml"
    config_path.write_text(
        """
vendors:
  sungrow:
    batch_size: 10
    max_concurrency: 1
    accounts:
      - id: sungrow-test
        username: operator@example.com
        password_env: SUNGROW_TEST_PASSWORD
        plants:
          - name: Plant One
            code: "P1"
          - name: Plant Two
            code: "P2"
""",
        encoding="utf-8",
    )
    environment = {
        "SUNGROW_URL": "https://sungrow.example/openapi",
        "SUNGROW_APP_KEY": "app-key",
        "SUNGROW_ACCESS_KEY": "access-key",
        "SUNGROW_SYS_CODE": "sys-code",
        "SUNGROW_TEST_PASSWORD": "password",
    }
    api_calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(
        self: sungrow.SungrowClient,
        path: str,
        body: dict[str, object],
    ) -> dict[str, object]:
        api_calls.append((path, body))
        if path == "/login":
            return {
                "result_code": "1",
                "result_data": {"token": "session-token"},
            }
        if path == "/getDeviceRealTimeData":
            return {
                "result_code": "1",
                "result_data": {
                    "fail_ps_key_list": [],
                    "device_point_list": [
                        {
                            "device_point": {
                                "ps_key": "P2_11_0_0",
                                "p83022": "200.25",
                                "p83013": "20.5",
                                "device_time": "20260623120000",
                            }
                        },
                        {
                            "device_point": {
                                "ps_key": "P1_11_0_0",
                                "p83022": "100.125",
                                "p83013": "10.75",
                                "device_time": "20260623115900",
                            }
                        },
                    ],
                },
            }
        raise AssertionError(f"unexpected Sungrow path: {path}")

    monkeypatch.setattr(sungrow.SungrowClient, "_post", fake_post)
    monkeypatch.setattr(
        collector,
        "load_config",
        lambda path: load_config(path, environ=environment),
    )

    await collector.run(config_path=config_path, data_root=tmp_path / "data")

    output_files = list((tmp_path / "data" / "sungrow").rglob("*.csv"))
    assert len(output_files) == 1
    with output_files[0].open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    assert rows == [
        {
            "no": "1",
            "plant_name": "Plant One",
            "plant_code": "P1",
            "daily_yield_wh": "100.125",
            "daily_irradiation_w_m2": "10.75",
            "fetched_at": rows[0]["fetched_at"],
            "collect_time": "2026-06-23T11:59:00+07:00",
        },
        {
            "no": "2",
            "plant_name": "Plant Two",
            "plant_code": "P2",
            "daily_yield_wh": "200.25",
            "daily_irradiation_w_m2": "20.5",
            "fetched_at": rows[1]["fetched_at"],
            "collect_time": "2026-06-23T12:00:00+07:00",
        },
    ]
    assert rows[0]["fetched_at"] == rows[1]["fetched_at"]
    assert api_calls == [
        (
            "/login",
            {
                "appkey": "app-key",
                "user_account": "operator@example.com",
                "user_password": "password",
                "lang": "_en_US",
            },
        ),
        (
            "/getDeviceRealTimeData",
            {
                "appkey": "app-key",
                "token": "session-token",
                "device_type": 11,
                "point_id_list": ["83022", "83013"],
                "ps_key_list": ["P1_11_0_0", "P2_11_0_0"],
            },
        ),
    ]
