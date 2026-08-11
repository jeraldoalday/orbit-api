from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_organization_or_404,
    get_project_or_404,
    require_org_member,
    require_org_role,
)
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_service import (
    create_project,
    delete_project,
    list_projects,
    update_project,
)

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
    _membership: Membership = Depends(require_org_member),
) -> list[ProjectRead]:
    return list_projects(db, organization.id)


@router.get("/{project_id}", response_model=ProjectRead)
def get(
    project: Project = Depends(get_project_or_404),
    _membership: Membership = Depends(require_org_member),
) -> ProjectRead:
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update(
    project_in: ProjectUpdate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _membership: Membership = Depends(require_org_member),
) -> ProjectRead:
    return update_project(db, project, project_in)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> None:
    delete_project(db, project)
