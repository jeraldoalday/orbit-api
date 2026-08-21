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


def _add_org_member(client, headers, org_id, email, role="member"):
    return client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": email, "role": role},
        headers=headers,
    )


def _create_project(client, headers, org_id, name="Website Revamp"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects", json={"name": name}, headers=headers
    ).json()


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


def _me(client, headers):
    return client.get("/api/v1/users/me", headers=headers).json()


def _setup(client, member_email="member@example.com"):
    """An org with an owner and one plain member, plus an open project."""
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email=member_email)
    org = _create_org(client, owner_headers)
    _add_org_member(client, owner_headers, org["id"], member_email)
    project = _create_project(client, owner_headers, org["id"])
    return owner_headers, member_headers, org, project


def test_notifications_start_empty(client):
    headers = _register_and_login(client)

    response = client.get("/api/v1/notifications", headers=headers)

    assert response.status_code == 200
    assert response.json() == []


def test_notifications_require_authentication(client):
    assert client.get("/api/v1/notifications").status_code == 401


def test_assigning_a_task_notifies_the_assignee(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)

    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    )

    notifications = client.get("/api/v1/notifications", headers=member_headers).json()
    assert len(notifications) == 1
    assert notifications[0]["notification_type"] == "task_assigned"
    assert notifications[0]["actor"]["email"] == "owner@example.com"
    assert notifications[0]["data"]["task_title"] == "Ship it"
    assert notifications[0]["is_read"] is False


def test_self_assignment_does_not_notify(client):
    owner_headers, _member_headers, org, project = _setup(client)
    owner = _me(client, owner_headers)

    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": owner["id"]},
        headers=owner_headers,
    )

    assert client.get("/api/v1/notifications", headers=owner_headers).json() == []


def test_reassigning_a_task_notifies_the_new_assignee(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=owner_headers
    ).json()

    client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"assignee_id": member["id"]},
        headers=owner_headers,
    )

    notifications = client.get("/api/v1/notifications", headers=member_headers).json()
    assert [n["notification_type"] for n in notifications] == ["task_assigned"]


def test_unassigning_a_task_notifies_nobody(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    ).json()

    client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"assignee_id": None},
        headers=owner_headers,
    )

    notifications = client.get("/api/v1/notifications", headers=member_headers).json()
    assert len(notifications) == 1


def test_commenting_notifies_the_assignee(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    ).json()

    client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "Any progress?"},
        headers=owner_headers,
    )

    notifications = client.get("/api/v1/notifications", headers=member_headers).json()
    # Newest first: the comment lands above the original assignment.
    assert [n["notification_type"] for n in notifications] == ["task_commented", "task_assigned"]


def test_assignee_commenting_on_own_task_does_not_self_notify(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    ).json()

    client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "Working on it"},
        headers=member_headers,
    )

    notifications = client.get("/api/v1/notifications", headers=member_headers).json()
    assert [n["notification_type"] for n in notifications] == ["task_assigned"]


def test_mention_notifies_the_mentioned_user(client):
    owner_headers, member_headers, org, project = _setup(client)
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=owner_headers
    ).json()

    client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "Can you look at this @member@example.com?"},
        headers=owner_headers,
    )

    notifications = client.get("/api/v1/notifications", headers=member_headers).json()
    assert [n["notification_type"] for n in notifications] == ["mentioned"]


def test_mention_of_the_assignee_produces_a_single_notification(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    ).json()

    client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "@member@example.com ping"},
        headers=owner_headers,
    )

    notifications = client.get(
        "/api/v1/notifications?unread_only=true", headers=member_headers
    ).json()
    assert [n["notification_type"] for n in notifications] == ["mentioned", "task_assigned"]


def test_mentioning_a_non_member_is_ignored(client):
    owner_headers, _member_headers, org, project = _setup(client)
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=owner_headers
    ).json()

    client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "hey @outsider@example.com"},
        headers=owner_headers,
    )

    assert client.get("/api/v1/notifications", headers=outsider_headers).json() == []


def test_mentioning_an_unknown_address_is_ignored(client):
    owner_headers, _member_headers, org, project = _setup(client)
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=owner_headers
    ).json()

    response = client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "hey @nobody@example.com"},
        headers=owner_headers,
    )

    assert response.status_code == 201


