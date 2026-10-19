from datetime import datetime


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


def _create_project(client, headers, org_id, name="Website Revamp"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects", json={"name": name}, headers=headers
    ).json()


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


def _setup(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    return headers, org, project


def _parse_dt(value):
    # The SQLite test backend doesn't round-trip UTC offsets, so compare naive
    # timestamps rather than raw strings (Postgres preserves the offset in prod).
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def test_create_task_defaults_to_todo(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Set up CI"
    assert body["status"] == "todo"
    assert body["assignee_id"] is None


def test_create_task_requires_membership(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=outsider_headers
    )

    assert response.status_code == 404


def test_assign_task_to_non_member_rejected(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])
    outsider_user_id = client.get("/api/v1/users/me", headers=outsider_headers).json()["id"]

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Set up CI", "assignee_id": outsider_user_id},
        headers=owner_headers,
    )

    assert response.status_code == 422


def test_assign_task_to_member_succeeds(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])
    owner_id = client.get("/api/v1/users/me", headers=owner_headers).json()["id"]

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Set up CI", "assignee_id": owner_id},
        headers=owner_headers,
    )

    assert response.status_code == 201
    assert response.json()["assignee_id"] == owner_id


def test_list_tasks_scoped_to_project(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project_a = _create_project(client, headers, org["id"], name="Project A")
    project_b = _create_project(client, headers, org["id"], name="Project B")
    client.post(_tasks_url(org["id"], project_a["id"]), json={"title": "A task"}, headers=headers)
    client.post(_tasks_url(org["id"], project_b["id"]), json={"title": "B task"}, headers=headers)

    response = client.get(_tasks_url(org["id"], project_a["id"]), headers=headers)

    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    assert titles == ["A task"]


def test_update_task_status(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=headers
    ).json()

    response = client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"status": "in_progress"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


def test_update_task_can_unassign(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    user_id = client.get("/api/v1/users/me", headers=headers).json()["id"]
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Set up CI", "assignee_id": user_id},
        headers=headers,
    ).json()
    assert task["assignee_id"] == user_id

    response = client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"assignee_id": None},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["assignee_id"] is None


def test_delete_task(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=headers
    ).json()

    response = client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers
    )

    assert response.status_code == 204
    assert (
        client.get(
            _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=headers
        ).status_code
        == 404
    )


def test_member_cannot_delete_task(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    project = _create_project(client, owner_headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=owner_headers
    ).json()

    response = client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=member_headers
    )

    assert response.status_code == 403


def test_admin_can_delete_task(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, owner_headers)
    project = _create_project(client, owner_headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=owner_headers
    ).json()

    response = client.delete(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"), headers=owner_headers
    )

    assert response.status_code == 204


def test_list_tasks_filters_by_status(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    todo = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Todo task"}, headers=headers
    ).json()
    done = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Done task"}, headers=headers
    ).json()
    client.patch(
        _tasks_url(org["id"], project["id"], f"/{done['id']}"),
        json={"status": "done"},
        headers=headers,
    )

    response = client.get(_tasks_url(org["id"], project["id"], "?status=done"), headers=headers)

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [done["id"]]
    assert todo["id"] not in ids


def test_list_tasks_filters_by_assignee(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    user_id = client.get("/api/v1/users/me", headers=headers).json()["id"]
    assigned = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Assigned task", "assignee_id": user_id},
        headers=headers,
    ).json()
    client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Unassigned task"}, headers=headers
    )

    response = client.get(
        _tasks_url(org["id"], project["id"], f"?assignee_id={user_id}"), headers=headers
    )

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [assigned["id"]]


