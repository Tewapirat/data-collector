# AGENTS.md — Inverter API Collector

> PoC phase. Internal use only.  
> Design principle: **flat over layered, explicit over implicit, fail loudly.**

## Overview

This service collects raw plant data from two inverter vendor APIs on a fixed
schedule. Each vendor may have multiple accounts, and each account owns a
distinct set of plants. The service logs in once per account, fetches that
account's plants through batch API requests, and appends successful rows to one
daily CSV file per brand.

The generated files are exposed to internal users through an nginx file server.
This PoC intentionally uses no database, web application, queue, or distributed
job system.

## Repository Structure

```text
inverter-data-collector/
├── collector.py          # Brand orchestration and CSV writing
├── config.py             # Load and validate YAML, environment, and settings
├── config/
│   └── plants.yaml       # Vendor/account/plant hierarchy; no secrets
├── adapters/
│   ├── __init__.py
│   ├── inverter_a.py     # Account login, batching, and Vendor A mapping
│   └── inverter_b.py     # Account login, batching, and Vendor B mapping
├── data/
│   ├── inverter_a/       # inverter_a_YYYY-MM-DD.csv
│   └── inverter_b/       # inverter_b_YYYY-MM-DD.csv
├── logs/
│   └── collector.log
├── docker-compose.yml
├── Dockerfile
├── crontab
├── nginx.conf
├── .env                  # Secrets; never commit
├── .env.example
└── requirements.txt
```

## Technology Choices

| Component | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Native `asyncio` support |
| HTTP | `aiohttp` | Lightweight asynchronous requests |
| Plant config | YAML | Represents vendor/account/plant ownership clearly |
| Secrets | Environment variables | Keeps credentials out of source and YAML |
| Scheduling | cron | Stable and has no idle application process |
| Storage | Daily CSV files | Simple, portable, and Excel-compatible |
| File serving | nginx autoindex | No custom web application required |
| Packaging | Docker Compose | Repeatable two-container deployment |

## Configuration Model

`config/plants.yaml` is the source of truth for account and plant ownership.
Vendor API URLs and account secrets remain in `.env`.

```yaml
vendors:
  inverter_a:
    batch_size: 50
    max_concurrency: 5
    accounts:
      - id: acc_001
        username: user_a@company.com
        password_env: INVERTER_A_ACC_001_PASSWORD
        plants:
          - name: "Factory A"
            code: PLT001
          - name: "Factory B"
            code: PLT002

      - id: acc_002
        username: user_b@company.com
        password_env: INVERTER_A_ACC_002_PASSWORD
        plants:
          - name: "Factory C"
            code: PLT003

  inverter_b:
    batch_size: 100
    max_concurrency: 3
    accounts:
      - id: acc_003
        username: user_c@company.com
        password_env: INVERTER_B_ACC_003_PASSWORD
        plants:
          - name: "Factory D"
            code: PLT004
```

Example `.env` entries:

```dotenv
INVERTER_A_URL=https://vendor-a.example/api
INVERTER_B_URL=https://vendor-b.example/api
INVERTER_A_ACC_001_PASSWORD=
INVERTER_A_ACC_002_PASSWORD=
INVERTER_B_ACC_003_PASSWORD=
```

Do not put passwords, tokens, API keys, or cookies in `plants.yaml`.

### Configuration Invariants

The configuration loader must validate all configuration before making an API
request:

- Every vendor has a positive `batch_size` and `max_concurrency`.
- Account IDs are unique within a vendor.
- Every account has a username, a resolvable secret environment variable, and
  at least one plant.
- A plant belongs to exactly one account.
- `plant_code` is unique across all accounts within the same vendor.
- Plant names and codes are non-empty.

Invalid configuration must terminate the run with a clear error. Never silently
drop invalid accounts or plants.

## Architecture and Responsibilities

```text
cron
  |
  v
collector.py
  |-- concurrently call inverter_a.fetch(vendor_config)
  |-- concurrently call inverter_b.fetch(vendor_config)
  |
  +--> adapter
         |-- login accounts concurrently
         |-- reuse one token per account for the current run
         |-- chunk that account's plants by batch_size
         |-- fetch batches with bounded concurrency
         |-- map responses by plant_code
         +-- return successful rows
  |
  +--> append once per brand to data/{brand}/{brand}_YYYY-MM-DD.csv
```

