# Local OM App Runbook

This runbook starts the all-in-one `app` container when the Compose file and
runtime files live in separate local directories.

## Paths

Compose directory:

```text
/Users/greenz/om-data-collector/om-docker-compose
```

Runtime directory:

```text
/Users/greenz/om-data-collector/om-data-collector-runtime
```

The Compose directory contains:

```text
docker-compose.yml
```

The runtime directory contains:

```text
/Users/greenz/om-data-collector/om-data-collector-runtime/
├── .env
├── config/
│   └── plants.yaml
├── data/
│   ├── sungrow/
│   ├── huawei/
│   └── .locks/
└── logs/
```

## Prepare Runtime Directory

Create directories if they do not exist:

```bash
mkdir -p /Users/greenz/om-data-collector/om-data-collector-runtime/config
mkdir -p /Users/greenz/om-data-collector/om-data-collector-runtime/data/sungrow
mkdir -p /Users/greenz/om-data-collector/om-data-collector-runtime/data/huawei
mkdir -p /Users/greenz/om-data-collector/om-data-collector-runtime/data/.locks
mkdir -p /Users/greenz/om-data-collector/om-data-collector-runtime/logs
```

Copy runtime files:

```bash
cp .env /Users/greenz/om-data-collector/om-data-collector-runtime/.env
cp config/plants.yaml /Users/greenz/om-data-collector/om-data-collector-runtime/config/plants.yaml
chmod 600 /Users/greenz/om-data-collector/om-data-collector-runtime/.env
```

If those files already exist in the runtime directory, verify them instead of
overwriting them:

```bash
ls -la /Users/greenz/om-data-collector/om-data-collector-runtime
ls -la /Users/greenz/om-data-collector/om-data-collector-runtime/config
grep -n "meteo:" /Users/greenz/om-data-collector/om-data-collector-runtime/config/plants.yaml | head
```

## Start App

Run Compose from the Compose directory:

```bash
cd /Users/greenz/om-data-collector/om-docker-compose

INVERTER_RUNTIME_ROOT=/Users/greenz/om-data-collector/om-data-collector-runtime \
docker compose up -d app
```

The app serves files at:

```text
http://127.0.0.1:8080/
```

## Verify

Check the container:

```bash
cd /Users/greenz/om-data-collector/om-docker-compose

INVERTER_RUNTIME_ROOT=/Users/greenz/om-data-collector/om-data-collector-runtime \
docker compose ps
```

Check supervised processes:

```bash
INVERTER_RUNTIME_ROOT=/Users/greenz/om-data-collector/om-data-collector-runtime \
docker compose exec app supervisorctl status
```

Expected:

```text
nginx                            RUNNING
supercronic                      RUNNING
```

Check the configured supercronic schedule:

```bash
INVERTER_RUNTIME_ROOT=/Users/greenz/om-data-collector/om-data-collector-runtime \
docker compose exec app cat /etc/supercronic/collector.cron
```

Expected:

```cron
0 20 * * * cd /app && python collector.py >> /app/logs/cron.log 2>&1
```

Check supercronic startup logs:

```bash
INVERTER_RUNTIME_ROOT=/Users/greenz/om-data-collector/om-data-collector-runtime \
docker compose logs --tail=100 app
```

Expected log pattern:

```text
read crontab: /etc/supercronic/collector.cron
```

Check HTTP endpoints:

```bash
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/sungrow/
curl -I http://127.0.0.1:8080/huawei/
```

## Manual Collector Run

Run one collector pass manually:

```bash
cd /Users/greenz/om-data-collector/om-docker-compose

INVERTER_RUNTIME_ROOT=/Users/greenz/om-data-collector/om-data-collector-runtime \
docker compose run --rm app python collector.py
```

Check logs:

```bash
tail -n 100 /Users/greenz/om-data-collector/om-data-collector-runtime/logs/collector.log
tail -n 100 /Users/greenz/om-data-collector/om-data-collector-runtime/logs/cron.log
```

Find the latest CSV files:

```bash
find /Users/greenz/om-data-collector/om-data-collector-runtime/data -type f -name '*.csv' | sort | tail
```

## Scheduling

The `app` container includes supercronic and runs the collector at 20:00
Asia/Bangkok. It does not run the collector when the container starts.

Do not install host cron or a systemd timer for this local all-in-one setup.

## Restart Or Stop

Restart:

```bash
cd /Users/greenz/om-data-collector/om-docker-compose

INVERTER_RUNTIME_ROOT=/Users/greenz/om-data-collector/om-data-collector-runtime \
docker compose restart app
```

Stop:

```bash
INVERTER_RUNTIME_ROOT=/Users/greenz/om-data-collector/om-data-collector-runtime \
docker compose stop app
```

## Troubleshooting

`env file .../.env not found`:

- Confirm `.env` exists at `/Users/greenz/om-data-collector/om-data-collector-runtime/.env`.
- Confirm `INVERTER_RUNTIME_ROOT` points to `/Users/greenz/om-data-collector/om-data-collector-runtime`.

Port 8080 is already allocated:

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
```

Stop the conflicting process or change the Compose port mapping.

No `daily_irradiation_wh_m2` values:

- Confirm the runtime `plants.yaml` is the version with `meteo.ps_key`.
- Check collector logs for:

```bash
grep -n "missing meteo mapping\|meteo batch failed\|meteo API failed\|malformed meteo" \
  /Users/greenz/om-data-collector/om-data-collector-runtime/logs/collector.log
```

Container is running but files are stale:

- Confirm you are looking at `http://127.0.0.1:8080/`.
- Hard refresh or clear browser cache.
- Confirm CSV files exist under `/Users/greenz/om-data-collector/om-data-collector-runtime/data`.
