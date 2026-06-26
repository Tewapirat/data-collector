import asyncio

import pytest

from adapters import sungrow


def sungrow_record(code: str) -> dict[str, object]:
    return {
        "device_point": {
            "ps_key": f"{code}_11_0_0",
            "p83022": "4147700.0",
            "p83013": "5718.2808",
            "device_time": "20260616150000",
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


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def test_public_facade_exports_supported_interface() -> None:
    assert sungrow.SCHEMA
    assert sungrow.POINTS
    assert sungrow.BatchResult
    assert sungrow.SungrowClient
    assert sungrow.SungrowAdapter
    assert sungrow.SungrowAPIError
    assert sungrow.fetch


def test_ps_key_round_trip() -> None:
    assert sungrow.make_ps_key("1286347") == "1286347_11_0_0"
    assert sungrow.plant_code_from_ps_key("1286347_11_0_0") == "1286347"
    assert sungrow.plant_code_from_ps_key("invalid") is None


@pytest.mark.asyncio
async def test_sungrow_login_uses_exact_contract() -> None:
    session = FakeSession(
        {
            "result_code": "1",
            "result_msg": "success",
            "result_data": {"token": "session-token"},
        }
    )
    config = sungrow_config()
    account = {"username": "operator@example.com", "password": "password"}
    client = sungrow.SungrowClient(session, config, asyncio.Semaphore(1))

    token = await client.login(account)

    assert token == "session-token"
    assert session.calls == [
        (
            "https://gateway.isolarcloud.com.hk/openapi/login",
            {
                "headers": {
                    "x-access-key": "access-key",
                    "sys_code": "sys-code",
                },
                "json": {
                    "appkey": "app-key",
                    "user_account": "operator@example.com",
                    "user_password": "password",
                    "lang": "_en_US",
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_sungrow_login_rejects_non_success_result() -> None:
    session = FakeSession(
        {
            "result_code": "0",
            "result_msg": "invalid credentials",
            "result_data": None,
        }
    )
    client = sungrow.SungrowClient(
        session, sungrow_config(), asyncio.Semaphore(1)
    )

    with pytest.raises(sungrow.SungrowAPIError, match="result_code='0'"):
        await client.login({"username": "u", "password": "p"})


@pytest.mark.asyncio
async def test_sungrow_data_request_uses_exact_contract() -> None:
    session = FakeSession(
        {
            "result_code": "1",
            "result_msg": "success",
            "result_data": {
                "fail_ps_key_list": [],
                "device_point_list": [sungrow_record("1286347")],
            },
        }
    )
    client = sungrow.SungrowClient(
        session, sungrow_config(), asyncio.Semaphore(1)
    )

    result = await client.fetch_batch(
        "session-token",
        [{"name": "STEC Solar", "code": "1286347"}],
    )

    assert result.failed_ps_keys == ()
    assert session.calls == [
        (
            "https://gateway.isolarcloud.com.hk/openapi/getDeviceRealTimeData",
            {
                "headers": {
                    "x-access-key": "access-key",
                    "sys_code": "sys-code",
                },
                "json": {
                    "appkey": "app-key",
                    "token": "session-token",
                    "device_type": 11,
                    "point_id_list": ["83022", "83013"],
                    "ps_key_list": ["1286347_11_0_0"],
                },
            },
        )
    ]

