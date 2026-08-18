import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_organization_or_404, require_org_role
from app.core.config import get_settings
from app.db.session import get_db
from app.models.audit_log import AuditAction, AuditResource
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.schemas.audit_log import AuditLogRead
from app.services.audit_service import list_audit_logs

settings = get_settings()

# Read-only by design: there is no route that writes, edits or deletes an entry.
# An audit trail the people it describes can change answers nothing.
router = APIRouter(
    prefix="/organizations/{org_id}/audit-logs",
    tags=["audit"],
    dependencies=[Depends(require_org_role(MembershipRole.ADMIN))],
)


@router.get("", response_model=list[AuditLogRead])
def list_for_org(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
    action: Optional[AuditAction] = None,
    resource_type: Optional[AuditResource] = None,
    resource_id: Optional[uuid.UUID] = None,
    actor_id: Optional[uuid.UUID] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[AuditLogRead]:
    return list_audit_logs(
        db,
        organization.id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
