"""Task dependencies: the graph, the guards on it, and the completion gate."""

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


def _create_project(client, headers, org_id, name="Website Revamp"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects", json={"name": name}, headers=headers
    ).json()


def _create_task(client, headers, org_id, project_id, title="Set up CI"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks",
        json={"title": title},
        headers=headers,
    ).json()


def _deps_url(org_id, project_id, task_id, suffix=""):
    return (
        f"/api/v1/organizations/{org_id}/projects/{project_id}"
        f"/tasks/{task_id}/dependencies{suffix}"
    )


def _task_url(org_id, project_id, task_id):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks/{task_id}"


@pytest.fixture()
def setup(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    return headers, org["id"], project["id"]


def _add(client, headers, org_id, project_id, task_id, depends_on_id):
    return client.post(
        _deps_url(org_id, project_id, task_id),
        json={"depends_on_id": depends_on_id},
        headers=headers,
    )


def test_add_dependency_returns_the_graph(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")

    response = _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    assert response.status_code == 201
    body = response.json()
    assert [task["id"] for task in body["blocked_by"]] == [blocker["id"]]
    assert [task["id"] for task in body["open_blockers"]] == [blocker["id"]]
    assert body["blocks"] == []
    assert body["is_blocked"] is True


def test_dependency_is_visible_from_both_ends(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    upstream = client.get(_deps_url(org_id, project_id, blocker["id"]), headers=headers).json()

    assert [task["id"] for task in upstream["blocks"]] == [blocked["id"]]
    assert upstream["blocked_by"] == []
    assert upstream["is_blocked"] is False


def test_task_cannot_depend_on_itself(client, setup):
    headers, org_id, project_id = setup
    task = _create_task(client, headers, org_id, project_id)

    response = _add(client, headers, org_id, project_id, task["id"], task["id"])

    assert response.status_code == 422
    assert "itself" in response.json()["detail"]


def test_duplicate_dependency_conflicts(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    response = _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    assert response.status_code == 409


def test_direct_cycle_is_rejected(client, setup):
    headers, org_id, project_id = setup
    first = _create_task(client, headers, org_id, project_id, "First")
    second = _create_task(client, headers, org_id, project_id, "Second")
    _add(client, headers, org_id, project_id, first["id"], second["id"])

    response = _add(client, headers, org_id, project_id, second["id"], first["id"])

    assert response.status_code == 409
    assert "cycle" in response.json()["detail"]


def test_indirect_cycle_is_rejected(client, setup):
    """A -> B -> C, then C -> A: the loop only closes three edges in."""
    headers, org_id, project_id = setup
    a = _create_task(client, headers, org_id, project_id, "A")
    b = _create_task(client, headers, org_id, project_id, "B")
    c = _create_task(client, headers, org_id, project_id, "C")
    _add(client, headers, org_id, project_id, a["id"], b["id"])
    _add(client, headers, org_id, project_id, b["id"], c["id"])

    response = _add(client, headers, org_id, project_id, c["id"], a["id"])

    assert response.status_code == 409


def test_diamond_is_allowed(client, setup):
    """Two tasks depending on the same blocker isn't a cycle."""
    headers, org_id, project_id = setup
    left = _create_task(client, headers, org_id, project_id, "Left")
    right = _create_task(client, headers, org_id, project_id, "Right")
    shared = _create_task(client, headers, org_id, project_id, "Shared")

    assert _add(client, headers, org_id, project_id, left["id"], shared["id"]).status_code == 201
    assert _add(client, headers, org_id, project_id, right["id"], shared["id"]).status_code == 201

    graph = client.get(_deps_url(org_id, project_id, shared["id"]), headers=headers).json()
    assert sorted(task["id"] for task in graph["blocks"]) == sorted([left["id"], right["id"]])


def test_dependency_from_another_project_is_not_found(client, setup):
    headers, org_id, project_id = setup
    other_project = _create_project(client, headers, org_id, "Other")
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    foreign = _create_task(client, headers, org_id, other_project["id"], "Elsewhere")

    response = _add(client, headers, org_id, project_id, blocked["id"], foreign["id"])

    assert response.status_code == 404


def test_unknown_dependency_task_is_not_found(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id)

    response = _add(
        client,
        headers,
        org_id,
        project_id,
        blocked["id"],
        "00000000-0000-0000-0000-000000000000",
    )

    assert response.status_code == 404


def test_remove_dependency(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    response = client.delete(
        _deps_url(org_id, project_id, blocked["id"], f"/{blocker['id']}"), headers=headers
    )

    assert response.status_code == 204
    graph = client.get(_deps_url(org_id, project_id, blocked["id"]), headers=headers).json()
    assert graph["blocked_by"] == []
    assert graph["is_blocked"] is False


def test_removing_a_dependency_that_does_not_exist_is_404(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    unrelated = _create_task(client, headers, org_id, project_id, "Unrelated")

    response = client.delete(
        _deps_url(org_id, project_id, blocked["id"], f"/{unrelated['id']}"), headers=headers
    )

    assert response.status_code == 404


def test_dependency_edges_are_recorded_on_the_timeline(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    timeline = client.get(
        f"{_task_url(org_id, project_id, blocked['id'])}/timeline", headers=headers
    ).json()

    added = [
        entry
        for entry in timeline
        if entry["kind"] == "activity"
        and ((entry["activity"].get("data") or {}).get("blocked_by") or {}).get("added")
        == blocker["id"]
    ]
    assert len(added) == 1


# --- the completion gate -------------------------------------------------


def _set_status(client, headers, org_id, project_id, task_id, status):
    return client.patch(
        _task_url(org_id, project_id, task_id), json={"status": status}, headers=headers
    )


def test_cannot_complete_a_task_with_an_open_blocker(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    response = _set_status(client, headers, org_id, project_id, blocked["id"], "done")

    assert response.status_code == 409
    assert "Write changelog" in response.json()["detail"]


def test_blocked_task_can_still_move_to_in_progress(client, setup):
    """The gate is on *finishing*, not on working on something."""
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    response = _set_status(client, headers, org_id, project_id, blocked["id"], "in_progress")

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_completing_the_blocker_unblocks_the_task(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])
    _set_status(client, headers, org_id, project_id, blocker["id"], "done")

    response = _set_status(client, headers, org_id, project_id, blocked["id"], "done")

    assert response.status_code == 200
    assert response.json()["status"] == "done"


def test_soft_deleted_blocker_stops_blocking(client, setup):
    """Deleting a task must not freeze whatever was waiting on it forever."""
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])
    client.delete(_task_url(org_id, project_id, blocker["id"]), headers=headers)

    response = _set_status(client, headers, org_id, project_id, blocked["id"], "done")

    assert response.status_code == 200


def test_blocked_update_leaves_the_other_fields_untouched(client, setup):
    """A rejected completion must not half-apply the rest of the patch."""
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    response = client.patch(
        _task_url(org_id, project_id, blocked["id"]),
        json={"title": "Renamed", "status": "done"},
        headers=headers,
    )
    assert response.status_code == 409

    after = client.get(_task_url(org_id, project_id, blocked["id"]), headers=headers).json()
    assert after["title"] == "Ship release"
    assert after["status"] == "todo"


def test_already_done_task_can_be_patched_while_blocked(client, setup):
    """The gate only fires on the transition into done, not on every write."""
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _set_status(client, headers, org_id, project_id, blocked["id"], "done")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    response = client.patch(
        _task_url(org_id, project_id, blocked["id"]),
        json={"status": "done", "title": "Ship release v2"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["title"] == "Ship release v2"


def test_viewer_cannot_change_dependencies(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")

    client.patch(
        f"/api/v1/organizations/{org_id}/projects/{project_id}",
        json={"visibility": "restricted"},
        headers=headers,
    )
    viewer_headers = _register_and_login(client, email="viewer@example.com", full_name="Vic Viewer")
    client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "viewer@example.com", "role": "member"},
        headers=headers,
    )
    client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/members",
        json={"email": "viewer@example.com", "role": "viewer"},
        headers=headers,
    )

    response = _add(client, viewer_headers, org_id, project_id, blocked["id"], blocker["id"])

    assert response.status_code == 403
    assert (
        client.get(_deps_url(org_id, project_id, blocked["id"]), headers=viewer_headers).status_code
        == 200
    )


def test_dependencies_require_authentication(client, setup):
    headers, org_id, project_id = setup
    task = _create_task(client, headers, org_id, project_id)

    assert client.get(_deps_url(org_id, project_id, task["id"])).status_code == 401


def test_purging_a_task_removes_its_edges(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, "Ship release")
    blocker = _create_task(client, headers, org_id, project_id, "Write changelog")
    _add(client, headers, org_id, project_id, blocked["id"], blocker["id"])

    client.delete(_task_url(org_id, project_id, blocker["id"]), headers=headers)
    purge = client.delete(f"{_task_url(org_id, project_id, blocker['id'])}/purge", headers=headers)
    assert purge.status_code == 204

    graph = client.get(_deps_url(org_id, project_id, blocked["id"]), headers=headers).json()
    assert graph["blocked_by"] == []


def test_reaches_refuses_a_chain_deeper_than_the_traversal_limit(db):
    """The depth guard that keeps an adversarially long chain from being walked forever.

    Built directly against the models rather than through the API: creating
    a hundred-plus tasks and edges one HTTP call at a time would make this
    test about the setup, not the limit it's checking.
    """
    from app.models.organization import Organization
    from app.models.project import Project
    from app.models.task import Task
    from app.models.task_dependency import TaskDependency
    from app.services.task_dependency_service import MAX_GRAPH_DEPTH, DependencyCycleError, reaches

    org = Organization(name="Acme Inc", slug="acme-inc")
    db.add(org)
    db.flush()
    project = Project(organization_id=org.id, name="Big Graph")
    db.add(project)
    db.flush()

    # A straight chain, each task depending on the one before it, longer than
    # MAX_GRAPH_DEPTH hops from the last task back to the first.
    tasks = [Task(project_id=project.id, title=f"Task {i}") for i in range(MAX_GRAPH_DEPTH + 5)]
    db.add_all(tasks)
    db.flush()
    for later, earlier in zip(tasks[1:], tasks):
        db.add(TaskDependency(task_id=later.id, depends_on_id=earlier.id))
    db.commit()

    with pytest.raises(DependencyCycleError):
        reaches(db, tasks[-1].id, tasks[0].id)
