"""Project and organization statistics."""

from datetime import datetime, timedelta, timezone

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


def _create_project(client, headers, org_id, name="Website Revamp", visibility=None):
    payload = {"name": name}
    if visibility is not None:
        payload["visibility"] = visibility
    return client.post(
        f"/api/v1/organizations/{org_id}/projects", json=payload, headers=headers
    ).json()


def _create_task(client, headers, org_id, project_id, **fields):
    payload = {"title": "Task"}
    payload.update(fields)
    return client.post(_tasks_url(org_id, project_id), json=payload, headers=headers).json()


def _set_status(client, headers, org_id, project_id, task_id, status):
    return client.patch(
        _tasks_url(org_id, project_id, f"/{task_id}"),
        json={"status": status},
        headers=headers,
    )


@pytest.fixture()
def setup(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = client.post("/api/v1/organizations", json={"name": "Acme Inc"}, headers=headers).json()
    project = _create_project(client, headers, org["id"])
    return headers, org["id"], project["id"]


def _project_stats(client, headers, org_id, project_id):
    return client.get(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/stats", headers=headers
    )


def _org_stats(client, headers, org_id):
    return client.get(f"/api/v1/organizations/{org_id}/stats", headers=headers)


def test_empty_project_reports_zeroes_not_nulls(client, setup):
    headers, org_id, project_id = setup

    body = _project_stats(client, headers, org_id, project_id).json()

    assert body["tasks"]["total"] == 0
    assert body["tasks"]["completion_rate"] == 0.0
    assert body["tasks"]["by_status"] == {"todo": 0, "in_progress": 0, "done": 0}
    assert set(body["tasks"]["by_priority"]) == {"low", "medium", "high", "urgent"}
    assert body["by_assignee"] == []
    assert body["by_milestone"] == []


def test_status_and_priority_breakdown(client, setup):
    headers, org_id, project_id = setup
    _create_task(client, headers, org_id, project_id, title="A", priority="urgent")
    _create_task(client, headers, org_id, project_id, title="B", priority="low")
    done = _create_task(client, headers, org_id, project_id, title="C")
    _set_status(client, headers, org_id, project_id, done["id"], "done")

    stats = _project_stats(client, headers, org_id, project_id).json()["tasks"]

    assert stats["total"] == 3
    assert stats["by_status"] == {"todo": 2, "in_progress": 0, "done": 1}
    assert stats["by_priority"] == {"low": 1, "medium": 1, "high": 0, "urgent": 1}
    assert stats["done"] == 1
    assert stats["completion_rate"] == round(1 / 3, 4)


def test_overdue_and_due_soon_are_disjoint(client, setup):
    headers, org_id, project_id = setup
    now = datetime.now(timezone.utc)
    _create_task(
        client,
        headers,
        org_id,
        project_id,
        title="Late",
        due_date=(now - timedelta(days=2)).isoformat(),
    )
    _create_task(
        client,
        headers,
        org_id,
        project_id,
        title="Soon",
        due_date=(now + timedelta(days=2)).isoformat(),
    )
    _create_task(
        client,
        headers,
        org_id,
        project_id,
        title="Later",
        due_date=(now + timedelta(days=60)).isoformat(),
    )
    _create_task(client, headers, org_id, project_id, title="No date")

    stats = _project_stats(client, headers, org_id, project_id).json()["tasks"]

    assert stats["overdue"] == 1
    assert stats["due_soon"] == 1


def test_a_completed_task_is_never_overdue(client, setup):
    headers, org_id, project_id = setup
    past = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    task = _create_task(client, headers, org_id, project_id, title="Late", due_date=past)
    _set_status(client, headers, org_id, project_id, task["id"], "done")

    assert _project_stats(client, headers, org_id, project_id).json()["tasks"]["overdue"] == 0


def test_blocked_count_tracks_open_dependencies(client, setup):
    headers, org_id, project_id = setup
    blocked = _create_task(client, headers, org_id, project_id, title="Ship")
    blocker = _create_task(client, headers, org_id, project_id, title="Changelog")
    client.post(
        _tasks_url(org_id, project_id, f"/{blocked['id']}/dependencies"),
        json={"depends_on_id": blocker["id"]},
        headers=headers,
    )

    assert _project_stats(client, headers, org_id, project_id).json()["tasks"]["blocked"] == 1

    _set_status(client, headers, org_id, project_id, blocker["id"], "done")

    assert _project_stats(client, headers, org_id, project_id).json()["tasks"]["blocked"] == 0


def test_assignee_breakdown_keeps_the_unassigned_bucket(client, setup):
    headers, org_id, project_id = setup
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, headers, org_id, "member@example.com")
    member = _me(client, member_headers)
    first = _create_task(
        client, headers, org_id, project_id, title="Assigned", assignee_id=member["id"]
    )
    _create_task(client, headers, org_id, project_id, title="Also", assignee_id=member["id"])
    _create_task(client, headers, org_id, project_id, title="Nobody's")
    _set_status(client, headers, org_id, project_id, first["id"], "done")

    breakdown = _project_stats(client, headers, org_id, project_id).json()["by_assignee"]

    by_id = {row["assignee_id"]: row for row in breakdown}
    assert by_id[member["id"]] == {
        "assignee_id": member["id"],
        "email": "member@example.com",
        "total": 2,
        "done": 1,
    }
    assert by_id[None]["total"] == 1
    assert sum(row["total"] for row in breakdown) == 3


