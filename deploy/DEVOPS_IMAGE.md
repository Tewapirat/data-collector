# DevOps Image Deployment Runbook

This runbook deploys the inverter data collector from Docker Hub images. The
server does not need the full source tree. It needs only a Compose file,
runtime files, Docker access to the image registry, and one host scheduler.

## Images

Use these Docker Hub images by default:

```text
apiratgrz/inverter-data-collector:collector-latest
apiratgrz/inverter-data-collector:fileserver-latest
apiratgrz/inverter-data-collector:app-latest
```

For production, prefer immutable release tags when available, for example:

```text
apiratgrz/inverter-data-collector:collector-2026-06-26
apiratgrz/inverter-data-collector:fileserver-2026-06-26
apiratgrz/inverter-data-collector:app-2026-06-26
```

`collector-latest` and `fileserver-latest` should be used for testing or when
the team intentionally wants the newest published image. The `all-in-one`
image is an alternate deployment mode and should not be run together with host
cron or the systemd timer.

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
├── nginx.conf
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
sudo cp nginx.conf /srv/inverter-data-collector/nginx.conf
sudo chmod 600 /srv/inverter-data-collector/.env
```

Runtime ownership must allow Docker to read `.env`, `plants.yaml`, and
`nginx.conf`, and to write `data`, `data/.locks`, and `logs`.

## Compose File

Place this at `/opt/inverter-data-collector/docker-compose.yml`:

```yaml
services:
  collector:
    image: apiratgrz/inverter-data-collector:collector-latest
    profiles:
      - collector-job
    env_file: ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/.env
    volumes:
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/config/plants.yaml:/app/config/plants.yaml:ro
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/data/sungrow:/app/data/sungrow
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/data/huawei:/app/data/huawei
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/data/.locks:/app/data/.locks
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/logs:/app/logs

  fileserver:
    image: apiratgrz/inverter-data-collector:fileserver-latest
    restart: unless-stopped
    ports:
      - "127.0.0.1:8080:8080"
    volumes:
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/data/sungrow:/data/sungrow:ro
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/data/huawei:/data/huawei:ro
      - ${INVERTER_RUNTIME_ROOT:-/srv/inverter-data-collector}/nginx.conf:/etc/nginx/conf.d/default.conf:ro
```

Optional all-in-one service:

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

This service runs nginx and supercronic in one container. Supercronic runs the
collector at 20:00 Asia/Bangkok and does not run the collector at container
startup.

The fileserver HTML, CSS, and logo are baked into the `fileserver` image. Do
not mount source `fileserver/` assets on the server.

## Preflight

Validate Compose without printing expanded secrets:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose --profile collector-job config --quiet
```

Do not paste full `docker compose config` output into tickets or chat because
Compose can expand `env_file` values.

## Pull And Start

Pull images and start the long-lived fileserver:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose pull
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d fileserver
```

Run the collector once:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector
```

The collector is a one-shot job. It starts a temporary container, collects one
batch, writes CSV/log files into the runtime directory, then exits.

## Scheduling

Install exactly one scheduler: host cron or a systemd timer. Do not run cron
inside the collector container.

If using the optional `app` all-in-one service, do not install host cron or the
systemd timer. The `app` container already includes the 20:00 Asia/Bangkok
schedule through supercronic.

Production schedule: 20:00 Asia/Bangkok, after iSolarCloud and
FusionSolar plant values are expected to be stable. On a UTC server, that is
13:00 UTC.

Cron example:

```cron
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

0 13 * * * cd /opt/inverter-data-collector && INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector >> /srv/inverter-data-collector/logs/cron.log 2>&1
```

If Docker is not available as `docker` in cron, replace it with the absolute
path from `command -v docker`.

Systemd service example:

```ini
[Unit]
Description=Inverter data collector one-shot job
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=/opt/inverter-data-collector
Environment=INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector
ExecStart=/usr/bin/docker compose run --rm collector
StandardOutput=append:/srv/inverter-data-collector/logs/cron.log
StandardError=append:/srv/inverter-data-collector/logs/cron.log
```

Systemd timer example:

```ini
[Unit]
Description=Run inverter data collector at 20:00 Asia/Bangkok

[Timer]
OnCalendar=*-*-* 13:00:00
Persistent=true
Unit=inverter-collector.service

[Install]
WantedBy=timers.target
```

Install the timer:

```bash
sudo cp inverter-collector.service /etc/systemd/system/
sudo cp inverter-collector.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now inverter-collector.timer
systemctl list-timers inverter-collector.timer
```

## Network Access

The fileserver binds to local host only:

```text
127.0.0.1:8080
```

Expose it to users through a trusted internal reverse proxy, VPN, or Cloudflare
Access/Tunnel. Do not expose the container port publicly without access control.

## Verification

Check fileserver:

```bash
curl -I http://127.0.0.1:8080/
docker compose ps
```

Check collector logs and generated CSV files:

```bash
tail -n 100 /srv/inverter-data-collector/logs/collector.log
tail -n 100 /srv/inverter-data-collector/logs/cron.log
find /srv/inverter-data-collector/data -type f -name '*.csv' | sort | tail
```

For systemd scheduling:

```bash
systemctl status inverter-collector.timer
systemctl status inverter-collector.service
journalctl -u inverter-collector.service -n 100 --no-pager
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

The backup includes `.env`, `plants.yaml`, `nginx.conf`, CSV files, locks, and
logs. It contains secrets and must be stored with production credential access
controls.

Restore runtime and pull images:

```bash
sudo tar -xzf inverter-backup-2026-06-26.tar.gz -C /srv
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose pull
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d fileserver
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector
```

## Upgrade And Rollback

To upgrade, edit image tags in `/opt/inverter-data-collector/docker-compose.yml`,
then pull and restart fileserver:

```bash
cd /opt/inverter-data-collector
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose pull
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose up -d fileserver
```

The next scheduled collector run uses the new collector image. To test
immediately, run:

```bash
INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector docker compose run --rm collector
```

To roll back, restore the previous image tags in `docker-compose.yml`, then run
`docker compose pull` and restart fileserver again.

## Troubleshooting

`env file .../.env not found`:

- Confirm `/srv/inverter-data-collector/.env` exists.
- Confirm the cron/systemd command includes `INVERTER_RUNTIME_ROOT=/srv/inverter-data-collector`.

CSV not generated:

- Check `collector.log`; zero successful rows intentionally writes no file.
- Confirm `.env` values and `plants.yaml` account ownership are current.

Collector overlap:

- The collector has a process-level lock, but duplicate cron/systemd entries
  should still be removed. The lock is a guard, not the scheduler design.

Rate limiting:

- Reduce `max_concurrency` in `plants.yaml` first.
- Reduce `batch_size` only if the vendor batch limit changed or responses are
  unstable.
