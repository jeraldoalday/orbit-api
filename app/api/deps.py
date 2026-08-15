import uuid
from typing import Callable, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.security import InvalidTokenError, TokenType, decode_token
from app.db.session import get_db
from app.models.label import Label
from app.models.membership import Membership, MembershipRole, role_at_least
from app.models.organization import Organization
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.auth_service import get_user_by_id
from app.services.label_service import get_label
from app.services.membership_service import get_membership
from app.services.organization_service import get_organization
from app.services.project_service import get_project
from app.services.task_service import get_task

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if token is None:
        raise credentials_error

    try:
        subject = decode_token(token, TokenType.ACCESS)
        user_id = uuid.UUID(subject)
    except (InvalidTokenError, ValueError) as exc:
        raise credentials_error from exc

    user = get_user_by_id(db, user_id)
    if user is None:
        raise credentials_error

    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return current_user


def get_organization_or_404(
    org_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> Organization:
    organization = get_organization(db, org_id)
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


def require_org_member(
    organization: Organization = Depends(get_organization_or_404),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> Membership:
    membership = get_membership(db, organization.id, current_user.id)
    if membership is None:
        # Not a member: treat identically to a missing org so membership can't be probed.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return membership


def require_org_role(minimum: MembershipRole) -> Callable[..., Membership]:
    def dependency(membership: Membership = Depends(require_org_member)) -> Membership:
        if not role_at_least(membership.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this organization",
            )
        return membership

    return dependency


def get_project_or_404(
    project_id: uuid.UUID,
    organization: Organization = Depends(get_organization_or_404),
    db: Session = Depends(get_db),
) -> Project:
    project = get_project(db, organization.id, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def get_task_or_404(
    task_id: uuid.UUID,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
) -> Task:
    task = get_task(db, project.id, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def get_label_or_404(
    label_id: uuid.UUID,
    organization: Organization = Depends(get_organization_or_404),
    db: Session = Depends(get_db),
) -> Label:
    label = get_label(db, organization.id, label_id)
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label not found")
    return label
