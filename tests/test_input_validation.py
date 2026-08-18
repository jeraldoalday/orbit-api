"""Whitespace-only and unbounded input must be rejected at the schema edge.

`min_length=1` alone accepts "   ", which reaches the database as an unusable
name; these cases pin the shared non-blank field types down.
"""

import pytest


def _register_and_login(
    client, email="jane@example.com", password="supersecret1", full_name="Jane Doe"
):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_org(client, headers, name="Acme Inc"):
    return client.post("/api/v1/organizations", json={"name": name}, headers=headers).json()


def _create_project(client, headers, org_id, name="Website Revamp"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects", json={"name": name}, headers=headers
    ).json()


def _setup(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    return headers, org, project


BLANK_VALUES = ["", "   ", "\t", "\n", "  \t\n  "]


@pytest.mark.parametrize("value", BLANK_VALUES)
def test_blank_organization_name_rejected(client, value):
    headers = _register_and_login(client)

    response = client.post("/api/v1/organizations", json={"name": value}, headers=headers)

    assert response.status_code == 422


@pytest.mark.parametrize("value", BLANK_VALUES)
def test_blank_project_name_rejected(client, value):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/projects", json={"name": value}, headers=headers
    )

    assert response.status_code == 422


@pytest.mark.parametrize("value", BLANK_VALUES)
def test_blank_task_title_rejected(client, value):
    headers, org, project = _setup(client)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks",
        json={"title": value},
        headers=headers,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("value", BLANK_VALUES)
def test_blank_comment_body_rejected(client, value):
    headers, org, project = _setup(client)
    task = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks",
        json={"title": "Ship it"},
        headers=headers,
    ).json()

    response = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks/{task['id']}/comments",
        json={"body": value},
        headers=headers,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("value", BLANK_VALUES)
def test_blank_label_name_rejected(client, value):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/labels", json={"name": value}, headers=headers
    )

    assert response.status_code == 422


def test_surrounding_whitespace_is_stripped_from_names(client):
    headers = _register_and_login(client)

    response = client.post(
        "/api/v1/organizations", json={"name": "   Acme Inc   "}, headers=headers
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Acme Inc"


def test_surrounding_whitespace_is_stripped_from_task_titles(client):
    headers, org, project = _setup(client)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks",
        json={"title": "  Ship it  "},
        headers=headers,
    )

    assert response.json()["title"] == "Ship it"


def test_blank_update_is_rejected_rather_than_ignored(client):
    headers, org, project = _setup(client)

    response = client.patch(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}",
        json={"name": "   "},
        headers=headers,
    )

    assert response.status_code == 422


def test_overlong_task_title_rejected(client):
    headers, org, project = _setup(client)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks",
        json={"title": "x" * 201},
        headers=headers,
    )

    assert response.status_code == 422


def test_overlong_label_name_rejected(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/labels", json={"name": "x" * 51}, headers=headers
    )

    assert response.status_code == 422


def test_overlong_comment_body_rejected(client):
    headers, org, project = _setup(client)
    task = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks",
        json={"title": "Ship it"},
        headers=headers,
    ).json()

    response = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks/{task['id']}/comments",
        json={"body": "x" * 5001},
        headers=headers,
    )

    assert response.status_code == 422


def test_whitespace_only_search_query_is_accepted_but_matches_nothing(client):
    headers, org, _project = _setup(client)

    response = client.get(f"/api/v1/organizations/{org['id']}/search?q=%20%20", headers=headers)

    assert response.status_code == 200
    assert response.json()["results"] == []
