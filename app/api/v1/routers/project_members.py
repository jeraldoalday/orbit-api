from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_project_member_or_404, get_project_or_404, require_project_role
from app.core.config import get_settings
from app.db.session import get_db
from app.models.project import Project
from app.models.project_member import ProjectMember, ProjectRole
from app.schemas.project_member import (
    ProjectMemberCreate,
    ProjectMemberRead,
    ProjectMemberRoleUpdate,
)
from app.services.project_member_service import (
    AlreadyProjectMemberError,
    NotOrgMemberError,
    UserNotFoundError,
    add_project_member,
    list_project_members,
    remove_project_member,
    update_project_member_role,
)

settings = get_settings()

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/members", tags=["project-members"]
)


@router.get("", response_model=list[ProjectMemberRead])
def list_mine(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[ProjectMemberRead]:
    return list_project_members(db, project.id, limit=limit, offset=offset)


@router.post("", response_model=ProjectMemberRead, status_code=status.HTTP_201_CREATED)
def add(
    member_in: ProjectMemberCreate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.MANAGER)),
) -> ProjectMemberRead:
    try:
        return add_project_member(db, project, member_in.email, member_in.role)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotOrgMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except AlreadyProjectMemberError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{member_id}", response_model=ProjectMemberRead)
def update_role(
    role_in: ProjectMemberRoleUpdate,
    db: Session = Depends(get_db),
    project_member: ProjectMember = Depends(get_project_member_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.MANAGER)),
) -> ProjectMemberRead:
    return update_project_member_role(db, project_member, role_in.role)


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    db: Session = Depends(get_db),
    project_member: ProjectMember = Depends(get_project_member_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.MANAGER)),
) -> None:
    remove_project_member(db, project_member)
