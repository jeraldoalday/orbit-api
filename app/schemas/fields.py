from typing import Annotated

from pydantic import AfterValidator, Field

MAX_NAME_LENGTH = 200
MAX_LABEL_LENGTH = 50
MAX_BODY_LENGTH = 5000


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
