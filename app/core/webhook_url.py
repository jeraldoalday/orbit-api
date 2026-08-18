"""Validation for caller-supplied webhook target URLs.

An org admin gets to name an arbitrary URL that this server will then make
requests to, which is the classic setup for server-side request forgery: the
target might be the metadata service, an internal admin panel, or anything
else reachable from inside the network but not from the caller's own machine.
"""

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse

ALLOWED_SCHEMES = frozenset({"http", "https"})

MAX_URL_LENGTH = 2048

# Hostnames that resolve to the local machine no matter what DNS says.
_BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", "ip6-localhost"})


class InvalidWebhookUrlError(ValueError):
    """Raised when a target URL is malformed or points somewhere it may not."""


def _is_blocked_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolved_addresses(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        # A name that doesn't resolve isn't necessarily an attack — DNS may
        # simply be unavailable here — so leave the decision to delivery time,
        # where the same check runs again against the address actually used.
        return []
    return [info[4][0] for info in infos]


def validate_webhook_url(raw_url: str, *, require_https: bool = False, resolve: bool = True) -> str:
    """Return the normalized URL, or raise :class:`InvalidWebhookUrlError`.

    DNS resolution here is a best-effort filter, not a guarantee: a name can
    resolve differently between this check and the actual request (DNS
    rebinding). The delivery worker therefore re-checks the address it is about
    to connect to, and this validation exists to reject the obvious mistakes
    at the point where a human can still see the error message.
    """
    url = (raw_url or "").strip()
    if not url:
        raise InvalidWebhookUrlError("Webhook URL must not be blank")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidWebhookUrlError(f"Webhook URL must be at most {MAX_URL_LENGTH} characters")

    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise InvalidWebhookUrlError("Webhook URL must use http or https")
    if require_https and parsed.scheme != "https":
        raise InvalidWebhookUrlError("Webhook URL must use https")
    if not parsed.hostname:
        raise InvalidWebhookUrlError("Webhook URL must include a host")
    if parsed.username or parsed.password:
        raise InvalidWebhookUrlError("Webhook URL must not embed credentials")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in _BLOCKED_HOSTNAMES:
        raise InvalidWebhookUrlError("Webhook URL must not point at localhost")
    if _is_blocked_address(hostname):
        raise InvalidWebhookUrlError("Webhook URL must not point at a private or reserved address")

    if resolve:
        for address in _resolved_addresses(hostname):
            if _is_blocked_address(address):
                raise InvalidWebhookUrlError(
                    "Webhook URL resolves to a private or reserved address"
                )

    return url


def resolve_primary_address(url: str) -> Optional[str]:
    """The first address a URL's host resolves to, or None if it can't be resolved.

    Used at delivery time so a hostname that was public when the subscription
    was created is re-checked against where it points now.
    """
    hostname = urlparse(url).hostname
    if not hostname:
        return None

    addresses = _resolved_addresses(hostname.lower().rstrip("."))
    return addresses[0] if addresses else None


def address_is_deliverable(address: Optional[str]) -> bool:
    """Whether the worker may open a connection to ``address``."""
    if not address:
        return False
    return not _is_blocked_address(address)
