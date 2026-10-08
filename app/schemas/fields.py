from typing import Annotated

from pydantic import AfterValidator, Field

MAX_NAME_LENGTH = 200
MAX_LABEL_LENGTH = 50
MAX_BODY_LENGTH = 5000
MAX_PASSWORD_BYTES = 72


def _non_blank(value: str) -> str:
    """Reject whitespace-only input and normalize the surrounding whitespace.

    `min_length=1` alone happily accepts "   ", which then reaches the database
    as an unusable name. Stripping here also means a value can't sort or
    compare differently just because of trailing spaces a user didn't intend.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


NonBlankStr = Annotated[str, AfterValidator(_non_blank)]

NameStr = Annotated[NonBlankStr, Field(min_length=1, max_length=MAX_NAME_LENGTH)]
LabelNameStr = Annotated[NonBlankStr, Field(min_length=1, max_length=MAX_LABEL_LENGTH)]
BodyStr = Annotated[NonBlankStr, Field(min_length=1, max_length=MAX_BODY_LENGTH)]


def _max_password_bytes(value: str) -> str:
    """Reject a password bcrypt would silently truncate rather than check in full.

    bcrypt only hashes the first 72 *bytes* of its input, and passlib's bcrypt
    backend truncates to that silently rather than raising - so a password past
    the limit still "works", but everything after byte 72 is never actually
    checked. A plain `max_length=72` on the field counts Unicode characters, not
    bytes, so it misses exactly the passwords this matters for: one made of
    multi-byte characters can be 72 characters long and well past 72 bytes,
    passing that check while silently losing everything past the truncation
    point. A user who set a long, high-entropy password would have no way to
    know only its prefix was ever actually being verified.
    """
    if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"must be at most {MAX_PASSWORD_BYTES} bytes once encoded")
    return value


PasswordStr = Annotated[
    str, Field(min_length=8, max_length=MAX_PASSWORD_BYTES), AfterValidator(_max_password_bytes)
]
