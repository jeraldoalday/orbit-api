import uuid

import pytest

from app.db.session import get_db
from app.main import app
from app.models.webhook import WebhookEvent
from app.services.webhook_delivery_service import enqueue_event


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


# --- delivery inspection endpoints ------------------------------------------


def _enqueue_delivery(org_id):
    """Queue one event through the service layer, as an emitting route would."""
    session = next(app.dependency_overrides[get_db]())
    return enqueue_event(session, uuid.UUID(org_id), WebhookEvent.TASK_CREATED, {"task_id": "x"})


def test_deliveries_start_empty(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()

    listed = client.get(_url(org["id"], f"/{created['id']}/deliveries"), headers=headers)

    assert listed.status_code == 200
    assert listed.json() == []


def test_a_queued_delivery_is_listed(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()
    _enqueue_delivery(org["id"])

    listed = client.get(_url(org["id"], f"/{created['id']}/deliveries"), headers=headers).json()

    assert len(listed) == 1
    assert listed[0]["event_type"] == "task.created"
    assert listed[0]["status"] == "pending"
    assert listed[0]["attempts"] == 0
    # The list view is a summary; the payload is only on the detail view.
    assert "payload" not in listed[0]


def test_a_single_delivery_includes_its_payload(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()
    delivery = _enqueue_delivery(org["id"])[0]

    detail = client.get(
        _url(org["id"], f"/{created['id']}/deliveries/{delivery.id}"), headers=headers
    ).json()

    assert detail["payload"]["event"] == "task.created"
    assert detail["payload"]["data"] == {"task_id": "x"}


def test_deliveries_can_be_filtered_by_status(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()
    _enqueue_delivery(org["id"])

    pending = client.get(
        _url(org["id"], f"/{created['id']}/deliveries?status=pending"), headers=headers
    ).json()
    succeeded = client.get(
        _url(org["id"], f"/{created['id']}/deliveries?status=succeeded"), headers=headers
    ).json()

    assert len(pending) == 1
    assert succeeded == []


def test_retrying_a_delivery_puts_it_back_in_the_queue(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()
    delivery = _enqueue_delivery(org["id"])[0]
    delivery.attempts = 4
    delivery.error = "boom"

    retried = client.post(
        _url(org["id"], f"/{created['id']}/deliveries/{delivery.id}/retry"), headers=headers
    ).json()

    assert retried["status"] == "pending"
    assert retried["attempts"] == 0
    assert retried["error"] is None


def test_an_unknown_delivery_is_404(client, setup):
    headers, org = setup
    created = _create_webhook(client, headers, org["id"]).json()

    response = client.get(
        _url(
            org["id"],
            f"/{created['id']}/deliveries/00000000-0000-0000-0000-000000000000",
        ),
        headers=headers,
    )

    assert response.status_code == 404


def test_a_plain_member_cannot_read_deliveries(client, setup):
    owner_headers, org = setup
    created = _create_webhook(client, owner_headers, org["id"]).json()
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, owner_headers, org["id"], "member@example.com")

    response = client.get(
        _url(org["id"], f"/{created['id']}/deliveries"), headers=member_headers
    )

    assert response.status_code == 403
