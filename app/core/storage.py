"""Object storage for task attachments.

The API stores only metadata rows; the bytes live behind this interface so the
local filesystem used in development can be swapped for S3/GCS without any
caller changing. Everything above this module deals in opaque storage *keys*
and never in paths.
"""

import os
import re
import shutil
import unicodedata
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator
from functools import lru_cache
from typing import BinaryIO

from app.core.config import get_settings

# Read/write in chunks so a large upload never lands in memory in one piece.
CHUNK_SIZE = 64 * 1024

MAX_FILENAME_LENGTH = 255

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class StorageError(Exception):
    """Raised when the backing store cannot serve a key."""


class ObjectTooLargeError(Exception):
    """Raised when an upload exceeds the configured size ceiling."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"File exceeds the maximum size of {max_bytes} bytes")
        self.max_bytes = max_bytes


def sanitize_filename(filename: str) -> str:
    """Reduce a client-supplied filename to a safe, storable basename.

    Browsers and API clients send whatever they like here, including
    ``../../etc/passwd`` and NUL bytes. Only the basename survives, and only
    from a conservative character set, so a filename can never influence where
    the bytes land — that is decided by :func:`build_storage_key` alone.
    """
    # Normalize first: a decomposed "é" would otherwise be stripped to "e".
    normalized = unicodedata.normalize("NFKC", filename or "")
    # Both separators, because a Windows client sends backslashes.
    basename = normalized.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", basename).strip("._")

    if not cleaned:
        return "file"

    return cleaned[:MAX_FILENAME_LENGTH]


def build_storage_key(task_id: uuid.UUID, filename: str) -> str:
    """A collision-free key for one uploaded file.

    The random component means two people uploading ``report.pdf`` to the same
    task never overwrite each other, and the task prefix keeps a bucket
    listing browsable.
    """
    return f"tasks/{task_id}/{uuid.uuid4().hex}-{sanitize_filename(filename)}"


class ObjectStorage(ABC):
    """The contract every backend implements."""

    @abstractmethod
    def save(self, key: str, source: BinaryIO, *, max_bytes: int) -> int:
        """Persist ``source`` under ``key`` and return the number of bytes written.

        Raises :class:`ObjectTooLargeError` — after cleaning up the partial
        object — once more than ``max_bytes`` have been read.
        """

    @abstractmethod
    def open(self, key: str) -> BinaryIO:
        """Return a readable binary stream for ``key``."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove ``key``. Deleting a key that is already gone is not an error."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Whether ``key`` currently holds an object."""


class LocalObjectStorage(ObjectStorage):
    """Filesystem-backed storage, intended for development and tests."""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)

    def _path_for(self, key: str) -> str:
        # Defence in depth: keys are generated internally, but a stored key is
        # still user-adjacent data, and a traversal here would hand out
        # arbitrary files from the host.
        path = os.path.abspath(os.path.join(self.root, key))
        if path != self.root and not path.startswith(self.root + os.sep):
            raise StorageError(f"Refusing to resolve key outside the storage root: {key!r}")
        return path

    def save(self, key: str, source: BinaryIO, *, max_bytes: int) -> int:
        path = self._path_for(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        written = 0
        try:
            with open(path, "wb") as destination:
                for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
                    written += len(chunk)
                    if written > max_bytes:
                        raise ObjectTooLargeError(max_bytes)
                    destination.write(chunk)
        except Exception:
            # Never leave a half-written object behind for a failed upload:
            # its metadata row was never committed, so nothing would ever
            # reference it and nothing would ever clean it up.
            self.delete(key)
            raise

        return written

    def open(self, key: str) -> BinaryIO:
        path = self._path_for(key)
        try:
            return open(path, "rb")
        except OSError as exc:
            raise StorageError(f"Object is missing from storage: {key!r}") from exc

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path_for(key))
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise StorageError(f"Could not delete object: {key!r}") from exc

    def exists(self, key: str) -> bool:
        return os.path.isfile(self._path_for(key))

    def clear(self) -> None:
        """Drop everything under the root. Only for tests and local resets."""
        shutil.rmtree(self.root, ignore_errors=True)


def stream_object(storage: ObjectStorage, key: str) -> Iterator[bytes]:
    """Yield an object's bytes in chunks, closing the handle when exhausted."""
    handle = storage.open(key)
    try:
        yield from iter(lambda: handle.read(CHUNK_SIZE), b"")
    finally:
        handle.close()


@lru_cache
def get_storage() -> ObjectStorage:
    settings = get_settings()
    return LocalObjectStorage(settings.attachment_storage_dir)
