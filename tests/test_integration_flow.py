"""End-to-end coverage that exercises every module together in one realistic
workflow, as opposed to the per-router tests elsewhere that each isolate a
single feature.
"""

import csv
import io

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


def test_a_release_plan_from_dependencies_through_bulk_to_statistics(client):
    """One team plans a release: a dependency chain, watchers on the critical
    task, a bulk sweep to close the finished work, and a dashboard at the end.
    """
    lead_headers = _register_and_login(client, "lead@example.com", full_name="Lead")
    dev_headers = _register_and_login(client, "dev@example.com", full_name="Dev")
    reviewer_headers = _register_and_login(client, "reviewer@example.com", full_name="Reviewer")
    dev_id = client.get("/api/v1/users/me", headers=dev_headers).json()["id"]

    org = client.post(
        "/api/v1/organizations", json={"name": "Release Co"}, headers=lead_headers
    ).json()
    for email in ("dev@example.com", "reviewer@example.com"):
        client.post(
            f"/api/v1/organizations/{org['id']}/members",
            json={"email": email, "role": "member"},
            headers=lead_headers,
        )

    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "1.0"},
        headers=lead_headers,
    ).json()
    tasks_url = f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks"

    def create(title, **fields):
        return client.post(tasks_url, json={"title": title, **fields}, headers=lead_headers).json()

    migrate = create("Run the migration", priority="urgent")
    changelog = create("Write the changelog")
    ship = create("Ship 1.0", assignee_id=dev_id)

    # Shipping waits on both, and the changelog waits on the migration.
    for blocked, blocker in ((ship, migrate), (ship, changelog), (changelog, migrate)):
        added = client.post(
            f"{tasks_url}/{blocked['id']}/dependencies",
            json={"depends_on_id": blocker["id"]},
            headers=lead_headers,
        )
        assert added.status_code == 201

    # ...and the chain can't be closed back on itself.
    cycle = client.post(
        f"{tasks_url}/{migrate['id']}/dependencies",
        json={"depends_on_id": ship["id"]},
        headers=lead_headers,
    )
    assert cycle.status_code == 409

    # The reviewer follows the release task without being handed it.
    assert (
        client.post(f"{tasks_url}/{ship['id']}/watchers", headers=reviewer_headers).status_code
        == 201
    )

    # Shipping is refused while its blockers are open.
    blocked_attempt = client.patch(
        f"{tasks_url}/{ship['id']}", json={"status": "done"}, headers=dev_headers
    )
    assert blocked_attempt.status_code == 409
    assert "Run the migration" in blocked_attempt.json()["detail"]

    stats_url = f"/api/v1/organizations/{org['id']}/projects/{project['id']}/stats"
    before = client.get(stats_url, headers=lead_headers).json()
    assert before["tasks"]["total"] == 3
    assert before["tasks"]["blocked"] == 2
    assert before["tasks"]["done"] == 0

    # A sweep listed downstream-first only closes what is already unblocked:
    # the batch is applied task by task, in the order given, so the two still
    # waiting fall out with a reason rather than failing the call.
    sweep = client.post(
        f"{tasks_url}/bulk",
        json={"task_ids": [ship["id"], changelog["id"], migrate["id"]], "status": "done"},
        headers=lead_headers,
    ).json()
    assert sweep["updated"] == [migrate["id"]]
    assert sorted(failure["task_id"] for failure in sweep["failed"]) == sorted(
        [changelog["id"], ship["id"]]
    )

    # With the migration done, the rest go through.
    second_sweep = client.post(
        f"{tasks_url}/bulk",
        json={"task_ids": [changelog["id"], ship["id"]], "status": "done"},
        headers=lead_headers,
    ).json()
    assert sorted(second_sweep["updated"]) == sorted([changelog["id"], ship["id"]])
    assert second_sweep["failed"] == []

    # The watcher heard about the release task moving, and only about that.
    inbox = client.get("/api/v1/notifications", headers=reviewer_headers).json()
    assert [row["notification_type"] for row in inbox] == ["task_updated"]
    assert inbox[0]["data"]["status"] == "done"

    # The assignee heard about the assignment, not about the lead's sweep.
    dev_inbox = client.get("/api/v1/notifications", headers=dev_headers).json()
    assert [row["notification_type"] for row in dev_inbox] == ["task_assigned"]

    after = client.get(stats_url, headers=lead_headers).json()
    assert after["tasks"]["done"] == 3
    assert after["tasks"]["completion_rate"] == 1.0
    assert after["tasks"]["blocked"] == 0

    org_stats = client.get(f"/api/v1/organizations/{org['id']}/stats", headers=lead_headers).json()
    assert org_stats["projects"] == 1
    assert org_stats["tasks"]["total"] == 3
    assert [row["name"] for row in org_stats["per_project"]] == ["1.0"]
    by_assignee = {row["assignee_id"]: row for row in org_stats["by_assignee"]}
    assert by_assignee[dev_id]["total"] == 1
    assert by_assignee[None]["total"] == 2


