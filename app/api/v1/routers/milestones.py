import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404, require_project_role
from app.db.session import get_db
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.project_member import ProjectRole
from app.schemas.milestone import (
    MilestoneCreate,
    MilestoneDetail,
    MilestoneRead,
    MilestoneUpdate,
)
from app.services.milestone_service import (
    MilestoneAlreadyCompletedError,
    MilestoneHasOpenTasksError,
    MilestoneNotCompletedError,
    complete_milestone,
    create_milestone,
    delete_milestone,
    get_milestone,
    list_milestones,
    milestone_detail,
    reopen_milestone,
    update_milestone,
)

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/milestones", tags=["milestones"]
)


def _milestone_or_404(
    milestone_id: uuid.UUID,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
) -> Milestone:
    milestone = get_milestone(db, project.id, milestone_id)
    if milestone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Milestone not found")
    return milestone


@router.get("", response_model=list[MilestoneDetail])
def list_all(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    include_completed: bool = Query(default=True),
) -> list[MilestoneDetail]:
    """The project's milestones, soonest due first, each with its progress."""
    return list_milestones(db, project.id, include_completed=include_completed)


@router.post("", response_model=MilestoneRead, status_code=status.HTTP_201_CREATED)
def create(
    milestone_in: MilestoneCreate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    # Manager, not editor: a milestone is the shape of the plan rather than a
    # change to one task, and an editor can still file work under it.
    _role: ProjectRole = Depends(require_project_role(ProjectRole.MANAGER)),
) -> MilestoneRead:
    return create_milestone(db, project, milestone_in)


@router.get("/{milestone_id}", response_model=MilestoneDetail)
def get(
    db: Session = Depends(get_db),
    milestone: Milestone = Depends(_milestone_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> MilestoneDetail:
    return milestone_detail(db, milestone)


@router.patch("/{milestone_id}", response_model=MilestoneRead)
def update(
    changes: MilestoneUpdate,
    db: Session = Depends(get_db),
    milestone: Milestone = Depends(_milestone_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.MANAGER)),
) -> MilestoneRead:
    return update_milestone(db, milestone, changes)


@router.post("/{milestone_id}/complete", response_model=MilestoneDetail)
def complete(
    db: Session = Depends(get_db),
    milestone: Milestone = Depends(_milestone_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.MANAGER)),
    force: bool = Query(
        default=False,
        description="Complete the milestone even though open tasks remain under it.",
    ),
) -> MilestoneDetail:
    """Close a milestone. Refused while work under it is still open."""
    try:
        complete_milestone(db, milestone, force=force)
    except MilestoneHasOpenTasksError as exc:
        # 409 for the same reason completing a blocked task is: the request is
        # well-formed and would be accepted once the tasks close.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MilestoneAlreadyCompletedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return milestone_detail(db, milestone)


@router.post("/{milestone_id}/reopen", response_model=MilestoneDetail)
def reopen(
    db: Session = Depends(get_db),
    milestone: Milestone = Depends(_milestone_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.MANAGER)),
) -> MilestoneDetail:
    try:
        reopen_milestone(db, milestone)
    except MilestoneNotCompletedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return milestone_detail(db, milestone)


@router.delete("/{milestone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    milestone: Milestone = Depends(_milestone_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.MANAGER)),
) -> None:
    """Delete the grouping. The tasks under it survive, unfiled."""
    delete_milestone(db, milestone)
