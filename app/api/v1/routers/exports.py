import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404, require_project_role
from app.core.config import get_settings
from app.db.session import get_db
from app.models.project import Project
from app.models.project_member import ProjectRole
from app.models.task import TaskPriority, TaskStatus
from app.services.export_service import export_filename, stream_csv, task_rows

settings = get_settings()

# Its own prefix rather than a route under /tasks: a literal path segment
# living beside "/{task_id}" is one route ordering mistake away from being
# read as a task id.
router = APIRouter(prefix="/organizations/{org_id}/projects/{project_id}/export", tags=["exports"])


@router.get("/tasks.csv")
def tasks_csv(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    status_: Optional[TaskStatus] = Query(default=None, alias="status"),
    assignee_id: Optional[uuid.UUID] = None,
    priority: Optional[TaskPriority] = None,
    milestone_id: Optional[uuid.UUID] = None,
    label_id: Optional[uuid.UUID] = None,
    limit: int = Query(default=settings.export_max_rows, ge=1, le=settings.export_max_rows),
) -> StreamingResponse:
    """The project's tasks as a CSV file, filtered like the task list.

    Reading a project is enough to export it: the file contains what the
    caller can already page through, and refusing it only means they paste it
    into a spreadsheet by hand.
    """
    rows = task_rows(
        db,
        project,
        status=status_,
        assignee_id=assignee_id,
        priority=priority,
        milestone_id=milestone_id,
        label_id=label_id,
        limit=limit,
    )

    return StreamingResponse(
        stream_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{export_filename(project)}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
