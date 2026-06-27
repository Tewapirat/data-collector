# Inverter API Collector

Internal PoC that logs into Sungrow and Huawei vendor accounts, fetches
account-scoped plant batches concurrently, and writes successful records to
timestamped CSV files served by nginx.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python collector.py
```

If the project directory is moved after creating `.venv`, recreate the virtual
environment so console-script shebangs point at the current path.

CSV file locking uses Unix `fcntl`; run the collector on Linux, macOS, or inside
the provided Docker container. Output files are written under:

```text
data/{vendor}/YYYY/MM/{vendor}_DD_HH_MM_SS.csv
```

Each collector run uses one Asia/Bangkok timestamp for both vendors. A vendor
that returns no successful rows does not create or modify a CSV file.

Sungrow uses the iSolarCloud OpenAPI base URL and requires these environment
variables:

```dotenv
SUNGROW_URL=https://gateway.isolarcloud.com.hk/openapi
SUNGROW_APP_KEY=
SUNGROW_ACCESS_KEY=
SUNGROW_SYS_CODE=
SUNGROW_ACC_001_PASSWORD=
```

The Sungrow adapter requests plant device type `11` with point ID `83022`
(daily yield in Wh), then requests meteo device type `5` with point ID `2001`
(daily horizontal irradiation in Wh/m²) using optional per-plant `meteo.ps_key`
entries in `config/plants.yaml`. It writes both the collector timestamp and the
Asia/Bangkok device timestamp.

Sungrow implementation is split by responsibility:

```text
adapters/sungrow/
├── contract.py  # API constants, point definitions, schema, and PS key helpers
├── client.py    # HTTP requests and API envelope validation
├── adapter.py   # account orchestration and row mapping
└── __init__.py  # stable public interface
```

Huawei uses the FusionSolar Northbound API and requires:

```dotenv
HUAWEI_URL=https://sg5.fusionsolar.huawei.com
HUAWEI_ACC_001_SYSTEM_CODE=
```

Each Huawei account uses an isolated HTTP session. The login response's
`XSRF-TOKEN` cookie is sent as the `XSRF-TOKEN` header for station KPI
requests. The Huawei station list in `config/plants.yaml` is mirrored from
`datasource/huawei-config.csv`.

## Tests

```bash
pytest
```

## Deployment

The production model separates code from runtime files and runs the collector
as a one-shot Docker Compose job. The nginx file server is the only long-lived
container. Fileserver HTML, CSS, and logo assets are baked into the fileserver
image; runtime backup contains only data, config, secrets, and logs.

```bash
sudo mkdir -p /srv/inverter-data-collector/{config,data/sungrow,data/huawei,data/.locks,logs}
sudo cp .env /srv/inverter-data-collector/.env
sudo cp config/plants.yaml /srv/inverter-data-collector/config/plants.yaml
sudo cp nginx.conf /srv/inverter-data-collector/nginx.conf
sudo chmod 600 /srv/inverter-data-collector/.env

INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d --build fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector
```

CSV files are served at `http://localhost:8080/`. Restrict port 8080 to the
trusted internal network in the deployment environment.

See [deploy/DEVOPS_IMAGE.md](deploy/DEVOPS_IMAGE.md) for Docker Hub image deployment,
[deploy/DEVOPS.md](deploy/DEVOPS.md) for source-based deployment, and
[deploy/PRODUCTION_READINESS.md](deploy/PRODUCTION_READINESS.md) for the current
readiness checklist.