### `collector.py`

The collector owns brand-level orchestration and persistence:

- Capture one run timestamp.
- Run vendor adapters concurrently with failure isolation.
- Receive complete successful rows from each adapter.
- Append rows once per brand per run.
- Log row counts, failures, duration, and output paths.
- Skip the write when an adapter returns no successful rows.

The collector must not know how accounts authenticate, how vendor payloads are
formed, how batches are split, or how vendor responses are parsed.

### Vendor Adapters

Each adapter owns all API-specific behavior:

- Log in separately for every configured account.
- Reuse the resulting account token for all batches belonging to that account
  during the current collection run.
- Never put plants from different accounts in the same batch.
- Send all plants in one request when their count is at most `batch_size`.
- Split larger plant lists into account-scoped chunks.
- Execute account and batch work concurrently, bounded by the vendor's shared
  `max_concurrency` semaphore.
- Match response items to configured plants using `plant_code` or the vendor's
  equivalent stable identifier. Never match by response position.
- Convert successful vendor records into that brand's stable CSV schema.
- Log and omit failed batches, missing plants, malformed records, and failed
  account logins without blocking other accounts or vendors.

For example, if `inverter_a` has one account with 10 plants and another with 5,
and `batch_size >= 10`, the adapter performs two login requests and two data
requests: one 10-plant batch and one 5-plant batch.

## Adapter Contract

Each adapter exposes one brand-level entry point:

```python
async def fetch(vendor_config: dict, fetched_at: datetime) -> list[dict]:
    """Return successful rows for all configured accounts and plants."""
```

Rows must include the configured plant identity followed by a stable set of
brand-specific metrics:

```python
{
    "plant_name": "Factory A",
    "plant_code": "PLT001",
    "parameter_1": 123.4,
    "parameter_2": 56.7,
}
```

Plant names come from YAML. API identifiers are used to match responses, not to
silently rename configured plants. All rows returned by one adapter must have
the same keys and key order. Do not force different vendors into one normalized
metric schema.

Suggested internal flow:

```python
async def fetch_account(session, account, vendor_config, fetched_at):
    token = await login(session, account)
    batches = chunked(account["plants"], vendor_config["batch_size"])
    results = await gather_bounded_batch_requests(
        session=session,
        token=token,
        batches=batches,
        limit=vendor_config["max_concurrency"],
    )
    return map_successful_rows(account["plants"], results, fetched_at)
```

## Concurrency and Failure Isolation

Use `asyncio.gather(..., return_exceptions=True)` at vendor and account
boundaries. Handle batch exceptions explicitly so one failed request does not
discard successful batches.

The concurrency semaphore is shared across all accounts of one vendor. This
prevents a large account count from multiplying the effective API concurrency.
Do not create an independent full-size semaphore for every account.

Failure behavior:

- **Vendor failure:** log it and allow other vendors to finish.
- **Account login failure:** log the account ID and omit all its plants.
- **Batch failure:** log the account ID and affected plant codes; retain other
  successful batches.
- **Plant missing from a successful response:** log it as missing/no-data and
  omit its row.
- **Malformed plant response:** log a controlled summary and omit its row.
- **No successful rows for a brand:** do not create, truncate, or modify its CSV.

Never log passwords, tokens, cookies, authorization headers, complete
authentication responses, or full response bodies.

## CSV File Convention

- **Path:** `data/{brand}/{brand}_YYYY-MM-DD.csv`
- **Mode:** append; all runs on the same local date use the same file.
- **Header:** write once when creating the file.
- **Encoding:** UTF-8.
- **Columns:** `plant_name,plant_code,<brand-specific metrics>`.
- **Write ownership:** only `collector.py` writes files. Async adapter tasks
  return rows and never write directly.

Use the configured `Asia/Bangkok` timezone to select the daily filename. Before
appending, verify that the existing header exactly matches the adapter's
declared schema. Fail loudly on schema drift instead of corrupting the file.

## Logging

Every run must record vendor, account/batch context where applicable, row count,
duration, and output path. Use account IDs and plant codes in diagnostics, but
do not log usernames unless operationally required.

