# Centinela Analytics Service

Backend of the component *Explanatory and predictive analytics for academic
decision-making* in Centinela V3. This increment is a bootstrap: runtime
health, service metadata and OpenAPI. ETL, topic discovery, time series,
forecasting and explainability are pending under their backlog tasks.

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
  data/         adapters to search-service / search-bff-service / storage
  schemas/      Pydantic models of the public API
  core/         settings and composition
tests/
```

Dependencies point inward: `api` and `data` depend on `application`/`domain`,
never the reverse. Empty layers are placeholders, not implemented features.

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

## Container

```bash
docker network create centinela-net || true
docker compose up -d --build
```

Compose binds to `127.0.0.1:8006`, joins `centinela-net` with the alias
`analytics-service`, runs as non-root with a read-only filesystem.

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
