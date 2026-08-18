import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.membership import Membership, MembershipRole, role_at_least
from app.models.project import Project, ProjectVisibility
from app.models.project_member import ProjectMember, ProjectRole
from app.services.auth_service import get_user_by_email
from app.services.membership_service import get_membership


class UserNotFoundError(Exception):
    pass


class NotOrgMemberError(Exception):
    pass


class AlreadyProjectMemberError(Exception):
    pass


def get_project_member(
    db: Session, project_id: uuid.UUID, user_id: uuid.UUID
) -> Optional[ProjectMember]:
    stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
    )
    return db.execute(stmt).scalar_one_or_none()


def get_project_member_by_id(
    db: Session, project_id: uuid.UUID, member_id: uuid.UUID
) -> Optional[ProjectMember]:
    stmt = select(ProjectMember).where(
        ProjectMember.project_id == project_id, ProjectMember.id == member_id
    )
    return db.execute(stmt).scalar_one_or_none()


def list_project_members(
    db: Session, project_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> list[ProjectMember]:
    stmt = (
        select(ProjectMember)
        .options(joinedload(ProjectMember.user))
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.created_at, ProjectMember.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def resolve_project_role(
    db: Session, project: Project, membership: Membership
) -> Optional[ProjectRole]:
    """Effective role of an org member on one project, or None if they can't see it.

    Org admins and owners manage every project regardless of the members table,
    so revoking someone's project role can never lock an admin out of their own
    organization. Plain members fall back to their org-wide access: everything
    on an open project, nothing at all on a restricted one.
    """
    if role_at_least(membership.role, MembershipRole.ADMIN):
        return ProjectRole.MANAGER

    project_member = get_project_member(db, project.id, membership.user_id)
    if project_member is not None:
        return project_member.role

    if project.visibility == ProjectVisibility.OPEN:
        return ProjectRole.EDITOR

    return None


def add_project_member(
    db: Session, project: Project, email: str, role: ProjectRole
) -> ProjectMember:
    user = get_user_by_email(db, email.strip().lower())
    if user is None:
        raise UserNotFoundError(f"No user is registered with email {email}")

    if get_membership(db, project.organization_id, user.id) is None:
        raise NotOrgMemberError(
            f"{email} must join the organization before being added to a project"
        )

    if get_project_member(db, project.id, user.id) is not None:
        raise AlreadyProjectMemberError(f"{email} is already a member of this project")

    project_member = ProjectMember(project_id=project.id, user_id=user.id, role=role)
    db.add(project_member)
    db.commit()
    db.refresh(project_member)
    return project_member


def update_project_member_role(
    db: Session, project_member: ProjectMember, new_role: ProjectRole
) -> ProjectMember:
    project_member.role = new_role
    db.commit()
    db.refresh(project_member)
    return project_member


def remove_project_member(db: Session, project_member: ProjectMember) -> None:
    db.delete(project_member)
    db.commit()


def list_visible_projects(
    db: Session, org_id: uuid.UUID, membership: Membership, *, limit: int = 50, offset: int = 0
) -> list[Project]:
    """Projects in an org the caller may see, newest-name-first and paginated."""
    stmt = select(Project).where(Project.organization_id == org_id)

    if not role_at_least(membership.role, MembershipRole.ADMIN):
        # Plain members see open projects plus the restricted ones they're on.
        member_project_ids = select(ProjectMember.project_id).where(
            ProjectMember.user_id == membership.user_id
        )
        stmt = stmt.where(
            (Project.visibility == ProjectVisibility.OPEN)
            | (Project.id.in_(member_project_ids))
        )

    stmt = stmt.order_by(Project.name, Project.id).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())
