from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_deleted_project_or_404,
    get_organization_or_404,
    get_project_or_404,
    require_org_member,
    require_org_role,
    require_project_role,
)
from app.core.config import get_settings
from app.core.storage import ObjectStorage, get_storage
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.project import Project
from app.models.project_member import ProjectRole
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_member_service import list_visible_projects
from app.services.project_service import (
    create_project,
    list_deleted_projects,
    purge_project,
    restore_project,
    soft_delete_project,
    update_project,
)

settings = get_settings()

router = APIRouter(prefix="/organizations/{org_id}/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_member),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    return create_project(db, organization, project_in, current_user)


@router.get("", response_model=list[ProjectRead])
def list_mine(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    membership: Membership = Depends(require_org_member),
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectRead]:
    return list_visible_projects(db, organization.id, membership, limit=limit, offset=offset)


# Registered before "/{project_id}" so the literal path wins the match: the
# other order sends "deleted" into the UUID path parameter and returns a 422.
@router.get("/deleted", response_model=list[ProjectRead])
def list_deleted(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectRead]:
    """The recycle bin — admin-only, since a deleted project is hidden from
    ordinary members precisely so that they stop seeing it."""
    return list_deleted_projects(db, organization.id, limit=limit, offset=offset)


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
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    # Editors maintain a project's content; flipping visibility decides who can
    # see it at all, so that stays a manager-level decision.
    if project_in.visibility is not None and role != ProjectRole.MANAGER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a project manager can change project visibility",
        )
    return update_project(db, project, project_in, current_user)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Soft-delete: the project vanishes from every read but stays restorable."""
    soft_delete_project(db, project, current_user)


@router.post("/{project_id}/restore", response_model=ProjectRead)
def restore(
    db: Session = Depends(get_db),
    project: Project = Depends(get_deleted_project_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
    current_user: User = Depends(get_current_active_user),
) -> ProjectRead:
    if not project.is_deleted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project is not deleted")
    return restore_project(db, project, current_user)


@router.delete("/{project_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge(
    db: Session = Depends(get_db),
    project: Project = Depends(get_deleted_project_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.OWNER)),
    current_user: User = Depends(get_current_active_user),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    """Delete a project and everything under it, irreversibly.

    Restricted to owners, and it refuses a project that hasn't been
    soft-deleted first: the soft delete *is* the confirmation step, so no
    single call takes a live project straight to gone.
    """
    if not project.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Delete the project before purging it",
        )
    purge_project(db, storage, project, current_user)
