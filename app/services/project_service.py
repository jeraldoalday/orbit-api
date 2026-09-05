import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import ObjectStorage
from app.models.audit_log import AuditAction, AuditResource
from app.models.organization import Organization
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate
from app.services.attachment_service import delete_objects, storage_keys_for_project
from app.services.audit_service import record_audit


def _audit(
    db: Session,
    project: Project,
    action: AuditAction,
    actor: Optional[User],
    data: Optional[dict] = None,
) -> None:
    record_audit(
        db,
        organization_id=project.organization_id,
        action=action,
        resource_type=AuditResource.PROJECT,
        actor=actor,
        resource_id=project.id,
        data={"name": project.name, **(data or {})},
    )


def create_project(
    db: Session,
    organization: Organization,
    project_in: ProjectCreate,
    actor: Optional[User] = None,
) -> Project:
    project = Project(
        organization_id=organization.id,
        name=project_in.name,
        description=project_in.description,
        visibility=project_in.visibility,
    )
    db.add(project)
    db.flush()
    _audit(db, project, AuditAction.PROJECT_CREATED, actor)
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


def update_project(
    db: Session, project: Project, project_in: ProjectUpdate, actor: Optional[User] = None
) -> Project:
    # `description` is nullable, so an explicit null has to be told apart from an
    # omitted key: checking `is not None` alone made the field impossible to clear.
    fields_set = project_in.model_fields_set

    if project_in.name is not None:
        project.name = project_in.name
    if "description" in fields_set:
        project.description = project_in.description
    if project_in.visibility is not None:
        # Visibility is the one field that changes who can see the project at
        # all, so the trail records what it moved between.
        _audit(
            db,
            project,
            AuditAction.PROJECT_UPDATED,
            actor,
            {"visibility": {"from": project.visibility.value, "to": project_in.visibility.value}},
        )
        project.visibility = project_in.visibility
    db.commit()
    db.refresh(project)
    return project


def soft_delete_project(db: Session, project: Project, actor: Optional[User] = None) -> Project:
    """Hide a project without destroying it or anything under it."""
    project.mark_deleted()
    _audit(db, project, AuditAction.PROJECT_DELETED, actor)
    db.commit()
    db.refresh(project)
    return project


def restore_project(db: Session, project: Project, actor: Optional[User] = None) -> Project:
    project.mark_restored()
    _audit(db, project, AuditAction.PROJECT_RESTORED, actor)
    db.commit()
    db.refresh(project)
    return project


def purge_project(
    db: Session,
    storage: ObjectStorage,
    project: Project,
    actor: Optional[User] = None,
) -> None:
    """Delete for real, taking every task, comment and attachment with it.

    Unlike the soft delete this is unrecoverable, which is why the route that
    reaches it is limited to org owners and refuses a project that has not been
    soft-deleted first.
    """
    # The entry is written before the row goes away, and survives it: the audit
    # log holds a plain UUID rather than a foreign key precisely so a purge
    # can't take its own record with it.
    _audit(db, project, AuditAction.PROJECT_PURGED, actor)
    # The attachment rows go with the cascade, and with them the only record of
    # which stored objects belonged here — so the keys are collected first and
    # the objects removed once the delete has actually committed.
    keys = storage_keys_for_project(db, project.id)
    db.delete(project)
    db.commit()
    delete_objects(storage, keys)
