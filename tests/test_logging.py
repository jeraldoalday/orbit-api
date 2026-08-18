import json
import logging

import pytest

from app.core.logging import (
    AccessLogMiddleware,
    JSONFormatter,
    configure_logging,
    request_id_var,
)


@pytest.fixture()
def formatter():
    return JSONFormatter()


def _record(**kwargs):
    defaults = {
        "name": "orbit.test",
        "level": logging.INFO,
        "pathname": __file__,
        "lineno": 1,
        "msg": "hello",
        "args": (),
        "exc_info": None,
    }
    defaults.update(kwargs)
    return logging.LogRecord(**defaults)


def test_formatter_emits_valid_json(formatter):
    payload = json.loads(formatter.format(_record()))

    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "orbit.test"
    assert "timestamp" in payload


def test_formatter_emits_a_single_line(formatter):
    """Multi-line output would be split into separate entries downstream."""
    record = _record(msg="line one\nline two")

    assert "\n" not in formatter.format(record)


def test_formatter_includes_extra_fields(formatter):
    record = _record()
    record.status_code = 201
    record.path = "/api/v1/tasks"

    payload = json.loads(formatter.format(record))

    assert payload["status_code"] == 201
    assert payload["path"] == "/api/v1/tasks"


def test_formatter_includes_request_id_from_context(formatter):
    token = request_id_var.set("abc-123")
    try:
        payload = json.loads(formatter.format(_record()))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "abc-123"


def test_formatter_omits_request_id_outside_a_request(formatter):
    payload = json.loads(formatter.format(_record()))

    assert "request_id" not in payload


def test_formatter_renders_exceptions(formatter):
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = _record(exc_info=sys.exc_info())

    payload = json.loads(formatter.format(record))

    assert "ValueError: boom" in payload["exception"]


def test_formatter_serializes_unjsonable_values(formatter):
    record = _record()
    record.weird = object()

    payload = json.loads(formatter.format(record))

    assert payload["weird"].startswith("<object")


def test_configure_logging_replaces_handlers():
    configure_logging("INFO")
    configure_logging("INFO")

    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JSONFormatter)


def test_configure_logging_sets_level():
    try:
        configure_logging("warning")
        assert logging.getLogger().level == logging.WARNING
    finally:
        configure_logging("INFO")


def test_uvicorn_loggers_are_routed_through_the_json_handler():
    configure_logging("INFO")

    assert logging.getLogger("uvicorn.access").handlers == []
    assert logging.getLogger("uvicorn.access").propagate is True


def test_access_log_records_method_path_and_status(client, caplog):
    with caplog.at_level(logging.INFO, logger="orbit.access"):
        client.get("/api/v1/health")

    record = next(r for r in caplog.records if r.name == "orbit.access")
    assert record.http_method == "GET"
    assert record.path == "/api/v1/health"
    assert record.status_code == 200
    assert record.duration_ms >= 0


def test_access_log_records_error_statuses(client, caplog):
    with caplog.at_level(logging.INFO, logger="orbit.access"):
        client.get("/api/v1/notifications")

    record = next(r for r in caplog.records if r.name == "orbit.access")
    assert record.status_code == 401


def test_request_id_context_is_cleared_after_the_request(client):
    client.get("/api/v1/health")

    assert request_id_var.get() is None


def test_request_id_header_is_reused_when_supplied(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "trace-me"})

    assert response.headers["X-Request-ID"] == "trace-me"


def test_access_middleware_is_installed():
    from app.main import app

    assert any(m.cls is AccessLogMiddleware for m in app.user_middleware)
