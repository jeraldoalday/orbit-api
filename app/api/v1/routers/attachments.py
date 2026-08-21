import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_task_or_404, require_project_role
from app.core.config import get_settings
from app.core.storage import (
    ObjectStorage,
    ObjectTooLargeError,
    StorageError,
    get_storage,
    stream_object,
)
from app.db.session import get_db
from app.models.attachment import Attachment
from app.models.project_member import ProjectRole
from app.models.task import Task
from app.models.user import User
from app.schemas.attachment import AttachmentQuota, AttachmentRead
from app.services.attachment_service import (
    AttachmentLimitError,
    AttachmentQuotaError,
    EmptyUploadError,
    count_attachments,
    create_attachment,
    delete_attachment,
    get_attachment,
    list_attachments,
    total_bytes,
)

settings = get_settings()

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/tasks/{task_id}/attachments",
    tags=["attachments"],
)


def _content_disposition(filename: str) -> str:
    """Offer the original name as a download without letting it break the header.

    ``filename*`` carries the percent-encoded UTF-8 name for clients that
    understand RFC 5987; the plain ``filename`` stays for those that don't.
    """
    return f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"


def _get_attachment_or_404(
    attachment_id: uuid.UUID,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
) -> Attachment:
    attachment = get_attachment(db, task.id, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    return attachment


@router.post("", response_model=AttachmentRead, status_code=status.HTTP_201_CREATED)
def upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    current_user: User = Depends(get_current_active_user),
    storage: ObjectStorage = Depends(get_storage),
) -> AttachmentRead:
    try:
        return create_attachment(
            db,
            storage,
            task,
            filename=file.filename or "file",
            content_type=file.content_type,
            source=file.file,
            uploader=current_user,
            max_bytes=settings.attachment_max_bytes,
            max_per_task=settings.attachment_max_per_task,
            max_total_bytes=settings.attachment_max_total_bytes_per_task,
        )
    except ObjectTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc
    except (AttachmentLimitError, AttachmentQuotaError, EmptyUploadError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("", response_model=list[AttachmentRead])
def list_for_task(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[AttachmentRead]:
    return list_attachments(db, task.id, limit=limit, offset=offset)


@router.get("/quota", response_model=AttachmentQuota)
def quota(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> AttachmentQuota:
    used = count_attachments(db, task.id)
    used_bytes = total_bytes(db, task.id)
    max_total = settings.attachment_max_total_bytes_per_task
    return AttachmentQuota(
        max_bytes=settings.attachment_max_bytes,
        max_per_task=settings.attachment_max_per_task,
        used=used,
        remaining=max(settings.attachment_max_per_task - used, 0),
        max_total_bytes=max_total,
        used_bytes=used_bytes,
        remaining_bytes=max(max_total - used_bytes, 0),
    )


@router.get("/{attachment_id}/download")
def download(
    attachment: Attachment = Depends(_get_attachment_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    storage: ObjectStorage = Depends(get_storage),
) -> StreamingResponse:
    try:
        stream = stream_object(storage, attachment.storage_key)
    except StorageError as exc:
        # The row outlived its object. That's a server-side inconsistency, not
        # a missing resource, so don't tell the caller the file never existed.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Attachment is missing from storage",
        ) from exc

    return StreamingResponse(
        stream,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": _content_disposition(attachment.filename),
            "Content-Length": str(attachment.size_bytes),
            # Never let a browser sniff an uploaded blob into something
            # executable regardless of what content type we recorded.
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    attachment: Attachment = Depends(_get_attachment_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    delete_attachment(db, storage, attachment)
