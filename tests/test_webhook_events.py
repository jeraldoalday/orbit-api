"""Which domain changes queue which events, and what they carry."""

import uuid

import pytest

from app.db.session import get_db
from app.main import app
from app.models.webhook import DeliveryStatus, WebhookDelivery


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


def _create_project(client, headers, org_id, name="Website Revamp"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects", json={"name": name}, headers=headers
    ).json()


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


ALL_EVENTS = [
    "task.created",
    "task.updated",
    "task.deleted",
    "task.assigned",
    "comment.created",
    "comment.deleted",
]


def _subscribe(client, headers, org_id, events=None):
    return client.post(
        f"/api/v1/organizations/{org_id}/webhooks",
        json={"url": "https://hooks.example.com/orbit", "events": events or ALL_EVENTS},
        headers=headers,
    ).json()


def _deliveries():
    """Every queued delivery, oldest first, read straight from the session."""
    session = next(app.dependency_overrides[get_db]())
    return (
        session.query(WebhookDelivery)
        .order_by(WebhookDelivery.created_at, WebhookDelivery.id)
        .all()
    )


def _events():
    return [delivery.event_type.value for delivery in _deliveries()]


@pytest.fixture()
def setup(client):
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    return headers, org, project


def test_creating_a_task_queues_task_created(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"])

    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers)

    assert _events() == ["task.created"]
    payload = _deliveries()[0].payload
    assert payload["data"]["task"]["title"] == "Ship it"
    assert payload["data"]["task"]["project_name"] == "Website Revamp"
    assert payload["data"]["actor"]["email"] == "owner@example.com"
    assert payload["organization_id"] == org["id"]


def test_no_subscription_means_no_deliveries(client, setup):
    headers, org, project = setup

    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers)

    assert _deliveries() == []


def test_only_subscribed_events_are_queued(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"], events=["task.deleted"])

    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers)

    assert _deliveries() == []


def test_updating_a_task_queues_task_updated_with_a_diff(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers
    ).json()

    client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"status": "in_progress"},
        headers=headers,
    )

    assert _events() == ["task.created", "task.updated"]
    changes = _deliveries()[1].payload["data"]["changes"]
    assert changes["status"] == {"from": "todo", "to": "in_progress"}


def test_a_no_op_update_queues_nothing(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers
    ).json()

    client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"title": "Ship it"},
        headers=headers,
    )

    assert _events() == ["task.created"]


def test_reassigning_queues_both_updated_and_assigned(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"])
    member_headers = _register_and_login(client, email="member@example.com")
    _add_org_member(client, headers, org["id"], "member@example.com")
    member = client.get("/api/v1/users/me", headers=member_headers).json()
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers
    ).json()

    client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"assignee_id": member["id"]},
        headers=headers,
    )

    assert _events() == ["task.created", "task.updated", "task.assigned"]
    assert _deliveries()[2].payload["data"]["task"]["assignee_id"] == member["id"]


def test_deleting_a_task_queues_task_deleted_with_its_final_state(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers
    ).json()

    client.delete(_tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers)

    assert _events() == ["task.created", "task.deleted"]
    # The payload has to be captured before the row goes away.
    assert _deliveries()[1].payload["data"]["task"]["id"] == task["id"]
    assert _deliveries()[1].payload["data"]["task"]["title"] == "Ship it"


def test_commenting_queues_comment_created(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers
    ).json()

    client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "Looks good"},
        headers=headers,
    )

    assert _events() == ["task.created", "comment.created"]
    comment = _deliveries()[1].payload["data"]["comment"]
    assert comment["body"] == "Looks good"


def test_deleting_a_comment_queues_comment_deleted_with_its_final_state(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers
    ).json()
    comment = client.post(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments"),
        json={"body": "Looks good"},
        headers=headers,
    ).json()

    client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/comments/{comment['id']}"),
        headers=headers,
    )

    assert _events() == ["task.created", "comment.created", "comment.deleted"]
    # The payload has to be captured before the row goes away.
    deleted = _deliveries()[2].payload["data"]["comment"]
    assert deleted["id"] == comment["id"]
    assert deleted["body"] == "Looks good"


def test_an_inactive_subscription_receives_nothing(client, setup):
    headers, org, project = setup
    subscription = _subscribe(client, headers, org["id"])
    client.patch(
        f"/api/v1/organizations/{org['id']}/webhooks/{subscription['id']}",
        json={"is_active": False},
        headers=headers,
    )

    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers)

    assert _deliveries() == []


def test_two_subscriptions_each_get_their_own_delivery(client, setup):
    headers, org, project = setup
    _subscribe(client, headers, org["id"])
    client.post(
        f"/api/v1/organizations/{org['id']}/webhooks",
        json={"url": "https://other.example.com/hook", "events": ["task.created"]},
        headers=headers,
    )

    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers)

    deliveries = _deliveries()
    assert len(deliveries) == 2
    assert {delivery.subscription_id for delivery in deliveries} != {None}
    assert all(delivery.status == DeliveryStatus.PENDING for delivery in deliveries)


def test_another_orgs_subscription_does_not_see_these_events(client, setup):
    headers, org, project = setup
    other_org = _create_org(client, headers, name="Other Inc")
    _subscribe(client, headers, other_org["id"])

    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Ship it"}, headers=headers)

    assert _deliveries() == []


def test_a_rejected_task_creation_queues_nothing(client, setup):
    """The delivery row shares the transaction, so a failed write emits nothing."""
    headers, org, project = setup
    _subscribe(client, headers, org["id"])

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "assignee_id": str(uuid.uuid4())},
        headers=headers,
    )

    assert response.status_code == 422
    assert _deliveries() == []
