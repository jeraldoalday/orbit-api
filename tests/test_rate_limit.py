import pytest

from app.core.rate_limit import (
    SlidingWindowRateLimiter,
    auth_limiter,
    client_key,
    general_limiter,
    limiter_for,
)


class _FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_limiter_allows_up_to_the_limit():
    limiter = SlidingWindowRateLimiter(3, 60, time_source=_FakeClock())

    decisions = [limiter.check("caller") for _ in range(3)]

    assert [d.allowed for d in decisions] == [True, True, True]
    assert [d.remaining for d in decisions] == [2, 1, 0]


def test_limiter_blocks_past_the_limit():
    limiter = SlidingWindowRateLimiter(2, 60, time_source=_FakeClock())
    limiter.check("caller")
    limiter.check("caller")

    decision = limiter.check("caller")

    assert decision.allowed is False
    assert decision.remaining == 0
    assert decision.retry_after > 0


def test_limiter_window_slides():
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(2, 60, time_source=clock)
    limiter.check("caller")
    limiter.check("caller")
    assert limiter.check("caller").allowed is False

    clock.advance(61)

    assert limiter.check("caller").allowed is True


def test_limiter_window_slides_partially():
    """Only the hits that aged out should free capacity, not the whole window."""
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(2, 60, time_source=clock)
    limiter.check("caller")
    clock.advance(30)
    limiter.check("caller")

    clock.advance(31)  # the first hit is now outside the window, the second isn't

    first = limiter.check("caller")
    second = limiter.check("caller")
    assert first.allowed is True
    assert second.allowed is False


def test_limiter_keys_are_independent():
    limiter = SlidingWindowRateLimiter(1, 60, time_source=_FakeClock())
    limiter.check("alice")

    assert limiter.check("bob").allowed is True
    assert limiter.check("alice").allowed is False


def test_limiter_evicts_least_recently_used_keys():
    limiter = SlidingWindowRateLimiter(5, 60, max_keys=2, time_source=_FakeClock())

    for key in ["a", "b", "c", "d"]:
        limiter.check(key)

    assert len(limiter._hits) <= 2


def test_limiter_reset_clears_state():
    limiter = SlidingWindowRateLimiter(1, 60, time_source=_FakeClock())
    limiter.check("caller")

    limiter.reset()

    assert limiter.check("caller").allowed is True


def test_retry_after_reflects_time_left_in_window():
    clock = _FakeClock()
    limiter = SlidingWindowRateLimiter(1, 60, time_source=clock)
    limiter.check("caller")
    clock.advance(20)

    decision = limiter.check("caller")

    assert decision.allowed is False
    assert 39 <= decision.retry_after <= 42


def test_health_endpoints_are_exempt():
    assert limiter_for("/api/v1/health") is None
    assert limiter_for("/api/v1/health/db") is None


def test_auth_paths_use_the_stricter_limiter():
    assert limiter_for("/api/v1/auth/login") is auth_limiter
    assert limiter_for("/api/v1/auth/register") is auth_limiter
    assert limiter_for("/api/v1/organizations") is general_limiter


class _FakeRequest:
    def __init__(self, headers=None, host=None):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})() if host is not None else None


def test_client_key_ignores_forwarded_for_by_default():
    """Without a known proxy in front, the header is just caller input."""
    request = _FakeRequest(headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"}, host="10.0.0.1")

    assert client_key(request) == "10.0.0.1"


def test_client_key_prefers_forwarded_for_when_proxy_is_trusted():
    request = _FakeRequest(headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"}, host="10.0.0.1")

    assert client_key(request, trust_proxy=True) == "203.0.113.5"


def test_client_key_falls_back_to_peer_address():
    assert client_key(_FakeRequest(host="198.51.100.9")) == "198.51.100.9"


def test_client_key_handles_missing_client():
    assert client_key(_FakeRequest()) == "unknown"


def test_responses_carry_rate_limit_headers(client):
    response = client.get("/api/v1/notifications")

    assert response.headers["X-RateLimit-Limit"] == "300"
    assert int(response.headers["X-RateLimit-Remaining"]) < 300


def test_health_response_has_no_rate_limit_headers(client):
    response = client.get("/api/v1/health")

    assert "X-RateLimit-Limit" not in response.headers


@pytest.mark.parametrize("path", ["/api/v1/auth/login", "/api/v1/auth/register"])
def test_auth_endpoints_are_throttled(client, path):
    payload = {"email": "nobody@example.com", "password": "wrongpassword", "full_name": "N"}

    statuses = [client.post(path, json=payload).status_code for _ in range(12)]

    assert 429 in statuses
    assert statuses[0] != 429


def test_throttled_response_includes_retry_after(client):
    payload = {"email": "nobody@example.com", "password": "wrongpassword"}
    for _ in range(12):
        response = client.post("/api/v1/auth/login", json=payload)
        if response.status_code == 429:
            break

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.json()["detail"].startswith("Rate limit exceeded")


def test_throttled_response_still_carries_a_request_id(client):
    payload = {"email": "nobody@example.com", "password": "wrongpassword"}
    for _ in range(12):
        response = client.post("/api/v1/auth/login", json=payload)
        if response.status_code == 429:
            break

    assert response.status_code == 429
    assert response.headers["X-Request-ID"]
