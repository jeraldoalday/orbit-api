"""HMAC signing for outbound webhook deliveries.

A receiver has no other way to tell an Orbit delivery from anyone who guessed
the endpoint URL, so every request carries a signature over its exact body.
The scheme mirrors the one Stripe popularised: a timestamp is signed alongside
the body, which lets a receiver reject a replayed-but-otherwise-valid request.
"""

import hashlib
import hmac
import secrets
import time
from typing import Optional

SIGNATURE_HEADER = "X-Orbit-Signature"
EVENT_HEADER = "X-Orbit-Event"
DELIVERY_HEADER = "X-Orbit-Delivery"

SIGNATURE_VERSION = "v1"

SECRET_BYTES = 32

# How far a delivery's timestamp may be from the receiver's clock. Generous
# enough for ordinary skew, short enough that a captured request stops being
# replayable the same day.
DEFAULT_TOLERANCE_SECONDS = 300


def generate_secret() -> str:
    """A fresh subscription secret, shown to the caller exactly once."""
    return secrets.token_hex(SECRET_BYTES)


def _signing_payload(timestamp: int, body: bytes) -> bytes:
    # The timestamp is inside the signed material, not merely alongside it —
    # otherwise an attacker could replay an old body under a fresh timestamp.
    return f"{timestamp}.".encode() + body


def compute_signature(secret: str, timestamp: int, body: bytes) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), _signing_payload(timestamp, body), hashlib.sha256
    ).hexdigest()
    return digest


def build_signature_header(secret: str, body: bytes, *, timestamp: Optional[int] = None) -> str:
    """The full header value, e.g. ``t=1712345678,v1=<hex>``.

    The version prefix leaves room to roll the algorithm forward: a receiver
    that understands several can accept both during a migration.
    """
    stamp = int(time.time()) if timestamp is None else timestamp
    return f"t={stamp},{SIGNATURE_VERSION}={compute_signature(secret, stamp, body)}"


def parse_signature_header(header: str) -> tuple[Optional[int], list[str]]:
    """Split a header value into its timestamp and its candidate signatures.

    Returns ``(None, [])`` rather than raising on anything malformed: a caller
    verifying an untrusted header should get a plain verification failure, not
    an exception to handle separately.
    """
    timestamp: Optional[int] = None
    signatures: list[str] = []

    for part in (header or "").split(","):
        key, separator, value = part.strip().partition("=")
        if not separator:
            continue
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return None, []
        elif key == SIGNATURE_VERSION:
            signatures.append(value)

    return timestamp, signatures


def verify_signature(
    secret: str,
    body: bytes,
    header: str,
    *,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: Optional[int] = None,
) -> bool:
    """Whether ``header`` is a valid, in-date signature of ``body``.

    Shipped as part of the API rather than left to each consumer because this
    is the half of the scheme that is easy to get wrong — and it is what the
    test suite uses to prove the sent header is verifiable.
    """
    timestamp, signatures = parse_signature_header(header)
    if timestamp is None or not signatures:
        return False

    current = int(time.time()) if now is None else now
    if abs(current - timestamp) > tolerance_seconds:
        return False

    expected = compute_signature(secret, timestamp, body)
    # compare_digest, not ==, so the check doesn't leak the correct prefix
    # length through its timing.
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)
