import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.audit_log import AuditAction, AuditLog, AuditResource
from app.models.user import User


def record_audit(
    db: Session,
    *,
    organization_id: uuid.UUID,
    action: AuditAction,
    resource_type: AuditResource,
    actor: Optional[User] = None,
    resource_id: Optional[uuid.UUID] = None,
    data: Optional[dict[str, Any]] = None,
    commit: bool = False,
) -> AuditLog:
    """Append one entry to an organization's audit trail.

    Defaults to ``commit=False`` so the entry joins the transaction that made
    the change. An audit log written afterwards, in its own transaction, is one
    crash away from claiming something happened that didn't — or, worse,
    missing something that did.
    """
    entry = AuditLog(
        organization_id=organization_id,
        actor_id=actor.id if actor is not None else None,
        actor_email=actor.email if actor is not None else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        data=data,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    else:
        db.flush()
    return entry


def list_audit_logs(
    db: Session,
    organization_id: uuid.UUID,
    *,
    action: Optional[AuditAction] = None,
    resource_type: Optional[AuditResource] = None,
    resource_id: Optional[uuid.UUID] = None,
    actor_id: Optional[uuid.UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .options(joinedload(AuditLog.actor))
        .where(AuditLog.organization_id == organization_id)
    )

    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type is not None:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    if actor_id is not None:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if since is not None:
        stmt = stmt.where(AuditLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(AuditLog.created_at <= until)

    # Newest first: a trail is read from the incident backwards.
    stmt = (
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)
    )
    return list(db.execute(stmt).scalars().all())
