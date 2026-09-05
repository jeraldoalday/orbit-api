"""Milestones: dated goals a project's tasks are filed under."""

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


def _milestones_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/milestones{suffix}"


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


@pytest.fixture()
def setup(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = client.post(
        "/api/v1/organizations", json={"name": "Acme Inc"}, headers=owner_headers
    ).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Website Revamp"},
        headers=owner_headers,
    ).json()
    return owner_headers, org["id"], project["id"]


def _create_milestone(client, headers, org_id, project_id, name="v1.0", **extra):
    return client.post(
        _milestones_url(org_id, project_id), json={"name": name, **extra}, headers=headers
    )


def _create_task(client, headers, org_id, project_id, title="A task", **extra):
    return client.post(
        _tasks_url(org_id, project_id), json={"title": title, **extra}, headers=headers
    )


def test_create_and_read_a_milestone(client, setup):
    headers, org_id, project_id = setup

    response = _create_milestone(
        client, headers, org_id, project_id, name="v1.0", description="First public cut"
    )

    assert response.status_code == 201
    assert response.json()["name"] == "v1.0"
    assert response.json()["completed_at"] is None


def test_an_empty_milestone_is_zero_per_cent_done(client, setup):
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()

    body = client.get(_milestones_url(org_id, project_id, f"/{milestone['id']}"), headers=headers)

    assert body.json()["progress"] == {"total": 0, "done": 0, "open": 0, "completion_rate": 0.0}


def test_progress_counts_the_tasks_filed_under_it(client, setup):
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    first = _create_task(
        client, headers, org_id, project_id, "Write it", milestone_id=milestone["id"]
    ).json()
    _create_task(client, headers, org_id, project_id, "Ship it", milestone_id=milestone["id"])
    # A task outside the milestone must not move its numbers.
    _create_task(client, headers, org_id, project_id, "Unrelated")

    client.patch(
        _tasks_url(org_id, project_id, f"/{first['id']}"), json={"status": "done"}, headers=headers
    )

    progress = client.get(
        _milestones_url(org_id, project_id, f"/{milestone['id']}"), headers=headers
    ).json()["progress"]
    assert progress == {"total": 2, "done": 1, "open": 1, "completion_rate": 0.5}


def test_a_soft_deleted_task_leaves_the_denominator(client, setup):
    """Otherwise deleting work would make a milestone unfinishable."""
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    doomed = _create_task(
        client, headers, org_id, project_id, "Cut this", milestone_id=milestone["id"]
    ).json()
    kept = _create_task(
        client, headers, org_id, project_id, "Keep this", milestone_id=milestone["id"]
    ).json()
    client.patch(
        _tasks_url(org_id, project_id, f"/{kept['id']}"), json={"status": "done"}, headers=headers
    )

    client.delete(_tasks_url(org_id, project_id, f"/{doomed['id']}"), headers=headers)

    progress = client.get(
        _milestones_url(org_id, project_id, f"/{milestone['id']}"), headers=headers
    ).json()["progress"]
    assert progress == {"total": 1, "done": 1, "open": 0, "completion_rate": 1.0}


def test_milestones_are_listed_by_due_date_with_undated_ones_last(client, setup):
    headers, org_id, project_id = setup
    _create_milestone(client, headers, org_id, project_id, name="Someday")
    _create_milestone(
        client, headers, org_id, project_id, name="v2.0", due_date="2026-11-01T00:00:00Z"
    )
    _create_milestone(
        client, headers, org_id, project_id, name="v1.0", due_date="2026-10-01T00:00:00Z"
    )

    listed = client.get(_milestones_url(org_id, project_id), headers=headers).json()

    assert [milestone["name"] for milestone in listed] == ["v1.0", "v2.0", "Someday"]


def test_completed_milestones_can_be_filtered_out(client, setup):
    headers, org_id, project_id = setup
    done = _create_milestone(client, headers, org_id, project_id, name="v0.9").json()
    _create_milestone(client, headers, org_id, project_id, name="v1.0")
    client.post(_milestones_url(org_id, project_id, f"/{done['id']}/complete"), headers=headers)

    listed = client.get(
        _milestones_url(org_id, project_id), params={"include_completed": False}, headers=headers
    ).json()

    assert [milestone["name"] for milestone in listed] == ["v1.0"]


def test_completing_a_milestone_with_open_work_is_refused(client, setup):
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    _create_task(client, headers, org_id, project_id, "Not done", milestone_id=milestone["id"])

    response = client.post(
        _milestones_url(org_id, project_id, f"/{milestone['id']}/complete"), headers=headers
    )

    assert response.status_code == 409
    assert "1 task(s)" in response.json()["detail"]


