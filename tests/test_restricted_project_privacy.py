"""A restricted project must not announce itself through the side channels.

Access control on the routes is only half of it: assignment and @mention both
create a notification carrying the task's title and its project id. Sending
one to an org member who is deliberately not on a restricted project hands
them exactly what the restriction is there to withhold.
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
    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}


def _add_org_member(client, headers, org_id, email, role="member"):
    return client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": email, "role": role},
        headers=headers,
    )


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


def _me(client, headers):
    return client.get("/api/v1/users/me", headers=headers).json()


@pytest.fixture()
def restricted(client):
    """An owner with a restricted project, and an org member kept off it."""
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = client.post(
        "/api/v1/organizations", json={"name": "Acme Inc"}, headers=owner_headers
    ).json()
    _add_org_member(client, owner_headers, org["id"], "outsider@example.com")
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Acquisition", "visibility": "restricted"},
        headers=owner_headers,
    ).json()
    return owner_headers, outsider_headers, org, project


def test_outsider_cannot_see_the_project_at_all(client, restricted):
    owner_headers, outsider_headers, org, project = restricted

    response = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}", headers=outsider_headers
    )

    assert response.status_code == 404


def test_cannot_assign_a_restricted_task_to_an_outsider(client, restricted):
    owner_headers, outsider_headers, org, project = restricted
    outsider = _me(client, outsider_headers)

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Draft the term sheet", "assignee_id": outsider["id"]},
        headers=owner_headers,
    )

    assert response.status_code == 422
    assert client.get("/api/v1/notifications", headers=outsider_headers).json() == []


def test_cannot_reassign_a_restricted_task_to_an_outsider(client, restricted):
    owner_headers, outsider_headers, org, project = restricted
    outsider = _me(client, outsider_headers)
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Draft the term sheet"},
        headers=owner_headers,
    ).json()

    response = client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"assignee_id": outsider["id"]},
        headers=owner_headers,
    )

    assert response.status_code == 422
    assert client.get("/api/v1/notifications", headers=outsider_headers).json() == []


def test_mentioning_an_outsider_in_a_restricted_project_notifies_nobody(client, restricted):
    owner_headers, outsider_headers, org, project = restricted
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Draft the term sheet"},
        headers=owner_headers,
    ).json()

    response = client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "@outsider@example.com can you look at this?"},
        headers=owner_headers,
    )

    assert response.status_code == 201
    assert client.get("/api/v1/notifications", headers=outsider_headers).json() == []


def test_adding_the_outsider_to_the_project_restores_both(client, restricted):
    """The guard is about visibility, not about singling anyone out."""
    owner_headers, outsider_headers, org, project = restricted
    insider = _me(client, outsider_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/members",
        json={"email": "outsider@example.com", "role": "editor"},
        headers=owner_headers,
    )

    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Draft the term sheet", "assignee_id": insider["id"]},
        headers=owner_headers,
    )
    assert task.status_code == 201

    client.post(
        _tasks_url(org["id"], project["id"], f"/{task.json()['id']}/comments"),
        json={"body": "@outsider@example.com over to you"},
        headers=owner_headers,
    )

    kinds = [
        notification["notification_type"]
        for notification in client.get("/api/v1/notifications", headers=outsider_headers).json()
    ]
    assert sorted(kinds) == ["mentioned", "task_assigned"]


def test_open_projects_still_accept_any_org_member(client):
    """The narrower check must not break the ordinary open-project case."""
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = client.post(
        "/api/v1/organizations", json={"name": "Acme Inc"}, headers=owner_headers
    ).json()
    _add_org_member(client, owner_headers, org["id"], "member@example.com")
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Website Revamp"},
        headers=owner_headers,
    ).json()
    member = _me(client, member_headers)

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    )

    assert response.status_code == 201
    assert len(client.get("/api/v1/notifications", headers=member_headers).json()) == 1


def test_assignee_outside_the_organization_is_still_rejected(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    stranger_headers = _register_and_login(client, email="stranger@example.com")
    org = client.post(
        "/api/v1/organizations", json={"name": "Acme Inc"}, headers=owner_headers
    ).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Website Revamp"},
        headers=owner_headers,
    ).json()
    stranger = _me(client, stranger_headers)

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": stranger["id"]},
        headers=owner_headers,
    )

    assert response.status_code == 422
