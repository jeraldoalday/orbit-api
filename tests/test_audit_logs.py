"""The audit trail: what gets recorded, by whom, and who may read it."""

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


def _audit_url(org_id, query=""):
    return f"/api/v1/organizations/{org_id}/audit-logs{query}"


def _create_project(client, headers, org_id, name="Website Revamp"):
    return client.post(_projects_url(org_id), json={"name": name}, headers=headers).json()


def _entries(client, headers, org_id, query=""):
    return client.get(_audit_url(org_id, query), headers=headers).json()


def _actions(client, headers, org_id, query=""):
    return [entry["action"] for entry in _entries(client, headers, org_id, query)]


@pytest.fixture()
def setup(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)
    return headers, org


def test_the_trail_starts_empty(client, setup):
    headers, org = setup

    assert _entries(client, headers, org["id"]) == []


def test_creating_a_project_is_recorded(client, setup):
    headers, org = setup
    project = _create_project(client, headers, org["id"])

    entries = _entries(client, headers, org["id"])

    assert len(entries) == 1
    assert entries[0]["action"] == "project.created"
    assert entries[0]["resource_type"] == "project"
    assert entries[0]["resource_id"] == project["id"]
    assert entries[0]["actor"]["email"] == "owner@example.com"
    assert entries[0]["actor_email"] == "owner@example.com"
    assert entries[0]["data"]["name"] == "Website Revamp"


def test_entries_are_newest_first(client, setup):
    headers, org = setup
    project = _create_project(client, headers, org["id"])
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)

    assert _actions(client, headers, org["id"]) == ["project.deleted", "project.created"]


def test_the_delete_restore_purge_cycle_is_fully_recorded(client, setup):
    headers, org = setup
    project = _create_project(client, headers, org["id"])
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)
    client.post(_projects_url(org["id"], f"/{project['id']}/restore"), headers=headers)
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)
    client.delete(_projects_url(org["id"], f"/{project['id']}/purge"), headers=headers)

    assert _actions(client, headers, org["id"]) == [
        "project.purged",
        "project.deleted",
        "project.restored",
        "project.deleted",
        "project.created",
    ]


def test_a_purge_entry_outlives_the_project_it_describes(client, setup):
    """The entry holds a plain UUID, not a foreign key, precisely for this."""
    headers, org = setup
    project = _create_project(client, headers, org["id"])
    client.delete(_projects_url(org["id"], f"/{project['id']}"), headers=headers)
    client.delete(_projects_url(org["id"], f"/{project['id']}/purge"), headers=headers)

    purged = _entries(client, headers, org["id"], "?action=project.purged")

    assert purged[0]["resource_id"] == project["id"]
    assert purged[0]["data"]["name"] == "Website Revamp"


def test_a_visibility_change_records_what_it_moved_between(client, setup):
    headers, org = setup
    project = _create_project(client, headers, org["id"])

    client.patch(
        _projects_url(org["id"], f"/{project['id']}"),
        json={"visibility": "restricted"},
        headers=headers,
    )

    updated = _entries(client, headers, org["id"], "?action=project.updated")
    assert updated[0]["data"]["visibility"] == {"from": "open", "to": "restricted"}


def test_a_rename_alone_is_not_recorded(client, setup):
    """Only visibility changes who can see the project, so only it is audited."""
    headers, org = setup
    project = _create_project(client, headers, org["id"])

    client.patch(
        _projects_url(org["id"], f"/{project['id']}"), json={"name": "Renamed"}, headers=headers
    )

    assert _entries(client, headers, org["id"], "?action=project.updated") == []


def test_task_delete_restore_and_purge_are_recorded(client, setup):
    headers, org = setup
    project = _create_project(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers
    ).json()

    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)
    client.post(_tasks_url(org["id"], project["id"], f"/{task['id']}/restore"), headers=headers)
    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)
    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}/purge"), headers=headers)

    assert _actions(client, headers, org["id"], "?resource_type=task") == [
        "task.purged",
        "task.deleted",
        "task.restored",
        "task.deleted",
    ]


def test_membership_changes_are_recorded(client, setup):
    headers, org = setup
    _register_and_login(client, email="member@example.com")
    added = _add_org_member(client, headers, org["id"], "member@example.com").json()

    client.patch(
        f"/api/v1/organizations/{org['id']}/members/{added['id']}",
        json={"role": "admin"},
        headers=headers,
    )
    client.delete(f"/api/v1/organizations/{org['id']}/members/{added['id']}", headers=headers)

    entries = _entries(client, headers, org["id"], "?resource_type=membership")
    assert [entry["action"] for entry in entries] == [
        "member.removed",
        "member.role_changed",
        "member.added",
    ]
    assert entries[1]["data"] == {"from": "member", "to": "admin"}
    assert entries[2]["data"]["email"] == "member@example.com"


def test_webhook_lifecycle_is_recorded_without_the_secret(client, setup):
    headers, org = setup
    subscription = client.post(
        f"/api/v1/organizations/{org['id']}/webhooks",
        json={"url": "https://hooks.example.com/orbit", "events": ["task.created"]},
        headers=headers,
    ).json()

    client.post(
        f"/api/v1/organizations/{org['id']}/webhooks/{subscription['id']}/rotate_secret",
        headers=headers,
    )
    client.delete(
        f"/api/v1/organizations/{org['id']}/webhooks/{subscription['id']}", headers=headers
    )

    entries = _entries(client, headers, org["id"], "?resource_type=webhook")
    assert [entry["action"] for entry in entries] == [
        "webhook.deleted",
        "webhook.secret_rotated",
        "webhook.created",
    ]
    # An audit trail holding credentials is a second place to steal them from.
    serialized = str(entries)
    assert subscription["secret"] not in serialized


