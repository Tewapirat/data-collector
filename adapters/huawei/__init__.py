"""Public interface for the Huawei adapter package."""

from .adapter import (
    HuaweiAdapter,
    chunked,
    collect_time_ms,
    fetch,
    iso_collect_time,
)
from .client import HuaweiAPIError, HuaweiClient
from .contract import (
    METRICS,
    SCHEMA,
    BatchResult,
    MetricDefinition,
)

__all__ = [
    "METRICS",
    "SCHEMA",
    "BatchResult",
    "HuaweiAPIError",
    "HuaweiAdapter",
    "HuaweiClient",
    "MetricDefinition",
    "chunked",
    "collect_time_ms",
    "fetch",
    "iso_collect_time",
]
