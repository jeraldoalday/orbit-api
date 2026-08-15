import uuid

from pydantic import BaseModel


class TaskLabelAttach(BaseModel):
    label_id: uuid.UUID
