from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_organization_or_404,
    get_project_or_404,
    require_org_member,
    require_org_role,
    require_project_role,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.project_member import ProjectRole
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_member_service import list_visible_projects
from app.services.project_service import create_project, delete_project, update_project

settings = get_settings()

router = APIRouter(prefix="/organizations/{org_id}/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_member),
) -> ProjectRead:
    return create_project(db, organization, project_in)


@router.get("", response_model=list[ProjectRead])
def list_mine(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    membership: Membership = Depends(require_org_member),
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectRead]:
    return list_visible_projects(db, organization.id, membership, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectRead)
def get(
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> ProjectRead:
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update(
    project_in: ProjectUpdate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
) -> ProjectRead:
    # Editors maintain a project's content; flipping visibility decides who can
    # see it at all, so that stays a manager-level decision.
    if project_in.visibility is not None and role != ProjectRole.MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a project manager can change project visibility",
        )
    return update_project(db, project, project_in)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> None:
    delete_project(db, project)
