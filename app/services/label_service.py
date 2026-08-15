import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.label import Label
from app.models.organization import Organization


class DuplicateLabelError(Exception):
    pass


def create_label(db: Session, organization: Organization, name: str, color: str) -> Label:
    name = name.strip()
    label = Label(organization_id=organization.id, name=name, color=color)
    db.add(label)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateLabelError(
            f"A label named {name!r} already exists in this organization"
        ) from exc
    db.refresh(label)
    return label


def get_label(db: Session, org_id: uuid.UUID, label_id: uuid.UUID) -> Optional[Label]:
    stmt = select(Label).where(Label.id == label_id, Label.organization_id == org_id)
    return db.execute(stmt).scalar_one_or_none()


def list_labels(db: Session, org_id: uuid.UUID) -> list[Label]:
    stmt = select(Label).where(Label.organization_id == org_id).order_by(Label.name, Label.id)
    return list(db.execute(stmt).scalars().all())


def delete_label(db: Session, label: Label) -> None:
    db.delete(label)
    db.commit()
