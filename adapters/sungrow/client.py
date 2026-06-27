"""Reusable HTTP client for the Sungrow iSolarCloud OpenAPI."""
## ===========================================================
## รับผิดชอบการสื่อสารกับ Sungrow API:
## ===========================================================

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .contract import (
    DATA_PATH,
    LANGUAGE,
    LOGIN_PATH,
    METEO_POINT,
    PLANT_POINTS,
    BatchResult,
    DeviceType,
    make_ps_key,
)


class SungrowAPIError(RuntimeError):
    """Controlled Sungrow API or response-contract failure."""

## ===========================================================
## เตรียม URL, app key, headers และ shared semaphore
## ===========================================================
class SungrowClient:
    """Handle Sungrow HTTP requests and validate API envelopes."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        vendor_config: dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._session = session
        self._base_url = vendor_config["base_url"]
        self._app_key = vendor_config["app_key"]
        self._headers = {
            "x-access-key": vendor_config["access_key"],
            "sys_code": vendor_config["sys_code"],
        }
        self._semaphore = semaphore

## ===========================================================
## ส่ง POST request ภายใต้ concurrency limit และตรวจ HTTP/JSON
## ===========================================================
    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self._semaphore:
            async with self._session.post(
                f"{self._base_url}{path}",
                headers=self._headers,
                json=body,
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        if not isinstance(payload, dict):
            raise SungrowAPIError("response JSON must be an object")
        return payload

## ===========================================================
## ตรวจ result_code และดึง result_data จาก payload
## ===========================================================
    @staticmethod
    def _result_data(payload: dict[str, Any], operation: str) -> dict[str, Any]:
        result_code = payload.get("result_code")
        if result_code != "1":
            result_msg = payload.get("result_msg")
            raise SungrowAPIError(
                f"{operation} rejected result_code={result_code!r} "
                f"result_msg={result_msg!r}"
            )
        result_data = payload.get("result_data")
        if not isinstance(result_data, dict):
            raise SungrowAPIError(f"{operation} response missing result_data")
        return result_data

## ===========================================================
## login ด้วย account แล้วคืน token
## ===========================================================
    async def login(self, account: dict[str, Any]) -> str:
        payload = await self._post(
            LOGIN_PATH,
            {
                "appkey": self._app_key,
                "user_account": account["username"],
                "user_password": account["password"],
                "lang": LANGUAGE,
            },
        )
        token = self._result_data(payload, "login").get("token")
        if not isinstance(token, str) or not token:
            raise SungrowAPIError("login response missing token")
        return token

## ===========================================================
## ขอข้อมูล plants หนึ่ง batch และคืน BatchResult
## ===========================================================
    async def fetch_batch(
        self,
        token: str,
        plants: list[dict[str, str]],
    ) -> BatchResult:
        payload = await self._post(
            DATA_PATH,
            {
                "appkey": self._app_key,
                "token": token,
                "device_type": int(DeviceType.PLANT),
                "point_id_list": [point.point_id for point in PLANT_POINTS],
                "ps_key_list": [make_ps_key(plant["code"]) for plant in plants],
            },
        )
        return self._parse_batch_result(payload)

    async def fetch_meteo_batch(
        self,
        token: str,
        ps_keys: list[str],
    ) -> BatchResult:
        payload = await self._post(
            DATA_PATH,
            {
                "appkey": self._app_key,
                "token": token,
                "device_type": int(DeviceType.METEO),
                "point_id_list": [METEO_POINT.point_id],
                "ps_key_list": ps_keys,
            },
        )
        return self._parse_batch_result(payload)

    @classmethod
    def _parse_batch_result(cls, payload: dict[str, Any]) -> BatchResult:
        result_data = cls._result_data(payload, "getDeviceRealTimeData")
        records = result_data.get("device_point_list")
        failed_ps_keys = result_data.get("fail_ps_key_list")
        if not isinstance(records, list):
            raise SungrowAPIError("data response missing device_point_list")
        if not isinstance(failed_ps_keys, list) or not all(
            isinstance(key, str) for key in failed_ps_keys
        ):
            raise SungrowAPIError("data response has invalid fail_ps_key_list")
        return BatchResult(records=records, failed_ps_keys=tuple(failed_ps_keys))