def test_milestone_breakdown_keeps_the_unfiled_bucket(client, setup):
    headers, org_id, project_id = setup
    milestone = client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/milestones",
        json={"name": "Beta"},
        headers=headers,
    ).json()
    first = _create_task(
        client, headers, org_id, project_id, title="Filed", milestone_id=milestone["id"]
    )
    _create_task(client, headers, org_id, project_id, title="Also", milestone_id=milestone["id"])
    _create_task(client, headers, org_id, project_id, title="Unfiled")
    _set_status(client, headers, org_id, project_id, first["id"], "done")

    breakdown = _project_stats(client, headers, org_id, project_id).json()["by_milestone"]

    by_id = {row["milestone_id"]: row for row in breakdown}
    assert by_id[milestone["id"]] == {
        "milestone_id": milestone["id"],
        "name": "Beta",
        "total": 2,
        "done": 1,
    }
    assert by_id[None]["total"] == 1
    assert sum(row["total"] for row in breakdown) == 3


def test_soft_deleted_tasks_are_excluded(client, setup):
    headers, org_id, project_id = setup
    task = _create_task(client, headers, org_id, project_id, title="Gone")
    _create_task(client, headers, org_id, project_id, title="Here")
    client.delete(_tasks_url(org_id, project_id, f"/{task['id']}"), headers=headers)

    assert _project_stats(client, headers, org_id, project_id).json()["tasks"]["total"] == 1


def test_organization_stats_span_projects(client, setup):
    headers, org_id, project_id = setup
    other = _create_project(client, headers, org_id, "Mobile App")
    _create_task(client, headers, org_id, project_id, title="One")
    _create_task(client, headers, org_id, other["id"], title="Two")
    _create_task(client, headers, org_id, other["id"], title="Three")

    body = _org_stats(client, headers, org_id).json()

    assert body["projects"] == 2
    assert body["tasks"]["total"] == 3
    per_project = {row["name"]: row["total"] for row in body["per_project"]}
    assert per_project == {"Website Revamp": 1, "Mobile App": 2}


def test_a_project_with_no_tasks_still_appears(client, setup):
    headers, org_id, project_id = setup
    _create_project(client, headers, org_id, "Empty")

    body = _org_stats(client, headers, org_id).json()

    assert {"project_id", "name", "total", "done"} == set(body["per_project"][0])
    assert {row["name"] for row in body["per_project"]} == {"Website Revamp", "Empty"}


def test_deleted_projects_are_excluded(client, setup):
    headers, org_id, project_id = setup
    doomed = _create_project(client, headers, org_id, "Doomed")
    _create_task(client, headers, org_id, doomed["id"], title="Ghost")
    client.delete(f"/api/v1/organizations/{org_id}/projects/{doomed['id']}", headers=headers)

    body = _org_stats(client, headers, org_id).json()

    assert body["projects"] == 1
    assert body["tasks"]["total"] == 0


def test_org_stats_hide_restricted_projects_from_outsiders(client, setup):
    """The totals must not report the size of a project the caller can't open."""
    headers, org_id, project_id = setup
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    _add_org_member(client, headers, org_id, "outsider@example.com")
    secret = _create_project(client, headers, org_id, "Acquisition", visibility="restricted")
    _create_task(client, headers, org_id, secret["id"], title="Term sheet")
    _create_task(client, headers, org_id, project_id, title="Public work")

    owner_view = _org_stats(client, headers, org_id).json()
    outsider_view = _org_stats(client, outsider_headers, org_id).json()

    assert owner_view["projects"] == 2
    assert owner_view["tasks"]["total"] == 2
    assert outsider_view["projects"] == 1
    assert outsider_view["tasks"]["total"] == 1
    assert [row["name"] for row in outsider_view["per_project"]] == ["Website Revamp"]


def test_project_stats_are_404_for_an_outsider(client, setup):
    headers, org_id, project_id = setup
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    _add_org_member(client, headers, org_id, "outsider@example.com")
    secret = _create_project(client, headers, org_id, "Acquisition", visibility="restricted")

    response = _project_stats(client, outsider_headers, org_id, secret["id"])

    assert response.status_code == 404


def test_stats_require_membership(client, setup):
    headers, org_id, project_id = setup
    stranger_headers = _register_and_login(client, email="stranger@example.com")

    assert _org_stats(client, stranger_headers, org_id).status_code == 404
    assert _project_stats(client, stranger_headers, org_id, project_id).status_code == 404


def test_stats_require_authentication(client, setup):
    headers, org_id, project_id = setup

    assert client.get(f"/api/v1/organizations/{org_id}/stats").status_code == 401
