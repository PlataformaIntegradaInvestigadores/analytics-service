# Centinela Analytics Service

Backend of the component *Explanatory and predictive analytics for academic
decision-making* in Centinela V3. The local data foundation implements curation,
quality reports, versioned SQLite snapshots, temporal partitions, series from
provided topic assignments, historical features, reference forecasts and rolling
evaluation. It also provides read-only software/environment audits and reference
run restoration/replay. The status endpoint reports `data-foundation`.

Corpus acquisition, a deployed Data Lakehouse, fitted topic/predictive models,
XAI and frontend/identity integration remain pending. Controlled test fixtures
are explicitly synthetic and do not constitute empirical thesis results.

## Planned scope

ETL/ELT with data lineage, topic discovery, time-series construction, topic
forecasting, local/global explainability, reproducible technical evaluation
and the API consumed by `centinela-front`.

## Layout

```
app/
  api/          HTTP adapter (routes, health)
  application/  use cases
  domain/       business rules, no framework imports
  data/         local SQLite snapshots and reference runs
  schemas/      Pydantic models of the public API
  core/         settings, input limits, JSON decoding and software provenance
  audit.py      read-only inventory, manifest, schema and replay commands
tests/
```

Dependencies point inward: `api` and `data` depend on `application`/`domain`,
never the reverse. External source adapters and final analytical storage are
pending; the existing Neo4j/MongoDB services are not replaced by local SQLite.

## Run locally

Python 3.11 is the deployment and CI target (same as the other services).

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt   # Windows: .venv\Scripts\python.exe
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8006
```

Use `GET /health`, `GET /api/v1/status` and `/docs`.

Settings use the `ANALYTICS_` prefix and an optional `.env` (copy
`.env.example`). Example files contain no credentials.

## Local analytical API and evidence

The following POST operations are enabled only when
`ANALYTICS_ENVIRONMENT=local`:

```text
/api/v1/datasets/curate
/api/v1/datasets/split
/api/v1/series/build
/api/v1/forecasts/features
/api/v1/forecasts/reference
/api/v1/evaluations/backtest
```

OpenAPI describes inputs, outputs and errors. HTTP bodies and CLI input files
are limited to 8 MiB by default; HTTP limits can be configured with
`ANALYTICS_MAX_REQUEST_BYTES`. Unknown coverage remains null; complete coverage
is a caller declaration rather than an independently verified corpus property.

```bash
python -X utf8 -m app.cli series --input tests/fixtures/synthetic_series.json
python -X utf8 -m app.audit environment
python -X utf8 -m app.audit inventory
python -X utf8 -m app.audit schema --public-base-path /api/analytics
```

See [local operations and reproduction](docs/operacion-reproducible.md),
[architecture diagnosis](docs/diagnostico-arquitectura.md) and
[provided-literature review](docs/revision-literatura.md).
The dated environment/inventory JSON files in `docs/` record a specific local
inspection; their platform and dependency versions are not universal defaults.

## Container

```bash
docker network create centinela-net || true
docker compose up -d --build
```

Compose binds to `127.0.0.1:8006`, joins `centinela-net` with the alias
`analytics-service`, runs as non-root with a read-only filesystem.
Compose defaults to the `local` environment. A deployment owner must explicitly
set `ANALYTICS_ENVIRONMENT=staging` or `production` until remote analytical access
has been integrated with Centinela identity. Container/deployment verification
requires the actual shared environment.

## Gateway

Public prefix: `/api/analytics/` -> `analytics-service:8006/api/v1/`.
Health: `/api/analytics/health`. Configured in `gateway-service`.

## Quality

```bash
python -m ruff check .
python -m black --check .
python -m pytest --cov=app --cov-report=term-missing
```

Coverage (line + branch) must stay at or above 90 %. CI also validates
`docker compose config` and builds the image.

## Workflow

`feature/*` and `chore/*` -> `develop` -> `main`, via PR with 2 approvals and
code-owner review. Merging to `develop` deploys to staging; production
deploys on push to `main`.
