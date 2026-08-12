from fastapi import APIRouter

from app.api.v1.routers import (
    auth,
    health,
    memberships,
    organizations,
    projects,
    task_comments,
    tasks,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(organizations.router)
api_router.include_router(memberships.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(task_comments.router)
