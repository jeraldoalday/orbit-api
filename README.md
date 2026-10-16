# Orbit API

Multi-tenant project & task management backend.

> **How this project is built:** I develop this service with AI coding agents. I decide what the project, task, and access rules should be, review each change and its tests, and merge what holds up.

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
- **Day 15:** Task dependencies — a per-project "must finish first" graph with cycle detection, and a gate that refuses to complete a task while a blocker is open.
- **Day 16:** Bulk task operations — one edit or one delete applied across a selection, reported per task rather than per batch.
- **Day 17:** Statistics — task counts by status, priority, assignee and due date for a project and for a whole organization, visibility-aware.
- **Day 18:** Task watchers — following a task you aren't assigned to, with a de-duplicated notification fan-out on status changes and comments.
- **Day 19:** Planning and delivery — task checklists, project milestones with a completion gate, time logging against an estimate with per-project reports, and a CSV export of a project's tasks.

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

### Task dependencies

A dependency is a directed "must finish first" edge between two tasks in the
same project. `POST .../tasks/{id}/dependencies` adds one, `GET` returns the
task's immediate neighbourhood — what it waits on, what waits on it, and which
of its blockers are still open — and `DELETE .../{depends_on_id}` removes one.

Every edge is checked before it is written: no self-edges, no second copy of an
existing edge, and no edge whose blocker can already reach back to the task.
The graph therefore stays acyclic by construction, which is what lets the
completion gate look only at a task's *direct* blockers instead of walking the
whole graph on every status change.

Moving a task to `done` while something it depends on is open fails with 409,
naming the blockers. A soft-deleted blocker doesn't count — it has been taken
out of the project, and letting it hold a live task would mean deleting a task
could freeze another one with no way back. Edges never cross projects: a
blocker in a project the caller can't see would turn a refusal into one they
could never explain or clear.

### Bulk edits

`POST .../tasks/bulk` applies one change — status, priority, assignee,
milestone or due date — across a selection, and `POST .../tasks/bulk/delete` soft-deletes one.
Both answer 200 with a per-task breakdown (`updated`, `unchanged`, `failed`
with a reason) rather than one verdict for the whole batch: a real selection
routinely contains a task somebody else just deleted or one an open blocker
holds, and discarding the rest over it would defeat the point.

Each task still goes through the ordinary update path, so a task edited in bulk
gets the same timeline entry, notification and webhook as one edited on its
own. Title and description aren't bulk-editable, and `BULK_TASK_MAX_ITEMS`
caps the batch.

The batch is applied in the order given. Closing a dependency chain in one call
therefore works if the blockers are listed first, and reports the rest as
blocked if they aren't — reordering it silently would produce a per-task report
that no longer lines up with what was sent.

### Statistics

`GET .../projects/{id}/stats` and `GET /organizations/{id}/stats` answer what a
dashboard opens with: counts by status and priority, how many tasks are
overdue or due within a week, how many are unassigned or held by an unfinished
dependency, and a per-assignee breakdown. Every number is a `GROUP BY` or a
`COUNT` in the database rather than a pass over loaded rows.

The org view counts only projects the caller can see, totals included. A count
that swept in a restricted project they were kept off would report its size —
and its existence — through a route with no 404 to hide behind.

### Watchers

Assignment notifies one person and a mention notifies whoever is named;
watching covers everyone else with a stake — a reviewer, whoever filed the
task, a lead tracking a release — without handing any of them the work.

`POST .../tasks/{id}/watchers` with no body watches it yourself, which a plain
viewer may do. Adding *someone else* (by email) changes the task's audience and
needs editor rights, and the target has to be able to reach the project.

Watchers hear about status changes and new comments, not about every field:
titles and priorities move often enough that notifying on them trains people to
ignore the inbox. Anyone already notified another way — the assignee, someone
mentioned, whoever made the change — is skipped, so one write leaves at most
one row per person.

### Checklists

`GET/POST .../tasks/{id}/checklist` keeps a task's steps: short lines that are
either done or not. Subtasks would give every step its own assignee, status,
comments and notification fan-out, which nobody wants for "write the
migration"; a checklist is the cheap half of that.

