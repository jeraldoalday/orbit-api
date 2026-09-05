"""Task checklists: ordered steps inside one task."""

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


def _checklist_url(org_id, project_id, task_id, suffix=""):
    return (
        f"/api/v1/organizations/{org_id}/projects/{project_id}"
        f"/tasks/{task_id}/checklist{suffix}"
    )


@pytest.fixture()
def setup(client):
    """An owner, a restricted-free project and one task to hang steps off."""
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = client.post(
        "/api/v1/organizations", json={"name": "Acme Inc"}, headers=owner_headers
    ).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Website Revamp"},
        headers=owner_headers,
    ).json()
    task = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks",
        json={"title": "Ship the release"},
        headers=owner_headers,
    ).json()
    return owner_headers, org["id"], project["id"], task["id"]


def _add(client, headers, url, content):
    return client.post(url, json={"content": content}, headers=headers)


def test_items_append_in_order(client, setup):
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)

    for content in ("Write the migration", "Deploy it", "Tell support"):
        assert _add(client, headers, url, content).status_code == 201

    body = client.get(url, headers=headers).json()

    assert [item["content"] for item in body["items"]] == [
        "Write the migration",
        "Deploy it",
        "Tell support",
    ]
    assert [item["position"] for item in body["items"]] == [0, 1, 2]


def test_progress_counts_ticked_items(client, setup):
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)
    first = _add(client, headers, url, "Write the migration").json()
    _add(client, headers, url, "Deploy it")

    client.patch(f"{url}/{first['id']}", json={"is_done": True}, headers=headers)

    body = client.get(url, headers=headers).json()
    assert body["total"] == 2
    assert body["done"] == 1
    assert body["completion_rate"] == 0.5


def test_an_empty_checklist_is_zero_per_cent_not_null(client, setup):
    headers, org_id, project_id, task_id = setup

    body = client.get(_checklist_url(org_id, project_id, task_id), headers=headers).json()

    assert body == {"items": [], "total": 0, "done": 0, "completion_rate": 0.0}


def test_renaming_a_step_leaves_it_ticked(client, setup):
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)
    item = _add(client, headers, url, "Write the migration").json()
    client.patch(f"{url}/{item['id']}", json={"is_done": True}, headers=headers)

    response = client.patch(
        f"{url}/{item['id']}",
        json={"content": "Write the migration and review it"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["content"] == "Write the migration and review it"
    assert response.json()["is_done"] is True


def test_reorder_rewrites_the_positions(client, setup):
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)
    first = _add(client, headers, url, "First").json()
    second = _add(client, headers, url, "Second").json()
    third = _add(client, headers, url, "Third").json()

    response = client.post(
        f"{url}/reorder",
        json={"item_ids": [third["id"], first["id"], second["id"]]},
        headers=headers,
    )

    assert response.status_code == 200
    assert [item["content"] for item in response.json()["items"]] == ["Third", "First", "Second"]
    assert [item["position"] for item in response.json()["items"]] == [0, 1, 2]


def test_a_partial_reorder_is_refused(client, setup):
    """Half an ordering leaves the other half wherever it happened to be."""
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)
    first = _add(client, headers, url, "First").json()
    _add(client, headers, url, "Second")

    response = client.post(f"{url}/reorder", json={"item_ids": [first["id"]]}, headers=headers)

    assert response.status_code == 422
    assert client.get(url, headers=headers).json()["items"][0]["content"] == "First"


def test_a_reorder_naming_the_same_item_twice_is_refused(client, setup):
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)
    first = _add(client, headers, url, "First").json()
    _add(client, headers, url, "Second")

    response = client.post(
        f"{url}/reorder", json={"item_ids": [first["id"], first["id"]]}, headers=headers
    )

    assert response.status_code == 422


def test_deleting_an_item_closes_the_gap(client, setup):
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)
    first = _add(client, headers, url, "First").json()
    _add(client, headers, url, "Second")
    _add(client, headers, url, "Third")

    assert client.delete(f"{url}/{first['id']}", headers=headers).status_code == 204

    items = client.get(url, headers=headers).json()["items"]
    assert [item["position"] for item in items] == [0, 1]
    assert [item["content"] for item in items] == ["Second", "Third"]


def test_an_append_after_a_delete_lands_last(client, setup):
    """Renumbering on delete is what keeps the next append from colliding."""
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)
    first = _add(client, headers, url, "First").json()
    _add(client, headers, url, "Second")
    client.delete(f"{url}/{first['id']}", headers=headers)

    _add(client, headers, url, "Third")

    items = client.get(url, headers=headers).json()["items"]
    assert [item["content"] for item in items] == ["Second", "Third"]
    assert [item["position"] for item in items] == [0, 1]


def test_an_item_from_another_task_is_not_found(client, setup):
    """Item ids are looked up under their task, never on their own."""
    headers, org_id, project_id, task_id = setup
    other = client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks",
        json={"title": "Something else"},
        headers=headers,
    ).json()
    item = _add(client, headers, _checklist_url(org_id, project_id, task_id), "First").json()

    response = client.patch(
        f"{_checklist_url(org_id, project_id, other['id'])}/{item['id']}",
        json={"is_done": True},
        headers=headers,
    )

    assert response.status_code == 404


def test_blank_content_is_refused(client, setup):
    headers, org_id, project_id, task_id = setup

    response = _add(client, headers, _checklist_url(org_id, project_id, task_id), "   ")

    assert response.status_code == 422


def test_the_item_cap_is_enforced(client, setup, monkeypatch):
    headers, org_id, project_id, task_id = setup
    url = _checklist_url(org_id, project_id, task_id)
    monkeypatch.setattr("app.api.v1.routers.task_checklist.settings.checklist_max_items", 2)

    _add(client, headers, url, "First")
    _add(client, headers, url, "Second")
    response = _add(client, headers, url, "Third")

    assert response.status_code == 422
    assert "at most 2" in response.json()["detail"]


def test_a_viewer_may_read_but_not_edit(client, setup):
    owner_headers, org_id, project_id, task_id = setup
    viewer_headers = _register_and_login(client, email="viewer@example.com")
    client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "viewer@example.com", "role": "member"},
        headers=owner_headers,
    )
    client.patch(
        f"/api/v1/organizations/{org_id}/projects/{project_id}",
        json={"visibility": "restricted"},
        headers=owner_headers,
    )
    client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/members",
        json={"email": "viewer@example.com", "role": "viewer"},
        headers=owner_headers,
    )
    url = _checklist_url(org_id, project_id, task_id)
    _add(client, owner_headers, url, "First")

    assert client.get(url, headers=viewer_headers).status_code == 200
    assert _add(client, viewer_headers, url, "Sneaky").status_code == 403


def test_a_non_member_cannot_see_the_checklist(client, setup):
    _owner_headers, org_id, project_id, task_id = setup
    outsider_headers = _register_and_login(client, email="outsider@example.com")

    response = client.get(_checklist_url(org_id, project_id, task_id), headers=outsider_headers)

    assert response.status_code == 404


def test_the_checklist_needs_authentication(client, setup):
    _headers, org_id, project_id, task_id = setup

    assert client.get(_checklist_url(org_id, project_id, task_id)).status_code == 401
