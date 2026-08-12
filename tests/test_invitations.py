from datetime import datetime, timedelta, timezone

from app.services.invitation_service import get_invitation_by_token


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


def _invitations_url(org_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/invitations{suffix}"


def test_admin_can_create_invitation(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)

    response = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "newhire@example.com"
    assert body["status"] == "pending"
    assert "token" in body


def test_member_cannot_create_invitation(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )

    response = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=member_headers,
    )

    assert response.status_code == 403


def test_cannot_invite_existing_member(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )

    response = client.post(
        _invitations_url(org["id"]),
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )

    assert response.status_code == 409


def test_duplicate_pending_invitation_rejected(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)
    client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=headers,
    )

    response = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=headers,
    )

    assert response.status_code == 409


def test_admin_can_list_and_revoke_invitation(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)
    invitation = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=headers,
    ).json()

    list_response = client.get(_invitations_url(org["id"]), headers=headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    revoke_response = client.delete(
        _invitations_url(org["id"], f"/{invitation['id']}"), headers=headers
    )
    assert revoke_response.status_code == 204


def test_accept_invitation_creates_membership_with_invited_role(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    invitation = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "admin"},
        headers=owner_headers,
    ).json()

    invitee_headers = _register_and_login(client, email="newhire@example.com")
    accept_response = client.post(
        "/api/v1/invitations/accept", json={"token": invitation["token"]}, headers=invitee_headers
    )

    assert accept_response.status_code == 200
    assert accept_response.json()["role"] == "admin"

    members = client.get(
        f"/api/v1/organizations/{org['id']}/members", headers=owner_headers
    ).json()
    emails = [m["user"]["email"] for m in members]
    assert "newhire@example.com" in emails


def test_accept_invitation_rejects_wrong_email(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    invitation = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=owner_headers,
    ).json()

    outsider_headers = _register_and_login(client, email="outsider@example.com")
    response = client.post(
        "/api/v1/invitations/accept", json={"token": invitation["token"]}, headers=outsider_headers
    )

    assert response.status_code == 403


def test_admin_cannot_invite_owner_role(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    admin_headers = _register_and_login(client, email="admin@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "admin@example.com", "role": "admin"},
        headers=owner_headers,
    )

    response = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "owner"},
        headers=admin_headers,
    )

    assert response.status_code == 403


def test_owner_can_invite_owner_role(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)

    response = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "owner"},
        headers=owner_headers,
    )

    assert response.status_code == 201


def test_duplicate_invitation_rejected_regardless_of_email_case(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)
    client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=headers,
    )

    response = client.post(
        _invitations_url(org["id"]),
        json={"email": "NewHire@Example.com", "role": "member"},
        headers=headers,
    )

    assert response.status_code == 409


def test_cannot_revoke_accepted_invitation(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    invitation = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=owner_headers,
    ).json()
    invitee_headers = _register_and_login(client, email="newhire@example.com")
    client.post(
        "/api/v1/invitations/accept", json={"token": invitation["token"]}, headers=invitee_headers
    )

    response = client.delete(
        _invitations_url(org["id"], f"/{invitation['id']}"), headers=owner_headers
    )

    assert response.status_code == 409


def test_cannot_accept_invitation_twice(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    invitation = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=owner_headers,
    ).json()
    invitee_headers = _register_and_login(client, email="newhire@example.com")
    client.post(
        "/api/v1/invitations/accept", json={"token": invitation["token"]}, headers=invitee_headers
    )

    response = client.post(
        "/api/v1/invitations/accept", json={"token": invitation["token"]}, headers=invitee_headers
    )

    assert response.status_code == 409


def test_accept_expired_invitation_rejected(client, db):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    invitation = client.post(
        _invitations_url(org["id"]),
        json={"email": "newhire@example.com", "role": "member"},
        headers=owner_headers,
    ).json()

    stored = get_invitation_by_token(db, invitation["token"])
    stored.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    invitee_headers = _register_and_login(client, email="newhire@example.com")
    response = client.post(
        "/api/v1/invitations/accept", json={"token": invitation["token"]}, headers=invitee_headers
    )

    assert response.status_code == 409
