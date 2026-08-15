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


def _create_label(client, headers, org_id, name="Bug"):
    return client.post(
        f"/api/v1/organizations/{org_id}/labels", json={"name": name}, headers=headers
    ).json()


def _task_labels_url(org_id, project_id, task_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks/{task_id}/labels{suffix}"


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


def _setup(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    return headers, org, project


def test_attach_label_to_task(client):
    headers, org, project = _setup(client)
    task = _create_task(client, headers, org["id"], project["id"])
    label = _create_label(client, headers, org["id"])

    response = client.post(
        _task_labels_url(org["id"], project["id"], task["id"]),
        json={"label_id": label["id"]},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["id"] == label["id"]

    listing = client.get(_task_labels_url(org["id"], project["id"], task["id"]), headers=headers)
    assert [label_["id"] for label_ in listing.json()] == [label["id"]]


def test_attach_same_label_twice_rejected(client):
    headers, org, project = _setup(client)
    task = _create_task(client, headers, org["id"], project["id"])
    label = _create_label(client, headers, org["id"])
    client.post(
        _task_labels_url(org["id"], project["id"], task["id"]),
        json={"label_id": label["id"]},
        headers=headers,
    )

    response = client.post(
        _task_labels_url(org["id"], project["id"], task["id"]),
        json={"label_id": label["id"]},
        headers=headers,
    )

    assert response.status_code == 409


def test_attach_unknown_label_returns_404(client):
    headers, org, project = _setup(client)
    task = _create_task(client, headers, org["id"], project["id"])

    response = client.post(
        _task_labels_url(org["id"], project["id"], task["id"]),
        json={"label_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )

    assert response.status_code == 404


def test_detach_label_from_task(client):
    headers, org, project = _setup(client)
    task = _create_task(client, headers, org["id"], project["id"])
    label = _create_label(client, headers, org["id"])
    client.post(
        _task_labels_url(org["id"], project["id"], task["id"]),
        json={"label_id": label["id"]},
        headers=headers,
    )

    response = client.delete(
        _task_labels_url(org["id"], project["id"], task["id"], f"/{label['id']}"),
        headers=headers,
    )

    assert response.status_code == 204
    listing = client.get(_task_labels_url(org["id"], project["id"], task["id"]), headers=headers)
    assert listing.json() == []


def test_detach_label_not_attached_returns_404(client):
    headers, org, project = _setup(client)
    task = _create_task(client, headers, org["id"], project["id"])
    label = _create_label(client, headers, org["id"])

    response = client.delete(
        _task_labels_url(org["id"], project["id"], task["id"], f"/{label['id']}"),
        headers=headers,
    )

    assert response.status_code == 404


def test_deleting_label_detaches_it_from_tasks(client):
    headers, org, project = _setup(client)
    task = _create_task(client, headers, org["id"], project["id"])
    label = _create_label(client, headers, org["id"])
    client.post(
        _task_labels_url(org["id"], project["id"], task["id"]),
        json={"label_id": label["id"]},
        headers=headers,
    )

    delete_response = client.delete(
        f"/api/v1/organizations/{org['id']}/labels/{label['id']}", headers=headers
    )
    assert delete_response.status_code == 204

    listing = client.get(_task_labels_url(org["id"], project["id"], task["id"]), headers=headers)
    assert listing.json() == []


def test_list_tasks_filters_by_label(client):
    headers, org, project = _setup(client)
    labeled = _create_task(client, headers, org["id"], project["id"], title="Labeled")
    _create_task(client, headers, org["id"], project["id"], title="Unlabeled")
    label = _create_label(client, headers, org["id"])
    client.post(
        _task_labels_url(org["id"], project["id"], labeled["id"]),
        json={"label_id": label["id"]},
        headers=headers,
    )

    response = client.get(
        _tasks_url(org["id"], project["id"], f"?label_id={label['id']}"), headers=headers
    )

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [labeled["id"]]
