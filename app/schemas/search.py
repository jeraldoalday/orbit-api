from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.project import ProjectRead
from app.schemas.task import TaskRead


class SearchHit(BaseModel):
    kind: Literal["project", "task"]
    score: int
    project: Optional[ProjectRead] = None
    task: Optional[TaskRead] = None


class SearchResults(BaseModel):
    query: str
    # How many hits are in `results`, not how many exist: search is capped
    # rather than paginated, so there is no offset that would reach any more.
    total: int
    results: list[SearchHit]
