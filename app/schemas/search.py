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
    total: int
    results: list[SearchHit]
