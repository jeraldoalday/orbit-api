"""Bulk task edits: the per-task report, and the guards around it."""

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
def setup(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = client.post("/api/v1/organizations", json={"name": "Acme Inc"}, headers=headers).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Website Revamp"},
        headers=headers,
    ).json()
    return headers, org["id"], project["id"]


def _make_tasks(client, headers, org_id, project_id, count, prefix="Task"):
    return [
        client.post(
            _tasks_url(org_id, project_id),
            json={"title": f"{prefix} {index}"},
            headers=headers,
        ).json()
        for index in range(count)
    ]


def _bulk(client, headers, org_id, project_id, payload, suffix="/bulk"):
    return client.post(_tasks_url(org_id, project_id, suffix), json=payload, headers=headers)


def test_bulk_status_change(client, setup):
    headers, org_id, project_id = setup
    tasks = _make_tasks(client, headers, org_id, project_id, 3)
    ids = [task["id"] for task in tasks]

    response = _bulk(client, headers, org_id, project_id, {"task_ids": ids, "status": "done"})

    assert response.status_code == 200
    body = response.json()
    assert sorted(body["updated"]) == sorted(ids)
    assert body["unchanged"] == []
    assert body["failed"] == []

    listing = client.get(_tasks_url(org_id, project_id), headers=headers).json()
    assert {task["status"] for task in listing} == {"done"}


def test_tasks_already_at_the_target_are_reported_unchanged(client, setup):
    headers, org_id, project_id = setup
    tasks = _make_tasks(client, headers, org_id, project_id, 2)
    ids = [task["id"] for task in tasks]
    _bulk(client, headers, org_id, project_id, {"task_ids": [ids[0]], "priority": "high"})

    response = _bulk(client, headers, org_id, project_id, {"task_ids": ids, "priority": "high"})

    body = response.json()
    assert body["unchanged"] == [ids[0]]
    assert body["updated"] == [ids[1]]


def test_unknown_task_is_reported_not_the_whole_batch(client, setup):
    headers, org_id, project_id = setup
    tasks = _make_tasks(client, headers, org_id, project_id, 2)
    ids = [task["id"] for task in tasks]
    missing = "00000000-0000-0000-0000-000000000000"

    response = _bulk(
        client, headers, org_id, project_id, {"task_ids": ids + [missing], "status": "done"}
    )

    assert response.status_code == 200
    body = response.json()
    assert sorted(body["updated"]) == sorted(ids)
    assert body["failed"] == [{"task_id": missing, "reason": "Task not found"}]


def test_blocked_task_falls_out_and_the_rest_go_through(client, setup):
    headers, org_id, project_id = setup
    blocked, blocker, free = _make_tasks(client, headers, org_id, project_id, 3)
    client.post(
        _tasks_url(org_id, project_id, f"/{blocked['id']}/dependencies"),
        json={"depends_on_id": blocker["id"]},
        headers=headers,
    )

    response = _bulk(
        client,
        headers,
        org_id,
        project_id,
        {"task_ids": [blocked["id"], free["id"]], "status": "done"},
    )

    body = response.json()
    assert body["updated"] == [free["id"]]
    assert [failure["task_id"] for failure in body["failed"]] == [blocked["id"]]
    assert "Blocked by" in body["failed"][0]["reason"]


def test_duplicate_ids_are_applied_once(client, setup):
    headers, org_id, project_id = setup
    task = _make_tasks(client, headers, org_id, project_id, 1)[0]

    response = _bulk(
        client,
        headers,
        org_id,
        project_id,
        {"task_ids": [task["id"], task["id"], task["id"]], "status": "done"},
    )

    assert response.json()["updated"] == [task["id"]]


def test_bulk_assign(client, setup):
    headers, org_id, project_id = setup
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, headers, org_id, "member@example.com")
    member = _me(client, member_headers)
    tasks = _make_tasks(client, headers, org_id, project_id, 2)
    ids = [task["id"] for task in tasks]

    response = _bulk(
        client, headers, org_id, project_id, {"task_ids": ids, "assignee_id": member["id"]}
    )

    assert sorted(response.json()["updated"]) == sorted(ids)
    inbox = client.get("/api/v1/notifications", headers=member_headers).json()
    assert len(inbox) == 2


def test_bulk_unassign_with_an_explicit_null(client, setup):
    headers, org_id, project_id = setup
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, headers, org_id, "member@example.com")
    member = _me(client, member_headers)
    tasks = _make_tasks(client, headers, org_id, project_id, 2)
    ids = [task["id"] for task in tasks]
    _bulk(client, headers, org_id, project_id, {"task_ids": ids, "assignee_id": member["id"]})

    response = _bulk(client, headers, org_id, project_id, {"task_ids": ids, "assignee_id": None})

    assert sorted(response.json()["updated"]) == sorted(ids)
    listing = client.get(_tasks_url(org_id, project_id), headers=headers).json()
    assert {task["assignee_id"] for task in listing} == {None}