def test_completing_can_be_forced(client, setup):
    """Cutting scope is a real answer; the alternative is lying about the tasks."""
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    _create_task(client, headers, org_id, project_id, "Not done", milestone_id=milestone["id"])

    response = client.post(
        _milestones_url(org_id, project_id, f"/{milestone['id']}/complete"),
        params={"force": True},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["completed_at"] is not None
    assert response.json()["progress"]["open"] == 1


def test_completing_twice_conflicts_and_reopening_clears_the_stamp(client, setup):
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    url = _milestones_url(org_id, project_id, f"/{milestone['id']}")
    client.post(f"{url}/complete", headers=headers)

    assert client.post(f"{url}/complete", headers=headers).status_code == 409

    assert client.post(f"{url}/reopen", headers=headers).json()["completed_at"] is None
    assert client.post(f"{url}/reopen", headers=headers).status_code == 409


def test_tasks_can_be_filtered_by_milestone(client, setup):
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    _create_task(client, headers, org_id, project_id, "In the plan", milestone_id=milestone["id"])
    _create_task(client, headers, org_id, project_id, "Out of it")

    listed = client.get(
        _tasks_url(org_id, project_id), params={"milestone_id": milestone["id"]}, headers=headers
    ).json()

    assert [task["title"] for task in listed] == ["In the plan"]


def test_a_task_cannot_be_filed_under_another_projects_milestone(client, setup):
    headers, org_id, project_id = setup
    other_project = client.post(
        f"/api/v1/organizations/{org_id}/projects",
        json={"name": "Something Else"},
        headers=headers,
    ).json()
    foreign = _create_milestone(client, headers, org_id, other_project["id"]).json()

    response = _create_task(
        client, headers, org_id, project_id, "Confused", milestone_id=foreign["id"]
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Milestone not found in this project"


def test_a_task_can_be_detached_from_its_milestone(client, setup):
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    task = _create_task(
        client, headers, org_id, project_id, "Filed", milestone_id=milestone["id"]
    ).json()

    response = client.patch(
        _tasks_url(org_id, project_id, f"/{task['id']}"),
        json={"milestone_id": None},
        headers=headers,
    )

    assert response.json()["milestone_id"] is None
    assert (
        client.get(
            _milestones_url(org_id, project_id, f"/{milestone['id']}"), headers=headers
        ).json()["progress"]["total"]
        == 0
    )


def test_a_bulk_edit_can_file_a_selection_under_a_milestone(client, setup):
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    first = _create_task(client, headers, org_id, project_id, "One").json()
    second = _create_task(client, headers, org_id, project_id, "Two").json()

    response = client.post(
        _tasks_url(org_id, project_id, "/bulk"),
        json={"task_ids": [first["id"], second["id"]], "milestone_id": milestone["id"]},
        headers=headers,
    )

    assert response.status_code == 200
    assert len(response.json()["updated"]) == 2
    assert (
        client.get(
            _milestones_url(org_id, project_id, f"/{milestone['id']}"), headers=headers
        ).json()["progress"]["total"]
        == 2
    )


def test_a_bulk_edit_rejects_a_foreign_milestone_outright(client, setup):
    """Wrong for the request, not for one task in it, so no per-task rows."""
    headers, org_id, project_id = setup
    other_project = client.post(
        f"/api/v1/organizations/{org_id}/projects", json={"name": "Elsewhere"}, headers=headers
    ).json()
    foreign = _create_milestone(client, headers, org_id, other_project["id"]).json()
    task = _create_task(client, headers, org_id, project_id, "One").json()

    response = client.post(
        _tasks_url(org_id, project_id, "/bulk"),
        json={"task_ids": [task["id"]], "milestone_id": foreign["id"]},
        headers=headers,
    )

    assert response.status_code == 422


def test_deleting_a_milestone_keeps_its_tasks(client, setup):
    headers, org_id, project_id = setup
    milestone = _create_milestone(client, headers, org_id, project_id).json()
    task = _create_task(
        client, headers, org_id, project_id, "Survivor", milestone_id=milestone["id"]
    ).json()

    assert (
        client.delete(
            _milestones_url(org_id, project_id, f"/{milestone['id']}"), headers=headers
        ).status_code
        == 204
    )

    remaining = client.get(_tasks_url(org_id, project_id, f"/{task['id']}"), headers=headers)
    assert remaining.status_code == 200
    assert remaining.json()["milestone_id"] is None


def test_an_editor_may_file_work_but_not_reshape_the_plan(client, setup):
    owner_headers, org_id, project_id = setup
    editor_headers = _register_and_login(client, email="editor@example.com")
    client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "editor@example.com", "role": "member"},
        headers=owner_headers,
    )
    milestone = _create_milestone(client, owner_headers, org_id, project_id).json()

    assert (
        _create_task(
            client, editor_headers, org_id, project_id, "Filed", milestone_id=milestone["id"]
        ).status_code
        == 201
    )
    assert (
        _create_milestone(client, editor_headers, org_id, project_id, name="v2").status_code == 403
    )
    assert (
        client.delete(
            _milestones_url(org_id, project_id, f"/{milestone['id']}"), headers=editor_headers
        ).status_code
        == 403
    )


def test_a_milestone_from_another_project_is_not_found(client, setup):
    headers, org_id, project_id = setup
    other_project = client.post(
        f"/api/v1/organizations/{org_id}/projects", json={"name": "Elsewhere"}, headers=headers
    ).json()
    milestone = _create_milestone(client, headers, org_id, other_project["id"]).json()

    response = client.get(
        _milestones_url(org_id, project_id, f"/{milestone['id']}"), headers=headers
    )

    assert response.status_code == 404


def test_milestones_need_authentication(client, setup):
    _headers, org_id, project_id = setup

    assert client.get(_milestones_url(org_id, project_id)).status_code == 401
