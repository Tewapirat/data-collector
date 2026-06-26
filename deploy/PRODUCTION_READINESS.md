# Production Readiness Review

Last reviewed: 2026-06-25

## Current Readiness

This project is ready for a controlled internal PoC deployment on a single
host, provided the runtime directory is backed up and scheduling is installed
on the host. For Docker Hub image deployment, use `deploy/DEVOPS_IMAGE.md`
and `deploy/docker-compose.images.yml`. It is not a multi-tenant,
internet-facing, or high-availability service.

## Ready

- Configuration fails before API calls when required YAML, vendor URLs, or
  secret-backed fields are missing.
- Sungrow and Huawei adapters isolate account, batch, plant, and vendor
  failures; successful rows from other accounts and vendors are retained.
- API responses are matched by configured plant or station code, not by array
  position.
- CSV schema order is declared by each adapter and validated before write.
- CSV writes use `fcntl` locks and a process-level collector lock to avoid
  overlapping local runs.
- Logs rotate daily and retain 30 files through `TimedRotatingFileHandler`.
- Docker Compose keeps `.env`, runtime config, logs, locks, and CSV files
  outside the image.
- The fileserver HTML, CSS, and logo are baked into the fileserver image, so
  runtime backup stays limited to data, config, secrets, and logs.
- The fileserver mounts data read-only and binds nginx to `127.0.0.1:8080` by
  default.
- Live API tests are opt-in through `RUN_LIVE_TESTS=1`; normal automated tests
  do not call vendor APIs.

## Must Be True Before Production Cron Is Enabled

- `/srv/inverter-data-collector/.env` exists, is owned by the deployment user
  or root, and is mode `600`.
- `/srv/inverter-data-collector/config/plants.yaml` is current and contains no
  passwords, tokens, cookies, or API keys.
- `/srv/inverter-data-collector/data/.locks`, `data/sungrow`, `data/huawei`,
  and `logs` exist and are writable by the Docker process.
- `INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose --profile collector-job config --quiet`
  passes from `/opt/inverter-data-collector`.
- A one-shot collector run exits `0` and either writes expected CSV files or
  logs a clear no-data reason for each vendor.
- `docker compose up -d --build fileserver` is running and port `8080` is
  reachable only from trusted internal clients or a local reverse proxy.
- Host cron or a systemd timer is installed exactly once.
- The scheduler uses the correct Docker executable path for the host.
- Runtime backup has been tested by restoring to a temporary directory.

Do not paste full `docker compose config` output into tickets or chat. Compose
expands `env_file` values and can print vendor secrets.

## Known Residual Risks

- There is no database, retry queue, or backfill workflow. A failed scheduled
  run is represented only by logs and missing CSV output.
- Vendor API contract changes can cause rows to be omitted until mapping code
  is updated.
- Huawei current-day daily KPI data may not be available at the collection
  time; this appears as successful batches with missing station rows.
- The service assumes one host-local runtime directory. Network filesystems may
  change lock semantics and should be avoided unless tested.
- `docker compose run --rm collector` creates short-lived containers. Disk
  cleanup for old images and stopped containers remains an operator task.
- nginx `autoindex` intentionally exposes generated CSV names and directory
  structure to anyone who can reach the fileserver.

## Operational Acceptance Checks

Run these after initial deployment and after material changes:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose --profile collector-job config --quiet
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose build collector fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d --build fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector
tail -n 100 /srv/inverter-data-collector/logs/collector.log
find /srv/inverter-data-collector/data -type f -name '*.csv' | sort | tail
```

For local macOS testing, substitute:

```bash
export INVERTER_RUNTIME_ROOT=/Users/greenz/inverter-data-collector-runtime
```

## Go/No-Go

Go for internal PoC if all "Must Be True" checks pass.

No-go if the collector cannot obtain the runtime `.env`, any mounted runtime
directory is unwritable, nginx is exposed beyond the trusted network, or
scheduled runs can overlap from multiple cron/systemd entries.
