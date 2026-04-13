# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run all tests
```bash
pytest
```

### Run tests excluding integration (no MSSQL required)
```bash
pytest -k "not integration"
```

### Run a single test file
```bash
pytest tests/test_tools.py
```

### Run a single test by name
```bash
pytest tests/test_tools.py::test_fetch_swagger_json_success
```

### Run with coverage
```bash
pytest --cov=app --cov-report=term-missing
```

### Start the app locally (requires `.env`)
```bash
uvicorn app.main:app --reload
```

### Run database migrations
```bash
alembic upgrade head
```

### Docker (production)
```bash
docker-compose up --build
```

### Docker (debug with live reload + debugpy on port 5678)
```bash
docker-compose -f docker-compose.yml -f docker-compose.debug.yml up --build
```

## Environment Variables

Copy `.env.example` to `.env`. Key variables:

| Variable | Purpose |
|----------|---------|
| `DB_HOST/PORT/NAME/USER/PASSWORD` | MSSQL connection |
| `OPENAI_API_KEY` | Required for LLM analysis steps |
| `LLM_MODEL` | Default: `gpt-5-mini` (steps 1–4 pipeline) |
| `LLM_TEMPERATURE` | Default: `0.0` |
| `LLM_ANALYSIS_MODEL` | Default: `gpt-5-mini` (steps 5–6 analysis) |
| `LLM_ANALYSIS_TEMPERATURE` | Default: `0.2` |
| `APP_HOST` | Default: `0.0.0.0` |
| `APP_PORT` | Default: `8000` |

## Architecture

SwaggerAgent is a FastAPI service that periodically fetches, parses, and stores OpenAPI/Swagger documentation from registered APIs, with LLM-powered analysis.

### Data flow

1. A **Service** (name + swagger URL) is registered via `POST /services`
2. A scan is triggered manually (`POST /services/{id}/scan`) or automatically by APScheduler
3. The **pipeline runner** (`app/agent.py`) orchestrates a 7-step workflow:
   - Step 1: `fetch_swagger_json` — tries several URL variants to retrieve the OpenAPI document
   - Step 2: `parse_swagger_document` — normalizes OpenAPI 3.x and Swagger 2.0 into a unified structure
   - Step 3: change detection — compares parsed endpoints against DB; returns `"no_changes"` early if nothing changed (skipped when `force=True`)
   - Step 4: enrich + `save_service_data` — `compute_auth_type` / `compute_auth_required` (from `app/analysis.py`) annotate each endpoint before `crud.replace_endpoints()` writes them
   - Step 5: verify via direct DB query (no LLM)
   - Step 6: `analyze_service_with_llm` — LLM generates overview, use-cases, quality score (`gpt-5-mini`)
   - Step 7: `analyze_endpoint_with_llm` — deep per-endpoint analysis for endpoints missing request/response examples; capped at 50 endpoints
4. Results are stored in three tables: **Service → Endpoint → ScanLog** (cascade on delete)
5. Markdown reports and analysis are generated on demand (`app/markdown.py`)

### Key modules

| File | Role |
|------|------|
| `app/main.py` | FastAPI app + lifespan; configures logging to `logs/swagger_agent.log` |
| `app/api.py` | 15 REST endpoints + `/health`; background scans via `BackgroundTasks` |
| `app/agent.py` | Pipeline runner; steps 1–5 pure Python, steps 6–7 LLM |
| `app/analysis.py` | `compute_auth_type` and `compute_auth_required` — deterministic auth inference from spec + heuristics |
| `app/tools.py` | 6 tools: fetch, parse, save, analyze_service, analyze_endpoint, get_service_info |
| `app/crud.py` | All DB operations; `replace_endpoints()` does delete-then-insert |
| `app/database.py` | SQLAlchemy engine, `SessionLocal`, `Base`, and `get_db` dependency |
| `app/models.py` | SQLAlchemy ORM: `Service`, `Endpoint`, `ScanLog` |
| `app/schemas.py` | Pydantic schemas with `from_attributes=True` for ORM compat |
| `app/config.py` | Pydantic-Settings; builds MSSQL ODBC connection string |

### Testing strategy

Tests use in-memory SQLite (not MSSQL). `tests/conftest.py` does several critical things at import time:

1. Stubs `pyodbc` before SQLAlchemy imports it (pyodbc not available in test env)
2. Creates a `StaticPool` SQLite engine so tables persist within a session
3. Overrides FastAPI's `get_db` dependency
4. Patches APScheduler to prevent background jobs from running

Tests marked `integration` require a live MSSQL instance and are skipped by default with `-k "not integration"`.

### Logging

- `logs/swagger_agent.log` — all application logs (stdout + file); format: `timestamp [LEVEL] logger_name: message`

All modules use `logging.getLogger(__name__)`. The root handler (both `StreamHandler` and `FileHandler`) is configured in `app/main.py` via `logging.basicConfig`.
