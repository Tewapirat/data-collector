import asyncio
from http.cookies import SimpleCookie

import pytest

from adapters import huawei


class FakeResponse:
    def __init__(self, payload, cookies=None):
        self.payload = payload
        self.cookies = SimpleCookie()
        for name, value in (cookies or {}).items():
            self.cookies[name] = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    def raise_for_status(self):
        return None

    async def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def success(data=None):
    return {
        "data": data,
        "success": True,
        "failCode": 0,
        "params": {},
        "message": None,
    }


def test_public_facade_exports_supported_interface() -> None:
    assert huawei.SCHEMA
    assert huawei.METRICS
    assert huawei.BatchResult
    assert huawei.HuaweiClient
    assert huawei.HuaweiAdapter
    assert huawei.HuaweiAPIError
    assert huawei.fetch


@pytest.mark.asyncio
async def test_login_reads_xsrf_cookie_and_data_request_uses_header() -> None:
    session = FakeSession(
        [
            FakeResponse(success(), {"XSRF-TOKEN": "xsrf-token"}),
            FakeResponse(success([])),
        ]
    )
    client = huawei.HuaweiClient(
        session,
        "https://sg5.fusionsolar.huawei.com",
        asyncio.Semaphore(1),
    )

    await client.login(
        {"username": "greenergyz", "system_code": "system-code"}
    )
    result = await client.fetch_batch(
        [
            {"name": "One", "code": "NE=1"},
            {"name": "Two", "code": "NE=2"},
        ],
        1781888400000,
    )

    assert result.records == []
    assert session.calls == [
        (
            "https://sg5.fusionsolar.huawei.com/thirdData/login",
            {
                "json": {
                    "userName": "greenergyz",
                    "systemCode": "system-code",
                }
            },
        ),
        (
            "https://sg5.fusionsolar.huawei.com/thirdData/getKpiStationDay",
            {
                "headers": {"XSRF-TOKEN": "xsrf-token"},
                "json": {
                    "stationCodes": "NE=1,NE=2",
                    "collectTime": 1781888400000,
                },
            },
        ),
    ]


@pytest.mark.asyncio
async def test_login_rejects_failed_api_result() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "data": None,
                    "success": False,
                    "failCode": 20001,
                    "message": "login failed",
                },
                {"XSRF-TOKEN": "unused"},
            )
        ]
    )
    client = huawei.HuaweiClient(
        session,
        "https://sg5.fusionsolar.huawei.com",
        asyncio.Semaphore(1),
    )

    with pytest.raises(huawei.HuaweiAPIError, match="failCode=20001"):
        await client.login({"username": "u", "system_code": "s"})


@pytest.mark.asyncio
async def test_login_requires_xsrf_cookie() -> None:
    session = FakeSession([FakeResponse(success())])
    client = huawei.HuaweiClient(
        session,
        "https://sg5.fusionsolar.huawei.com",
        asyncio.Semaphore(1),
    )

    with pytest.raises(huawei.HuaweiAPIError, match="XSRF-TOKEN"):
        await client.login({"username": "u", "system_code": "s"})


@pytest.mark.asyncio
async def test_fetch_requires_login() -> None:
    client = huawei.HuaweiClient(
        FakeSession([]),
        "https://sg5.fusionsolar.huawei.com",
        asyncio.Semaphore(1),
    )

    with pytest.raises(huawei.HuaweiAPIError, match="login is required"):
        await client.fetch_batch([], 0)


@pytest.mark.asyncio
async def test_clients_share_vendor_semaphore() -> None:
    active = 0
    peak = 0
    lock = asyncio.Lock()

    class TrackingResponse(FakeResponse):
        async def __aenter__(self):
            nonlocal active, peak
            async with lock:
                active += 1
                peak = max(peak, active)
            await asyncio.sleep(0.01)
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            nonlocal active
            async with lock:
                active -= 1
            return False

    semaphore = asyncio.Semaphore(2)
    clients = [
        huawei.HuaweiClient(
            FakeSession(
                [
                    TrackingResponse(
                        success(), {"XSRF-TOKEN": f"token-{index}"}
                    )
                ]
            ),
            "https://sg5.fusionsolar.huawei.com",
            semaphore,
        )
        for index in range(4)
    ]

    await asyncio.gather(
        *(
            client.login(
                {"username": f"user-{index}", "system_code": "system-code"}
            )
            for index, client in enumerate(clients)
        )
    )

    assert peak == 2