def test_bad_assignee_fails_the_request_not_each_task(client, setup):
    headers, org_id, project_id = setup
    stranger_headers = _register_and_login(client, email="stranger@example.com")
    stranger = _me(client, stranger_headers)
    ids = [task["id"] for task in _make_tasks(client, headers, org_id, project_id, 2)]

    response = _bulk(
        client, headers, org_id, project_id, {"task_ids": ids, "assignee_id": stranger["id"]}
    )

    assert response.status_code == 422


def test_an_edit_with_no_fields_is_rejected(client, setup):
    headers, org_id, project_id = setup
    ids = [task["id"] for task in _make_tasks(client, headers, org_id, project_id, 1)]

    response = _bulk(client, headers, org_id, project_id, {"task_ids": ids})

    assert response.status_code == 422


def test_an_empty_selection_is_rejected(client, setup):
    headers, org_id, project_id = setup

    response = _bulk(client, headers, org_id, project_id, {"task_ids": [], "status": "done"})

    assert response.status_code == 422


def test_batch_size_is_capped(client, setup):
    headers, org_id, project_id = setup
    ids = ["00000000-0000-0000-0000-000000000000"] * 101

    response = _bulk(client, headers, org_id, project_id, {"task_ids": ids, "status": "done"})

    assert response.status_code == 422
    assert "At most 100" in response.json()["detail"]


def test_bulk_edit_writes_the_timeline_and_fires_webhooks(client, setup):
    """Bulk must not be a back door around the per-task bookkeeping."""
    headers, org_id, project_id = setup
    task = _make_tasks(client, headers, org_id, project_id, 1)[0]

    _bulk(client, headers, org_id, project_id, {"task_ids": [task["id"]], "priority": "urgent"})

    timeline = client.get(
        _tasks_url(org_id, project_id, f"/{task['id']}/timeline"), headers=headers
    ).json()
    priority_changes = [
        entry
        for entry in timeline
        if entry["kind"] == "activity" and "priority" in (entry["activity"].get("data") or {})
    ]
    assert len(priority_changes) == 1


def test_bulk_delete_soft_deletes(client, setup):
    headers, org_id, project_id = setup
    ids = [task["id"] for task in _make_tasks(client, headers, org_id, project_id, 3)]

    response = _bulk(client, headers, org_id, project_id, {"task_ids": ids}, suffix="/bulk/delete")

    assert response.status_code == 200
    assert sorted(response.json()["updated"]) == sorted(ids)
    assert client.get(_tasks_url(org_id, project_id), headers=headers).json() == []
    deleted = client.get(_tasks_url(org_id, project_id, "/deleted"), headers=headers).json()
    assert sorted(task["id"] for task in deleted) == sorted(ids)


def test_bulk_delete_reports_tasks_already_gone(client, setup):
    headers, org_id, project_id = setup
    ids = [task["id"] for task in _make_tasks(client, headers, org_id, project_id, 2)]
    client.delete(_tasks_url(org_id, project_id, f"/{ids[0]}"), headers=headers)

    response = _bulk(client, headers, org_id, project_id, {"task_ids": ids}, suffix="/bulk/delete")

    body = response.json()
    assert body["updated"] == [ids[1]]
    assert [failure["task_id"] for failure in body["failed"]] == [ids[0]]


def test_plain_member_cannot_bulk_delete(client, setup):
    headers, org_id, project_id = setup
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, headers, org_id, "member@example.com")
    ids = [task["id"] for task in _make_tasks(client, headers, org_id, project_id, 1)]

    response = _bulk(
        client, member_headers, org_id, project_id, {"task_ids": ids}, suffix="/bulk/delete"
    )

    assert response.status_code == 403


def test_project_viewer_cannot_bulk_edit(client, setup):
    headers, org_id, project_id = setup
    client.patch(
        f"/api/v1/organizations/{org_id}/projects/{project_id}",
        json={"visibility": "restricted"},
        headers=headers,
    )
    viewer_headers = _register_and_login(client, email="viewer@example.com")
    _add_org_member(client, headers, org_id, "viewer@example.com")
    client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/members",
        json={"email": "viewer@example.com", "role": "viewer"},
        headers=headers,
    )
    ids = [task["id"] for task in _make_tasks(client, headers, org_id, project_id, 1)]

    response = _bulk(
        client, viewer_headers, org_id, project_id, {"task_ids": ids, "status": "done"}
    )

    assert response.status_code == 403


def test_bulk_requires_authentication(client, setup):
    headers, org_id, project_id = setup

    response = client.post(
        _tasks_url(org_id, project_id, "/bulk"),
        json={"task_ids": ["00000000-0000-0000-0000-000000000000"], "status": "done"},
    )

    assert response.status_code == 401


def test_bulk_cannot_reach_tasks_in_another_project(client, setup):
    headers, org_id, project_id = setup
    other = client.post(
        f"/api/v1/organizations/{org_id}/projects",
        json={"name": "Other"},
        headers=headers,
    ).json()
    foreign = _make_tasks(client, headers, org_id, other["id"], 1, prefix="Foreign")[0]

    response = _bulk(
        client, headers, org_id, project_id, {"task_ids": [foreign["id"]], "status": "done"}
    )

    assert response.json()["failed"] == [{"task_id": foreign["id"], "reason": "Task not found"}]
