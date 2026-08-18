import logging
import uuid
from typing import BinaryIO, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.storage import (
    ObjectStorage,
    ObjectTooLargeError,
    build_storage_key,
    sanitize_filename,
)
from app.models.attachment import Attachment
from app.models.task import Task
from app.models.user import User

logger = logging.getLogger("app.attachments")

DEFAULT_CONTENT_TYPE = "application/octet-stream"

MAX_CONTENT_TYPE_LENGTH = 100


class AttachmentLimitError(Exception):
    """Raised when a task already holds as many attachments as it may."""


class EmptyUploadError(Exception):
    """Raised when the uploaded body contains no bytes at all."""


def _normalize_content_type(content_type: Optional[str]) -> str:
    """Keep only the media type, discarding parameters and any client noise.

    The value is echoed back in the download response's ``Content-Type``, so a
    header like ``text/html; charset=utf-8`` from an untrusted uploader must
    not survive verbatim into a response a browser will render.
    """
    if not content_type:
        return DEFAULT_CONTENT_TYPE

    media_type = content_type.split(";", 1)[0].strip().lower()
    if not media_type or "/" not in media_type:
        return DEFAULT_CONTENT_TYPE
    if any(character.isspace() for character in media_type):
        return DEFAULT_CONTENT_TYPE

    return media_type[:MAX_CONTENT_TYPE_LENGTH]


def count_attachments(db: Session, task_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(Attachment).where(Attachment.task_id == task_id)
    return db.execute(stmt).scalar_one()


def total_bytes(db: Session, task_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.sum(Attachment.size_bytes), 0)).where(
        Attachment.task_id == task_id
    )
    return int(db.execute(stmt).scalar_one())


def create_attachment(
    db: Session,
    storage: ObjectStorage,
    task: Task,
    *,
    filename: str,
    content_type: Optional[str],
    source: BinaryIO,
    uploader: User,
    max_bytes: int,
    max_per_task: int,
) -> Attachment:
    """Stream an upload into storage and record its metadata.

    The object is written before the row is inserted, so a failure part-way
    through leaves at worst an orphaned object (which the storage layer already
    removes) rather than a row pointing at bytes that were never stored.
    """
    if count_attachments(db, task.id) >= max_per_task:
        raise AttachmentLimitError(
            f"A task may have at most {max_per_task} attachments"
        )

    safe_filename = sanitize_filename(filename)
    storage_key = build_storage_key(task.id, safe_filename)

    size_bytes = storage.save(storage_key, source, max_bytes=max_bytes)
    if size_bytes == 0:
        storage.delete(storage_key)
        raise EmptyUploadError("Uploaded file is empty")

    attachment = Attachment(
        task_id=task.id,
        uploaded_by_id=uploader.id,
        filename=safe_filename,
        content_type=_normalize_content_type(content_type),
        size_bytes=size_bytes,
        storage_key=storage_key,
    )
    db.add(attachment)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(storage_key)
        raise
    db.refresh(attachment)
    return attachment


def list_attachments(
    db: Session, task_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> list[Attachment]:
    stmt = (
        select(Attachment)
        .options(joinedload(Attachment.uploaded_by))
        .where(Attachment.task_id == task_id)
        .order_by(Attachment.created_at, Attachment.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def get_attachment(
    db: Session, task_id: uuid.UUID, attachment_id: uuid.UUID
) -> Optional[Attachment]:
    stmt = select(Attachment).where(
        Attachment.id == attachment_id, Attachment.task_id == task_id
    )
    return db.execute(stmt).scalar_one_or_none()


def storage_keys_for_task(db: Session, task_id: uuid.UUID) -> list[str]:
    stmt = select(Attachment.storage_key).where(Attachment.task_id == task_id)
    return list(db.execute(stmt).scalars().all())


def storage_keys_for_project(db: Session, project_id: uuid.UUID) -> list[str]:
    stmt = (
        select(Attachment.storage_key)
        .join(Task, Task.id == Attachment.task_id)
        .where(Task.project_id == project_id)
    )
    return list(db.execute(stmt).scalars().all())


def delete_objects(storage: ObjectStorage, keys: list[str]) -> int:
    """Best-effort removal of stored objects whose rows are already gone.

    One key failing must not abort the rest: the metadata is committed by this
    point, so raising here would leave *more* objects orphaned than carrying on
    does. Failures are logged so the leak is at least visible.
    """
    removed = 0
    for key in keys:
        try:
            storage.delete(key)
            removed += 1
        except Exception:
            logger.exception("failed to delete stored object", extra={"storage_key": key})
    return removed


def delete_attachment(db: Session, storage: ObjectStorage, attachment: Attachment) -> None:
    """Remove the row first, then the object.

    The other order would delete the bytes and then, if the commit failed,
    leave a row promising a download that can never succeed. This way the worst
    case is an orphaned object, which costs storage but never breaks a read.
    """
    storage_key = attachment.storage_key
    db.delete(attachment)
    db.commit()
    storage.delete(storage_key)


__all__ = [
    "AttachmentLimitError",
    "EmptyUploadError",
    "ObjectTooLargeError",
    "count_attachments",
    "create_attachment",
    "delete_attachment",
    "delete_objects",
    "get_attachment",
    "list_attachments",
    "storage_keys_for_project",
    "storage_keys_for_task",
    "total_bytes",
]
