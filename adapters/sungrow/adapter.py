"""Sungrow account orchestration and response-to-row mapping."""
## ===========================================================
## รับผิดชอบ orchestration และแปลงข้อมูลเป็น CSV rows
## ===========================================================

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from .client import SungrowClient
from .contract import (
    POINTS,
    BatchResult,
    PointDefinition,
    plant_code_from_ps_key,
)

LOGGER = logging.getLogger("collector")
BANGKOK = ZoneInfo("Asia/Bangkok")

## ===========================================================
## แบ่งรายการ plants ตาม batch_size
## ===========================================================
def chunked(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


class SungrowAdapter:
    """Coordinate accounts and convert API records to stable CSV rows."""

    def __init__(
        self,
        client: SungrowClient,
        vendor_config: dict[str, Any],
        fetched_at: datetime,
    ) -> None:
        self._client = client
        self._vendor_config = vendor_config
        self._fetched_at = fetched_at


## ===========================================================
## แปลงเวลา Sungrow เป็น ISO 8601 เวลา Bangkok
## ===========================================================
    @staticmethod
    def _parse_device_time(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("device_time must be a string")
        parsed = datetime.strptime(value, "%Y%m%d%H%M%S").replace(tzinfo=BANGKOK)
        return parsed.isoformat()

## ===========================================================
## ตรวจและแปลง metric เป็น Decimal
## ===========================================================
    @staticmethod
    def _parse_optional_decimal(
        record: dict[str, Any], point: PointDefinition
    ) -> Decimal | None:
        value = record.get(point.response_key)
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(
            value, (str, int, float, Decimal)
        ):
            raise ValueError(f"{point.response_key} must be numeric")
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{point.response_key} must be numeric") from exc
        if not number.is_finite():
            raise ValueError(f"{point.response_key} must be finite")
        return number

## ===========================================================
## สร้าง lookup ด้วย plant code พร้อมตัด records ที่ malformed/ซ้ำ
## ===========================================================
    def _index_records(
        self,
        account_id: str,
        records: list[Any],
    ) -> dict[str, dict[str, Any]]:
        by_code: dict[str, dict[str, Any]] = {}
        for wrapper in records:
            if not isinstance(wrapper, dict):
                LOGGER.error(
                    "[sungrow][%s] malformed record wrapper_type=%s",
                    account_id,
                    type(wrapper).__name__,
                )
                continue
            record = wrapper.get("device_point")
            if not isinstance(record, dict):
                LOGGER.error(
                    "[sungrow][%s] malformed record missing device_point",
                    account_id,
                )
                continue
            code = plant_code_from_ps_key(record.get("ps_key"))
            if code is None:
                LOGGER.error(
                    "[sungrow][%s] malformed record invalid ps_key",
                    account_id,
                )
                continue
            if code in by_code:
                LOGGER.error(
                    "[sungrow][%s] duplicate plant response plant_code=%s",
                    account_id,
                    code,
                )
                continue
            by_code[code] = record
        return by_code

## ===========================================================
## จับคู่ response กับ YAML plants และสร้าง rows ตาม schema
## ===========================================================
    def map_records(
        self,
        account_id: str,
        plants: list[dict[str, str]],
        batch_result: BatchResult,
    ) -> list[dict[str, Any]]:
        failed_codes: set[str] = set()
        for ps_key in batch_result.failed_ps_keys:
            LOGGER.error("[sungrow][%s] API failed ps_key=%s", account_id, ps_key)
            code = plant_code_from_ps_key(ps_key)
            if code is not None:
                failed_codes.add(code)

        by_code = self._index_records(account_id, batch_result.records)
        configured_codes = {plant["code"] for plant in plants}
        for unexpected_code in by_code.keys() - configured_codes:
            LOGGER.error(
                "[sungrow][%s] unexpected plant response plant_code=%s",
                account_id,
                unexpected_code,
            )

        rows: list[dict[str, Any]] = []
        for plant in plants:
            if plant["code"] in failed_codes:
                continue
            record = by_code.get(plant["code"])
            if record is None:
                LOGGER.error(
                    "[sungrow][%s] missing plant plant_code=%s",
                    account_id,
                    plant["code"],
                )
                continue
            try:
                device_time = self._parse_device_time(record.get("device_time"))
                metrics = {
                    point.column: self._parse_optional_decimal(record, point)
                    for point in POINTS
                }
            except ValueError as exc:
                LOGGER.error(
                    "[sungrow][%s] malformed plant plant_code=%s error=%s",
                    account_id,
                    plant["code"],
                    str(exc),
                )
                continue
            rows.append(
                {
                    "no": len(rows) + 1,
                    "plant_name": plant["name"],
                    "plant_code": plant["code"],
                    **metrics,
                    "fetched_at": self._fetched_at.isoformat(),
                    "collect_time": device_time,
                }
            )
        return rows
    
## ===========================================================
## login หนึ่ง account, เรียกทุก batch พร้อมกัน และแยกความล้มเหลวราย batch
## ===========================================================
    async def fetch_account(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        account_id = account["id"]
        try:
            token = await self._client.login(account)
            LOGGER.info("[sungrow][%s] login succeeded", account_id)
        except Exception as exc:
            LOGGER.error(
                "[sungrow][%s] login failed error=%s detail=%s",
                account_id,
                type(exc).__name__,
                str(exc),
            )
            return []

        batches = chunked(account["plants"], self._vendor_config["batch_size"])
        results = await asyncio.gather(
            *(self._client.fetch_batch(token, batch) for batch in batches),
            return_exceptions=True,
        )

        rows: list[dict[str, Any]] = []
        for batch, result in zip(batches, results, strict=True):
            codes = ",".join(plant["code"] for plant in batch)
            if isinstance(result, BaseException):
                LOGGER.error(
                    "[sungrow][%s] batch failed plant_codes=%s error=%s detail=%s",
                    account_id,
                    codes,
                    type(result).__name__,
                    str(result),
                )
                continue
            batch_rows = self.map_records(account_id, batch, result)
            rows.extend(batch_rows)
            LOGGER.info(
                "[sungrow][%s] batch succeeded plants=%d rows=%d",
                account_id,
                len(batch),
                len(batch_rows),
            )
        return rows

    async def fetch(self) -> list[dict[str, Any]]:
        accounts = self._vendor_config["accounts"]
        results = await asyncio.gather(
            *(self.fetch_account(account) for account in accounts),
            return_exceptions=True,
        )

        rows: list[dict[str, Any]] = []
        for account, result in zip(accounts, results, strict=True):
            if isinstance(result, BaseException):
                LOGGER.error(
                    "[sungrow][%s] account failed error=%s detail=%s",
                    account["id"],
                    type(result).__name__,
                    str(result),
                )
                continue
            rows.extend(result)
        for index, row in enumerate(rows, start=1):
            row["no"] = index
        return rows

## ===================================================================================
## ระดับ module — entry point ที่ collector.py ใช้ สร้าง HTTP session และ shared semaphore
## ===================================================================================
async def fetch(vendor_config: dict[str, Any], fetched_at: datetime) -> list[dict[str, Any]]:
    """Adapter contract used by collector.py."""
    semaphore = asyncio.Semaphore(vendor_config["max_concurrency"])
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        client = SungrowClient(session, vendor_config, semaphore)
        adapter = SungrowAdapter(client, vendor_config, fetched_at)
        return await adapter.fetch()
