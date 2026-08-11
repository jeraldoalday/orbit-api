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
    )


def test_member_can_create_project(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    response = _create_project(client, headers, org["id"])

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Website Revamp"
    assert body["organization_id"] == org["id"]


def test_create_project_requires_membership(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)

    response = _create_project(client, outsider_headers, org["id"])

    assert response.status_code == 404


def test_list_projects_scoped_to_organization(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org_a = _create_org(client, owner_headers, name="Org A")
    org_b = _create_org(client, owner_headers, name="Org B")
    _create_project(client, owner_headers, org_a["id"], name="A Project")
    _create_project(client, owner_headers, org_b["id"], name="B Project")

    response = client.get(f"/api/v1/organizations/{org_a['id']}/projects", headers=owner_headers)

    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert names == ["A Project"]


def test_get_project_not_found(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)

    response = client.get(
        f"/api/v1/organizations/{org['id']}/projects/00000000-0000-0000-0000-000000000000",
        headers=owner_headers,
    )

    assert response.status_code == 404


def test_member_can_update_project(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"]).json()

    response = client.patch(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}",
        json={"description": "New scope"},
        headers=owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["description"] == "New scope"


def test_member_cannot_delete_project(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    project = _create_project(client, owner_headers, org["id"]).json()

    response = client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}", headers=member_headers
    )

    assert response.status_code == 403


def test_admin_can_delete_project(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"]).json()

    response = client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}", headers=owner_headers
    )

    assert response.status_code == 204
