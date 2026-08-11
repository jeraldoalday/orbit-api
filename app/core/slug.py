import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.organization import Organization

_SLUG_INVALID_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    slug = _SLUG_INVALID_CHARS.sub("-", text.lower()).strip("-")
    return slug or "org"


def generate_unique_org_slug(db: Session, name: str) -> str:
    base_slug = slugify(name)
    slug = base_slug

    while db.execute(select(Organization).where(Organization.slug == slug)).first() is not None:
        slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    return slug
