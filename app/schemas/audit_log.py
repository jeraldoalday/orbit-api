import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.models.audit_log import AuditAction, AuditResource
from app.schemas.user import UserRead


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    action: AuditAction
    resource_type: AuditResource
    resource_id: Optional[uuid.UUID]
    actor: Optional[UserRead]
    # Kept alongside `actor` because the relationship goes null when the
    # account is deleted, and the trail still has to name who acted.
    actor_email: Optional[str]
    data: Optional[dict[str, Any]]
    created_at: datetime
