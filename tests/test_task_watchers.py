"""Task watchers: following a task you aren't assigned to."""

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


def _me(client, headers):
    return client.get("/api/v1/users/me", headers=headers).json()


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


def _watchers_url(org_id, project_id, task_id, suffix=""):
    return _tasks_url(org_id, project_id, f"/{task_id}/watchers{suffix}")


def _inbox(client, headers):
    return client.get("/api/v1/notifications", headers=headers).json()


@pytest.fixture()
def setup(client):
    """An owner, a plain member, an open project and one task."""
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
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship the release"},
        headers=owner_headers,
    ).json()
    return owner_headers, member_headers, org["id"], project["id"], task["id"]


def test_watch_and_list(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup

    response = client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "member@example.com"

    watchers = client.get(_watchers_url(org_id, project_id, task_id), headers=owner_headers)
    assert [row["user"]["email"] for row in watchers.json()] == ["member@example.com"]


def test_watching_twice_conflicts(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    response = client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    assert response.status_code == 409


def test_unwatch(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    response = client.delete(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    assert response.status_code == 204
    assert (
        client.get(_watchers_url(org_id, project_id, task_id), headers=owner_headers).json() == []
    )


def test_unwatching_when_not_watching_is_404(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup

    response = client.delete(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    assert response.status_code == 404


def test_editor_can_add_someone_else(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup

    response = client.post(
        _watchers_url(org_id, project_id, task_id),
        json={"email": "member@example.com"},
        headers=owner_headers,
    )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "member@example.com"


def test_adding_an_unknown_address_is_404(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup

    response = client.post(
        _watchers_url(org_id, project_id, task_id),
        json={"email": "nobody@example.com"},
        headers=owner_headers,
    )

    assert response.status_code == 404


def test_cannot_add_someone_who_cannot_see_the_project(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    _register_and_login(client, email="stranger@example.com")

    response = client.post(
        _watchers_url(org_id, project_id, task_id),
        json={"email": "stranger@example.com"},
        headers=owner_headers,
    )

    assert response.status_code == 422


def test_a_viewer_may_watch_but_not_enlist_others(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.patch(
        f"/api/v1/organizations/{org_id}/projects/{project_id}",
        json={"visibility": "restricted"},
        headers=owner_headers,
    )
    client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/members",
        json={"email": "member@example.com", "role": "viewer"},
        headers=owner_headers,
    )

    assert (
        client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers).status_code
        == 201
    )

    response = client.post(
        _watchers_url(org_id, project_id, task_id),
        json={"email": "owner@example.com"},
        headers=member_headers,
    )
    assert response.status_code == 403


def test_a_viewer_can_remove_their_own_watch_by_id(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    member = _me(client, member_headers)
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    response = client.delete(
        _watchers_url(org_id, project_id, task_id, f"/{member['id']}"), headers=member_headers
    )

    assert response.status_code == 204


def test_editor_can_remove_someone_elses_watch(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    member = _me(client, member_headers)
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    response = client.delete(
        _watchers_url(org_id, project_id, task_id, f"/{member['id']}"), headers=owner_headers
    )

    assert response.status_code == 204


def test_watchers_require_authentication(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup

    assert client.get(_watchers_url(org_id, project_id, task_id)).status_code == 401


# --- the fan-out ---------------------------------------------------------


def test_watchers_hear_about_a_status_change(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    client.patch(
        _tasks_url(org_id, project_id, f"/{task_id}"),
        json={"status": "in_progress"},
        headers=owner_headers,
    )

    inbox = _inbox(client, member_headers)
    assert [row["notification_type"] for row in inbox] == ["task_updated"]
    assert inbox[0]["data"]["status"] == "in_progress"


def test_watchers_are_not_told_about_every_field(client, setup):
    """Following a task shouldn't mean hearing about each typo fix."""
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    client.patch(
        _tasks_url(org_id, project_id, f"/{task_id}"),
        json={"title": "Ship the release, properly", "priority": "urgent"},
        headers=owner_headers,
    )

    assert _inbox(client, member_headers) == []


def test_watchers_hear_about_comments(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    client.post(
        _tasks_url(org_id, project_id, f"/{task_id}/comments"),
        json={"body": "Started on this"},
        headers=owner_headers,
    )

    assert [row["notification_type"] for row in _inbox(client, member_headers)] == [
        "task_commented"
    ]


def test_a_watcher_who_is_also_mentioned_gets_one_notification(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    client.post(
        _tasks_url(org_id, project_id, f"/{task_id}/comments"),
        json={"body": "@member@example.com take a look"},
        headers=owner_headers,
    )

    assert [row["notification_type"] for row in _inbox(client, member_headers)] == ["mentioned"]


def test_a_watcher_who_is_also_the_assignee_gets_one_notification(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    member = _me(client, member_headers)
    client.patch(
        _tasks_url(org_id, project_id, f"/{task_id}"),
        json={"assignee_id": member["id"]},
        headers=owner_headers,
    )
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    client.post(
        _tasks_url(org_id, project_id, f"/{task_id}/comments"),
        json={"body": "Any update?"},
        headers=owner_headers,
    )

    kinds = [row["notification_type"] for row in _inbox(client, member_headers)]
    assert kinds.count("task_commented") == 1


def test_a_reassignment_that_also_moves_status_notifies_once(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    member = _me(client, member_headers)
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    client.patch(
        _tasks_url(org_id, project_id, f"/{task_id}"),
        json={"assignee_id": member["id"], "status": "in_progress"},
        headers=owner_headers,
    )

    assert [row["notification_type"] for row in _inbox(client, member_headers)] == ["task_assigned"]


def test_you_are_not_notified_about_your_own_change(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    client.patch(
        _tasks_url(org_id, project_id, f"/{task_id}"),
        json={"status": "done"},
        headers=member_headers,
    )

    assert _inbox(client, member_headers) == []


def test_watchers_go_when_the_task_is_purged(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.post(_watchers_url(org_id, project_id, task_id), headers=member_headers)

    client.delete(_tasks_url(org_id, project_id, f"/{task_id}"), headers=owner_headers)
    purge = client.delete(
        _tasks_url(org_id, project_id, f"/{task_id}/purge"), headers=owner_headers
    )

    assert purge.status_code == 204
    assert (
        client.get(_watchers_url(org_id, project_id, task_id), headers=owner_headers).status_code
        == 404
    )