```text
2026-06-23 07:00:00 INFO  [inverter_a] collection started accounts=2 plants=15
2026-06-23 07:00:01 INFO  [inverter_a][acc_001] login succeeded
2026-06-23 07:00:02 INFO  [inverter_a][acc_001] batch succeeded plants=10 rows=10
2026-06-23 07:00:02 ERROR [inverter_a][acc_002] missing plant plant_code=PLT003
2026-06-23 07:00:02 INFO  [inverter_a] wrote rows=14 path=data/inverter_a/inverter_a_2026-06-23.csv
```

Rotate logs daily and retain them for 30 days.

## Scheduling

Keep the existing PoC schedule: 07:00, 12:00, and 17:00 Asia/Bangkok. The
container cron uses UTC equivalents:

```cron
0 0,5,10 * * * cd /app && python collector.py >> /app/logs/cron.log 2>&1
```

Do not duplicate scheduling logic inside adapters.

## Docker Deployment

Use two containers sharing host-mounted data:

- `collector`: Python application plus cron, with read-only plant configuration
  and read-write data/log mounts.
- `fileserver`: nginx autoindex with read-only access to generated data.

```yaml
services:
  collector:
    build: .
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ./logs:/app/logs

  fileserver:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data:ro
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - collector
```

Never copy `.env` into the image. Keep nginx restricted to trusted internal
networks for the PoC.

## Development and Verification

Install the minimal dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install aiohttp python-dotenv PyYAML
cp .env.example .env
python collector.py
```

At minimum, tests should cover:

- YAML loading and required environment-secret resolution.
- Duplicate account IDs and duplicate plant codes across accounts.
- Invalid `batch_size` and `max_concurrency`.
- One request when an account's plant count is within `batch_size`.
- Correct chunking when the plant count exceeds `batch_size`.
- No batch containing plants from multiple accounts.
- Out-of-order, partial, and malformed batch responses.
- Response mapping by plant code rather than array position.
- Account login, batch, plant, and vendor failure isolation.
- Shared per-vendor concurrency limits.
- Stable CSV column order, append behavior, and header mismatch detection.
- No file modification when a brand has no successful rows.

Use mocked HTTP responses. Automated tests must never call production vendor
APIs.

## Runbook

| Situation | Action |
|---|---|
| CSV not generated | Inspect `logs/collector.log`; a brand with zero successful rows intentionally writes nothing |
| Account login fails | Verify its `password_env` name in YAML and value in `.env` |
| Plant is missing | Verify ownership and `plant_code`, then inspect the vendor response mapping |
| Rate limiting occurs | Reduce `max_concurrency` or `batch_size` for that vendor |
| API batch limit changes | Update `batch_size` in YAML and rerun validation |
| API endpoint changes | Update the vendor URL in `.env` |
| Collector container stops | Run `docker compose restart collector` |
| Code or dependency changes | Run `docker compose up -d --build` |
| View live logs | Run `docker compose logs -f collector` |

## Design Decisions

| Decision | Chosen approach | Reason |
|---|---|---|
| Plant configuration | YAML hierarchy | Expresses account ownership without repeated flat fields |
| Secret storage | Environment variables referenced by YAML | Keeps credentials out of committed configuration |
| API requests | Account-scoped batch calls | Uses vendor batch capability and preserves token ownership |
| Concurrency | Bounded async account/batch work | Improves throughput without uncontrolled request volume |
| Response matching | Stable plant code | API order and completeness are not guaranteed |
| Persistence | One append-only daily CSV per brand | Simple internal PoC storage and download |
| Failure policy | Log and omit failed/missing plants | Preserves successful data without inventing metric rows |
| Scheduling | cron | Stable and operationally simple |
| File access | nginx autoindex | Avoids a custom web application |

## What Not to Add in the PoC

- Do not add a database, message queue, or distributed worker system.
- Do not build a custom web UI or API.
- Do not mix plants from different accounts in a request.
- Do not issue one request per plant when the vendor supports batching.
- Do not let adapters write CSV files.
- Do not store credentials in source code or YAML.
- Do not add Docker Swarm or Kubernetes for a single-server deployment.
