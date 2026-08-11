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
    return client.post("/api/v1/organizations", json={"name": name}, headers=headers)


def test_create_organization_makes_creator_owner(client):
    headers = _register_and_login(client)

    response = _create_org(client, headers)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Inc"
    assert body["slug"] == "acme-inc"
    assert "id" in body


def test_create_organization_requires_authentication(client):
    response = client.post("/api/v1/organizations", json={"name": "Acme Inc"})

    assert response.status_code == 401


def test_duplicate_org_names_get_unique_slugs(client):
    headers = _register_and_login(client)

    first = _create_org(client, headers)
    second = _create_org(client, headers)

    assert first.json()["slug"] != second.json()["slug"]


def test_list_organizations_returns_only_mine(client):
    headers_a = _register_and_login(client, email="a@example.com")
    headers_b = _register_and_login(client, email="b@example.com")
    _create_org(client, headers_a, name="A Corp")
    _create_org(client, headers_b, name="B Corp")

    response = client.get("/api/v1/organizations", headers=headers_a)

    assert response.status_code == 200
    names = [org["name"] for org in response.json()]
    assert names == ["A Corp"]


def test_get_organization_requires_membership(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org_id = _create_org(client, owner_headers).json()["id"]

    response = client.get(f"/api/v1/organizations/{org_id}", headers=outsider_headers)

    assert response.status_code == 404


def test_get_organization_as_member_succeeds(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org_id = _create_org(client, owner_headers).json()["id"]

    response = client.get(f"/api/v1/organizations/{org_id}", headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["id"] == org_id


def test_update_organization_requires_admin_role(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org_id = _create_org(client, owner_headers).json()["id"]
    client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )

    response = client.patch(
        f"/api/v1/organizations/{org_id}", json={"name": "New Name"}, headers=member_headers
    )

    assert response.status_code == 403


def test_owner_can_update_organization(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org_id = _create_org(client, owner_headers).json()["id"]

    response = client.patch(
        f"/api/v1/organizations/{org_id}", json={"name": "New Name"}, headers=owner_headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


def test_delete_organization_requires_owner_role(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    admin_headers = _register_and_login(client, email="admin@example.com")
    org_id = _create_org(client, owner_headers).json()["id"]
    client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "admin@example.com", "role": "admin"},
        headers=owner_headers,
    )

    response = client.delete(f"/api/v1/organizations/{org_id}", headers=admin_headers)

    assert response.status_code == 403


def test_owner_can_delete_organization(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org_id = _create_org(client, owner_headers).json()["id"]

    response = client.delete(f"/api/v1/organizations/{org_id}", headers=owner_headers)

    assert response.status_code == 204
    assert client.get(f"/api/v1/organizations/{org_id}", headers=owner_headers).status_code == 404
