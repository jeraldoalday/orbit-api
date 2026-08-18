import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class ProjectRole(str, enum.Enum):
    VIEWER = "viewer"
    EDITOR = "editor"
    MANAGER = "manager"


PROJECT_ROLE_RANK = {
    ProjectRole.VIEWER: 0,
    ProjectRole.EDITOR: 1,
    ProjectRole.MANAGER: 2,
}


def project_role_at_least(role: ProjectRole, minimum: ProjectRole) -> bool:
    return PROJECT_ROLE_RANK[role] >= PROJECT_ROLE_RANK[minimum]


class ProjectMember(UUIDPKMixin, TimestampMixin, Base):
    """A user granted an explicit role on a single project.

    Project roles sit *below* org roles: they narrow what a plain org member can
    do inside one project, but they never grant more than the org role already
    allows. Org admins and owners therefore skip this table entirely.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member_project_user"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role"), nullable=False, default=ProjectRole.EDITOR
    )

    project: Mapped["Project"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<ProjectMember project={self.project_id} user={self.user_id} role={self.role}>"
