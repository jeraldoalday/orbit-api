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


def test_list_members_includes_owner(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)

    response = client.get(f"/api/v1/organizations/{org['id']}/members", headers=owner_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["role"] == "owner"
    assert body[0]["user"]["email"] == "owner@example.com"


def test_admin_can_add_member(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    _register_and_login(client, email="new@example.com")
    org = _create_org(client, owner_headers)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "new@example.com", "role": "member"},
        headers=owner_headers,
    )

    assert response.status_code == 201
    assert response.json()["role"] == "member"
    assert response.json()["user"]["email"] == "new@example.com"


def test_member_cannot_add_member(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    _register_and_login(client, email="new@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )

    response = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "new@example.com", "role": "member"},
        headers=member_headers,
    )

    assert response.status_code == 403


def test_add_member_unknown_email_returns_404(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "ghost@example.com", "role": "member"},
        headers=owner_headers,
    )

    assert response.status_code == 404


def test_add_existing_member_returns_409(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)

    response = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "owner@example.com", "role": "member"},
        headers=owner_headers,
    )

    assert response.status_code == 409


def test_update_member_role(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    _register_and_login(client, email="member@example.com")
    member = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    ).json()

    response = client.patch(
        f"/api/v1/organizations/{org['id']}/members/{member['id']}",
        json={"role": "admin"},
        headers=owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_cannot_demote_last_owner(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    members = client.get(f"/api/v1/organizations/{org['id']}/members", headers=owner_headers).json()
    owner_membership = members[0]

    response = client.patch(
        f"/api/v1/organizations/{org['id']}/members/{owner_membership['id']}",
        json={"role": "admin"},
        headers=owner_headers,
    )

    assert response.status_code == 409


def test_member_can_remove_self(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    member_headers = _register_and_login(client, email="member@example.com")
    member = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    ).json()

    response = client.delete(
        f"/api/v1/organizations/{org['id']}/members/{member['id']}", headers=member_headers
    )

    assert response.status_code == 204


def test_member_cannot_remove_others(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    member_headers = _register_and_login(client, email="member@example.com")
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    _register_and_login(client, email="other2@example.com")
    other2 = client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "other2@example.com", "role": "member"},
        headers=owner_headers,
    ).json()

    response = client.delete(
        f"/api/v1/organizations/{org['id']}/members/{other2['id']}", headers=member_headers
    )

    assert response.status_code == 403


def test_cannot_remove_last_owner(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    members = client.get(f"/api/v1/organizations/{org['id']}/members", headers=owner_headers).json()
    owner_membership = members[0]

    response = client.delete(
        f"/api/v1/organizations/{org['id']}/members/{owner_membership['id']}", headers=owner_headers
    )

    assert response.status_code == 409
