import pytest


def _register_and_login(
    client, email="jane@example.com", password="supersecret1", full_name="Jane Doe"
):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}


def _create_org(client, headers, name="Acme Inc"):
    return client.post("/api/v1/organizations", json={"name": name}, headers=headers).json()


def _add_org_member(client, headers, org_id, email, role="member"):
    return client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": email, "role": role},
        headers=headers,
    )


def _url(org_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/webhooks{suffix}"


def _create_webhook(client, headers, org_id, **overrides):
    body = {"url": "https://hooks.example.com/orbit", "events": ["task.created"]}
    body.update(overrides)
    return client.post(_url(org_id), json=body, headers=headers)


@pytest.fixture()
def setup(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)
    return headers, org


def test_creating_a_subscription_returns_the_secret_once(client, setup):
    headers, org = setup

    response = _create_webhook(client, headers, org["id"], description="Ops relay")

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == "https://hooks.example.com/orbit"
    assert body["events"] == ["task.created"]
    assert body["description"] == "Ops relay"
    assert body["is_active"] is True
    assert len(body["secret"]) == 64


def test_the_secret_is_never_returned_again(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()

    fetched = client.get(_url(org["id"], f"/{created['id']}"), headers=headers).json()
    listed = client.get(_url(org["id"]), headers=headers).json()

    assert "secret" not in fetched
    assert all("secret" not in item for item in listed)


def test_duplicate_events_are_collapsed(client, setup):
    headers, org = setup

    body = _create_webhook(
        client, headers, org["id"], events=["task.created", "task.created", "task.updated"]
    ).json()

    assert body["events"] == ["task.created", "task.updated"]


def test_an_unknown_event_is_rejected(client, setup):
    headers, org = setup

    response = _create_webhook(client, headers, org["id"], events=["task.exploded"])

    assert response.status_code == 422


def test_an_empty_event_list_is_rejected(client, setup):
    headers, org = setup

    assert _create_webhook(client, headers, org["id"], events=[]).status_code == 422


def test_an_internal_target_is_rejected(client, setup):
    headers, org = setup

    response = _create_webhook(client, headers, org["id"], url="http://169.254.169.254/latest")

    assert response.status_code == 422
    assert "private or reserved" in response.json()["detail"]


def test_subscriptions_are_capped_per_org(client, setup, monkeypatch):
    headers, org = setup
    monkeypatch.setattr("app.api.v1.routers.webhooks.settings.webhook_max_per_org", 1)

    assert _create_webhook(client, headers, org["id"]).status_code == 201
    second = _create_webhook(client, headers, org["id"])

    assert second.status_code == 409


def test_updating_changes_url_events_and_active_state(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()

    updated = client.patch(
        _url(org["id"], f"/{created['id']}"),
        json={
            "url": "https://other.example.com/hook",
            "events": ["task.updated", "comment.created"],
            "is_active": False,
        },
        headers=headers,
    ).json()

    assert updated["url"] == "https://other.example.com/hook"
    assert updated["events"] == ["task.updated", "comment.created"]
    assert updated["is_active"] is False


def test_updating_to_an_internal_target_is_rejected(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()

    response = client.patch(
        _url(org["id"], f"/{created['id']}"), json={"url": "http://127.0.0.1/x"}, headers=headers
    )

    assert response.status_code == 422


def test_rotating_the_secret_issues_a_different_one(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()

    rotated = client.post(
        _url(org["id"], f"/{created['id']}/rotate_secret"), headers=headers
    ).json()

    assert rotated["secret"] != created["secret"]
    assert rotated["id"] == created["id"]


def test_an_admin_cannot_rotate_the_secret(client, setup):
    owner_headers, org = setup
    admin_headers = _register_and_login(client, email="admin@example.com")
    _add_org_member(client, owner_headers, org["id"], "admin@example.com", role="admin")
    created = _create_webhook(client, owner_headers, org["id"]).json()

    response = client.post(
        _url(org["id"], f"/{created['id']}/rotate_secret"), headers=admin_headers
    )

    assert response.status_code == 403


def test_deleting_removes_the_subscription(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()

    assert client.delete(_url(org["id"], f"/{created['id']}"), headers=headers).status_code == 204
    assert client.get(_url(org["id"]), headers=headers).json() == []


def test_a_plain_member_cannot_manage_webhooks(client, setup):
    owner_headers, org = setup
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, owner_headers, org["id"], "member@example.com")

    assert client.get(_url(org["id"]), headers=member_headers).status_code == 403
    assert _create_webhook(client, member_headers, org["id"]).status_code == 403


def test_a_non_member_cannot_probe_webhooks(client, setup):
    _owner_headers, org = setup
    outsider_headers = _register_and_login(client, email="outsider@example.com")

    assert client.get(_url(org["id"]), headers=outsider_headers).status_code == 404


def test_webhooks_require_authentication(client, setup):
    _headers, org = setup

    assert client.get(_url(org["id"])).status_code == 401


def test_another_orgs_subscription_is_not_reachable(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()
    other_org = _create_org(client, headers, name="Other Inc")

    response = client.get(_url(other_org["id"], f"/{created['id']}"), headers=headers)

    assert response.status_code == 404
