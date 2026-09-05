"""OpenAPI metadata.

Kept out of main.py so the app wiring stays about middleware and routers, and
so the tag descriptions — the part a consumer actually reads first — live
somewhere they can be edited without touching startup code.
"""

API_TITLE = "Orbit API"
API_VERSION = "0.1.0"

API_DESCRIPTION = """
Multi-tenant project and task management.

## Authentication

All endpoints except `/auth/register`, `/auth/login` and the health checks
require a bearer token: `Authorization: Bearer <access_token>`. Access tokens
are short-lived; exchange a refresh token at `/auth/refresh` rather than
re-sending credentials.

## Permissions

Two role systems compose. Organization roles (`owner` > `admin` > `member`)
govern the org and everything in it. Project roles (`manager` > `editor` >
`viewer`) narrow a plain member's access within one project, and never grant
more than the org role already allows.

## Not-found versus forbidden

A resource the caller may not see returns **404**, not 403, wherever telling
the two apart would leak its existence — a restricted project, or an
organization the caller isn't a member of. A 403 means "you can see this, but
you may not do that".

## Errors

Failures return `{"detail": "..."}`. Validation failures (422) instead return
FastAPI's field-level error list.
"""

TAGS_METADATA = [
    {"name": "health", "description": "Liveness and database reachability probes."},
    {"name": "auth", "description": "Registration, login and token refresh."},
    {"name": "users", "description": "The authenticated user's own profile."},
    {"name": "organizations", "description": "Tenant containers. Everything else hangs off one."},
    {"name": "memberships", "description": "Who belongs to an organization, and at what role."},
    {"name": "invitations", "description": "Inviting people who don't have an account yet."},
    {"name": "projects", "description": "Projects, their visibility, and the recycle bin."},
    {"name": "project-members", "description": "Per-project roles layered under org roles."},
    {
        "name": "milestones",
        "description": "Dated goals inside a project that tasks are grouped under.",
    },
    {"name": "tasks", "description": "Tasks, with filtering, sorting and soft delete."},
    {
        "name": "task-checklist",
        "description": "Ordered, tickable steps inside a single task.",
    },
    {"name": "task-comments", "description": "Discussion on a task, with @mentions."},
    {
        "name": "task-dependencies",
        "description": "Which tasks must finish before which others can.",
    },
    {"name": "task-labels", "description": "Attaching org labels to a task."},
    {
        "name": "task-watchers",
        "description": "Following a task you are not assigned to.",
    },
    {
        "name": "time-tracking",
        "description": "Work logged against a task, and per-project reports of it.",
    },
    {"name": "labels", "description": "Org-wide label definitions."},
    {"name": "attachments", "description": "Files uploaded against a task."},
    {"name": "notifications", "description": "The signed-in user's inbox."},
    {"name": "search", "description": "Ranked, visibility-aware search across an org."},
    {"name": "exports", "description": "A project's tasks as a downloadable CSV file."},
    {"name": "stats", "description": "Task counts for a project or a whole org."},
    {"name": "webhooks", "description": "Outbound event subscriptions and their deliveries."},
    {"name": "audit", "description": "Read-only trail of consequential actions."},
]


def generate_operation_id(route) -> str:
    """A readable, stable operation id: ``tasks-restore`` rather than
    ``restore_api_v1_organizations__org_id__projects...post``.

    Generated client methods are named from this, so the default — which
    encodes the whole path and the HTTP verb — produces method names nobody
    wants to type. Uniqueness is asserted in the schema tests, since a
    collision here silently overwrites one operation in a generated client.
    """
    tag = route.tags[0] if route.tags else "default"
    return f"{tag}-{route.name}"


# Attached to every route so the error shape is documented once rather than
# repeated on each operation.
COMMON_RESPONSES = {
    401: {"description": "Missing or invalid credentials"},
    403: {"description": "Authenticated, but not allowed to do this"},
    404: {"description": "Not found, or hidden from this caller"},
    429: {"description": "Rate limit exceeded"},
}
