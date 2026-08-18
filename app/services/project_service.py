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


def get_project(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> Optional[Project]:
    stmt = select(Project).where(Project.id == project_id, Project.organization_id == org_id)
    return db.execute(stmt).scalar_one_or_none()


def list_projects(db: Session, org_id: uuid.UUID) -> list[Project]:
    stmt = (
        select(Project)
        .where(Project.organization_id == org_id)
        .order_by(Project.name, Project.id)
    )
    return list(db.execute(stmt).scalars().all())


def update_project(db: Session, project: Project, project_in: ProjectUpdate) -> Project:
    if project_in.name is not None:
        project.name = project_in.name
    if project_in.description is not None:
        project.description = project_in.description
    if project_in.visibility is not None:
        project.visibility = project_in.visibility
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: Project) -> None:
    db.delete(project)
    db.commit()
