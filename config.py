"""Configuration loading and validation for the inverter collector."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import yaml
from dotenv import load_dotenv

SUPPORTED_VENDORS = {"sungrow", "huawei"}


class ConfigError(ValueError):
    """Raised when collector configuration is invalid."""


def _required_text(value: Any, path: str, errors: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path} must be a non-empty string")
        return ""
    return value.strip()


def _positive_int(value: Any, path: str, errors: list[str]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        errors.append(f"{path} must be a positive integer")
        return 0
    return value


def load_config(
    path: str | Path = "config/plants.yaml",
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: str | Path = ".env",
) -> dict[str, Any]:
    """Load YAML and resolve all required environment-backed values."""
    if environ is None:
        load_dotenv(dotenv_path=dotenv_path)
        environment: Mapping[str, str] = os.environ
    else:
        environment = environ

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"configuration file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc

    errors: list[str] = []
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a mapping")
    vendors = raw.get("vendors")
    if not isinstance(vendors, dict) or not vendors:
        raise ConfigError("vendors must be a non-empty mapping")

    resolved: dict[str, Any] = {"vendors": {}}
    for vendor_name, vendor_raw in vendors.items():
        vendor_path = f"vendors.{vendor_name}"
        if not isinstance(vendor_name, str) or not vendor_name.strip():
            errors.append("vendor names must be non-empty strings")
            continue
        if vendor_name not in SUPPORTED_VENDORS:
            errors.append(
                f"{vendor_path} is unsupported; expected one of "
                f"{sorted(SUPPORTED_VENDORS)}"
            )
            continue
        if not isinstance(vendor_raw, dict):
            errors.append(f"{vendor_path} must be a mapping")
            continue

        batch_size = _positive_int(
            vendor_raw.get("batch_size"), f"{vendor_path}.batch_size", errors
        )
        max_concurrency = _positive_int(
            vendor_raw.get("max_concurrency"),
            f"{vendor_path}.max_concurrency",
            errors,
        )
        if vendor_name == "sungrow" and batch_size > 50:
            errors.append(f"{vendor_path}.batch_size must not exceed 50")
        if vendor_name == "huawei" and batch_size > 100:
            errors.append(f"{vendor_path}.batch_size must not exceed 100")
        accounts_raw = vendor_raw.get("accounts")
        if not isinstance(accounts_raw, list) or not accounts_raw:
            errors.append(f"{vendor_path}.accounts must be a non-empty list")
            accounts_raw = []

        account_ids: set[str] = set()
        plant_codes: set[str] = set()
        accounts: list[dict[str, Any]] = []
        for account_index, account_raw in enumerate(accounts_raw):
            account_path = f"{vendor_path}.accounts[{account_index}]"
            if not isinstance(account_raw, dict):
                errors.append(f"{account_path} must be a mapping")
                continue

            account_id = _required_text(account_raw.get("id"), f"{account_path}.id", errors)
            if account_id in account_ids:
                errors.append(f"{account_path}.id duplicates account ID {account_id!r}")
            account_ids.add(account_id)

            username = _required_text(
                account_raw.get("username"), f"{account_path}.username", errors
            )
            credential: dict[str, str]
            if vendor_name == "huawei":
                system_code_env = _required_text(
                    account_raw.get("system_code_env"),
                    f"{account_path}.system_code_env",
                    errors,
                )
                system_code = (
                    environment.get(system_code_env, "")
                    if system_code_env
                    else ""
                )
                if system_code_env and not system_code:
                    errors.append(
                        f"{account_path}.system_code_env references missing or "
                        f"empty environment variable {system_code_env!r}"
                    )
                credential = {
                    "system_code_env": system_code_env,
                    "system_code": system_code,
                }
            else:
                password_env = _required_text(
                    account_raw.get("password_env"),
                    f"{account_path}.password_env",
                    errors,
                )
                password = (
                    environment.get(password_env, "") if password_env else ""
                )
                if password_env and not password:
                    errors.append(
                        f"{account_path}.password_env references missing or empty "
                        f"environment variable {password_env!r}"
                    )
                credential = {
                    "password_env": password_env,
                    "password": password,
                }

            plants_raw = account_raw.get("plants")
            if not isinstance(plants_raw, list) or not plants_raw:
                errors.append(f"{account_path}.plants must be a non-empty list")
                plants_raw = []

            plants: list[dict[str, str]] = []
            for plant_index, plant_raw in enumerate(plants_raw):
                plant_path = f"{account_path}.plants[{plant_index}]"
                if not isinstance(plant_raw, dict):
                    errors.append(f"{plant_path} must be a mapping")
                    continue
                name = _required_text(plant_raw.get("name"), f"{plant_path}.name", errors)
                code = _required_text(plant_raw.get("code"), f"{plant_path}.code", errors)
                if code in plant_codes:
                    errors.append(
                        f"{plant_path}.code duplicates plant code {code!r} within "
                        f"vendor {vendor_name!r}"
                    )
                plant_codes.add(code)
                plants.append({"name": name, "code": code})

            accounts.append(
                {
                    "id": account_id,
                    "username": username,
                    **credential,
                    "plants": plants,
                }
            )

        url_env = f"{vendor_name.upper()}_URL"
        base_url = environment.get(url_env, "").strip()
        if not base_url:
            errors.append(f"{vendor_path} requires environment variable {url_env!r}")

        resolved_vendor = {
            "base_url": base_url.rstrip("/"),
            "batch_size": batch_size,
            "max_concurrency": max_concurrency,
            "accounts": accounts,
        }
        if vendor_name == "sungrow":
            for config_key, environment_key in (
                ("app_key", "SUNGROW_APP_KEY"),
                ("access_key", "SUNGROW_ACCESS_KEY"),
                ("sys_code", "SUNGROW_SYS_CODE"),
            ):
                value = environment.get(environment_key, "").strip()
                if not value:
                    errors.append(
                        f"{vendor_path} requires environment variable "
                        f"{environment_key!r}"
                    )
                resolved_vendor[config_key] = value

        resolved["vendors"][vendor_name] = resolved_vendor

    if errors:
        formatted = "\n".join(f"- {error}" for error in errors)
        raise ConfigError(f"invalid collector configuration:\n{formatted}")
    return resolved
