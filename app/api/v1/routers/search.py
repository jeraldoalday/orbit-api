import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_organization_or_404, require_org_member
from app.core.config import get_settings
from app.db.session import get_db
from app.models.membership import Membership
from app.models.organization import Organization
from app.schemas.search import SearchHit, SearchResults
from app.services.search_service import search_projects, search_tasks

settings = get_settings()

router = APIRouter(prefix="/organizations/{org_id}/search", tags=["search"])


@router.get("", response_model=SearchResults)
def search(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    membership: Membership = Depends(require_org_member),
    q: str = Query(min_length=1, max_length=200),
    kind: Optional[str] = Query(default=None, pattern="^(project|task)$"),
    project_id: Optional[uuid.UUID] = None,
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
) -> SearchResults:
    hits: list[SearchHit] = []

    # `project_id` narrows to one project's tasks, so a project hit would be
    # noise; skip that half of the search entirely rather than filter it after.
    if kind != "task" and project_id is None:
        hits += [
            SearchHit(kind="project", score=score, project=project)
            for project, score in search_projects(db, organization.id, membership, q, limit=limit)
        ]

    if kind != "project":
        hits += [
            SearchHit(kind="task", score=score, task=task)
            for task, score in search_tasks(
                db, organization.id, membership, q, project_id=project_id, limit=limit
            )
        ]

    # Projects and tasks are ranked independently, so merge on score. Python's
    # sort is stable, which keeps each side's own tie-break order intact.
    hits.sort(key=lambda hit: hit.score, reverse=True)

    return SearchResults(query=q, total=len(hits), results=hits[:limit])
