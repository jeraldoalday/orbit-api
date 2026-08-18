"""Guards on the generated OpenAPI document.

The schema is what consumers generate clients from, so the things that quietly
rot — a new router with no tag, a tag nobody described, a duplicated operation
id — are worth failing the build over rather than discovering downstream.
"""

import pytest

from app.core.openapi import COMMON_RESPONSES, TAGS_METADATA
from app.main import app


@pytest.fixture(scope="module")
def schema() -> dict:
    return app.openapi()


def _operations(schema):
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            yield path, method, operation


def test_the_schema_builds(schema):
    assert schema["info"]["title"] == "Orbit API"
    assert schema["info"]["description"].strip()


def test_every_operation_has_a_tag(schema):
    untagged = [
        f"{method.upper()} {path}"
        for path, method, operation in _operations(schema)
        if not operation.get("tags")
    ]

    assert untagged == []


def test_every_tag_used_is_described(schema):
    described = {tag["name"] for tag in TAGS_METADATA}
    used = {tag for _p, _m, operation in _operations(schema) for tag in operation["tags"]}

    assert used - described == set()


def test_no_tag_is_described_without_being_used(schema):
    """A leftover description outlives the router it documented."""
    described = {tag["name"] for tag in TAGS_METADATA}
    used = {tag for _p, _m, operation in _operations(schema) for tag in operation["tags"]}

    assert described - used == set()


def test_every_described_tag_has_a_description(schema):
    assert all(tag.get("description") for tag in TAGS_METADATA)


def test_operation_ids_are_unique(schema):
    """A collision silently overwrites one operation in a generated client."""
    operation_ids = [
        operation["operationId"]
        for _p, _m, operation in _operations(schema)
        if "operationId" in operation
    ]

    assert len(operation_ids) == len(set(operation_ids))


def test_operation_ids_are_readable(schema):
    """The default encodes the whole path and verb, which nobody wants to type."""
    ids = {operation["operationId"] for _p, _m, operation in _operations(schema)}

    assert "tasks-restore" in ids
    assert "audit-list_for_org" in ids
    assert all("_api_v1_" not in operation_id for operation_id in ids)


def test_every_operation_id_is_prefixed_with_its_tag(schema):
    for _path, _method, operation in _operations(schema):
        assert operation["operationId"].startswith(f"{operation['tags'][0]}-")


def test_every_operation_has_a_summary(schema):
    missing = [
        f"{method.upper()} {path}"
        for path, method, operation in _operations(schema)
        if not operation.get("summary")
    ]

    assert missing == []


def test_the_common_error_responses_are_documented_everywhere(schema):
    expected = {str(code) for code in COMMON_RESPONSES}

    for path, method, operation in _operations(schema):
        documented = set(operation["responses"])
        assert expected <= documented, f"{method.upper()} {path} is missing {expected - documented}"


def test_every_path_is_under_the_version_prefix(schema):
    assert all(path.startswith("/api/v1/") for path in schema["paths"])


def test_the_docs_are_served_outside_production(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_the_docs_are_hidden_in_production():
    """A production deployment shouldn't publish a map of its own surface."""
    from fastapi import FastAPI

    from app.core.openapi import API_TITLE

    production_app = FastAPI(title=API_TITLE, docs_url=None, redoc_url=None)

    assert production_app.docs_url is None
    assert production_app.redoc_url is None
