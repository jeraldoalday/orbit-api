def _register(client, email="jane@example.com", password="supersecret1", full_name="Jane Doe"):
    return client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )


def test_register_creates_user(client):
    response = _register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "jane@example.com"
    assert body["full_name"] == "Jane Doe"
    assert body["is_active"] is True
    assert "id" in body
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_duplicate_email_is_rejected(client):
    _register(client)
    response = _register(client)

    assert response.status_code == 409


def test_register_normalizes_email_case(client):
    response = _register(client, email="  Jane@Example.com  ")

    assert response.status_code == 201
    assert response.json()["email"] == "jane@example.com"


def test_register_duplicate_email_is_rejected_case_insensitively(client):
    _register(client, email="jane@example.com")
    response = _register(client, email="JANE@EXAMPLE.COM")

    assert response.status_code == 409


def test_register_rejects_short_password(client):
    response = _register(client, password="short")

    assert response.status_code == 422


def test_login_returns_tokens(client):
    _register(client)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "jane@example.com", "password": "supersecret1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_is_case_insensitive_on_email(client):
    _register(client, email="jane@example.com")

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "Jane@Example.com", "password": "supersecret1"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_with_wrong_password_is_rejected(client):
    _register(client)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "jane@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_login_with_unknown_email_is_rejected(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "supersecret1"},
    )

    assert response.status_code == 401


def test_me_requires_authentication(client):
    response = client.get("/api/v1/users/me")

    assert response.status_code == 401


def test_me_returns_current_user(client):
    _register(client)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "jane@example.com", "password": "supersecret1"},
    )
    access_token = login_response.json()["access_token"]

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "jane@example.com"


def test_me_rejects_invalid_token(client):
    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401


def test_refresh_returns_new_tokens(client):
    _register(client)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "jane@example.com", "password": "supersecret1"},
    )
    refresh_token = login_response.json()["refresh_token"]

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


def test_refresh_rejects_access_token(client):
    _register(client)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "jane@example.com", "password": "supersecret1"},
    )
    access_token = login_response.json()["access_token"]

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},
    )

    assert response.status_code == 401