def test_list_tasks_sorts_by_title_desc(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Alpha"}, headers=headers)
    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Bravo"}, headers=headers)

    response = client.get(
        _tasks_url(org["id"], project["id"], "?sort_by=title&order=desc"), headers=headers
    )

    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    assert titles == ["Bravo", "Alpha"]


def test_list_tasks_paginates_with_limit_and_offset(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    for title in ["Task 1", "Task 2", "Task 3"]:
        client.post(_tasks_url(org["id"], project["id"]), json={"title": title}, headers=headers)

    first_page = client.get(
        _tasks_url(org["id"], project["id"], "?limit=2&offset=0"), headers=headers
    )
    second_page = client.get(
        _tasks_url(org["id"], project["id"], "?limit=2&offset=2"), headers=headers
    )

    assert [t["title"] for t in first_page.json()] == ["Task 1", "Task 2"]
    assert [t["title"] for t in second_page.json()] == ["Task 3"]


def test_list_tasks_rejects_limit_over_max(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.get(_tasks_url(org["id"], project["id"], "?limit=101"), headers=headers)

    assert response.status_code == 422


def test_list_tasks_rejects_negative_offset(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.get(_tasks_url(org["id"], project["id"], "?offset=-1"), headers=headers)

    assert response.status_code == 422


def test_list_tasks_rejects_invalid_status_filter(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.get(
        _tasks_url(org["id"], project["id"], "?status=not-a-status"), headers=headers
    )

    assert response.status_code == 422


def test_list_tasks_rejects_invalid_sort_by(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.get(
        _tasks_url(org["id"], project["id"], "?sort_by=not-a-field"), headers=headers
    )

    assert response.status_code == 422


def test_list_tasks_offset_past_end_returns_empty(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    client.post(_tasks_url(org["id"], project["id"]), json={"title": "Only task"}, headers=headers)

    response = client.get(
        _tasks_url(org["id"], project["id"], "?limit=10&offset=5"), headers=headers
    )

    assert response.status_code == 200
    assert response.json() == []


def test_list_tasks_combines_status_and_assignee_filters(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    user_id = client.get("/api/v1/users/me", headers=headers).json()["id"]
    match = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Assigned and done", "assignee_id": user_id},
        headers=headers,
    ).json()
    client.patch(
        _tasks_url(org["id"], project["id"], f"/{match['id']}"),
        json={"status": "done"},
        headers=headers,
    )
    unassigned_done = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Done, unassigned"}, headers=headers
    ).json()
    client.patch(
        _tasks_url(org["id"], project["id"], f"/{unassigned_done['id']}"),
        json={"status": "done"},
        headers=headers,
    )

    response = client.get(
        _tasks_url(org["id"], project["id"], f"?status=done&assignee_id={user_id}"),
        headers=headers,
    )

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [match["id"]]


def test_create_task_defaults_to_medium_priority(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["priority"] == "medium"
    assert body["due_date"] is None


def test_create_task_with_priority_and_due_date(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.post(
        _tasks_url(org["id"], project["id"]),
        json={
            "title": "Ship release",
            "priority": "urgent",
            "due_date": "2026-09-01T00:00:00Z",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["priority"] == "urgent"
    assert _parse_dt(body["due_date"]) == _parse_dt("2026-09-01T00:00:00Z")


def test_update_task_priority_and_due_date(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Set up CI"}, headers=headers
    ).json()

    response = client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"priority": "high", "due_date": "2026-10-15T12:00:00Z"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["priority"] == "high"
    assert _parse_dt(body["due_date"]) == _parse_dt("2026-10-15T12:00:00Z")


def test_update_task_can_clear_due_date(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Set up CI", "due_date": "2026-09-01T00:00:00Z"},
        headers=headers,
    ).json()

    response = client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"due_date": None},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["due_date"] is None


def test_list_tasks_filters_by_priority(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    urgent = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Urgent task", "priority": "urgent"},
        headers=headers,
    ).json()
    client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "Normal task"}, headers=headers
    )

    response = client.get(_tasks_url(org["id"], project["id"], "?priority=urgent"), headers=headers)

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [urgent["id"]]


def test_list_tasks_filters_by_due_date_range(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    early = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Early", "due_date": "2026-01-01T00:00:00Z"},
        headers=headers,
    ).json()
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Late", "due_date": "2026-12-01T00:00:00Z"},
        headers=headers,
    )
    client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "No due date"}, headers=headers
    )

    response = client.get(
        _tasks_url(
            org["id"],
            project["id"],
            "?due_before=2026-06-01T00:00:00Z",
        ),
        headers=headers,
    )

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [early["id"]]


def test_list_tasks_filters_by_due_after(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Early", "due_date": "2026-01-01T00:00:00Z"},
        headers=headers,
    )
    late = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Late", "due_date": "2026-12-01T00:00:00Z"},
        headers=headers,
    ).json()
    client.post(
        _tasks_url(org["id"], project["id"]), json={"title": "No due date"}, headers=headers
    )

    response = client.get(
        _tasks_url(
            org["id"],
            project["id"],
            "?due_after=2026-06-01T00:00:00Z",
        ),
        headers=headers,
    )

    assert response.status_code == 200
    ids = [t["id"] for t in response.json()]
    assert ids == [late["id"]]


def test_list_tasks_sorts_by_priority_rank_not_alphabetically(client):
    # "high" sorts before "low" alphabetically, so this only passes if sorting
    # uses urgency rank (low < medium < high < urgent) rather than the raw string.
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    priorities = [("Low", "low"), ("Urgent", "urgent"), ("High", "high"), ("Medium", "medium")]
    for title, priority in priorities:
        client.post(
            _tasks_url(org["id"], project["id"]),
            json={"title": title, "priority": priority},
            headers=headers,
        )

    response = client.get(
        _tasks_url(org["id"], project["id"], "?sort_by=priority&order=desc"), headers=headers
    )

    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    assert titles == ["Urgent", "High", "Medium", "Low"]


def test_list_tasks_rejects_invalid_priority_filter(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])

    response = client.get(
        _tasks_url(org["id"], project["id"], "?priority=not-a-priority"), headers=headers
    )

    assert response.status_code == 422


def test_task_not_found_for_wrong_project(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project_a = _create_project(client, headers, org["id"], name="Project A")
    project_b = _create_project(client, headers, org["id"], name="Project B")
    task = client.post(
        _tasks_url(org["id"], project_a["id"]), json={"title": "A task"}, headers=headers
    ).json()

    response = client.get(_tasks_url(org["id"], project_b["id"], f"/{task['id']}"), headers=headers)

    assert response.status_code == 404


def test_clear_task_description(client):
    headers, org, project = _setup(client)
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "description": "Some detail"},
        headers=headers,
    ).json()

    response = client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"description": None},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["description"] is None


def test_clearing_task_description_is_recorded_on_the_timeline(client):
    headers, org, project = _setup(client)
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "description": "Some detail"},
        headers=headers,
    ).json()

    client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"description": None},
        headers=headers,
    )

    timeline = client.get(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/timeline"), headers=headers
    ).json()
    updates = [entry for entry in timeline if entry["kind"] == "activity"]
    assert updates[-1]["activity"]["data"]["description"] == {
        "from": "Some detail",
        "to": None,
    }


def test_changing_task_estimate_is_recorded_on_the_timeline(client):
    headers, org, project = _setup(client)
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship it", "estimate_minutes": 60},
        headers=headers,
    ).json()

    client.patch(
        _tasks_url(org["id"], project["id"], f"/{task['id']}"),
        json={"estimate_minutes": 120},
        headers=headers,
    )

    timeline = client.get(
        _tasks_url(org["id"], project["id"], f"/{task['id']}/timeline"), headers=headers
    ).json()
    updates = [entry for entry in timeline if entry["kind"] == "activity"]
    assert updates[-1]["activity"]["data"]["estimate_minutes"] == {
        "from": 60,
        "to": 120,
    }
