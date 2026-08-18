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

Tests run against an in-memory SQLite database and export `BCRYPT_ROUNDS=4`;
hashing at the production cost factor accounted for almost the whole runtime.

## Webhook worker

Deliveries are queued by the API and posted by a separate process:

```bash
python -m app.worker
```

Run it alongside the API, not inside it — a slow subscriber must never add
latency to a request. Several workers can run at once; each leases the batch it
claims, so an event is not posted twice.

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
- **Day 11:** File attachments on tasks — streaming upload behind a pluggable object-storage interface, sanitized filenames, per-task size and count limits.
- **Day 12:** Webhooks — org-level subscriptions with SSRF-guarded targets, HMAC-signed deliveries, and a separate worker with leasing and exponential backoff.
- **Day 13:** Audit log + soft delete/restore for projects and tasks, with an owner-only purge.
- **Day 14:** Polish & ops — OpenAPI cleanup and schema guards, plus a faster test suite (structured logging, request-ID middleware, and the Dockerfile landed early, alongside day 10).

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

Interactive docs are served at `/docs` everywhere except production, where
publishing a map of the surface buys nothing.

### Attachment storage

Attachment bytes live behind an `ObjectStorage` interface; the shipped backend
writes to `ATTACHMENT_STORAGE_DIR` on local disk, which is fine for one host and
wrong for more than one — swap in an S3/GCS backend before scaling out. Metadata
rows and objects are written object-first and deleted row-first, so the worst
failure case is an orphaned object rather than a row promising a download that
can't succeed.

### Webhook delivery

Subscription targets are validated against SSRF: http(s) only, no embedded
credentials, and no host that is or resolves to a loopback, private, link-local
or reserved address. The address is re-checked before every attempt, because a
name that validated as public can be repointed later.

Each request carries `X-Orbit-Signature: t=<unix>,v1=<hmac-sha256>` over the
timestamp and the exact body. Verify it with `app.core.webhook_signing.
verify_signature`, and reject anything outside your clock-skew tolerance —
the timestamp is signed precisely so a captured request stops being replayable.

Failures retry with exponential backoff up to `WEBHOOK_MAX_ATTEMPTS`, then stop.
Redirects are never followed: a 3xx would hand a body signed for one host to
another.

### Deletion

`DELETE` on a project or task is a soft delete — the row is stamped and
disappears from every read, including search — and is reversible via
`POST .../restore`. `DELETE .../purge` is the irreversible one: owners only, and
it refuses anything not already soft-deleted, so the soft delete doubles as the
confirmation step. A purge also deletes the attachment objects, which is the one
thing a cascade can't do for us.

### Audit log

`GET /organizations/{id}/audit-logs` is an admin-only, read-only trail of
consequential actions — deletes, purges, restores, role changes and webhook
lifecycle. Entries are written in the same transaction as the change, hold a
plain resource UUID so they outlive what they describe, and never record a
secret.
