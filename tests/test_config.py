from pathlib import Path
import csv

import pytest

from config import ConfigError, load_config


def write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "plants.yaml"
    path.write_text(content, encoding="utf-8")
    return path


VALID_YAML = """
vendors:
  sungrow:
    batch_size: 2
    max_concurrency: 3
    accounts:
      - id: acc_1
        username: operator@example.com
        password_env: ACCOUNT_PASSWORD
        plants:
          - name: Plant One
            code: P1
"""

SUNGROW_ENV = {
    "SUNGROW_URL": "https://vendor.example/openapi/",
    "SUNGROW_APP_KEY": "app-key",
    "SUNGROW_ACCESS_KEY": "access-key",
    "SUNGROW_SYS_CODE": "sys-code",
    "ACCOUNT_PASSWORD": "secret",
}

HUAWEI_YAML = """
vendors:
  huawei:
    batch_size: 100
    max_concurrency: 3
    accounts:
      - id: greenergyz
        username: greenergyz
        system_code_env: HUAWEI_SYSTEM_CODE
        plants:
          - name: Plant One
            code: NE=1
"""

HUAWEI_ENV = {
    "HUAWEI_URL": "https://sg5.fusionsolar.huawei.com/",
    "HUAWEI_SYSTEM_CODE": "system-code",
}


def test_load_config_resolves_secret_and_url(tmp_path: Path) -> None:
    config = load_config(
        write_config(tmp_path, VALID_YAML),
        environ=SUNGROW_ENV,
    )

    vendor = config["vendors"]["sungrow"]
    assert vendor["base_url"] == "https://vendor.example/openapi"
    assert vendor["app_key"] == "app-key"
    assert vendor["access_key"] == "access-key"
    assert vendor["sys_code"] == "sys-code"
    assert vendor["accounts"][0]["password"] == "secret"


def test_missing_secret_fails_before_collection(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ACCOUNT_PASSWORD"):
        load_config(
            write_config(tmp_path, VALID_YAML),
            environ={key: value for key, value in SUNGROW_ENV.items() if key != "ACCOUNT_PASSWORD"},
        )


@pytest.mark.parametrize(
    "missing_key",
    ["SUNGROW_APP_KEY", "SUNGROW_ACCESS_KEY", "SUNGROW_SYS_CODE"],
)
def test_missing_sungrow_vendor_secret_fails(
    tmp_path: Path, missing_key: str
) -> None:
    environment = {
        key: value for key, value in SUNGROW_ENV.items() if key != missing_key
    }
    with pytest.raises(ConfigError, match=missing_key):
        load_config(write_config(tmp_path, VALID_YAML), environ=environment)


def test_load_huawei_resolves_system_code(tmp_path: Path) -> None:
    config = load_config(
        write_config(tmp_path, HUAWEI_YAML),
        environ=HUAWEI_ENV,
    )

    vendor = config["vendors"]["huawei"]
    assert vendor["base_url"] == "https://sg5.fusionsolar.huawei.com"
    assert vendor["accounts"][0]["system_code"] == "system-code"
    assert "password" not in vendor["accounts"][0]


def test_missing_huawei_system_code_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="HUAWEI_SYSTEM_CODE"):
        load_config(
            write_config(tmp_path, HUAWEI_YAML),
            environ={"HUAWEI_URL": "https://sg5.fusionsolar.huawei.com"},
        )


def test_huawei_batch_size_above_api_limit_is_rejected(tmp_path: Path) -> None:
    invalid = HUAWEI_YAML.replace("batch_size: 100", "batch_size: 101")
    with pytest.raises(ConfigError, match="must not exceed 100"):
        load_config(write_config(tmp_path, invalid), environ=HUAWEI_ENV)


def test_huawei_yaml_matches_station_datasource() -> None:
    with Path("datasource/huawei-config.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        expected = [
            (row["name"], row["station_code"]) for row in csv.DictReader(source)
        ]
    config = load_config(
        "config/plants.yaml",
        environ={
            **SUNGROW_ENV,
            "SUNGROW_ACC_001_PASSWORD": "secret",
            "HUAWEI_URL": "https://sg5.fusionsolar.huawei.com",
            "HUAWEI_ACC_001_SYSTEM_CODE": "system-code",
        },
    )
    plants = config["vendors"]["huawei"]["accounts"][0]["plants"]

    assert [(plant["name"], plant["code"]) for plant in plants] == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("batch_size", "0"),
        ("max_concurrency", "-1"),
    ],
)
def test_non_positive_vendor_limits_are_rejected(
    tmp_path: Path, field: str, value: str
) -> None:
    invalid = VALID_YAML.replace(f"{field}: {2 if field == 'batch_size' else 3}", f"{field}: {value}")
    with pytest.raises(ConfigError, match=field):
        load_config(
            write_config(tmp_path, invalid),
            environ=SUNGROW_ENV,
        )


def test_sungrow_batch_size_above_api_limit_is_rejected(tmp_path: Path) -> None:
    invalid = VALID_YAML.replace("batch_size: 2", "batch_size: 51")
    with pytest.raises(ConfigError, match="must not exceed 50"):
        load_config(write_config(tmp_path, invalid), environ=SUNGROW_ENV)


def test_duplicate_account_ids_and_cross_account_plant_codes_fail(
    tmp_path: Path,
) -> None:
    content = """
vendors:
  sungrow:
    batch_size: 10
    max_concurrency: 2
    accounts:
      - id: duplicate
        username: one@example.com
        password_env: PASSWORD_ONE
        plants:
          - {name: One, code: SAME}
      - id: duplicate
        username: two@example.com
        password_env: PASSWORD_TWO
        plants:
          - {name: Two, code: SAME}
"""
    with pytest.raises(ConfigError) as captured:
        load_config(
            write_config(tmp_path, content),
            environ={
                **SUNGROW_ENV,
                "PASSWORD_ONE": "one",
                "PASSWORD_TWO": "two",
            },
        )

    message = str(captured.value)
    assert "duplicates account ID" in message
    assert "duplicates plant code" in message


def test_empty_plant_name_and_code_are_rejected(tmp_path: Path) -> None:
    invalid = VALID_YAML.replace("name: Plant One", 'name: ""').replace(
        "code: P1", 'code: ""'
    )
    with pytest.raises(ConfigError, match="non-empty string"):
        load_config(
            write_config(tmp_path, invalid),
            environ=SUNGROW_ENV,
        )


def test_unsupported_vendor_is_rejected(tmp_path: Path) -> None:
    invalid = VALID_YAML.replace("sungrow:", "unknown_vendor:")
    with pytest.raises(ConfigError, match="unsupported"):
        load_config(
            write_config(tmp_path, invalid),
            environ={
                "UNKNOWN_VENDOR_URL": "https://vendor.example/api",
                "ACCOUNT_PASSWORD": "secret",
            },
        )
