from fastapi import APIRouter

from app.api.v1.routers import (
    attachments,
    audit_logs,
    auth,
    health,
    invitations,
    labels,
    memberships,
    milestones,
    notifications,
    organizations,
    project_members,
    projects,
    search,
    stats,
    task_checklist,
    task_comments,
    task_dependencies,
    task_labels,
    task_watchers,
    tasks,
    time_entries,
    users,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(organizations.router)
api_router.include_router(memberships.router)
api_router.include_router(projects.router)
api_router.include_router(project_members.router)
api_router.include_router(milestones.router)
api_router.include_router(tasks.router)
api_router.include_router(task_checklist.router)
api_router.include_router(task_comments.router)
api_router.include_router(task_dependencies.router)
api_router.include_router(task_labels.router)
api_router.include_router(task_watchers.router)
api_router.include_router(time_entries.router)
api_router.include_router(time_entries.report_router)
api_router.include_router(attachments.router)
api_router.include_router(labels.router)
api_router.include_router(invitations.router)
api_router.include_router(invitations.accept_router)
api_router.include_router(notifications.router)
api_router.include_router(search.router)
api_router.include_router(stats.router)
api_router.include_router(webhooks.router)
api_router.include_router(audit_logs.router)
