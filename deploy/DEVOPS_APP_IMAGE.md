# DevOps App Image Deployment Runbook

This runbook deploys the all-in-one `app` image. The container runs nginx for
CSV downloads and supercronic for the scheduled collector run. Do not install
host cron, a systemd timer, the split `collector` service, or the split
`fileserver` service for this deployment mode.

## Image

Use this image by default:

```text
apiratgrz/inverter-data-collector:app-latest
```

For production, prefer an immutable release tag when available, for example:

```text
apiratgrz/inverter-data-collector:app-2026-06-28
```

## Server Layout

Use one directory for Compose and one directory for runtime data:

```text
/opt/inverter-data-collector      # docker-compose.yml only
/srv/inverter-data-collector      # persistent runtime files
```

The runtime directory must contain:

```text
/srv/inverter-data-collector/
├── .env
├── config/
│   └── plants.yaml
├── data/
│   ├── sungrow/
│   ├── huawei/
│   └── .locks/
└── logs/
```

Create the directories:

```bash
sudo mkdir -p /opt/inverter-data-collector
sudo mkdir -p /srv/inverter-data-collector/config
sudo mkdir -p /srv/inverter-data-collector/data/sungrow
sudo mkdir -p /srv/inverter-data-collector/data/huawei
sudo mkdir -p /srv/inverter-data-collector/data/.locks
sudo mkdir -p /srv/inverter-data-collector/logs
```

Copy runtime files into place:

```bash
sudo cp .env /srv/inverter-data-collector/.env
sudo cp plants.yaml /srv/inverter-data-collector/config/plants.yaml
sudo chmod 600 /srv/inverter-data-collector/.env
```

Runtime ownership must allow Docker to read `.env` and `plants.yaml`, and to
write `data`, `data/.locks`, and `logs`.

The nginx HTML, CSS, logo, nginx config, collector code, and scheduler config
are baked into the `app` image. Do not copy `nginx.conf` for this deployment
mode.

## Compose File

Place this at `/opt/inverter-data-collector/docker-compose.yml`:

```yaml
services:
  app:
    image: apiratgrz/inverter-data-collector:app-latest
    restart: unless-stopped
    env_file: ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/.env
    environment:
      TZ: Asia/Bangkok
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/config/plants.yaml:/app/config/plants.yaml:ro
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/data/sungrow:/app/data/sungrow
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/data/huawei:/app/data/huawei
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/data/.locks:/app/data/.locks
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/logs:/app/logs
```

## Pull Or Load Image

Pull from the registry:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose pull app
```

If DevOps receives the image as a tar file instead:

```bash
docker load -i inverter-data-collector-app.tar
```

Then confirm the image exists:

```bash
docker image ls 'apiratgrz/inverter-data-collector'
```

## Preflight

Validate Compose without printing expanded secrets:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose config --quiet
```

Do not paste full `docker compose config` output into tickets or chat because
Compose can expand `env_file` values.

## Start

Start the all-in-one app:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d app
```

The app exposes nginx on:

```text
http://127.0.0.1:8080/
```

Expose it to users through a trusted internal reverse proxy, VPN, or Cloudflare
Access/Tunnel. Do not expose the container port publicly without access
control.

## Scheduling

The app image includes supercronic. It runs the collector at 20:00
Asia/Bangkok and does not run the collector when the container starts.

Do not install host cron or a systemd timer for this deployment mode. Do not
also start the split `collector` scheduled job. Duplicate scheduling can create
overlapping collection attempts; the collector lock is only a guard.

## Verification

Check the container and supervised processes:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose ps
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose exec app supervisorctl status
```

Expected process status:

```text
nginx                            RUNNING
supercronic                      RUNNING
```

Check the fileserver:

```bash
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/sungrow/
curl -I http://127.0.0.1:8080/huawei/
```

Run the collector manually once through the app image:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm app python collector.py
```

Check logs and generated CSV files:

```bash
tail -n 100 /srv/inverter-data-collector/logs/collector.log
tail -n 100 /srv/inverter-data-collector/logs/cron.log
find /srv/inverter-data-collector/data -type f -name '*.csv' | sort | tail
```

Expected collector log patterns:

```text
[sungrow] collection started
[huawei] collection started
[vendor] wrote rows=... path=...
```

A vendor with zero successful rows intentionally writes no CSV for that run.
Inspect earlier account, batch, missing plant, or malformed record logs.

## Backup And Restore

Back up the runtime directory:

```bash
sudo tar -czf inverter-backup-$(date +%F).tar.gz -C /srv inverter-data-collector
```

The backup includes `.env`, `plants.yaml`, CSV files, locks, and logs. It
contains secrets and must be stored with production credential access controls.

Restore runtime and start the app:

```bash
sudo tar -xzf inverter-backup-2026-06-28.tar.gz -C /srv
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose pull app
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d app
```

## Operations

View generated files:

```bash
curl -I http://127.0.0.1:8080/
```

Restart the app:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose restart app
```

Update the image:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose pull app
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d app
```

View app logs:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose logs -f app
```

Stop the app:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose stop app
```

## Troubleshooting

`env file .../.env not found`:

- Create `/srv/inverter-data-collector/.env`.
- Or set `INVERTER_RUNTIME_ROOT` to the runtime path before running Compose.

Port 8080 is already allocated:

- Confirm the split `fileserver` service is not running.
- Check for another host process with `sudo lsof -nP -iTCP:8080 -sTCP:LISTEN`.

Collector did not run at the expected time:

- Check `docker compose logs app` for supercronic messages.
- Confirm the app container was running at 20:00 Asia/Bangkok.
- The scheduler does not backfill missed runs after downtime.

CSV not generated:

- Check `collector.log`; zero successful rows intentionally writes no file.
- Confirm runtime `plants.yaml` and `.env` are present and readable.
- Confirm `data/.locks`, `data/sungrow`, `data/huawei`, and `logs` are writable
  by Docker.

Collector overlap:

- Remove duplicate host cron/systemd schedules.
- Stop any split `collector` scheduled job.
- The process-level `logs/collector.lock` makes the second run exit cleanly,
  but duplicate scheduling is still a deployment error.
