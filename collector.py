"""Brand orchestration and timestamped CSV persistence."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import csv
import logging
import time
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from adapters import huawei, sungrow
from config import ConfigError, load_config

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-Unix runtimes.
    fcntl = None  # type: ignore[assignment]

BANGKOK = ZoneInfo("Asia/Bangkok")
LOGGER = logging.getLogger("collector")
ADAPTERS = {
    "sungrow": sungrow,
    "huawei": huawei,
}


@contextmanager
def locked_path(lock_path: Path, *, blocking: bool = True):
    """Hold an OS file lock for the duration of the context."""
    if fcntl is None:
        raise RuntimeError(
            "CSV file locking requires fcntl; run the collector on Linux, "
            "macOS, or inside the Docker container"
        )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        operation = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(lock_file, operation)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def configure_logging(log_path: str | Path = "logs/collector.log") -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)-5s %(message)s")

    file_handler = TimedRotatingFileHandler(
        path,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    LOGGER.addHandler(console_handler)


def append_rows(
    brand: str,
    rows: list[dict[str, Any]],
    schema: tuple[str, ...],
    fetched_at: datetime,
    *,
    data_root: str | Path = "data",
) -> Path | None:
    """Write rows to the API fetch timestamp file after validating row keys."""
    if not rows:
        return None
    expected_keys = list(schema)
    for index, row in enumerate(rows):
        if list(row.keys()) != expected_keys:
            raise ValueError(
                f"{brand} row {index} schema mismatch: "
                f"expected {expected_keys}, got {list(row.keys())}"
            )

    local_time = fetched_at.astimezone(BANGKOK)
    directory = Path(data_root) / brand / f"{local_time:%Y}" / f"{local_time:%m}"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{brand}_{local_time:%d_%H_%M_%S}.csv"
    lock_path = (
        Path(data_root)
        / ".locks"
        / brand
        / f"{local_time:%Y}"
        / f"{local_time:%m}"
        / f"{path.name}.lock"
    )

    with locked_path(lock_path):
        exists = path.exists()
        if exists:
            with path.open("r", encoding="utf-8", newline="") as existing:
                actual_header = next(csv.reader(existing), None)
            if actual_header != expected_keys:
                raise ValueError(
                    f"{brand} CSV header mismatch at {path}: "
                    f"expected {expected_keys}, got {actual_header}"
                )

        with path.open("a", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=expected_keys,
                extrasaction="raise",
            )
            if not exists:
                writer.writeheader()
            writer.writerows(rows)
    return path


async def _collect_vendor(
    brand: str,
    vendor_config: dict[str, Any],
    fetched_at: datetime,
    data_root: str | Path,
) -> None:
    adapter = ADAPTERS[brand]
    account_count = len(vendor_config["accounts"])
    plant_count = sum(len(account["plants"]) for account in vendor_config["accounts"])
    started = time.monotonic()
    LOGGER.info(
        "[%s] collection started accounts=%d plants=%d",
        brand,
        account_count,
        plant_count,
    )
    rows = await adapter.fetch(vendor_config, fetched_at)
    path = append_rows(
        brand,
        rows,
        adapter.SCHEMA,
        fetched_at,
        data_root=data_root,
    )
    duration = time.monotonic() - started
    if path is None:
        LOGGER.warning(
            "[%s] no successful rows duration=%.2fs output=skipped",
            brand,
            duration,
        )
    else:
        LOGGER.info(
            "[%s] wrote rows=%d duration=%.2fs path=%s",
            brand,
            len(rows),
            duration,
            path,
        )


async def run(
    *,
    config_path: str | Path = "config/plants.yaml",
    data_root: str | Path = "data",
) -> None:
    fetched_at = datetime.now(BANGKOK)
    config = load_config(config_path)
    tasks = []
    brands = []
    for brand, vendor_config in config["vendors"].items():
        adapter = ADAPTERS.get(brand)
        if adapter is None:
            LOGGER.error("[%s] unsupported vendor", brand)
            continue
        brands.append(brand)
        tasks.append(_collect_vendor(brand, vendor_config, fetched_at, data_root))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for brand, result in zip(brands, results, strict=True):
        if isinstance(result, BaseException):
            LOGGER.exception(
                "[%s] vendor failed error=%s",
                brand,
                type(result).__name__,
                exc_info=(type(result), result, result.__traceback__),
            )


def main() -> int:
    configure_logging()
    try:
        with locked_path(Path("logs/collector.lock"), blocking=False) as acquired:
            if not acquired:
                LOGGER.warning("collector already running; exiting")
                return 0
            asyncio.run(run())
    except ConfigError as exc:
        LOGGER.critical("configuration failed: %s", exc)
        return 2
    except Exception:
        LOGGER.exception("collector run failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
