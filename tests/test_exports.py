"""CSV export of a project's tasks."""

import csv
import io

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


def _tasks_url(org_id, project_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks{suffix}"


def _export_url(org_id, project_id):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/export/tasks.csv"


def _rows(response):
    return list(csv.reader(io.StringIO(response.text)))


@pytest.fixture()
def setup(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    org = client.post(
        "/api/v1/organizations", json={"name": "Acme Inc"}, headers=owner_headers
    ).json()
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Website Revamp"},
        headers=owner_headers,
    ).json()
    return owner_headers, org["id"], project["id"]


def _create_task(client, headers, org_id, project_id, title="A task", **extra):
    return client.post(
        _tasks_url(org_id, project_id), json={"title": title, **extra}, headers=headers
    ).json()


def test_the_export_is_a_csv_attachment_named_after_the_project(client, setup):
    headers, org_id, project_id = setup

    response = client.get(_export_url(org_id, project_id), headers=headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="website-revamp-tasks.csv"' in response.headers["content-disposition"]


def test_an_empty_project_exports_a_header_only(client, setup):
    headers, org_id, project_id = setup

    rows = _rows(client.get(_export_url(org_id, project_id), headers=headers))

    assert len(rows) == 1
    assert rows[0][:5] == ["id", "title", "description", "status", "priority"]


def test_a_task_exports_its_fields(client, setup):
    headers, org_id, project_id = setup
    me = client.get("/api/v1/users/me", headers=headers).json()
    milestone = client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/milestones",
        json={"name": "v1.0"},
        headers=headers,
    ).json()
    task = _create_task(
        client,
        headers,
        org_id,
        project_id,
        "Ship the release",
        assignee_id=me["id"],
        milestone_id=milestone["id"],
        estimate_minutes=120,
        priority="high",
    )
    client.post(
        _tasks_url(org_id, project_id, f"/{task['id']}/time"),
        json={"minutes": 45},
        headers=headers,
    )

    header, row = _rows(client.get(_export_url(org_id, project_id), headers=headers))

    exported = dict(zip(header, row))
    assert exported["title"] == "Ship the release"
    assert exported["status"] == "todo"
    assert exported["priority"] == "high"
    assert exported["assignee_email"] == "owner@example.com"
    assert exported["milestone"] == "v1.0"
    assert exported["estimate_minutes"] == "120"
    assert exported["logged_minutes"] == "45"


def test_labels_are_joined_into_one_cell(client, setup):
    headers, org_id, project_id = setup
    task = _create_task(client, headers, org_id, project_id)
    for name in ("urgent", "backend"):
        label = client.post(
            f"/api/v1/organizations/{org_id}/labels", json={"name": name}, headers=headers
        ).json()
        client.post(
            _tasks_url(org_id, project_id, f"/{task['id']}/labels"),
            json={"label_id": label["id"]},
            headers=headers,
        )

    _header, row = _rows(client.get(_export_url(org_id, project_id), headers=headers))

    assert dict(zip(_header, row))["labels"] == "backend, urgent"


def test_a_formula_looking_title_is_defused(client, setup):
    """A spreadsheet runs a cell starting with = as code the moment it opens."""
    headers, org_id, project_id = setup
    _create_task(client, headers, org_id, project_id, "=HYPERLINK(1,2)")

    _header, row = _rows(client.get(_export_url(org_id, project_id), headers=headers))

    assert dict(zip(_header, row))["title"] == "'=HYPERLINK(1,2)"


@pytest.mark.parametrize("prefix", ["+", "-", "@", "\t", "\r"])
def test_other_formula_prefixes_are_also_defused(client, setup, prefix):
    """= isn't the only character a spreadsheet treats a cell's formula as
    starting with. Using the description rather than the title: unlike the
    title, it isn't stripped of leading whitespace, so this also covers the
    tab/carriage-return prefixes a title could never carry."""
    headers, org_id, project_id = setup
    _create_task(client, headers, org_id, project_id, description=f"{prefix}SUM(1,2)")

    _header, row = _rows(client.get(_export_url(org_id, project_id), headers=headers))

    assert dict(zip(_header, row))["description"] == f"'{prefix}SUM(1,2)"


def test_commas_and_quotes_survive_a_round_trip(client, setup):
    headers, org_id, project_id = setup
    _create_task(
        client,
        headers,
        org_id,
        project_id,
        "Fix, then ship",
        description='He said "no" and\nleft a newline',
    )

    _header, row = _rows(client.get(_export_url(org_id, project_id), headers=headers))

    exported = dict(zip(_header, row))
    assert exported["title"] == "Fix, then ship"
    assert exported["description"] == 'He said "no" and\nleft a newline'


def test_the_export_takes_the_same_filters_as_the_task_list(client, setup):
    headers, org_id, project_id = setup
    done = _create_task(client, headers, org_id, project_id, "Finished")
    _create_task(client, headers, org_id, project_id, "Still going")
    client.patch(
        _tasks_url(org_id, project_id, f"/{done['id']}"), json={"status": "done"}, headers=headers
    )

    rows = _rows(
        client.get(_export_url(org_id, project_id), params={"status": "done"}, headers=headers)
    )

    assert [row[1] for row in rows[1:]] == ["Finished"]


def test_a_soft_deleted_task_is_not_exported(client, setup):
    headers, org_id, project_id = setup
    task = _create_task(client, headers, org_id, project_id, "Deleted")
    _create_task(client, headers, org_id, project_id, "Kept")
    client.delete(_tasks_url(org_id, project_id, f"/{task['id']}"), headers=headers)

    rows = _rows(client.get(_export_url(org_id, project_id), headers=headers))

    assert [row[1] for row in rows[1:]] == ["Kept"]


def test_the_row_limit_is_bounded(client, setup):
    headers, org_id, project_id = setup
    for index in range(3):
        _create_task(client, headers, org_id, project_id, f"Task {index}")

    rows = _rows(client.get(_export_url(org_id, project_id), params={"limit": 2}, headers=headers))

    assert len(rows) == 3  # header plus two tasks
    assert (
        client.get(
            _export_url(org_id, project_id), params={"limit": 100000}, headers=headers
        ).status_code
        == 422
    )


def test_a_viewer_may_export_what_they_can_already_read(client, setup):
    owner_headers, org_id, project_id = setup
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
    _create_task(client, owner_headers, org_id, project_id, "Visible")

    rows = _rows(client.get(_export_url(org_id, project_id), headers=viewer_headers))

    assert [row[1] for row in rows[1:]] == ["Visible"]


def test_a_restricted_project_is_not_exportable_by_an_outsider(client, setup):
    owner_headers, org_id, project_id = setup
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": "outsider@example.com", "role": "member"},
        headers=owner_headers,
    )
    client.patch(
        f"/api/v1/organizations/{org_id}/projects/{project_id}",
        json={"visibility": "restricted"},
        headers=owner_headers,
    )

    response = client.get(_export_url(org_id, project_id), headers=outsider_headers)

    assert response.status_code == 404


def test_the_export_needs_authentication(client, setup):
    _headers, org_id, project_id = setup

    assert client.get(_export_url(org_id, project_id)).status_code == 401
