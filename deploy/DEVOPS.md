# DevOps Handoff

This runbook deploys the collector as a one-shot Docker Compose job and nginx
as the only long-lived container. Do not run cron inside the collector
container. For Docker Hub image deployment without a source checkout, use
`deploy/DEVOPS_IMAGE.md` and `deploy/docker-compose.images.yml`.

## Runtime Layout

Keep code and runtime files separate:

```text
/opt/inverter-data-collector      # repository checkout
/srv/inverter-data-collector      # persistent runtime files
```

Prepare the runtime tree:

```bash
sudo mkdir -p /srv/inverter-data-collector/config
sudo mkdir -p /srv/inverter-data-collector/data/sungrow
sudo mkdir -p /srv/inverter-data-collector/data/huawei
sudo mkdir -p /srv/inverter-data-collector/data/.locks
sudo mkdir -p /srv/inverter-data-collector/logs
sudo cp .env /srv/inverter-data-collector/.env
sudo cp config/plants.yaml /srv/inverter-data-collector/config/plants.yaml
sudo cp nginx.conf /srv/inverter-data-collector/nginx.conf
sudo chmod 600 /srv/inverter-data-collector/.env
```

Runtime ownership must allow Docker to read `.env` and `plants.yaml`, and to
write `data`, `data/.locks`, and `logs`.

The fileserver HTML, CSS, and logo are baked into the fileserver image from the
repository's `fileserver/` directory. They are application release assets, not
runtime files, so they are not included in the runtime backup.

The collector writes CSV files here:

```text
/srv/inverter-data-collector/data/{sungrow,huawei}/YYYY/MM/{vendor}_DD_HH_MM_SS.csv
```

The timestamp is Asia/Bangkok. A vendor with zero successful rows does not
write a CSV for that run.

## Preflight

Validate Compose without printing expanded secrets:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose --profile collector-job config --quiet
```

Do not paste full `docker compose config` output into tickets or chat because
Compose expands `env_file` values.

## Services

Build the collector and fileserver images, then start the file server:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose build collector fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d --build fileserver
```

Run the collector once:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector
```

Schedule the collector from host cron using `deploy/inverter-collector.cron`,
or from systemd using `deploy/inverter-collector.service` and
`deploy/inverter-collector.timer`. Install exactly one scheduler. The one-shot
compose command receives the configured `env_file` directly.

## Optional All-In-One Container

The `app` service is an alternate deployment mode that keeps the existing
collector and fileserver services intact. It runs nginx and supercronic in one
long-lived container, and supercronic runs `python collector.py` at 20:00
Asia/Bangkok. The collector is not run when the container starts.

Build and start it:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose build app
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d app
```

The all-in-one fileserver is exposed at:

```text
http://127.0.0.1:8080/
```

Run the collector manually through the all-in-one image:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm app python collector.py
```

Before relying on the all-in-one schedule, disable host cron or the systemd
timer. Do not run host scheduling and the all-in-one scheduler at the same
time; the collector lock is a guard, not the primary scheduling design.

Check the supervised processes:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose exec app supervisorctl status
```

Rollback to the split deployment:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose stop app
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector
```

## Scheduling

The production schedule is 20:00 Asia/Bangkok, after iSolarCloud and
FusionSolar plant values are expected to be stable. On a UTC server, install:

```bash
sudo crontab deploy/inverter-collector.cron
sudo crontab -l
```

If the server timezone is not UTC, convert the schedule before installing the
cron entry. Keep the cron command on one line and keep the
`INVERTER_RUNTIME_ROOT` assignment in the entry.

The cron file includes a conservative `PATH`. If Docker is installed somewhere
else, replace `docker` with the absolute path from `command -v docker`.

Systemd alternative:

```bash
sudo cp deploy/inverter-collector.service /etc/systemd/system/
sudo cp deploy/inverter-collector.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now inverter-collector.timer
systemctl list-timers inverter-collector.timer
```

If Docker is not `/usr/bin/docker`, update `ExecStart` before installing the
service file. Do not install both cron and the systemd timer.

Local macOS testing uses `deploy/inverter-collector.local.cron`, currently
scheduled every 30 minutes:

```bash
crontab deploy/inverter-collector.local.cron
crontab -l
```

The local paths are:

```text
/Users/greenz/inverter-data-collector
/Users/greenz/inverter-data-collector-runtime
```

Avoid placing the local project or runtime under `Documents` because macOS
privacy controls can block cron from reading those paths.

## Verification

After a manual run or scheduled run:

```bash
tail -n 100 /srv/inverter-data-collector/logs/collector.log
tail -n 100 /srv/inverter-data-collector/logs/cron.log
find /srv/inverter-data-collector/data -type f -name '*.csv' | sort | tail
docker compose ps
```

For systemd scheduling, also check:

```bash
systemctl status inverter-collector.timer
systemctl status inverter-collector.service
journalctl -u inverter-collector.service -n 100 --no-pager
```

Expected log patterns:

```text
[sungrow] collection started
[huawei] collection started
[vendor] wrote rows=... path=...
```

If a vendor logs `no successful rows`, no CSV is written for that vendor for
that run. Inspect the preceding account, batch, missing plant, or malformed
record logs.

## Backup And Restore

Back up the whole runtime directory. This includes `.env`, `plants.yaml`,
`nginx.conf`, CSV data, locks, and logs. It does not include fileserver HTML,
CSS, or logo assets because those are baked into the fileserver image from the
code release.

```bash
sudo tar -czf inverter-backup-$(date +%F).tar.gz -C /srv inverter-data-collector
```

Restore:

```bash
sudo tar -xzf inverter-backup-2026-06-24.tar.gz -C /srv
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose build collector fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d --build fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector
```

The backup contains secrets in `.env`; store it with the same access controls
as production credentials.

## Operations

View generated files:

```bash
curl -I http://127.0.0.1:8080/
```

Restart only the fileserver:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose restart fileserver
```

Rebuild after code or dependency changes:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose build collector fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d --build fileserver
```

Disable scheduling:

```bash
sudo crontab -l
sudo crontab -r
```

Use `crontab -r` only when the deployment user or root crontab contains no
other jobs that must be preserved.

## Troubleshooting

CSV not generated:

- Check `collector.log`; zero successful rows intentionally writes no file.
- Confirm runtime `plants.yaml` and `.env` are mounted from the same
  `INVERTER_RUNTIME_ROOT`.

`env file .../.env not found`:

- Create the runtime `.env`.
- Or set `INVERTER_RUNTIME_ROOT` to the local runtime path before running
  Compose.

Collector overlap:

- The process-level `logs/collector.lock` makes the second run exit cleanly.
- Remove duplicate cron/systemd entries; the lock is a guard, not the primary
  scheduler design.

Huawei missing station rows:

- Confirm station codes in `plants.yaml` match the Huawei account.
- Check whether current-day daily KPI data is available at the requested time.
- Inspect logs around `collectTime` and missing station messages.

Rate limiting:

- Reduce `max_concurrency` first.
- Then reduce `batch_size` if the vendor batch limit changed or responses are
  unstable.
