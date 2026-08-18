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
- **Day 4:** Task list filtering (status, assignee), sorting, and pagination, with configurable limits and edge-case tests.
- **Day 5:** Task priority (low/medium/high/urgent) and due date fields, with filtering (priority, due_before/after) and rank-based priority sorting.
- **Day 6:** Labels/tags — org-scoped Label model, attach/detach endpoints per task, filter task list by label, cascade-detach on label delete.
- **Day 7:** Project-level membership — project visibility (open/restricted), viewer/editor/manager project roles layered under org roles, member management endpoints, project-scoped guards on task/comment/label routes.
- **Day 8:** In-app notifications — assignment, comment, and @mention triggers, plus a user-scoped inbox with unread counts and mark-read/unread.
- **Day 9:** Org-wide search across projects and tasks, ranked and visibility-aware, backed by pg_trgm indexes.
- **Day 10:** API hardening — sliding-window rate limiting with a tighter budget on credential endpoints, and a non-blank/length validation pass over every user-supplied string.

### Upcoming

| Day | Feature |
|---|---|
| 11 | File attachments on tasks (upload to object storage, metadata model) |
| 12 | Webhooks — org-level subscriptions for task events, signed delivery worker |
| 13 | Audit log + soft delete/restore for projects and tasks |
| 14 | Polish & ops — OpenAPI cleanup, final test pass (structured logging, request-ID middleware, and the Dockerfile landed early, alongside day 10) |

## Project layout

```
app/
  core/       # settings, security, middleware, logging, rate limiting
  db/         # engine, session, declarative base
  models/     # SQLAlchemy ORM models
  schemas/    # Pydantic request/response schemas
  api/        # FastAPI routers
  services/   # business logic
tests/
alembic/      # migrations
```

## Permissions

Two role systems compose. Organization roles (`owner` > `admin` > `member`)
govern the org and everything in it. Project roles (`manager` > `editor` >
`viewer`) narrow a plain member's access *within* one project — they never
grant more than the org role already allows, and org admins and owners always
resolve to project manager.

A project is `open` by default, meaning every org member gets editor access
without an explicit row. Setting it to `restricted` limits it to its listed
members; to everyone else it returns 404 rather than 403, so its existence
can't be probed, and it's filtered out of project lists and search results.

## Operations

Logs are JSON, one object per line, and every line raised during a request
carries its `request_id`. `X-Request-ID` is honoured from inbound requests so
a trace survives across services, and echoed on every response.

Rate limiting is a sliding window keyed on client IP, with a tighter budget on
`/auth/login` and `/auth/register` and health checks exempt. Counters live in
the process, so with multiple workers the effective limit is per-worker.

The Dockerfile runs the app unprivileged with a healthcheck on
`/api/v1/health`. It deliberately does not run migrations at container start —
with more than one replica the containers would race — so run
`alembic upgrade head` as a separate release step.
