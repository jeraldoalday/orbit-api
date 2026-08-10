# Orbit API

Multi-tenant project & task management backend.

## Stack

- FastAPI
- SQLAlchemy 2.0 + Alembic
- Pydantic v2
- Postgres (Supabase)
- Pytest

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env  # fill in DATABASE_URL and JWT_SECRET_KEY

uvicorn app.main:app --reload
```

## Tests

```bash
pytest
```

## Project layout

```
app/
  core/       # settings, security
  db/         # engine, session, declarative base
  models/     # SQLAlchemy ORM models
  schemas/    # Pydantic request/response schemas
  api/        # FastAPI routers
  services/   # business logic
tests/
alembic/      # migrations
```
