from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from app.schemas.task_activity import TaskActivityRead
from app.schemas.task_comment import TaskCommentRead


class TaskTimelineEntry(BaseModel):
    kind: Literal["comment", "activity"]
    created_at: datetime
    comment: Optional[TaskCommentRead] = None
    activity: Optional[TaskActivityRead] = None
