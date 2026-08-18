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


def _create_project(client, headers, org_id, name="Website Revamp", visibility=None):
    payload = {"name": name}
    if visibility is not None:
        payload["visibility"] = visibility
    return client.post(
        f"/api/v1/organizations/{org_id}/projects", json=payload, headers=headers
    ).json()


def _project_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}{suffix}"


def _members_url(org_id, project_id, suffix=""):
    return _project_url(org_id, project_id, f"/members{suffix}")


def _tasks_url(org_id, project_id, suffix=""):
    return _project_url(org_id, project_id, f"/tasks{suffix}")


def _setup_org_with_member(client, member_email="member@example.com"):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email=member_email)
    org = _create_org(client, owner_headers)
    _add_org_member(client, owner_headers, org["id"], member_email)
    return owner_headers, member_headers, org


def test_projects_default_to_open_visibility(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    project = _create_project(client, headers, org["id"])

    assert project["visibility"] == "open"


def test_create_restricted_project(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    project = _create_project(client, headers, org["id"], visibility="restricted")

    assert project["visibility"] == "restricted"


def test_org_member_can_reach_open_project(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"])

    response = client.get(_project_url(org["id"], project["id"]), headers=member_headers)

    assert response.status_code == 200


def test_restricted_project_hidden_from_non_member(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")

    response = client.get(_project_url(org["id"], project["id"]), headers=member_headers)

    assert response.status_code == 404


def test_restricted_project_excluded_from_list_for_non_member(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    _create_project(client, owner_headers, org["id"], name="Public", visibility="open")
    _create_project(client, owner_headers, org["id"], name="Secret", visibility="restricted")

    response = client.get(f"/api/v1/organizations/{org['id']}/projects", headers=member_headers)

    assert response.status_code == 200
    assert [project["name"] for project in response.json()] == ["Public"]


def test_admin_sees_every_project_in_list(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    _create_project(client, owner_headers, org["id"], name="Public")
    _create_project(client, owner_headers, org["id"], name="Secret", visibility="restricted")

    response = client.get(f"/api/v1/organizations/{org['id']}/projects", headers=owner_headers)

    assert [project["name"] for project in response.json()] == ["Public", "Secret"]


def test_project_list_paginates(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    for name in ["Alpha", "Bravo", "Charlie"]:
        _create_project(client, headers, org["id"], name=name)

    response = client.get(
        f"/api/v1/organizations/{org['id']}/projects?limit=2&offset=1", headers=headers
    )

    assert [project["name"] for project in response.json()] == ["Bravo", "Charlie"]


def test_added_project_member_can_reach_restricted_project(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")

    add_response = client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "member@example.com", "role": "viewer"},
        headers=owner_headers,
    )

    assert add_response.status_code == 201
    assert add_response.json()["role"] == "viewer"
    assert add_response.json()["user"]["email"] == "member@example.com"

    response = client.get(_project_url(org["id"], project["id"]), headers=member_headers)
    assert response.status_code == 200


def test_viewer_cannot_create_tasks(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")
    client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "member@example.com", "role": "viewer"},
        headers=owner_headers,
    )

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Nope"}, headers=member_headers
    )

    assert response.status_code == 403


def test_editor_can_create_tasks(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")
    client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "member@example.com", "role": "editor"},
        headers=owner_headers,
    )

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=member_headers
    )

    assert response.status_code == 201


def test_viewer_can_read_tasks(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")
    client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=owner_headers
    )
    client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "member@example.com", "role": "viewer"},
        headers=owner_headers,
    )

    response = client.get(_tasks_url(org["id"], project["id"]), headers=member_headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_project_role_narrows_access_on_open_project(client):
    """An explicit viewer role must override the default editor access."""
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"])
    client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "member@example.com", "role": "viewer"},
        headers=owner_headers,
    )

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Nope"}, headers=member_headers
    )

    assert response.status_code == 403


def test_org_admin_keeps_access_despite_viewer_project_role(client):
    owner_headers, admin_headers, org = _setup_org_with_member(client, "admin@example.com")
    members = client.get(
        f"/api/v1/organizations/{org['id']}/members", headers=owner_headers
    ).json()
    admin_membership = next(m for m in members if m["user"]["email"] == "admin@example.com")
    client.patch(
        f"/api/v1/organizations/{org['id']}/members/{admin_membership['id']}",
        json={"role": "admin"},
        headers=owner_headers,
    )
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")
    client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "admin@example.com", "role": "viewer"},
        headers=owner_headers,
    )

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Still allowed"}, headers=admin_headers
    )

    assert response.status_code == 201


def test_add_project_member_requires_org_membership(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])

    response = client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "outsider@example.com", "role": "editor"},
        headers=owner_headers,
    )

    assert response.status_code == 422


def test_add_unknown_user_to_project_returns_404(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "ghost@example.com", "role": "editor"},
        headers=headers,
    )

    assert response.status_code == 404


def test_add_duplicate_project_member_rejected(client):
    owner_headers, _member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"])
    payload = {"email": "member@example.com", "role": "editor"}
    client.post(_members_url(org["id"], project["id"]), json=payload, headers=owner_headers)

    response = client.post(
        _members_url(org["id"], project["id"]), json=payload, headers=owner_headers
    )

    assert response.status_code == 409


def test_update_project_member_role(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")
    member = client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "member@example.com", "role": "viewer"},
        headers=owner_headers,
    ).json()

    response = client.patch(
        _members_url(org["id"], project["id"], f"/{member['id']}"),
        json={"role": "editor"},
        headers=owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["role"] == "editor"

    create_response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Now allowed"}, headers=member_headers
    )
    assert create_response.status_code == 201


def test_remove_project_member_revokes_restricted_access(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")
    member = client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "member@example.com", "role": "editor"},
        headers=owner_headers,
    ).json()

    response = client.delete(
        _members_url(org["id"], project["id"], f"/{member['id']}"), headers=owner_headers
    )

    assert response.status_code == 204
    assert (
        client.get(_project_url(org["id"], project["id"]), headers=member_headers).status_code
        == 404
    )


def test_editor_cannot_manage_project_members(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    _register_and_login(client, email="third@example.com")
    _add_org_member(client, owner_headers, org["id"], "third@example.com")
    project = _create_project(client, owner_headers, org["id"])

    response = client.post(
        _members_url(org["id"], project["id"]),
        json={"email": "third@example.com", "role": "editor"},
        headers=member_headers,
    )

    assert response.status_code == 403


def test_editor_cannot_change_visibility(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"])

    response = client.patch(
        _project_url(org["id"], project["id"]),
        json={"visibility": "restricted"},
        headers=member_headers,
    )

    assert response.status_code == 403


def test_editor_can_still_rename_project(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"])

    response = client.patch(
        _project_url(org["id"], project["id"]), json={"name": "Renamed"}, headers=member_headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_project_member_list_requires_project_access(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")

    response = client.get(_members_url(org["id"], project["id"]), headers=member_headers)

    assert response.status_code == 404


def test_project_member_not_found(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.delete(
        _members_url(org["id"], project["id"], "/00000000-0000-0000-0000-000000000000"),
        headers=headers,
    )

    assert response.status_code == 404


def test_restricted_project_comments_hidden_from_non_member(client):
    owner_headers, member_headers, org = _setup_org_with_member(client)
    project = _create_project(client, owner_headers, org["id"], visibility="restricted")
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Secret"}, headers=owner_headers
    ).json()

    response = client.get(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"), headers=member_headers
    )

    assert response.status_code == 404
