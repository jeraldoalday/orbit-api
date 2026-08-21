from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import (
    get_organization_or_404,
    get_project_or_404,
    require_org_member,
    require_project_role,
)
from app.db.session import get_db
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.project import Project
from app.models.project_member import ProjectRole
from app.schemas.stats import OrganizationStats, ProjectStats
from app.services.stats_service import organization_stats, project_stats

router = APIRouter(tags=["stats"])


@router.get("/organizations/{org_id}/stats", response_model=OrganizationStats)
def organization(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    membership: Membership = Depends(require_org_member),
) -> OrganizationStats:
    """Org-wide task counts, over the projects this caller can see.

    Restricted projects the caller isn't on are excluded from every number
    here, including the totals: an org-wide count that included them would
    report the size of a project the API otherwise answers 404 for.
    """
    return organization_stats(db, organization.id, membership)


@router.get("/organizations/{org_id}/projects/{project_id}/stats", response_model=ProjectStats)
def project(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> ProjectStats:
    """One project's task counts and its per-assignee breakdown."""
    return project_stats(db, project)
