"""The worker loop's control flow, independent of any HTTP or database work."""

import app.worker as worker
from app.core.webhook_transport import HttpxTransport, TransportError
from app.services.webhook_delivery_service import DispatchSummary


class _StubTransport:
    def post(self, url, body, headers, *, timeout):  # pragma: no cover - never called
        raise AssertionError("the stub transport should not be used")


class _StubSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_run_once_dispatches_with_the_configured_settings(monkeypatch):
    """Every webhook setting that governs a pass must reach dispatch_pending untouched."""
    session = _StubSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)

    captured = {}

    def _dispatch_pending(db, transport, **kwargs):
        captured["db"] = db
        captured["transport"] = transport
        captured.update(kwargs)
        return DispatchSummary(attempted=3, succeeded=3)

    monkeypatch.setattr(worker, "dispatch_pending", _dispatch_pending)

    transport = _StubTransport()
    summary = worker.run_once(transport)

    settings = worker.get_settings()
    assert summary.attempted == 3
    assert captured["db"] is session
    assert captured["transport"] is transport
    assert captured["limit"] == settings.webhook_batch_size
    assert captured["max_attempts"] == settings.webhook_max_attempts
    assert captured["timeout_seconds"] == settings.webhook_timeout_seconds
    assert captured["backoff_base_seconds"] == settings.webhook_backoff_base_seconds
    assert captured["lease_seconds"] == settings.webhook_lease_seconds
    assert captured["verify_target"] == settings.webhook_validate_dns
    # Closed once the pass is done, so a long-lived session never outlives it.
    assert session.closed is True


def test_run_once_closes_the_session_even_when_the_pass_fails(monkeypatch):
    session = _StubSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)

    def _explode(db, transport, **kwargs):
        raise RuntimeError("dispatch failed")

    monkeypatch.setattr(worker, "dispatch_pending", _explode)

    try:
        worker.run_once(_StubTransport())
    except RuntimeError:
        pass
    else:  # pragma: no cover - the call must not succeed
        raise AssertionError("expected a RuntimeError")

    assert session.closed is True


def test_run_once_defaults_to_an_httpx_transport_when_none_is_given(monkeypatch):
    session = _StubSession()
    monkeypatch.setattr(worker, "SessionLocal", lambda: session)

    captured = {}

    def _dispatch_pending(db, transport, **kwargs):
        captured["transport"] = transport
        return DispatchSummary()

    monkeypatch.setattr(worker, "dispatch_pending", _dispatch_pending)

    worker.run_once()

    assert isinstance(captured["transport"], HttpxTransport)


def test_run_forever_stops_after_a_shutdown_signal(monkeypatch):
    flag = worker._ShutdownFlag()
    passes = []

    def _run_once(transport):
        passes.append(transport)
        flag.request_stop(15, None)
        return DispatchSummary(attempted=1, succeeded=1)

    monkeypatch.setattr(worker, "run_once", _run_once)

    worker.run_forever(_StubTransport(), flag=flag)

    assert len(passes) == 1


def test_run_forever_sleeps_when_a_pass_is_empty(monkeypatch):
    flag = worker._ShutdownFlag()
    sleeps = []

    def _run_once(transport):
        flag.request_stop(15, None)
        return DispatchSummary()

    monkeypatch.setattr(worker, "run_once", _run_once)
    monkeypatch.setattr(worker.time, "sleep", sleeps.append)

    worker.run_forever(_StubTransport(), idle_sleep_seconds=2.5, flag=flag)

    assert sleeps == [2.5]


def test_a_failing_pass_does_not_stop_the_worker(monkeypatch):
    """A dropped database connection must not take the worker down."""
    flag = worker._ShutdownFlag()
    calls = []

    def _run_once(transport):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database went away")
        flag.request_stop(15, None)
        return DispatchSummary(attempted=1, succeeded=1)

    monkeypatch.setattr(worker, "run_once", _run_once)
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: None)

    worker.run_forever(_StubTransport(), flag=flag)

    assert len(calls) == 2


def test_the_shutdown_flag_starts_clear_and_latches():
    flag = worker._ShutdownFlag()

    assert flag.stopping is False
    flag.request_stop(15, None)
    assert flag.stopping is True


def test_httpx_transport_wraps_client_errors(monkeypatch):
    import httpx

    def _explode(*_args, **_kwargs):
        raise httpx.ConnectTimeout("too slow")

    monkeypatch.setattr(httpx, "post", _explode)

    try:
        HttpxTransport().post("https://example.com/hook", b"{}", {}, timeout=1.0)
    except TransportError as exc:
        assert "ConnectTimeout" in str(exc)
    else:  # pragma: no cover - the call must not succeed
        raise AssertionError("expected a TransportError")


def test_httpx_transport_returns_the_status_code(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(202))

    response = HttpxTransport().post("https://example.com/hook", b"{}", {}, timeout=1.0)

    assert response.status_code == 202


def test_httpx_transport_does_not_follow_redirects(monkeypatch):
    """A 3xx would hand a body signed for one host to another."""
    import httpx

    captured = {}

    def _capture(*_args, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", _capture)

    HttpxTransport().post("https://example.com/hook", b"{}", {}, timeout=3.0)

    assert captured["follow_redirects"] is False
    assert captured["timeout"] == 3.0
