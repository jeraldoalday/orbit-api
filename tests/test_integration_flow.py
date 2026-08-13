"""End-to-end coverage that exercises every module together in one realistic
workflow, as opposed to the per-router tests elsewhere that each isolate a
single feature.
"""


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
        json={"title": "Ship it", "assignee_id": invitee_id},
        headers=owner_headers,
    ).json()
    task_url = f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks/{task['id']}"

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
