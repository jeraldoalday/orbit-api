"""Soft delete and restore for projects and tasks.

The point of these is that a deleted row is *unreachable* rather than merely
hidden from one listing — a route that still serves it would make the delete a
lie, and search is the easiest of those to forget.
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


def _create_org(client, headers, name="Acme Inc"):
    return client.post("/api/v1/organizations", json={"name": name}, headers=headers).json()


def _add_org_member(client, headers, org_id, email, role="member"):
    return client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": email, "role": role},
        headers=headers,
    )


def _projects_url(org_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects{suffix}"


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


def _create_project(client, headers, org_id, name="Website Revamp"):
    return client.post(_projects_url(org_id), json={"name": name}, headers=headers).json()


def _create_task(client, headers, org_id, project_id, title="Ship it"):
    return client.post(
        _tasks_url(org_id, project_id), json={"title": title}, headers=headers
    ).json()


@pytest.fixture()
def setup(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = _create_task(client, headers, org["id"], project["id"])
    return headers, org, project, task


# --- projects ---------------------------------------------------------------


def test_deleting_a_project_hides_it_from_the_list(client, setup):
    headers, org, project, _task = setup

    assert (
        client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers).status_code
        == 204
    )

    assert client.get(_projects_url(org["id"]), headers=headers).json() == []


def test_a_deleted_project_is_not_readable(client, setup):
    headers, org, project, _task = setup
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    assert (
        client.get(_projects_url(org["id"], f"/{project['id']}"), headers=headers).status_code
        == 404
    )


def test_a_deleted_project_cannot_be_updated(client, setup):
    headers, org, project, _task = setup
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    response = client.patch(
        _projects_url(org["id"], f"/{project['id']}"), json={"name": "New"}, headers=headers
    )

    assert response.status_code == 404


def test_tasks_under_a_deleted_project_are_unreachable(client, setup):
    headers, org, project, task = setup
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    assert client.get(_tasks_url(org["id"], project["id"]), headers=headers).status_code == 404
    assert (
        client.get(
            _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers
        ).status_code
        == 404
    )


def _search(client, headers, org_id, query, kind=None):
    url = f"/api/v1/organizations/{org_id}/search?q={query}"
    if kind:
        url += f"&kind={kind}"
    return client.get(url, headers=headers).json()["results"]


def test_a_deleted_project_is_excluded_from_search(client, setup):
    headers, org, project, _task = setup
    assert _search(client, headers, org["id"], "Website", kind="project")

    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    assert _search(client, headers, org["id"], "Website", kind="project") == []


def test_tasks_of_a_deleted_project_are_excluded_from_search(client, setup):
    headers, org, project, _task = setup
    assert _search(client, headers, org["id"], "Ship", kind="task")

    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    assert _search(client, headers, org["id"], "Ship", kind="task") == []


def test_a_deleted_project_appears_in_the_recycle_bin(client, setup):
    headers, org, project, _task = setup
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    deleted = client.get(_projects_url(org["id"], "/deleted"), headers=headers).json()

    assert [item["id"] for item in deleted] == [project["id"]]
    assert deleted[0]["deleted_at"] is not None


def test_restoring_a_project_brings_it_and_its_tasks_back(client, setup):
    headers, org, project, task = setup
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    restored = client.post(_projects_url(org["id"], f"/{project['id']}/restore"), headers=headers)

    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert len(client.get(_projects_url(org["id"]), headers=headers).json()) == 1
    listed = client.get(_tasks_url(org["id"], project["id"]), headers=headers).json()
    assert [item["id"] for item in listed] == [task["id"]]


def test_restoring_a_live_project_is_a_conflict(client, setup):
    headers, org, project, _task = setup

    response = client.post(_projects_url(org["id"], f"/{project['id']}/restore"), headers=headers)

    assert response.status_code == 409


def test_deleting_twice_keeps_the_original_timestamp(client, setup):
    headers, org, project, _task = setup
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)
    first = client.get(_projects_url(org["id"], "/deleted"), headers=headers).json()[0]

    # The second delete has to go through the deleted lookup, since the plain
    # one no longer finds the project at all.
    assert (
        client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers).status_code
        == 404
    )
    again = client.get(_projects_url(org["id"], "/deleted"), headers=headers).json()[0]

    assert again["deleted_at"] == first["deleted_at"]


def test_a_plain_member_cannot_see_the_recycle_bin(client, setup):
    owner_headers, org, _project, _task = setup
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, owner_headers, org["id"], "member@example.com")

    assert (
        client.get(_projects_url(org["id"], "/deleted"), headers=member_headers).status_code == 403
    )


def test_purging_requires_a_soft_delete_first(client, setup):
    headers, org, project, _task = setup

    response = client.delete(_projects_url(org["id"], f"/{project['id']}/purge"), headers=headers)

    assert response.status_code == 409
    assert "before purging" in response.json()["detail"]


def test_purging_removes_the_project_for_good(client, setup):
    headers, org, project, _task = setup
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    purged = client.delete(_projects_url(org["id"], f"/{project['id']}/purge"), headers=headers)

    assert purged.status_code == 204
    assert client.get(_projects_url(org["id"], "/deleted"), headers=headers).json() == []
    assert (
        client.post(
            _projects_url(org["id"], f"/{project['id']}/restore"), headers=headers
        ).status_code
        == 404
    )


def test_only_an_owner_can_purge(client, setup):
    owner_headers, org, project, _task = setup
    admin_headers = _register_and_login(client, email="admin@example.com")
    _add_org_member(client, owner_headers, org["id"], "admin@example.com", role="admin")
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=owner_headers)

    response = client.delete(
        _projects_url(org["id"], f"/{project['id']}/purge"), headers=admin_headers
    )

    assert response.status_code == 403


# --- tasks ------------------------------------------------------------------


def test_deleting_a_task_hides_it_from_the_list(client, setup):
    headers, org, project, task = setup

    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)

    assert client.get(_tasks_url(org["id"], project["id"]), headers=headers).json() == []
    assert (
        client.get(
            _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers
        ).status_code
        == 404
    )


def test_a_deleted_task_is_excluded_from_search(client, setup):
    headers, org, project, task = setup
    assert _search(client, headers, org["id"], "Ship", kind="task")

    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)

    assert _search(client, headers, org["id"], "Ship", kind="task") == []


def test_a_deleted_task_appears_in_the_projects_recycle_bin(client, setup):
    headers, org, project, task = setup
    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)

    deleted = client.get(_tasks_url(org["id"], project["id"], "/deleted"), headers=headers).json()

    assert [item["id"] for item in deleted] == [task["id"]]


def test_restoring_a_task_brings_it_back(client, setup):
    headers, org, project, task = setup
    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)

    restored = client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/restore"), headers=headers
    )

    assert restored.status_code == 200
    assert restored.json()["deleted_at"] is None
    assert len(client.get(_tasks_url(org["id"], project["id"]), headers=headers).json()) == 1


def test_a_deleted_task_cannot_be_commented_on(client, setup):
    headers, org, project, task = setup
    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)

    response = client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "Still here?"},
        headers=headers,
    )

    assert response.status_code == 404


def test_a_deleted_tasks_comments_survive_the_restore(client, setup):
    headers, org, project, task = setup
    client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "Before the delete"},
        headers=headers,
    )
    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)

    client.post(_tasks_url(org["id"], project["id"], f"/{task['id']}/restore"), headers=headers)

    comments = client.get(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"), headers=headers
    ).json()
    assert [comment["body"] for comment in comments] == ["Before the delete"]


def test_purging_a_task_removes_it_for_good(client, setup):
    headers, org, project, task = setup
    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)

    purged = client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/purge"), headers=headers
    )

    assert purged.status_code == 204
    assert (
        client.get(_tasks_url(org["id"], project["id"], "/deleted"), headers=headers).json() == []
    )


def test_purging_a_live_task_is_a_conflict(client, setup):
    headers, org, project, task = setup

    response = client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/purge"), headers=headers
    )

    assert response.status_code == 409


def test_restore_and_purge_require_admin(client, setup):
    owner_headers, org, project, task = setup
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, owner_headers, org["id"], "member@example.com")
    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=owner_headers)

    assert (
        client.post(
            _tasks_url(org["id"], project["id"], f"/{task['id']}/restore"), headers=member_headers
        ).status_code
        == 403
    )
    assert (
        client.delete(
            _tasks_url(org["id"], project["id"], f"/{task['id']}/purge"), headers=member_headers
        ).status_code
        == 403
    )
