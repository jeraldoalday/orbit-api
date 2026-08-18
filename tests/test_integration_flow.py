"""End-to-end coverage that exercises every module together in one realistic
workflow, as opposed to the per-router tests elsewhere that each isolate a
single feature.
"""

import pytest

pytestmark = pytest.mark.integration


def _register_and_login(client, email, password="supersecret1", full_name="Test User"):
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_full_org_project_task_lifecycle(client):
    owner_headers = _register_and_login(client, "owner@example.com", full_name="Owner")
    invitee_headers = _register_and_login(client, "invitee@example.com", full_name="Invitee")
    invitee_id = client.get("/api/v1/users/me", headers=invitee_headers).json()["id"]

    org = client.post(
        "/api/v1/organizations", json={"name": "Integration Co"}, headers=owner_headers
    ).json()

    invitation = client.post(
        f"/api/v1/organizations/{org['id']}/invitations",
        json={"email": "invitee@example.com", "role": "member"},
        headers=owner_headers,
    ).json()

    accept_response = client.post(
        "/api/v1/invitations/accept",
        json={"token": invitation["token"]},
        headers=invitee_headers,
    )
    assert accept_response.status_code == 200
    assert accept_response.json()["role"] == "member"

    members = client.get(f"/api/v1/organizations/{org['id']}/members", headers=owner_headers).json()
    invitee_membership = next(m for m in members if m["user"]["id"] == invitee_id)
    assert invitee_membership["role"] == "member"

    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Launch"},
        headers=owner_headers,
    ).json()

    task = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks",
        json={
            "title": "Ship it",
            "assignee_id": invitee_id,
            "priority": "high",
            "due_date": "2026-12-31T00:00:00Z",
        },
        headers=owner_headers,
    ).json()
    assert task["priority"] == "high"
    task_url = f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks/{task['id']}"

    label = client.post(
        f"/api/v1/organizations/{org['id']}/labels",
        json={"name": "Launch Blocker", "color": "#ff0000"},
        headers=owner_headers,
    ).json()
    attach_response = client.post(
        f"{task_url}/labels", json={"label_id": label["id"]}, headers=owner_headers
    )
    assert attach_response.status_code == 201

    labeled_tasks = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks"
        f"?label_id={label['id']}&priority=high",
        headers=owner_headers,
    ).json()
    assert [t["id"] for t in labeled_tasks] == [task["id"]]

    update_response = client.patch(
        task_url, json={"status": "in_progress"}, headers=invitee_headers
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "in_progress"

    comment_response = client.post(
        f"{task_url}/comments", json={"body": "Working on it"}, headers=invitee_headers
    )
    assert comment_response.status_code == 201

    timeline = client.get(f"{task_url}/timeline", headers=owner_headers).json()
    kinds = [entry["kind"] for entry in timeline]
    assert kinds.count("comment") == 1
    assert kinds.count("activity") == 2  # created + status update
    assert timeline == sorted(timeline, key=lambda entry: entry["created_at"])

    # A plain member can't delete tasks yet.
    forbidden_delete = client.delete(task_url, headers=invitee_headers)
    assert forbidden_delete.status_code == 403

    promote_response = client.patch(
        f"/api/v1/organizations/{org['id']}/members/{invitee_membership['id']}",
        json={"role": "admin"},
        headers=owner_headers,
    )
    assert promote_response.status_code == 200
    assert promote_response.json()["role"] == "admin"

    # Now promoted to admin, the same user can delete the task.
    delete_response = client.delete(task_url, headers=invitee_headers)
    assert delete_response.status_code == 204

    remaining_tasks = client.get(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks", headers=owner_headers
    ).json()
    assert remaining_tasks == []


def test_restricted_project_notification_and_search_flow(client):
    """A second end-to-end pass over the features layered on after the basics:
    project-scoped membership, the notification inbox, and org-wide search.
    """
    owner_headers = _register_and_login(client, "lead@example.com", full_name="Lead")
    dev_headers = _register_and_login(client, "dev@example.com", full_name="Dev")
    outsider_headers = _register_and_login(client, "sales@example.com", full_name="Sales")
    dev_id = client.get("/api/v1/users/me", headers=dev_headers).json()["id"]

    org = client.post(
        "/api/v1/organizations", json={"name": "Skunkworks"}, headers=owner_headers
    ).json()
    for email in ["dev@example.com", "sales@example.com"]:
        client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"email": email, "role": "member"},
            headers=owner_headers,
        )

    # A restricted project is invisible to org members who aren't on it.
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Project Nimbus", "visibility": "restricted"},
        headers=owner_headers,
    ).json()
    project_url = f"/api/v1/organizations/{org['id']}/projects/{project['id']}"

    assert client.get(project_url, headers=outsider_headers).status_code == 404
    assert client.get(project_url, headers=dev_headers).status_code == 404

    # Grant the dev viewer access first: they can read, but not write.
    membership = client.post(
        f"{project_url}/members",
        json={"email": "dev@example.com", "role": "viewer"},
        headers=owner_headers,
    ).json()
    assert membership["role"] == "viewer"
    assert client.get(project_url, headers=dev_headers).status_code == 200
    assert (
        client.post(f"{project_url}/tasks", json={"title": "Nope"}, headers=dev_headers).status_code
        == 403
    )

    # Promoting to editor unlocks writes.
    client.patch(
        f"{project_url}/members/{membership['id']}", json={"role": "editor"}, headers=owner_headers
    )

    task = client.post(
        f"{project_url}/tasks",
        json={"title": "Design the nimbus rig", "assignee_id": dev_id},
        headers=owner_headers,
    ).json()
    task_url = f"{project_url}/tasks/{task['id']}"

    # The assignment landed in the dev's inbox, and nobody else's.
    inbox = client.get("/api/v1/notifications", headers=dev_headers).json()
    assert [n["notification_type"] for n in inbox] == ["task_assigned"]
    assert inbox[0]["actor"]["email"] == "lead@example.com"
    assert client.get("/api/v1/notifications", headers=owner_headers).json() == []

    # A mention notifies directly, and replaces the generic assignee ping.
    client.post(
        f"{task_url}/comments",
        json={"body": "@dev@example.com can you take the first pass?"},
        headers=owner_headers,
    )
    inbox = client.get("/api/v1/notifications", headers=dev_headers).json()
    assert [n["notification_type"] for n in inbox] == ["mentioned", "task_assigned"]
    assert client.get("/api/v1/notifications/unread_count", headers=dev_headers).json() == {
        "unread": 2
    }

    assert client.post("/api/v1/notifications/read_all", headers=dev_headers).json() == {
        "marked": 2
    }
    assert client.get("/api/v1/notifications/unread_count", headers=dev_headers).json() == {
        "unread": 0
    }

    # Search respects project visibility: the dev sees the restricted work, the
    # outsider sees nothing at all for the same query.
    dev_hits = client.get(
        f"/api/v1/organizations/{org['id']}/search?q=nimbus", headers=dev_headers
    ).json()
    assert sorted(hit["kind"] for hit in dev_hits["results"]) == ["project", "task"]

    outsider_hits = client.get(
        f"/api/v1/organizations/{org['id']}/search?q=nimbus", headers=outsider_headers
    ).json()
    assert outsider_hits["results"] == []

    # Revoking project membership revokes reads and search results together.
    client.delete(f"{project_url}/members/{membership['id']}", headers=owner_headers)
    assert client.get(project_url, headers=dev_headers).status_code == 404
    assert (
        client.get(
            f"/api/v1/organizations/{org['id']}/search?q=nimbus", headers=dev_headers
        ).json()["results"]
        == []
    )


