"""Reusable HTTP client for the Huawei FusionSolar Northbound API."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .contract import DATA_PATH, LOGIN_PATH, XSRF_NAME, BatchResult


class HuaweiAPIError(RuntimeError):
    """Controlled Huawei API or response-contract failure."""


class HuaweiClient:
    """Handle one account's HTTP session, cookies, and API validation."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._semaphore = semaphore
        self._xsrf_token: str | None = None

    @staticmethod
    def _validate_result(payload: dict[str, Any], operation: str) -> None:
        if payload.get("success") is not True or payload.get("failCode") != 0:
            raise HuaweiAPIError(
                f"{operation} rejected success={payload.get('success')!r} "
                f"failCode={payload.get('failCode')!r} "
                f"message={payload.get('message')!r}"
            )

    async def login(self, account: dict[str, Any]) -> None:
        async with self._semaphore:
            async with self._session.post(
                f"{self._base_url}{LOGIN_PATH}",
                json={
                    "userName": account["username"],
                    "systemCode": account["system_code"],
                },
            ) as response:
                response.raise_for_status()
                payload = await response.json()
                cookie = response.cookies.get(XSRF_NAME)

        if not isinstance(payload, dict):
            raise HuaweiAPIError("login response JSON must be an object")
        self._validate_result(payload, "login")
        if cookie is None or not cookie.value:
            raise HuaweiAPIError(f"login response missing {XSRF_NAME} cookie")
        self._xsrf_token = cookie.value

    async def fetch_batch(
        self,
        plants: list[dict[str, str]],
        collect_time_ms: int,
    ) -> BatchResult:
        if self._xsrf_token is None:
            raise HuaweiAPIError("login is required before fetching data")

        async with self._semaphore:
            async with self._session.post(
                f"{self._base_url}{DATA_PATH}",
                headers={XSRF_NAME: self._xsrf_token},
                json={
                    "stationCodes": ",".join(
                        plant["code"] for plant in plants
                    ),
                    "collectTime": collect_time_ms,
                },
            ) as response:
                response.raise_for_status()
                payload = await response.json()

        if not isinstance(payload, dict):
            raise HuaweiAPIError("data response JSON must be an object")
        self._validate_result(payload, "getKpiStationDay")
        records = payload.get("data")
        if not isinstance(records, list):
            raise HuaweiAPIError("data response missing data list")
        return BatchResult(records=records)

