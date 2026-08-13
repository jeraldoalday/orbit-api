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

## Roadmap

14-day feature plan for this service.

### Done

- **Day 1:** Scaffolding, config, DB/Alembic wiring, User/Org/Membership models, JWT auth (register/login/refresh/me), health check, CI, auth tests.
- **Day 2:** Org-scoped auth deps, organizations & memberships routers, Project/Task models + migration, project/task schemas/services/routers, flow tests.
- **Day 3:** Task comments, activity timeline, admin-gated task delete, org invitations (create/accept/revoke), invitation privilege-escalation fixes, centralized role ranking, atomic activity logging, guard tests.

### Upcoming

| Day | Feature |
|---|---|
| 4 | Task list filtering, sorting, and pagination (by status, assignee, project) |
| 5 | Task due dates + priority field, with filtering/sorting on them |
| 6 | Labels/tags — many-to-many model, attach/detach, filter tasks by label |
| 7 | Project-level membership — invite specific users to a project, scope permissions below org role |
| 8 | In-app notifications (assignment, comment, mention) — model + list/mark-read endpoints |
| 9 | Full-text search across tasks/projects (Postgres tsvector) |
| 10 | API hardening — rate limiting, stricter pagination limits, input validation pass |
| 11 | File attachments on tasks (upload to object storage, metadata model) |
| 12 | Webhooks — org-level subscriptions for task events, signed delivery worker |
| 13 | Audit log + soft delete/restore for projects and tasks |
| 14 | Polish & ops — OpenAPI cleanup, structured logging, request-ID middleware, Dockerfile, final test pass |

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
