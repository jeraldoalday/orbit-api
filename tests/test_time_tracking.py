"""Time tracking: minutes logged against a task, and the project report."""

from datetime import date, timedelta

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


def _time_url(org_id, project_id, task_id, suffix=""):
    return _tasks_url(org_id, project_id, f"/{task_id}/time{suffix}")


def _report_url(org_id, project_id):
    return f"/api/v1/organizations/{org_id}/projects/{project_id}/time"


@pytest.fixture()
def setup(client):
    """An owner, a second member, a project and one task with an estimate."""
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = client.post(
        "/api/v1/organizations", json={"name": "Acme Inc"}, headers=owner_headers
    ).json()
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    project = client.post(
        f"/api/v1/organizations/{org['id']}/projects",
        json={"name": "Website Revamp"},
        headers=owner_headers,
    ).json()
    task = client.post(
        _tasks_url(org["id"], project["id"]),
        json={"title": "Ship the release", "estimate_minutes": 120},
        headers=owner_headers,
    ).json()
    return owner_headers, member_headers, org["id"], project["id"], task["id"]


def _log(client, headers, url, minutes, **extra):
    return client.post(url, json={"minutes": minutes, **extra}, headers=headers)


def test_logging_time_defaults_to_today(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup

    response = _log(client, owner_headers, _time_url(org_id, project_id, task_id), 45)

    assert response.status_code == 201
    assert response.json()["minutes"] == 45
    assert response.json()["spent_on"] == date.today().isoformat()
    assert response.json()["user"]["email"] == "owner@example.com"


def test_the_summary_measures_against_the_estimate(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    _log(client, owner_headers, url, 45)
    _log(client, member_headers, url, 30)

    summary = client.get(url, headers=owner_headers).json()

    assert summary["logged_minutes"] == 75
    assert summary["estimate_minutes"] == 120
    assert summary["remaining_minutes"] == 45
    assert summary["over_estimate"] is False
    assert len(summary["entries"]) == 2


def test_passing_the_estimate_floors_remaining_at_zero(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    _log(client, owner_headers, url, 200)

    summary = client.get(url, headers=owner_headers).json()

    assert summary["remaining_minutes"] == 0
    assert summary["over_estimate"] is True


def test_a_task_without_an_estimate_has_no_remaining(client, setup):
    owner_headers, _member, org_id, project_id, _task_id = setup
    task = client.post(
        _tasks_url(org_id, project_id), json={"title": "Unestimated"}, headers=owner_headers
    ).json()
    url = _time_url(org_id, project_id, task["id"])
    _log(client, owner_headers, url, 60)

    summary = client.get(url, headers=owner_headers).json()

    assert summary["estimate_minutes"] is None
    assert summary["remaining_minutes"] is None
    assert summary["over_estimate"] is False


def test_entries_are_listed_most_recent_day_first(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    _log(client, owner_headers, url, 10, spent_on=(date.today() - timedelta(days=3)).isoformat())
    _log(client, owner_headers, url, 20, spent_on=date.today().isoformat())

    entries = client.get(url, headers=owner_headers).json()["entries"]

    assert [entry["minutes"] for entry in entries] == [20, 10]


def test_a_future_day_is_refused(client, setup):
    """A date that hasn't happened is a typo or a forecast, not a record."""
    owner_headers, _member, org_id, project_id, task_id = setup

    response = _log(
        client,
        owner_headers,
        _time_url(org_id, project_id, task_id),
        30,
        spent_on=(date.today() + timedelta(days=1)).isoformat(),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Work cannot be logged against a future date"


def test_an_absurd_duration_is_refused(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)

    assert _log(client, owner_headers, url, 24 * 60 + 1).status_code == 422
    assert _log(client, owner_headers, url, 0).status_code == 422


def test_updating_an_entrys_date_to_the_future_is_refused(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    entry = _log(client, owner_headers, url, 45).json()

    response = client.patch(
        f"{url}/{entry['id']}",
        json={"spent_on": (date.today() + timedelta(days=1)).isoformat()},
        headers=owner_headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Work cannot be logged against a future date"


def test_sending_an_explicit_null_leaves_minutes_and_date_unchanged(client, setup):
    """`minutes` and `spent_on` have no null meaning, unlike `note`."""
    owner_headers, _member, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    original_day = (date.today() - timedelta(days=2)).isoformat()
    entry = _log(client, owner_headers, url, 45, spent_on=original_day).json()

    response = client.patch(
        f"{url}/{entry['id']}",
        json={"minutes": None, "spent_on": None, "note": "kept the original minutes and date"},
        headers=owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["minutes"] == 45
    assert response.json()["spent_on"] == original_day
    assert response.json()["note"] == "kept the original minutes and date"


def test_an_author_can_correct_their_own_entry(client, setup):
    _owner, member_headers, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    entry = _log(client, member_headers, url, 45).json()

    response = client.patch(
        f"{url}/{entry['id']}", json={"minutes": 60, "note": "Rounded up"}, headers=member_headers
    )

    assert response.status_code == 200
    assert response.json()["minutes"] == 60
    assert response.json()["note"] == "Rounded up"


def test_an_editor_cannot_edit_someone_elses_hours(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    entry = _log(client, owner_headers, url, 45).json()

    response = client.patch(f"{url}/{entry['id']}", json={"minutes": 5}, headers=member_headers)

    assert response.status_code == 403
    assert client.delete(f"{url}/{entry['id']}", headers=member_headers).status_code == 403


def test_an_admin_can_correct_anyones_hours(client, setup):
    """Somebody has to be able to fix the entry of a person on leave."""
    owner_headers, member_headers, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    entry = _log(client, member_headers, url, 45).json()

    response = client.patch(f"{url}/{entry['id']}", json={"minutes": 30}, headers=owner_headers)

    assert response.status_code == 200
    assert client.get(url, headers=owner_headers).json()["logged_minutes"] == 30


def test_deleting_an_entry_removes_it_from_the_total(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    entry = _log(client, owner_headers, url, 45).json()
    _log(client, owner_headers, url, 15)

    assert client.delete(f"{url}/{entry['id']}", headers=owner_headers).status_code == 204

    assert client.get(url, headers=owner_headers).json()["logged_minutes"] == 15


def test_an_entry_from_another_task_is_not_found(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup
    other = client.post(
        _tasks_url(org_id, project_id), json={"title": "Elsewhere"}, headers=owner_headers
    ).json()
    entry = _log(client, owner_headers, _time_url(org_id, project_id, task_id), 45).json()

    response = client.delete(
        f"{_time_url(org_id, project_id, other['id'])}/{entry['id']}", headers=owner_headers
    )

    assert response.status_code == 404


def test_a_viewer_reads_the_log_but_cannot_add_to_it(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    client.patch(
        f"/api/v1/organizations/{org_id}/projects/{project_id}",
        json={"visibility": "restricted"},
        headers=owner_headers,
    )
    client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/members",
        json={"email": "member@example.com", "role": "viewer"},
        headers=owner_headers,
    )
    url = _time_url(org_id, project_id, task_id)

    assert client.get(url, headers=member_headers).status_code == 200
    assert _log(client, member_headers, url, 30).status_code == 403


def test_the_project_report_breaks_down_by_person_and_task(client, setup):
    owner_headers, member_headers, org_id, project_id, task_id = setup
    second = client.post(
        _tasks_url(org_id, project_id),
        json={"title": "Write the docs", "estimate_minutes": 60},
        headers=owner_headers,
    ).json()
    _log(client, owner_headers, _time_url(org_id, project_id, task_id), 90)
    _log(client, member_headers, _time_url(org_id, project_id, task_id), 30)
    _log(client, member_headers, _time_url(org_id, project_id, second["id"]), 45)

    report = client.get(_report_url(org_id, project_id), headers=owner_headers).json()

    assert report["logged_minutes"] == 165
    assert report["estimated_minutes"] == 180
    # Both breakdowns are ordered by minutes, heaviest first.
    assert [(row["label"], row["minutes"]) for row in report["by_user"]] == [
        ("owner@example.com", 90),
        ("member@example.com", 75),
    ]
    assert [(row["label"], row["minutes"]) for row in report["by_task"]] == [
        ("Ship the release", 120),
        ("Write the docs", 45),
    ]


def test_the_report_can_be_narrowed_to_a_date_range(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    old = (date.today() - timedelta(days=30)).isoformat()
    _log(client, owner_headers, url, 100, spent_on=old)
    _log(client, owner_headers, url, 20, spent_on=date.today().isoformat())

    report = client.get(
        _report_url(org_id, project_id),
        params={"spent_from": (date.today() - timedelta(days=7)).isoformat()},
        headers=owner_headers,
    ).json()

    assert report["logged_minutes"] == 20
    assert report["spent_to"] is None


def test_the_report_can_be_narrowed_by_an_upper_bound_alone(client, setup):
    owner_headers, _member, org_id, project_id, task_id = setup
    url = _time_url(org_id, project_id, task_id)
    old = (date.today() - timedelta(days=30)).isoformat()
    _log(client, owner_headers, url, 100, spent_on=old)
    _log(client, owner_headers, url, 20, spent_on=date.today().isoformat())

    report = client.get(
        _report_url(org_id, project_id),
        params={"spent_to": (date.today() - timedelta(days=7)).isoformat()},
        headers=owner_headers,
    ).json()

    assert report["logged_minutes"] == 100
    assert report["spent_from"] is None


def test_a_backwards_date_range_is_refused(client, setup):
    owner_headers, _member, org_id, project_id, _task_id = setup

    response = client.get(
        _report_url(org_id, project_id),
        params={"spent_from": "2026-05-01", "spent_to": "2026-04-01"},
        headers=owner_headers,
    )

    assert response.status_code == 422


def test_a_deleted_task_drops_out_of_the_report(client, setup):
    """The report describes the project as it stands, not before a clean-up."""
    owner_headers, _member, org_id, project_id, task_id = setup
    _log(client, owner_headers, _time_url(org_id, project_id, task_id), 90)

    client.delete(_tasks_url(org_id, project_id, f"/{task_id}"), headers=owner_headers)

    report = client.get(_report_url(org_id, project_id), headers=owner_headers).json()
    assert report["logged_minutes"] == 0
    assert report["by_task"] == []


def test_time_tracking_needs_authentication(client, setup):
    _owner, _member, org_id, project_id, task_id = setup

    assert client.get(_time_url(org_id, project_id, task_id)).status_code == 401
    assert client.get(_report_url(org_id, project_id)).status_code == 401