def test_attachments_webhooks_and_the_audit_trail_across_one_incident(client, storage):
    """One realistic incident, end to end.

    An admin wires up a webhook, work happens on a task with a file attached,
    the task is deleted by mistake and restored, and the whole thing is then
    purged — checking at each step that deliveries queued, that the trail
    recorded who did what, and that the purge took the stored bytes with it.
    """
    import io

    from app.core.webhook_signing import SIGNATURE_HEADER, verify_signature
    from app.core.webhook_transport import TransportResponse, WebhookTransport
    from app.db.session import get_db
    from app.main import app as fastapi_app
    from app.services.webhook_delivery_service import dispatch_pending

    class _Collector(WebhookTransport):
        def __init__(self):
            self.requests = []

        def post(self, url, body, headers, *, timeout):
            self.requests.append((url, body, headers))
            return TransportResponse(status_code=200)

    owner_headers = _register_and_login(client, "lead@example.com", full_name="Lead")
    engineer_headers = _register_and_login(client, "eng@example.com", full_name="Engineer")
    engineer_id = client.get("/api/v1/users/me", headers=engineer_headers).json()["id"]

    org = client.post(
        "/api/v1/organizations", json={"name": "Orbit Labs"}, headers=owner_headers
    ).json()
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "eng@example.com", "role": "member"},
        headers=owner_headers,
    )

    subscription = client.post(
        f"/api/v1/organizations/{org['id']}/webhooks",
        json={
            "url": "https://hooks.example.com/orbit",
            "events": ["task.created", "task.assigned", "task.deleted", "comment.created"],
            "description": "Incident relay",
        },
        headers=owner_headers,
    ).json()
    secret = subscription["secret"]

    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Incident 42"},
        headers=owner_headers,
    ).json()
    tasks_url = f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks"

    task = client.post(
        tasks_url, json={"title": "Restore the queue", "priority": "urgent"}, headers=owner_headers
    ).json()
    client.patch(
        f"{tasks_url}/{task['id']}", json={"assignee_id": engineer_id}, headers=owner_headers
    )
    client.post(
        f"{tasks_url}/{task['id']}/comments",
        json={"body": "Picking this up now"},
        headers=engineer_headers,
    )

    upload = client.post(
        f"{tasks_url}/{task['id']}/attachments",
        files={"file": ("postmortem.txt", io.BytesIO(b"root cause: the queue"), "text/plain")},
        headers=engineer_headers,
    )
    assert upload.status_code == 201
    attachment = upload.json()
    assert attachment["uploaded_by"]["email"] == "eng@example.com"

    download = client.get(
        f"{tasks_url}/{task['id']}/attachments/{attachment['id']}/download",
        headers=owner_headers,
    )
    assert download.content == b"root cause: the queue"

    # The engineer is notified of the assignment; the comment was their own.
    inbox = client.get("/api/v1/notifications", headers=engineer_headers).json()
    assert [item["notification_type"] for item in inbox] == ["task_assigned"]

    # Deliveries are queued but nothing has been posted until the worker runs.
    session = next(fastapi_app.dependency_overrides[get_db]())
    collector = _Collector()
    summary = dispatch_pending(session, collector, verify_target=False)

    assert summary.attempted == summary.succeeded == 3
    assert [headers["X-Orbit-Event"] for _url, _body, headers in collector.requests] == [
        "task.created",
        "task.assigned",
        "comment.created",
    ]
    for url, body, headers in collector.requests:
        assert url == "https://hooks.example.com/orbit"
        assert verify_signature(secret, body, headers[SIGNATURE_HEADER])

    # Deleted by mistake, then restored: the file survives the round trip.
    client.delete(f"{tasks_url}/{task['id']}", headers=owner_headers)
    assert client.get(f"{tasks_url}/{task['id']}", headers=owner_headers).status_code == 404
    assert client.get(f"{tasks_url}", headers=owner_headers).json() == []

    client.post(f"{tasks_url}/{task['id']}/restore", headers=owner_headers)
    restored = client.get(f"{tasks_url}/{task['id']}", headers=owner_headers).json()
    assert restored["deleted_at"] is None
    assert (
        client.get(f"{tasks_url}/{task['id']}/attachments", headers=owner_headers).json()[0]["id"]
        == attachment["id"]
    )

    # Purging the project takes the task, the file and the bytes with it.
    client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}", headers=owner_headers
    )
    purged = client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/purge", headers=owner_headers
    )
    assert purged.status_code == 204

    import os

    remaining = [name for _d, _s, files in os.walk(storage.root) for name in files]
    assert remaining == []

    # The trail outlives everything it describes.
    trail = client.get(
        f"/api/v1/organizations/{org['id']}/audit-logs", headers=owner_headers
    ).json()
    actions = [entry["action"] for entry in trail]
    assert actions == [
        "project.purged",
        "project.deleted",
        "task.restored",
        "task.deleted",
        "project.created",
        "webhook.created",
        "member.added",
    ]
    purge_entry = trail[0]
    assert purge_entry["resource_id"] == project["id"]
    assert purge_entry["actor_email"] == "lead@example.com"

    # Search finds nothing left, and the engineer can no longer reach any of it.
    results = client.get(
        f"/api/v1/organizations/{org['id']}/search?q=queue", headers=owner_headers
    ).json()
    assert results["results"] == []
    assert client.get(tasks_url, headers=engineer_headers).status_code == 404