def test_entries_can_be_filtered_by_actor(client, setup):
    owner_headers, org = setup
    admin_headers = _register_and_login(client, email="admin@example.com")
    _add_org_member(client, owner_headers, org["id"], "admin@example.com", role="admin")
    admin = client.get("/api/v1/users/me", headers=admin_headers).json()
    _create_project(client, owner_headers, org["id"], name="Owner Project")
    _create_project(client, admin_headers, org["id"], name="Admin Project")

    entries = _entries(client, owner_headers, org["id"], f"?actor_id={admin['id']}")

    assert [entry["data"]["name"] for entry in entries] == ["Admin Project"]


def test_entries_can_be_filtered_by_resource(client, setup):
    headers, org = setup
    first = _create_project(client, headers, org["id"], name="First")
    _create_project(client, headers, org["id"], name="Second")

    entries = _entries(client, headers, org["id"], f"?resource_id={first['id']}")

    assert [entry["data"]["name"] for entry in entries] == ["First"]


def test_pagination_walks_the_trail(client, setup):
    headers, org = setup
    for index in range(3):
        _create_project(client, headers, org["id"], name=f"Project {index}")

    page = _entries(client, headers, org["id"], "?limit=2")
    second_page = _entries(client, headers, org["id"], "?limit=2&offset=2")

    assert len(page) == 2
    assert len(second_page) == 1
    assert {entry["id"] for entry in page}.isdisjoint({entry["id"] for entry in second_page})


def test_another_orgs_actions_are_not_in_this_trail(client, setup):
    headers, org = setup
    other_org = _create_org(client, headers, name="Other Inc")
    _create_project(client, headers, other_org["id"], name="Elsewhere")

    assert _entries(client, headers, org["id"]) == []


def test_a_plain_member_cannot_read_the_trail(client, setup):
    owner_headers, org = setup
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, owner_headers, org["id"], "member@example.com")

    assert client.get(_audit_url(org["id"]), headers=member_headers).status_code == 403


def test_a_non_member_cannot_probe_the_trail(client, setup):
    _headers, org = setup
    outsider_headers = _register_and_login(client, email="outsider@example.com")

    assert client.get(_audit_url(org["id"]), headers=outsider_headers).status_code == 404


def test_the_trail_requires_authentication(client, setup):
    _headers, org = setup

    assert client.get(_audit_url(org["id"])).status_code == 401


def test_the_trail_is_read_only(client, setup):
    """There is no route that writes, edits or deletes an entry."""
    headers, org = setup
    _create_project(client, headers, org["id"])
    entry = _entries(client, headers, org["id"])[0]

    # POST hits the collection path, which only serves GET, so the method is
    # rejected; there is no per-entry path at all, so DELETE finds no route.
    assert client.post(_audit_url(org["id"]), json={}, headers=headers).status_code == 405
    assert (
        client.delete(_audit_url(org["id"], f"/{entry['id']}"), headers=headers).status_code == 404
    )


def test_a_rejected_change_leaves_no_entry(client, setup):
    """Entries share the transaction, so a failed write records nothing."""
    headers, org = setup

    response = _add_org_member(client, headers, org["id"], "nobody@example.com")

    assert response.status_code == 404
    assert _entries(client, headers, org["id"]) == []


def _backdate(db, resource_id, when):
    import uuid

    from app.models.audit_log import AuditLog

    entry = db.query(AuditLog).filter(AuditLog.resource_id == uuid.UUID(resource_id)).one()
    entry.created_at = when
    db.commit()


def test_entries_can_be_filtered_by_since(client, setup, db):
    from datetime import datetime, timedelta, timezone

    headers, org = setup
    old = _create_project(client, headers, org["id"], name="Old")
    _create_project(client, headers, org["id"], name="Recent")
    _backdate(db, old["id"], datetime.now(timezone.utc) - timedelta(days=10))

    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    entries = _entries(client, headers, org["id"], f"?since={cutoff}")

    assert [entry["data"]["name"] for entry in entries] == ["Recent"]


def test_entries_can_be_filtered_by_until(client, setup, db):
    from datetime import datetime, timedelta, timezone

    headers, org = setup
    old = _create_project(client, headers, org["id"], name="Old")
    _create_project(client, headers, org["id"], name="Recent")
    _backdate(db, old["id"], datetime.now(timezone.utc) - timedelta(days=10))

    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    entries = _entries(client, headers, org["id"], f"?until={cutoff}")

    assert [entry["data"]["name"] for entry in entries] == ["Old"]


def test_a_date_range_combines_since_and_until(client, setup, db):
    from datetime import datetime, timedelta, timezone

    headers, org = setup
    oldest = _create_project(client, headers, org["id"], name="Oldest")
    middle = _create_project(client, headers, org["id"], name="Middle")
    _create_project(client, headers, org["id"], name="Newest")

    now = datetime.now(timezone.utc)
    _backdate(db, oldest["id"], now - timedelta(days=10))
    _backdate(db, middle["id"], now - timedelta(days=5))

    since = (now - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    until = (now - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    entries = _entries(client, headers, org["id"], f"?since={since}&until={until}")

    assert [entry["data"]["name"] for entry in entries] == ["Middle"]
