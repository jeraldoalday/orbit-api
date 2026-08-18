import json
import logging
import sys
import time
from contextvars import ContextVar
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Set by RequestIDMiddleware and read by the formatter, so every log line
# emitted anywhere inside a request carries its correlation id without each
# call site having to thread the id through.
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

# LogRecord's own attributes; anything else on the record was passed by the
# caller via `extra=` and belongs in the JSON payload.
_RESERVED_RECORD_KEYS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }
)


class JSONFormatter(logging.Formatter):
    """Render log records as one JSON object per line.

    Log aggregators parse fields far more reliably than they parse prose, and a
    single line per event keeps multi-line tracebacks from being split into
    separate entries downstream.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Point the root logger at a single JSON stdout handler.

    Handlers are replaced rather than appended so repeated calls (reload, tests)
    don't produce duplicate lines.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Uvicorn installs its own colourized handlers; drop them so access and
    # error lines go through the same JSON pipeline as application logs.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


access_logger = logging.getLogger("orbit.access")


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Emit one structured line per request, including its duration."""

    async def dispatch(self, request: Request, call_next) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # An unhandled error still deserves a timed access line; without
            # this the request would simply vanish from the log.
            access_logger.exception(
                "request failed",
                extra={
                    "http_method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        access_logger.info(
            "request completed",
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
