"""Settings-level guards.

Configuration mistakes here surface as a runtime surprise in production — a
password hashed at a cost factor of 1, a CORS list that silently includes an
empty origin — so the parsing and bounds are pinned down.
"""

import pathlib

import pytest
from pydantic import ValidationError

from app.core.config import Settings

ENV_EXAMPLE = pathlib.Path(__file__).resolve().parent.parent / ".env.example"

BASE = {"database_url": "postgresql+psycopg2://u:p@localhost:5432/db", "jwt_secret_key": "s"}


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**BASE, **overrides})


def test_defaults_are_production_safe():
    # Read the declared defaults rather than an instance: the test process
    # exports BCRYPT_ROUNDS=4, and pydantic-settings honours the environment
    # even when the env file is disabled.
    defaults = Settings.model_fields

    assert defaults["bcrypt_rounds"].default == 12
    assert defaults["rate_limit_enabled"].default is True
    assert defaults["environment"].default == "development"


@pytest.mark.parametrize("rounds", [3, 0, -1, 32])
def test_bcrypt_rounds_outside_the_supported_range_is_rejected(rounds):
    with pytest.raises(ValidationError):
        _settings(bcrypt_rounds=rounds)


@pytest.mark.parametrize("rounds", [4, 12, 31])
def test_bcrypt_rounds_inside_the_supported_range_is_accepted(rounds):
    assert _settings(bcrypt_rounds=rounds).bcrypt_rounds == rounds


def test_is_production_tracks_the_environment_name():
    assert _settings(environment="production").is_production is True
    assert _settings(environment="staging").is_production is False


def test_cors_origins_are_split_and_stripped():
    settings = _settings(cors_origins=" https://a.example , https://b.example ,, ")

    assert settings.cors_origin_list == ["https://a.example", "https://b.example"]


def test_cors_origins_default_to_none_configured():
    assert _settings().cors_origin_list == []
    assert _settings(cors_origins="").cors_origin_list == []


def _example_keys() -> list[str]:
    return [
        line.split("=", 1)[0].strip()
        for line in ENV_EXAMPLE.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_every_key_in_the_env_example_is_a_real_setting():
    """A key nobody reads is a knob that silently does nothing when turned."""
    unknown = [key for key in _example_keys() if key.lower() not in Settings.model_fields]

    assert unknown == []


def test_the_env_example_lists_each_key_once():
    """A duplicate is two values for one knob, and the last line quietly wins."""
    keys = _example_keys()

    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    assert duplicates == []
