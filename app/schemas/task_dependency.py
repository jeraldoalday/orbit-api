import uuid

from pydantic import BaseModel, ConfigDict

from app.models.task import TaskStatus


class TaskDependencyCreate(BaseModel):
    depends_on_id: uuid.UUID


class TaskRef(BaseModel):
    """Just enough of a task to render a dependency chip and link to it.

    Deliberately not `TaskRead`: a dependency list is a sidebar, and echoing
    every field of every neighbour makes the response grow with the graph.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: TaskStatus


class TaskDependencyGraph(BaseModel):
    """A task's immediate neighbourhood in the dependency graph."""

    blocked_by: list[TaskRef]
    blocks: list[TaskRef]
    # Blockers that are still open — the subset of `blocked_by` that is
    # actually stopping this task from being completed right now.
    open_blockers: list[TaskRef]
    is_blocked: bool
