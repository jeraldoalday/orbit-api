import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

RATE_LIMIT_HEADER = "X-RateLimit-Limit"
RATE_LIMIT_REMAINING_HEADER = "X-RateLimit-Remaining"
RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"
RETRY_AFTER_HEADER = "Retry-After"

# Liveness probes shouldn't be able to exhaust a caller's budget, and a limiter
# that throttles the health check makes an outage look worse than it is.
EXEMPT_PATHS = frozenset({"/api/v1/health", "/api/v1/health/db"})

# Credential endpoints get their own, much tighter budget: these are the ones
# worth brute-forcing, and a legitimate client hits them once per session.
AUTH_PATHS = frozenset({"/api/v1/auth/login", "/api/v1/auth/register"})


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class SlidingWindowRateLimiter:
    """In-process sliding-window limiter.

    Keeps the timestamps of recent requests per key and counts the ones still
    inside the window. A sliding window avoids the burst-at-the-boundary
    problem of fixed windows, where a caller can spend two full budgets in the
    instant either side of a window rollover.

    State lives in this process, so with multiple workers the effective limit
    is per-worker. That's a deliberate trade: it needs no external dependency
    and still bounds a single client's blast radius. A shared store belongs
    here once the service runs behind more than one process.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        *,
        max_keys: int = 10_000,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._time = time_source
        # Ordered by least-recently-used so eviction is O(1) at the front.
        self._hits: "OrderedDict[str, deque[float]]" = OrderedDict()

    def _prune(self, hits: deque, now: float) -> None:
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()

    def _evict_if_needed(self) -> None:
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)

    def check(self, key: str) -> RateLimitDecision:
        now = self._time()
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        else:
            self._hits.move_to_end(key)

        self._prune(hits, now)

        if len(hits) >= self.limit:
            # The oldest hit in the window is the one that frees a slot.
            retry_after = max(1, int(self.window_seconds - (now - hits[0])) + 1)
            return RateLimitDecision(
                allowed=False, limit=self.limit, remaining=0, retry_after=retry_after
            )

        hits.append(now)
        self._evict_if_needed()
        return RateLimitDecision(
            allowed=True,
            limit=self.limit,
            remaining=self.limit - len(hits),
            retry_after=0,
        )

    def reset(self) -> None:
        self._hits.clear()


def client_key(request: Request) -> str:
    """Identify the caller, preferring the original IP behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # Left-most entry is the original client; the rest are proxy hops.
        return forwarded.split(",")[0].strip()
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


# Module-level so the counters survive middleware re-instantiation and so
# tests (and an admin endpoint, later) have one place to clear them from.
_settings = get_settings()
general_limiter = SlidingWindowRateLimiter(
    _settings.rate_limit_requests, _settings.rate_limit_window_seconds
)
auth_limiter = SlidingWindowRateLimiter(
    _settings.auth_rate_limit_requests, _settings.auth_rate_limit_window_seconds
)


def reset_rate_limits() -> None:
    general_limiter.reset()
    auth_limiter.reset()


def limiter_for(path: str) -> Optional[SlidingWindowRateLimiter]:
    if path in EXEMPT_PATHS:
        return None
    if path in AUTH_PATHS:
        return auth_limiter
    return general_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, enabled: Optional[bool] = None) -> None:
        super().__init__(app)
        self.enabled = get_settings().rate_limit_enabled if enabled is None else enabled

    async def dispatch(self, request: Request, call_next) -> Response:
        limiter = limiter_for(request.url.path) if self.enabled else None
        if limiter is None:
            return await call_next(request)

        # Auth and general budgets are tracked separately, so the key is
        # namespaced by bucket; otherwise a login attempt would also consume
        # the caller's general allowance.
        decision = limiter.check(f"{id(limiter)}:{client_key(request)}")

        if not decision.allowed:
            response: Response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry shortly."},
            )
            response.headers[RETRY_AFTER_HEADER] = str(decision.retry_after)
            response.headers[RATE_LIMIT_RESET_HEADER] = str(decision.retry_after)
        else:
            response = await call_next(request)

        response.headers[RATE_LIMIT_HEADER] = str(decision.limit)
        response.headers[RATE_LIMIT_REMAINING_HEADER] = str(decision.remaining)
        return response
