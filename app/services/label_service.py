import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.label import Label
from app.models.organization import Organization


class DuplicateLabelError(Exception):
    pass


def _find_by_name_ci(db: Session, org_id: uuid.UUID, name: str) -> Optional[Label]:
    stmt = select(Label).where(
        Label.organization_id == org_id, func.lower(Label.name) == name.lower()
    )
    return db.execute(stmt).scalar_one_or_none()


def create_label(db: Session, organization: Organization, name: str, color: str) -> Label:
    name = name.strip()
    # Checked case-insensitively: the unique constraint below only catches an
    # exact-case repeat, so "Bug" and "bug" would otherwise both be created,
    # leaving two labels in the same org that read as the same tag to anyone
    # who isn't looking closely at capitalization.
    if _find_by_name_ci(db, organization.id, name) is not None:
        raise DuplicateLabelError(f"A label named {name!r} already exists in this organization")

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


def list_labels(db: Session, org_id: uuid.UUID, *, limit: int = 50, offset: int = 0) -> list[Label]:
    stmt = (
        select(Label)
        .where(Label.organization_id == org_id)
        .order_by(Label.name, Label.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def delete_label(db: Session, label: Label) -> None:
    db.delete(label)
    db.commit()