Positions are dense and 0-based. Deleting an item closes the gap it leaves, so
the next append can't collide with a row that survived, and
`POST .../checklist/reorder` rewrites the order from a list that must name
every item on the task exactly once. A partial ordering is refused rather than
guessed at: leaving the unnamed items wherever they happened to be is how two
clients drag the same row and both end up wrong. The list response carries
`total`, `done` and `completion_rate` so a client doesn't recompute them.
`CHECKLIST_MAX_ITEMS` bounds a list.

### Milestones

A milestone is a dated goal inside one project that tasks are grouped under —
labels answer "what kind of work is this?" across the org, while a milestone
answers "what is left before the 12th?". A task belongs to at most one, set
through `milestone_id` on create, update or a bulk edit, and the task list and
CSV export both filter on it.

Creating and reshaping a milestone needs project manager rights; filing work
under one is an ordinary editor's edit to a task. Completing a milestone with
open tasks under it fails with 409 and a count, the same gate the dependency
graph puts on a task — `?force=true` overrides it, because cutting scope is a
real answer and the alternative is closing the tasks with a lie about them
being done. Completion is a timestamp, so "shipped on the 9th" survives and
`/reopen` is one column. Deleting a milestone unfiles its tasks and keeps them.

Progress counts live tasks only. A soft-deleted task that stayed in the
denominator would make a milestone permanently unfinishable, and a whole list
of milestones is counted in one grouped query rather than one per row.

### Time tracking

Tasks carry `estimate_minutes`; work is logged against them in the same unit
through `POST .../tasks/{id}/time`, so the two numbers compare without a
conversion nobody agrees on. Minutes rather than a start/stop timer — the
timer's failure mode is the one left running overnight, and every report here
wants a duration anyway.

An entry names the day the work happened (`spent_on`, defaulting to today),
which is routinely not the day it was written down. Future days are refused
and one entry is capped at 24 hours: a typo that lands in a report is worse
than one that bounces. Logging time needs editor rights, but correcting
somebody else's entry is limited to its author or a project manager.

`GET .../tasks/{id}/time` returns the entries with logged, remaining and
over-estimate figures. `GET .../projects/{id}/time` reports the project,
grouped by person and by task and optionally narrowed with `spent_from` /
`spent_to`; entries on soft-deleted tasks drop out, so the report describes the
project as it currently stands.

### CSV export

`GET .../projects/{id}/export/tasks.csv` streams a project's tasks as a
spreadsheet, taking the same filters as the task list — an export that can't
reproduce what is on screen sends people back to copying rows by hand. Each row
carries the assignee, milestone, labels, estimate and minutes logged, gathered
in one query each rather than per row.

Cells starting with `=`, `+`, `-` or `@` are prefixed with an apostrophe: every
spreadsheet application runs them as formulas, which makes a task title a code
injection vector into whoever opens the file. Reading a project is enough to
export it — the file holds what the caller can already page through — and
`EXPORT_MAX_ROWS` bounds one request.

### Attachment storage

Attachment bytes live behind an `ObjectStorage` interface; the shipped backend
writes to `ATTACHMENT_STORAGE_DIR` on local disk, which is fine for one host and
wrong for more than one — swap in an S3/GCS backend before scaling out. Metadata
rows and objects are written object-first and deleted row-first, so the worst
failure case is an orphaned object rather than a row promising a download that
can't succeed.

Two budgets bound a task: `ATTACHMENT_MAX_PER_TASK` files, each at most
`ATTACHMENT_MAX_BYTES`, and `ATTACHMENT_MAX_TOTAL_BYTES_PER_TASK` across all of
them together. The last one matters because the first two multiply — without
it, twenty files of ten megabytes is a perfectly legal two hundred. Uploads are
streamed, so the total is checked once before the body is read (refusing an
already-full task cheaply) and once after, when the size is finally known; an
upload that busts the budget deletes the object it just wrote.

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
