"""Turning domain changes into webhook payloads.

Kept apart from the task and comment services so those stay about the domain,
and so the shape of what subscribers receive is defined in one place — a
receiver's parser breaks if these dictionaries drift.
"""

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.task import Task
from app.models.task_comment import TaskComment
from app.models.user import User
from app.models.webhook import WebhookEvent
from app.services.webhook_delivery_service import enqueue_event


def _actor_payload(actor: Optional[User]) -> Optional[dict[str, Any]]:
    if actor is None:
        return None
    return {"id": str(actor.id), "email": actor.email, "full_name": actor.full_name}


def task_payload(project: Project, task: Task) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "project_id": str(project.id),
        "project_name": project.name,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "priority": task.priority.value,
        "assignee_id": str(task.assignee_id) if task.assignee_id else None,
        "milestone_id": str(task.milestone_id) if task.milestone_id else None,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def emit_task_event(
    db: Session,
    project: Project,
    task: Task,
    event: WebhookEvent,
    actor: Optional[User] = None,
    *,
    extra: Optional[dict[str, Any]] = None,
    commit: bool = False,
) -> None:
    """Queue ``event`` for every subscriber of ``project``'s organization.

    Defaults to ``commit=False`` so the delivery rows join the transaction that
    made the change: an event is never queued for a write that rolled back,
    and a committed write never silently skips its event.
    """
    data: dict[str, Any] = {"task": task_payload(project, task), "actor": _actor_payload(actor)}
    if extra:
        data.update(extra)
    enqueue_event(db, project.organization_id, event, data, commit=commit)


def emit_comment_event(
    db: Session,
    project: Project,
    task: Task,
    comment: TaskComment,
    actor: Optional[User] = None,
    *,
    commit: bool = False,
) -> None:
    data = {
        "task": task_payload(project, task),
        "actor": _actor_payload(actor),
        "comment": {
            "id": str(comment.id),
            "body": comment.body,
            "author_id": str(comment.author_id) if comment.author_id else None,
        },
    }
    enqueue_event(db, project.organization_id, WebhookEvent.COMMENT_CREATED, data, commit=commit)
