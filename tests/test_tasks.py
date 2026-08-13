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


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


def test_create_task_defaults_to_todo(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Set up CI"
    assert body["status"] == "todo"
    assert body["assignee_id"] is None


def test_create_task_requires_membership(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=outsider_headers
    )

    assert response.status_code == 404


def test_assign_task_to_non_member_rejected(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])
    outsider_user_id = client.get("/api/v1/users/me", headers=outsider_headers).json()["id"]

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Set up CI", "assignee_id": outsider_user_id},
        headers=owner_headers,
    )

    assert response.status_code == 422


def test_assign_task_to_member_succeeds(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])
    owner_id = client.get("/api/v1/users/me", headers=owner_headers).json()["id"]

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Set up CI", "assignee_id": owner_id},
        headers=owner_headers,
    )

    assert response.status_code == 201
    assert response.json()["assignee_id"] == owner_id


def test_list_tasks_scoped_to_project(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project_a = _create_project(client, headers, org["id"], name="Project A")
    project_b = _create_project(client, headers, org["id"], name="Project B")
    client.post(_tasks_url(org["id"], project_a["id"]), json={"title": "A task"}, headers=headers)
    client.post(_tasks_url(org["id"], project_b["id"]), json={"title": "B task"}, headers=headers)

    response = client.get(_tasks_url(org["id"], project_a["id"]), headers=headers)

    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    assert titles == ["A task"]


def test_update_task_status(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=headers
    ).json()

    response = client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"status": "in_progress"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_update_task_can_unassign(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    user_id = client.get("/api/v1/users/me", headers=headers).json()["id"]
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Set up CI", "assignee_id": user_id},
        headers=headers,
    ).json()
    assert task["assignee_id"] == user_id

    response = client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"assignee_id": None},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["assignee_id"] is None


def test_delete_task(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=headers
    ).json()

    response = client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers
    )

    assert response.status_code == 204
    assert (
        client.get(
            _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers
        ).status_code
        == 404
    )


def test_member_cannot_delete_task(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    project = _create_project(client, owner_headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=owner_headers
    ).json()

    response = client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=member_headers
    )

    assert response.status_code == 403


def test_admin_can_delete_task(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=owner_headers
    ).json()

    response = client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=owner_headers
    )

    assert response.status_code == 204


def test_list_tasks_filters_by_status(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    todo = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Todo task"}, headers=headers
    ).json()
    done = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Done task"}, headers=headers
    ).json()
    client.patch(
        _tasks_url(org["id"], project["id"], f"/{done['id']}"),
        json={"status": "done"},
        headers=headers,
    )

    response = client.get(_tasks_url(org["id"], project["id"], "?status=done"), headers=headers)

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [done["id"]]
    assert todo["id"] not in ids


def test_list_tasks_filters_by_assignee(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    user_id = client.get("/api/v1/users/me", headers=headers).json()["id"]
    assigned = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Assigned task", "assignee_id": user_id},
        headers=headers,
    ).json()
    client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Unassigned task"}, headers=headers
    )

    response = client.get(
        _tasks_url(org["id"], project["id"], f"?assignee_id={user_id}"), headers=headers
    )

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [assigned["id"]]


def test_list_tasks_sorts_by_title_desc(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Alpha"}, headers=headers)
    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Bravo"}, headers=headers)

    response = client.get(
        _tasks_url(org["id"], project["id"], "?sort_by=title&order=desc"), headers=headers
    )

    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    assert titles == ["Bravo", "Alpha"]


def test_task_not_found_for_wrong_project(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project_a = _create_project(client, headers, org["id"], name="Project A")
    project_b = _create_project(client, headers, org["id"], name="Project B")
    task = client.post(
        _tasks_url(org["id"], project_a["id"]), json={"title": "A task"}, headers=headers
    ).json()

    response = client.get(_tasks_url(org["id"], project_b["id"], f"/{task['id']}"), headers=headers)

    assert response.status_code == 404
