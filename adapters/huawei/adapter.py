"""Huawei account orchestration and response-to-row mapping."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from zoneinfo import ZoneInfo

import aiohttp

from .client import HuaweiClient
from .contract import METRICS, BatchResult, MetricDefinition

LOGGER = logging.getLogger("collector")
BANGKOK = ZoneInfo("Asia/Bangkok")


def chunked(items: list[dict[str, str]], size: int) -> list[list[dict[str, str]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def collect_time_ms(fetched_at: datetime) -> int:
    local = fetched_at.astimezone(BANGKOK)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


def iso_collect_time(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("collectTime must be an integer epoch milliseconds")
    return datetime.fromtimestamp(value / 1000, BANGKOK).isoformat()


def collect_date(value: Any) -> date:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("collectTime must be an integer epoch milliseconds")
    return datetime.fromtimestamp(value / 1000, BANGKOK).date()


class HuaweiAdapter:
    """Coordinate Huawei accounts and convert station KPIs to CSV rows."""

    def __init__(
        self,
        vendor_config: dict[str, Any],
        fetched_at: datetime,
        semaphore: asyncio.Semaphore,
        client_factory: Callable[[aiohttp.ClientSession], HuaweiClient] | None = None,
    ) -> None:
        self._vendor_config = vendor_config
        self._fetched_at = fetched_at
        self._semaphore = semaphore
        self._client_factory = client_factory

    @staticmethod
    def _parse_optional_decimal(
        data_item_map: dict[str, Any],
        metric: MetricDefinition,
    ) -> Decimal | None:
        value = data_item_map.get(metric.response_key)
        if value is None or value == "":
            return None
        if isinstance(value, bool) or not isinstance(
            value, (str, int, float, Decimal)
        ):
            raise ValueError(f"{metric.response_key} must be numeric or null")
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(
                f"{metric.response_key} must be numeric or null"
            ) from exc
        if not number.is_finite():
            raise ValueError(f"{metric.response_key} must be finite")
        return number

    def map_records(
        self,
        account_id: str,
        plants: list[dict[str, str]],
        batch_result: BatchResult,
    ) -> list[dict[str, Any]]:
        target_date = self._fetched_at.astimezone(BANGKOK).date()
        configured_codes = {plant["code"] for plant in plants}
        by_code: dict[str, dict[str, Any]] = {}

        for record in batch_result.records:
            if not isinstance(record, dict):
                LOGGER.error(
                    "[huawei][%s] malformed record type=%s",
                    account_id,
                    type(record).__name__,
                )
                continue
            code = record.get("stationCode")
            if not isinstance(code, str) or not code:
                LOGGER.error(
                    "[huawei][%s] malformed record missing stationCode",
                    account_id,
                )
                continue
            try:
                record_date = collect_date(record.get("collectTime"))
            except (ValueError, OSError, OverflowError) as exc:
                LOGGER.error(
                    "[huawei][%s] malformed station station_code=%s error=%s",
                    account_id,
                    code,
                    str(exc),
                )
                continue
            if record_date != target_date:
                continue
            if code not in configured_codes:
                LOGGER.error(
                    "[huawei][%s] unexpected station response station_code=%s",
                    account_id,
                    code,
                )
                continue
            if code in by_code:
                LOGGER.error(
                    "[huawei][%s] duplicate station response station_code=%s",
                    account_id,
                    code,
                )
                continue
            by_code[code] = record

        rows: list[dict[str, Any]] = []
        for plant in plants:
            record = by_code.get(plant["code"])
            if record is None:
                LOGGER.error(
                    "[huawei][%s] missing station station_code=%s",
                    account_id,
                    plant["code"],
                )
                continue
            data_item_map = record.get("dataItemMap")
            if not isinstance(data_item_map, dict):
                LOGGER.error(
                    "[huawei][%s] malformed station station_code=%s "
                    "missing dataItemMap",
                    account_id,
                    plant["code"],
                )
                continue
            try:
                record_time = iso_collect_time(record.get("collectTime"))
                metrics = {
                    metric.column: self._parse_optional_decimal(
                        data_item_map, metric
                    )
                    for metric in METRICS
                }
            except (ValueError, OSError, OverflowError) as exc:
                LOGGER.error(
                    "[huawei][%s] malformed station station_code=%s error=%s",
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
                    "collect_time": record_time,
                }
            )
        return rows

    async def fetch_account(self, account: dict[str, Any]) -> list[dict[str, Any]]:
        account_id = account["id"]
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            client = (
                self._client_factory(session)
                if self._client_factory is not None
                else HuaweiClient(
                    session,
                    self._vendor_config["base_url"],
                    self._semaphore,
                )
            )
            try:
                await client.login(account)
                LOGGER.info("[huawei][%s] login succeeded", account_id)
            except Exception as exc:
                LOGGER.error(
                    "[huawei][%s] login failed error=%s detail=%s",
                    account_id,
                    type(exc).__name__,
                    str(exc),
                )
                return []

            batches = chunked(
                account["plants"], self._vendor_config["batch_size"]
            )
            requested_time = collect_time_ms(self._fetched_at)
            results = await asyncio.gather(
                *(
                    client.fetch_batch(batch, requested_time)
                    for batch in batches
                ),
                return_exceptions=True,
            )

        rows: list[dict[str, Any]] = []
        for batch, result in zip(batches, results, strict=True):
            codes = ",".join(plant["code"] for plant in batch)
            if isinstance(result, BaseException):
                LOGGER.error(
                    "[huawei][%s] batch failed station_codes=%s "
                    "error=%s detail=%s",
                    account_id,
                    codes,
                    type(result).__name__,
                    str(result),
                )
                continue
            batch_rows = self.map_records(account_id, batch, result)
            rows.extend(batch_rows)
            LOGGER.info(
                "[huawei][%s] batch succeeded stations=%d rows=%d",
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
                    "[huawei][%s] account failed error=%s detail=%s",
                    account["id"],
                    type(result).__name__,
                    str(result),
                )
                continue
            rows.extend(result)
        for index, row in enumerate(rows, start=1):
            row["no"] = index
        return rows


async def fetch(vendor_config: dict[str, Any], fetched_at: datetime) -> list[dict[str, Any]]:
    """Adapter contract used by collector.py."""
    semaphore = asyncio.Semaphore(vendor_config["max_concurrency"])
    adapter = HuaweiAdapter(vendor_config, fetched_at, semaphore)
    return await adapter.fetch()