def test_unread_count(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    for title in ["One", "Two"]:
        client.post(
            _tasks_url(org["id"], project["id"]),
            json={"title": title, "assignee_id": member["id"]},
            headers=owner_headers,
        )

    response = client.get("/api/v1/notifications/unread_count", headers=member_headers)

    assert response.status_code == 200
    assert response.json() == {"unread": 2}


def test_mark_notification_read(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    )
    notification = client.get("/api/v1/notifications", headers=member_headers).json()[0]

    response = client.post(
        f"/api/v1/notifications/{notification['id']}/read", headers=member_headers
    )

    assert response.status_code == 200
    assert response.json()["is_read"] is True
    assert response.json()["read_at"] is not None
    assert client.get("/api/v1/notifications/unread_count", headers=member_headers).json() == {
        "unread": 0
    }


def test_marking_read_twice_keeps_the_first_timestamp(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    )
    notification = client.get("/api/v1/notifications", headers=member_headers).json()[0]
    first = client.post(
        f"/api/v1/notifications/{notification['id']}/read", headers=member_headers
    ).json()

    second = client.post(
        f"/api/v1/notifications/{notification['id']}/read", headers=member_headers
    ).json()

    assert second["read_at"] == first["read_at"]


def test_mark_notification_unread(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    )
    notification = client.get("/api/v1/notifications", headers=member_headers).json()[0]
    client.post(f"/api/v1/notifications/{notification['id']}/read", headers=member_headers)

    response = client.post(
        f"/api/v1/notifications/{notification['id']}/unread", headers=member_headers
    )

    assert response.status_code == 200
    assert response.json()["is_read"] is False
    assert client.get("/api/v1/notifications/unread_count", headers=member_headers).json() == {
        "unread": 1
    }


def test_mark_all_read(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    for title in ["One", "Two", "Three"]:
        client.post(
            _tasks_url(org["id"], project["id"]),
            json={"title": title, "assignee_id": member["id"]},
            headers=owner_headers,
        )

    response = client.post("/api/v1/notifications/read_all", headers=member_headers)

    assert response.status_code == 200
    assert response.json() == {"marked": 3}
    assert client.get("/api/v1/notifications/unread_count", headers=member_headers).json() == {
        "unread": 0
    }


def test_mark_all_read_is_idempotent(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    )
    client.post("/api/v1/notifications/read_all", headers=member_headers)

    response = client.post("/api/v1/notifications/read_all", headers=member_headers)

    assert response.json() == {"marked": 0}


def test_unread_only_filter(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    for title in ["One", "Two"]:
        client.post(
            _tasks_url(org["id"], project["id"]),
            json={"title": title, "assignee_id": member["id"]},
            headers=owner_headers,
        )
    notifications = client.get("/api/v1/notifications", headers=member_headers).json()
    client.post(f"/api/v1/notifications/{notifications[0]['id']}/read", headers=member_headers)

    response = client.get("/api/v1/notifications?unread_only=true", headers=member_headers)

    assert len(response.json()) == 1
    assert response.json()[0]["id"] == notifications[1]["id"]


def test_notifications_filter_by_organization(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    other_org = _create_org(client, owner_headers, name="Other Org")
    _add_org_member(client, owner_headers, other_org["id"], "member@example.com")
    other_project = _create_project(client, owner_headers, other_org["id"])
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "First org", "assignee_id": member["id"]},
        headers=owner_headers,
    )
    client.post(
        _tasks_url(other_org["id"], other_project["id"]),
        json={"title": "Second org", "assignee_id": member["id"]},
        headers=owner_headers,
    )

    response = client.get(
        f"/api/v1/notifications?organization_id={other_org['id']}", headers=member_headers
    )

    assert len(response.json()) == 1
    assert response.json()[0]["data"]["task_title"] == "Second org"


def test_notifications_paginate(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    for title in ["One", "Two", "Three"]:
        client.post(
            _tasks_url(org["id"], project["id"]),
            json={"title": title, "assignee_id": member["id"]},
            headers=owner_headers,
        )

    response = client.get("/api/v1/notifications?limit=2&offset=1", headers=member_headers)

    assert [n["data"]["task_title"] for n in response.json()] == ["Two", "One"]


def test_cannot_read_another_users_notification(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    )
    notification = client.get("/api/v1/notifications", headers=member_headers).json()[0]

    response = client.post(
        f"/api/v1/notifications/{notification['id']}/read", headers=owner_headers
    )

    assert response.status_code == 404


def test_delete_notification(client):
    owner_headers, member_headers, org, project = _setup(client)
    member = _me(client, member_headers)
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": member["id"]},
        headers=owner_headers,
    )
    notification = client.get("/api/v1/notifications", headers=member_headers).json()[0]

    response = client.delete(f"/api/v1/notifications/{notification['id']}", headers=member_headers)

    assert response.status_code == 204
    assert client.get("/api/v1/notifications", headers=member_headers).json() == []


def test_notification_not_found(client):
    headers = _register_and_login(client)

    response = client.delete(
        "/api/v1/notifications/00000000-0000-0000-0000-000000000000", headers=headers
    )

    assert response.status_code == 404
