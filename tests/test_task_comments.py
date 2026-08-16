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


def _create_task(client, headers, org_id, project_id, title="Set up CI"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks",
        json={"title": title},
        headers=headers,
    ).json()


def _task_base(org_id, project_id, task_id):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks/{task_id}"


def test_create_and_list_comments(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = _create_task(client, headers, org["id"], project["id"])

    response = client.post(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments",
        json={"body": "Looks good"},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "Looks good"
    assert body["author"]["email"] == "jane@example.com"

    list_response = client.get(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments", headers=headers
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_list_comments_with_tied_timestamps_orders_deterministically(client, monkeypatch):
    import app.models.mixins as mixins

    class _FixedDatetime(mixins.datetime):
        @classmethod
        def now(cls, tz=None):
            return mixins.datetime(2026, 1, 1, tzinfo=mixins.timezone.utc)

    monkeypatch.setattr(mixins, "datetime", _FixedDatetime)

    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = _create_task(client, headers, org["id"], project["id"])
    base = _task_base(org["id"], project["id"], task["id"])

    first = client.post(f"{base}/comments", json={"body": "First"}, headers=headers).json()
    second = client.post(f"{base}/comments", json={"body": "Second"}, headers=headers).json()
    assert first["created_at"] == second["created_at"]

    first_listing = client.get(f"{base}/comments", headers=headers).json()
    second_listing = client.get(f"{base}/comments", headers=headers).json()

    ids = [c["id"] for c in first_listing]
    assert set(ids) == {first["id"], second["id"]}
    assert ids == [c["id"] for c in second_listing]


def test_author_can_delete_own_comment(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = _create_task(client, headers, org["id"], project["id"])
    comment = client.post(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments",
        json={"body": "Looks good"},
        headers=headers,
    ).json()

    response = client.delete(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments/{comment['id']}",
        headers=headers,
    )

    assert response.status_code == 204


def test_non_author_non_admin_cannot_delete_comment(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    project = _create_project(client, owner_headers, org["id"])
    task = _create_task(client, owner_headers, org["id"], project["id"])
    comment = client.post(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments",
        json={"body": "Owner's comment"},
        headers=owner_headers,
    ).json()

    response = client.delete(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments/{comment['id']}",
        headers=member_headers,
    )

    assert response.status_code == 403


def test_admin_can_delete_any_comment(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    project = _create_project(client, owner_headers, org["id"])
    task = _create_task(client, owner_headers, org["id"], project["id"])
    comment = client.post(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments",
        json={"body": "Member's comment"},
        headers=member_headers,
    ).json()

    response = client.delete(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments/{comment['id']}",
        headers=owner_headers,
    )

    assert response.status_code == 204


def test_timeline_merges_comments_and_activities(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = _create_task(client, headers, org["id"], project["id"])
    client.patch(
        _task_base(org["id"], project["id"], task["id"]),
        json={"status": "in_progress"},
        headers=headers,
    )
    client.post(
        f"{_task_base(org['id'], project['id'], task['id'])}/comments",
        json={"body": "Started work"},
        headers=headers,
    )

    response = client.get(
        f"{_task_base(org['id'], project['id'], task['id'])}/timeline", headers=headers
    )

    assert response.status_code == 200
    entries = response.json()
    kinds = [entry["kind"] for entry in entries]
    assert sorted(kinds) == ["activity", "activity", "comment"]

    activity_types = {
        entry["activity"]["activity_type"] for entry in entries if entry["kind"] == "activity"
    }
    assert activity_types == {"created", "updated"}

    updated_entry = next(
        entry
        for entry in entries
        if entry["kind"] == "activity" and entry["activity"]["activity_type"] == "updated"
    )
    assert updated_entry["activity"]["data"] == {"status": {"from": "todo", "to": "in_progress"}}

    comment_entry = next(entry for entry in entries if entry["kind"] == "comment")
    assert comment_entry["comment"]["body"] == "Started work"


def test_updating_multiple_fields_records_a_single_activity(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = _create_task(client, headers, org["id"], project["id"])

    client.patch(
        _task_base(org["id"], project["id"], task["id"]),
        json={"title": "Ship CI", "status": "in_progress"},
        headers=headers,
    )

    response = client.get(
        f"{_task_base(org['id'], project['id'], task['id'])}/timeline", headers=headers
    )

    activities = [entry for entry in response.json() if entry["kind"] == "activity"]
    updated = [a for a in activities if a["activity"]["activity_type"] == "updated"]
    assert len(updated) == 1
    assert updated[0]["activity"]["data"] == {
        "title": {"from": "Set up CI", "to": "Ship CI"},
        "status": {"from": "todo", "to": "in_progress"},
    }


def test_outsider_cannot_access_comments_or_timeline(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])
    task = _create_task(client, owner_headers, org["id"], project["id"])

    base = _task_base(org["id"], project["id"], task["id"])
    assert client.get(f"{base}/comments", headers=outsider_headers).status_code == 404
    assert (
        client.post(f"{base}/comments", json={"body": "hi"}, headers=outsider_headers).status_code
        == 404
    )
    assert client.get(f"{base}/timeline", headers=outsider_headers).status_code == 404
