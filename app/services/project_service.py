import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


def create_project(db: Session, organization: Organization, project_in: ProjectCreate) -> Project:
    project = Project(
        organization_id=organization.id,
        name=project_in.name,
        description=project_in.description,
        visibility=project_in.visibility,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(
    db: Session, org_id: uuid.UUID, project_id: uuid.UUID, *, include_deleted: bool = False
) -> Optional[Project]:
    stmt = select(Project).where(Project.id == project_id, Project.organization_id == org_id)
    if not include_deleted:
        stmt = stmt.where(Project.deleted_at.is_(None))
    return db.execute(stmt).scalar_one_or_none()


def list_projects(
    db: Session, org_id: uuid.UUID, *, include_deleted: bool = False
) -> list[Project]:
    stmt = select(Project).where(Project.organization_id == org_id)
    if not include_deleted:
        stmt = stmt.where(Project.deleted_at.is_(None))
    return list(db.execute(stmt.order_by(Project.name, Project.id)).scalars().all())


def list_deleted_projects(
    db: Session, org_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> list[Project]:
    """Soft-deleted projects, most recently deleted first."""
    stmt = (
        select(Project)
        .where(Project.organization_id == org_id, Project.deleted_at.is_not(None))
        .order_by(Project.deleted_at.desc(), Project.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def update_project(db: Session, project: Project, project_in: ProjectUpdate) -> Project:
    # `description` is nullable, so an explicit null has to be told apart from an
    # omitted key: checking `is not None` alone made the field impossible to clear.
    fields_set = project_in.model_fields_set

    if project_in.name is not None:
        project.name = project_in.name
    if "description" in fields_set:
        project.description = project_in.description
    if project_in.visibility is not None:
        project.visibility = project_in.visibility
    db.commit()
    db.refresh(project)
    return project


def soft_delete_project(db: Session, project: Project) -> Project:
    """Hide a project without destroying it or anything under it."""
    project.mark_deleted()
    db.commit()
    db.refresh(project)
    return project


def restore_project(db: Session, project: Project) -> Project:
    project.mark_restored()
    db.commit()
    db.refresh(project)
    return project


def purge_project(db: Session, project: Project) -> None:
    """Delete for real, taking every task, comment and attachment with it.

    Unlike the soft delete this is unrecoverable, which is why the route that
    reaches it is limited to org owners and refuses a project that has not been
    soft-deleted first.
    """
    db.delete(project)
    db.commit()
