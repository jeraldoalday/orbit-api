import uuid
from typing import Optional

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models.membership import Membership
from app.models.project import Project
from app.models.task import Task
from app.services.project_member_service import visible_project_condition

# A pathological query ("a b c d e ..." ) would otherwise turn into an unbounded
# pile of LIKE predicates; ten terms is far past what a search box produces.
MAX_TERMS = 10

# Relevance tiers. The numbers only need to order correctly relative to each
# other — they're an ordering key, not a normalized score.
_SCORE_EXACT = 100
_SCORE_PREFIX = 50
_SCORE_CONTAINS = 25
_SCORE_BODY = 5


def tokenize(query: str) -> list[str]:
    """Split a raw query into unique lowercased terms, longest-first.

    Order is preserved for readability but duplicates are dropped so
    "bug bug bug" doesn't triple the work for a single predicate.
    """
    seen: dict[str, None] = {}
    for token in (query or "").split():
        cleaned = token.strip().lower()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)[:MAX_TERMS]


def _escape_like(term: str) -> str:
    """Neutralize LIKE wildcards so a literal % or _ can be searched for."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _contains(column: ColumnElement, term: str) -> ColumnElement:
    return func.lower(column).like(f"%{_escape_like(term)}%", escape="\\")


def _match_clause(
    title_column: ColumnElement, body_column: ColumnElement, terms: list[str]
) -> ColumnElement:
    """Every term must appear somewhere in the title or the body (AND of ORs)."""
    return and_(
        *[or_(_contains(title_column, term), _contains(body_column, term)) for term in terms]
    )


def _score_expression(title_column: ColumnElement, query: str) -> ColumnElement:
    normalized = query.strip().lower()
    escaped = _escape_like(normalized)
    lowered = func.lower(title_column)
    return case(
        (lowered == normalized, _SCORE_EXACT),
        (lowered.like(f"{escaped}%", escape="\\"), _SCORE_PREFIX),
        (lowered.like(f"%{escaped}%", escape="\\"), _SCORE_CONTAINS),
        else_=_SCORE_BODY,
    )


def search_projects(
    db: Session,
    org_id: uuid.UUID,
    membership: Membership,
    query: str,
    *,
    limit: int = 20,
) -> list[tuple[Project, int]]:
    terms = tokenize(query)
    if not terms:
        return []

    score = _score_expression(Project.name, query)
    stmt = (
        select(Project, score.label("score"))
        .where(
            Project.organization_id == org_id,
            Project.deleted_at.is_(None),
            _match_clause(Project.name, func.coalesce(Project.description, ""), terms),
        )
        .order_by(score.desc(), Project.name, Project.id)
        .limit(limit)
    )

    visible = visible_project_condition(membership)
    if visible is not None:
        stmt = stmt.where(visible)

    return [(row[0], row[1]) for row in db.execute(stmt).all()]


def search_tasks(
    db: Session,
    org_id: uuid.UUID,
    membership: Membership,
    query: str,
    *,
    project_id: Optional[uuid.UUID] = None,
    limit: int = 20,
) -> list[tuple[Task, int]]:
    terms = tokenize(query)
    if not terms:
        return []

    score = _score_expression(Task.title, query)
    stmt = (
        select(Task, score.label("score"))
        .join(Project, Project.id == Task.project_id)
        .where(
            Project.organization_id == org_id,
            # A task inside a deleted project is unreachable through the API,
            # so surfacing it in search would be the one way back to it.
            Project.deleted_at.is_(None),
            Task.deleted_at.is_(None),
            _match_clause(Task.title, func.coalesce(Task.description, ""), terms),
        )
        .order_by(score.desc(), Task.created_at.desc(), Task.id)
        .limit(limit)
    )

    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)

    visible = visible_project_condition(membership)
    if visible is not None:
        stmt = stmt.where(visible)

    return [(row[0], row[1]) for row in db.execute(stmt).all()]
