"""The HTTP side of webhook delivery, behind an interface.

Keeping the transport abstract means the delivery logic — retries, backoff,
signing — can be tested without a network, and the HTTP client can be swapped
without touching any of it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class TransportError(Exception):
    """A delivery attempt that never produced an HTTP status.

    Timeouts, DNS failures and refused connections all land here; they are
    retryable in exactly the same way a 5xx is.
    """


@dataclass(frozen=True)
class TransportResponse:
    status_code: int


class WebhookTransport(ABC):
    @abstractmethod
    def post(
        self, url: str, body: bytes, headers: dict, *, timeout: float
    ) -> TransportResponse:
        """POST ``body`` to ``url``, or raise :class:`TransportError`."""


class HttpxTransport(WebhookTransport):
    """The production transport."""

    def post(
        self, url: str, body: bytes, headers: dict, *, timeout: float
    ) -> TransportResponse:
        import httpx

        try:
            # Redirects are not followed: a 3xx to somewhere else would sign a
            # body for one host and hand it to another, and it is the standard
            # way to smuggle a delivery past the target validation.
            response = httpx.post(
                url, content=body, headers=headers, timeout=timeout, follow_redirects=False
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc

        return TransportResponse(status_code=response.status_code)
