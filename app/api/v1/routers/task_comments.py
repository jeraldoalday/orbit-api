import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_task_or_404,
    require_org_member,
    require_project_role,
)
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole, role_at_least
from app.models.project_member import ProjectRole
from app.models.task import Task
from app.models.user import User
from app.schemas.task_comment import TaskCommentCreate, TaskCommentRead
from app.schemas.task_timeline import TaskTimelineEntry
from app.services.task_activity_service import list_activities
from app.services.task_comment_service import (
    create_comment,
    delete_comment,
    get_comment,
    list_comments,
)

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/tasks/{task_id}", tags=["task-comments"]
)


@router.post("/comments", response_model=TaskCommentRead, status_code=status.HTTP_201_CREATED)
def create(
    comment_in: TaskCommentCreate,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    current_user: User = Depends(get_current_active_user),
) -> TaskCommentRead:
    return create_comment(db, task.id, current_user, comment_in.body)


@router.get("/comments", response_model=list[TaskCommentRead])
def list_mine(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> list[TaskCommentRead]:
    return list_comments(db, task.id)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    comment_id: uuid.UUID,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    membership: Membership = Depends(require_org_member),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    current_user: User = Depends(get_current_active_user),
) -> None:
    comment = get_comment(db, task.id, comment_id)
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    is_author = comment.author_id == current_user.id
    is_admin = role_at_least(membership.role, MembershipRole.ADMIN)
    if not is_author and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this organization",
        )

    delete_comment(db, comment)


@router.get("/timeline", response_model=list[TaskTimelineEntry])
def timeline(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> list[TaskTimelineEntry]:
    entries = [
        TaskTimelineEntry(kind="comment", created_at=comment.created_at, comment=comment)
        for comment in list_comments(db, task.id)
    ] + [
        TaskTimelineEntry(kind="activity", created_at=activity.created_at, activity=activity)
        for activity in list_activities(db, task.id)
    ]
    entries.sort(key=lambda entry: entry.created_at)
    return entries
