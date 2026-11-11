# GenHealth Order Intake API

A Python REST API for durable medical equipment (DME) order intake: CRUD for orders, and PDF upload that
extracts the patient's name and date of birth plus the ordering provider's name and NPI, validating
every value before it is saved.

## Stack

FastAPI, SQLAlchemy 2, Alembic, PostgreSQL (SQLite for local dev and tests), PyMuPDF, OpenAI vision
models, deployed on Render via Docker.

## Local development

```bash
uv sync
cp .env.example .env          # then fill in OPENAI_API_KEY
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Interactive docs: http://localhost:8000/docs

## Tests and lint

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Deployment

`render.yaml` is a Render Blueprint that provisions the web service (Docker) and a managed Postgres
database. Migrations run on container start (`scripts/start.sh`). Set `OPENAI_API_KEY` in the Render
dashboard; `JWT_SECRET` is generated automatically.
