from fastapi import APIRouter

from app.api.v1.routers import (
    auth,
    health,
    invitations,
    labels,
    memberships,
    organizations,
    project_members,
    projects,
    task_comments,
    task_labels,
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
api_router.include_router(project_members.router)
api_router.include_router(tasks.router)
api_router.include_router(task_comments.router)
api_router.include_router(task_labels.router)
api_router.include_router(labels.router)
api_router.include_router(invitations.router)
api_router.include_router(invitations.accept_router)
