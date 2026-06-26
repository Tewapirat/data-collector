"""Public interface for the Sungrow adapter package."""

from .adapter import SungrowAdapter, chunked, fetch
from .client import SungrowAPIError, SungrowClient
from .contract import (
    POINTS,
    SCHEMA,
    BatchResult,
    DeviceType,
    PointDefinition,
    make_ps_key,
    plant_code_from_ps_key,
)

__all__ = [
    "POINTS",
    "SCHEMA",
    "BatchResult",
    "DeviceType",
    "PointDefinition",
    "SungrowAPIError",
    "SungrowAdapter",
    "SungrowClient",
    "chunked",
    "fetch",
    "make_ps_key",
    "plant_code_from_ps_key",
]