def test_a_milestone_from_estimate_through_checklist_to_the_exported_sheet(client):
    """One team runs a milestone: work estimated and filed under it, steps
    ticked off as they go, hours logged against them, the milestone refusing
    to close early, and the whole thing exported for the status report.
    """
    lead_headers = _register_and_login(client, "lead@example.com", full_name="Lead")
    dev_headers = _register_and_login(client, "dev@example.com", full_name="Dev")
    dev_id = client.get("/api/v1/users/me", headers=dev_headers).json()["id"]

    org = client.post(
        "/api/v1/organizations", json={"name": "Milestone Co"}, headers=lead_headers
    ).json()
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "dev@example.com", "role": "member"},
        headers=lead_headers,
    )
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Q4 Launch"},
        headers=lead_headers,
    ).json()

    base = f"/api/v1/organizations/{org['id']}/projects/{project['id']}"
    tasks_url = f"{base}/tasks"
    milestones_url = f"{base}/milestones"

    milestone = client.post(
        milestones_url,
        json={"name": "Beta", "due_date": "2026-12-01T00:00:00Z"},
        headers=lead_headers,
    ).json()

    def create(title, **fields):
        return client.post(tasks_url, json={"title": title, **fields}, headers=lead_headers).json()

    api = create(
        "Build the API",
        assignee_id=dev_id,
        milestone_id=milestone["id"],
        estimate_minutes=240,
    )
    docs = create("Write the docs", milestone_id=milestone["id"], estimate_minutes=60)
    # Filed nowhere: it must stay out of the milestone's numbers.
    create("Unrelated chore")

    # The dev breaks their task into steps and works through them.
    checklist_url = f"{tasks_url}/{api['id']}/checklist"
    steps = [
        client.post(checklist_url, json={"content": content}, headers=dev_headers).json()
        for content in ("Design the schema", "Write the endpoints", "Add the tests")
    ]
    client.patch(f"{checklist_url}/{steps[0]['id']}", json={"is_done": True}, headers=dev_headers)
    checklist = client.get(checklist_url, headers=dev_headers).json()
    assert checklist["total"] == 3
    assert checklist["done"] == 1
    assert checklist["completion_rate"] == 0.3333

    # ...and reorders what is left, which does not disturb what is ticked.
    reordered = client.post(
        f"{checklist_url}/reorder",
        json={"item_ids": [steps[2]["id"], steps[0]["id"], steps[1]["id"]]},
        headers=dev_headers,
    ).json()
    assert [item["content"] for item in reordered["items"]] == [
        "Add the tests",
        "Design the schema",
        "Write the endpoints",
    ]
    assert reordered["done"] == 1

    # Hours go against the task, and blow through its estimate.
    for minutes in (180, 120):
        logged = client.post(
            f"{tasks_url}/{api['id']}/time", json={"minutes": minutes}, headers=dev_headers
        )
        assert logged.status_code == 201

    time_summary = client.get(f"{tasks_url}/{api['id']}/time", headers=dev_headers).json()
    assert time_summary["logged_minutes"] == 300
    assert time_summary["remaining_minutes"] == 0
    assert time_summary["over_estimate"] is True

    # The lead cannot close the milestone while the work under it is open.
    early = client.post(f"{milestones_url}/{milestone['id']}/complete", headers=lead_headers)
    assert early.status_code == 409
    assert "2 task(s)" in early.json()["detail"]

    # One task lands, and the milestone is half done.
    client.patch(f"{tasks_url}/{api['id']}", json={"status": "done"}, headers=dev_headers)
    halfway = client.get(f"{milestones_url}/{milestone['id']}", headers=lead_headers).json()
    assert halfway["progress"] == {"total": 2, "done": 1, "open": 1, "completion_rate": 0.5}

    # The rest is cut rather than done, which is what force is for.
    client.post(
        f"{tasks_url}/bulk",
        json={"task_ids": [docs["id"]], "milestone_id": None},
        headers=lead_headers,
    )
    completed = client.post(
        f"{milestones_url}/{milestone['id']}/complete", headers=lead_headers
    ).json()
    assert completed["completed_at"] is not None
    assert completed["progress"] == {"total": 1, "done": 1, "open": 0, "completion_rate": 1.0}

    # The project's time report adds up what was actually spent.
    report = client.get(f"{base}/time", headers=lead_headers).json()
    assert report["logged_minutes"] == 300
    assert [(row["label"], row["minutes"]) for row in report["by_user"]] == [
        ("dev@example.com", 300)
    ]

    # And the status report leaves as a spreadsheet.
    export = client.get(f"{base}/export/tasks.csv", headers=lead_headers)
    assert export.status_code == 200
    assert 'filename="q4-launch-tasks.csv"' in export.headers["content-disposition"]
    exported = list(csv.reader(io.StringIO(export.text)))
    header, rows = exported[0], exported[1:]
    by_title = {row[header.index("title")]: dict(zip(header, row)) for row in rows}
    assert set(by_title) == {"Build the API", "Write the docs", "Unrelated chore"}
    assert by_title["Build the API"]["milestone"] == "Beta"
    assert by_title["Build the API"]["logged_minutes"] == "300"
    assert by_title["Build the API"]["assignee_email"] == "dev@example.com"
    assert by_title["Write the docs"]["milestone"] == ""
