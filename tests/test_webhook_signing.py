"""Unit tests for the outbound signature scheme and the target-URL guard."""

import pytest

from app.core.webhook_signing import (
    build_signature_header,
    compute_signature,
    generate_secret,
    parse_signature_header,
    verify_signature,
)
from app.core.webhook_url import InvalidWebhookUrlError, validate_webhook_url

SECRET = "0123456789abcdef"
BODY = b'{"event":"task.created"}'


def test_generated_secrets_are_unique_and_long_enough():
    secrets = {generate_secret() for _ in range(10)}

    assert len(secrets) == 10
    assert all(len(secret) == 64 for secret in secrets)


def test_signature_is_deterministic_for_the_same_inputs():
    assert compute_signature(SECRET, 100, BODY) == compute_signature(SECRET, 100, BODY)


def test_signature_changes_with_the_timestamp():
    assert compute_signature(SECRET, 100, BODY) != compute_signature(SECRET, 101, BODY)


def test_signature_changes_with_the_secret():
    assert compute_signature(SECRET, 100, BODY) != compute_signature("other", 100, BODY)


def test_header_round_trips():
    header = build_signature_header(SECRET, BODY, timestamp=1_700_000_000)

    timestamp, signatures = parse_signature_header(header)

    assert timestamp == 1_700_000_000
    assert signatures == [compute_signature(SECRET, 1_700_000_000, BODY)]


def test_a_freshly_built_header_verifies():
    header = build_signature_header(SECRET, BODY, timestamp=1_700_000_000)

    assert verify_signature(SECRET, BODY, header, now=1_700_000_000)


def test_verification_fails_for_a_tampered_body():
    header = build_signature_header(SECRET, BODY, timestamp=1_700_000_000)

    assert not verify_signature(SECRET, BODY + b" ", header, now=1_700_000_000)


def test_verification_fails_for_the_wrong_secret():
    header = build_signature_header(SECRET, BODY, timestamp=1_700_000_000)

    assert not verify_signature("wrong", BODY, header, now=1_700_000_000)


def test_verification_rejects_a_replayed_request():
    header = build_signature_header(SECRET, BODY, timestamp=1_700_000_000)

    # Same body, same signature, but hours later.
    assert not verify_signature(SECRET, BODY, header, now=1_700_000_000 + 3600)


def test_verification_accepts_clock_skew_inside_the_tolerance():
    header = build_signature_header(SECRET, BODY, timestamp=1_700_000_000)

    assert verify_signature(SECRET, BODY, header, now=1_700_000_000 - 120)


@pytest.mark.parametrize(
    "header",
    ["", "garbage", "t=abc,v1=deadbeef", "v1=deadbeef", "t=1700000000", "t=1700000000,v9=x"],
)
def test_verification_rejects_malformed_headers(header):
    assert not verify_signature(SECRET, BODY, header, now=1_700_000_000)


# --- target URL validation --------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.example.com/orbit",
        "http://example.org:8080/path?x=1",
    ],
)
def test_public_urls_are_accepted(url):
    assert validate_webhook_url(url, resolve=False) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/hook",
        "http://[::1]/hook",
        "http://localhost/hook",
        "http://LOCALHOST./hook",
        "http://10.0.0.5/hook",
        "http://192.168.1.10/hook",
        "http://172.16.0.1/hook",
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/hook",
    ],
)
def test_internal_targets_are_rejected(url):
    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_url(url, resolve=False)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "ftp://example.com/hook",
        "file:///etc/passwd",
        "https://",
        "https://user:password@example.com/hook",
        "not-a-url",
    ],
)
def test_malformed_urls_are_rejected(url):
    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_url(url, resolve=False)


def test_https_can_be_required():
    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_url("http://example.com/hook", require_https=True, resolve=False)

    assert validate_webhook_url("https://example.com/hook", require_https=True, resolve=False)


def test_an_over_long_url_is_rejected():
    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_url("https://example.com/" + "a" * 2100, resolve=False)


def test_resolution_rejects_a_name_pointing_at_an_internal_address(monkeypatch):
    """A public-looking name aimed at an internal address is caught by DNS."""
    monkeypatch.setattr("app.core.webhook_url._resolved_addresses", lambda hostname: ["10.1.2.3"])

    with pytest.raises(InvalidWebhookUrlError):
        validate_webhook_url("http://sneaky.example.com/hook", resolve=True)


def test_resolution_allows_a_name_pointing_at_a_public_address(monkeypatch):
    monkeypatch.setattr(
        "app.core.webhook_url._resolved_addresses", lambda hostname: ["93.184.216.34"]
    )

    assert validate_webhook_url("http://example.com/hook", resolve=True)


def test_an_unresolvable_name_is_left_for_delivery_time(monkeypatch):
    """DNS being unavailable must not turn into a validation error for the user."""
    monkeypatch.setattr("app.core.webhook_url._resolved_addresses", lambda hostname: [])

    assert validate_webhook_url("http://nowhere.example.com/hook", resolve=True)


def test_address_is_deliverable_matches_the_validation_rules():
    from app.core.webhook_url import address_is_deliverable

    assert address_is_deliverable("93.184.216.34")
    assert not address_is_deliverable("127.0.0.1")
    assert not address_is_deliverable("10.0.0.1")
    assert not address_is_deliverable(None)
