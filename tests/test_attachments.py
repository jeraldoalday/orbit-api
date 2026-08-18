import io

import pytest

from app.core.storage import (
    LocalObjectStorage,
    ObjectTooLargeError,
    StorageError,
    build_storage_key,
    sanitize_filename,
)


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


def _add_org_member(client, headers, org_id, email, role="member"):
    return client.post(
        f"/api/v1/organizations/{org_id}/members",
        json={"email": email, "role": role},
        headers=headers,
    )


def _create_project(client, headers, org_id, name="Website Revamp", visibility="open"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects",
        json={"name": name, "visibility": visibility},
        headers=headers,
    ).json()


def _create_task(client, headers, org_id, project_id, title="Ship it"):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks",
        json={"title": title},
        headers=headers,
    ).json()


def _url(org_id, project_id, task_id, suffix=""):
    return (
        f"/api/v1/organizations/{org_id}/projects/{project_id}"
        f"/tasks/{task_id}/attachments{suffix}"
    )


@pytest.fixture()
def setup(client):
    """An owner with an org, an open project and one task on it."""
    headers = _register_and_login(client, email="owner@example.com")
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    task = _create_task(client, headers, org["id"], project["id"])
    return headers, org, project, task


def _upload(
    client, headers, org, project, task, name="notes.txt", body=b"hello", ctype="text/plain"
):
    return client.post(
        _url(org["id"], project["id"], task["id"]),
        files={"file": (name, io.BytesIO(body), ctype)},
        headers=headers,
    )


# --- storage unit tests -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../etc/passwd", "passwd"),
        (r"C:\Users\me\secret.txt", "secret.txt"),
        ("weird name!.txt", "weird_name_.txt"),
        ("", "file"),
        ("...", "file"),
        ("/", "file"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_truncates_to_the_column_width():
    assert len(sanitize_filename("a" * 400)) == 255


def test_storage_keys_are_unique_per_upload():
    import uuid

    task_id = uuid.uuid4()

    first = build_storage_key(task_id, "same.txt")
    second = build_storage_key(task_id, "same.txt")

    assert first != second
    assert first.startswith(f"tasks/{task_id}/")
    assert first.endswith("-same.txt")


def test_local_storage_round_trips_an_object(storage):
    written = storage.save("tasks/x/one.txt", io.BytesIO(b"payload"), max_bytes=100)

    assert written == 7
    assert storage.exists("tasks/x/one.txt")
    with storage.open("tasks/x/one.txt") as handle:
        assert handle.read() == b"payload"


def test_local_storage_rejects_and_cleans_up_an_oversized_object(storage):
    with pytest.raises(ObjectTooLargeError):
        storage.save("tasks/x/big.bin", io.BytesIO(b"a" * 200), max_bytes=50)

    assert not storage.exists("tasks/x/big.bin")


def test_local_storage_refuses_a_key_escaping_the_root(tmp_path):
    storage = LocalObjectStorage(str(tmp_path / "root"))

    with pytest.raises(StorageError):
        storage.save("../escaped.txt", io.BytesIO(b"x"), max_bytes=100)


def test_deleting_a_missing_object_is_not_an_error(storage):
    storage.delete("tasks/x/never-existed.txt")


# --- API tests --------------------------------------------------------------


def test_upload_returns_metadata(client, setup):
    headers, org, project, task = setup

    response = _upload(client, headers, org, project, task)

    assert response.status_code == 201
    body = response.json()
    assert body["filename"] == "notes.txt"
    assert body["content_type"] == "text/plain"
    assert body["size_bytes"] == 5
    assert body["uploaded_by"]["email"] == "owner@example.com"
    assert body["task_id"] == task["id"]


def test_uploaded_file_can_be_downloaded(client, setup):
    headers, org, project, task = setup
    attachment = _upload(client, headers, org, project, task, body=b"the contents").json()

    response = client.get(
        _url(org["id"], project["id"], task["id"], f"/{attachment['id']}/download"),
        headers=headers,
    )

    assert response.status_code == 200
    assert response.content == b"the contents"
    assert response.headers["content-type"].startswith("text/plain")
    assert "notes.txt" in response.headers["content-disposition"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_attachments_are_listed_oldest_first(client, setup):
    headers, org, project, task = setup
    _upload(client, headers, org, project, task, name="first.txt")
    _upload(client, headers, org, project, task, name="second.txt")

    listed = client.get(_url(org["id"], project["id"], task["id"]), headers=headers).json()

    assert [item["filename"] for item in listed] == ["first.txt", "second.txt"]


def test_upload_sanitizes_a_traversing_filename(client, setup):
    headers, org, project, task = setup

    body = _upload(client, headers, org, project, task, name="../../etc/passwd").json()

    assert body["filename"] == "passwd"


def test_upload_normalizes_a_parameterized_content_type(client, setup):
    headers, org, project, task = setup

    body = _upload(
        client, headers, org, project, task, ctype="text/html; charset=utf-8"
    ).json()

    assert body["content_type"] == "text/html"


def test_empty_upload_is_rejected(client, setup):
    headers, org, project, task = setup

    response = _upload(client, headers, org, project, task, body=b"")

    assert response.status_code == 422
    assert "empty" in response.json()["detail"].lower()


def test_oversized_upload_is_rejected(client, setup, monkeypatch):
    headers, org, project, task = setup
    monkeypatch.setattr("app.api.v1.routers.attachments.settings.attachment_max_bytes", 4)

    response = _upload(client, headers, org, project, task, body=b"far too long")

    assert response.status_code == 413


def test_upload_is_capped_per_task(client, setup, monkeypatch):
    headers, org, project, task = setup
    monkeypatch.setattr("app.api.v1.routers.attachments.settings.attachment_max_per_task", 1)

    assert _upload(client, headers, org, project, task, name="a.txt").status_code == 201
    second = _upload(client, headers, org, project, task, name="b.txt")

    assert second.status_code == 422
    assert "at most 1" in second.json()["detail"]


def test_quota_reports_remaining_slots(client, setup):
    headers, org, project, task = setup
    _upload(client, headers, org, project, task)

    quota = client.get(
        _url(org["id"], project["id"], task["id"], "/quota"), headers=headers
    ).json()

    assert quota["used"] == 1
    assert quota["remaining"] == quota["max_per_task"] - 1


def test_deleting_an_attachment_removes_the_stored_object(client, setup, storage):
    headers, org, project, task = setup
    attachment = _upload(client, headers, org, project, task).json()
    keys_before = [path for path in _all_keys(storage)]

    response = client.delete(
        _url(org["id"], project["id"], task["id"], f"/{attachment['id']}"), headers=headers
    )

    assert response.status_code == 204
    assert keys_before and _all_keys(storage) == []
    assert client.get(_url(org["id"], project["id"], task["id"]), headers=headers).json() == []


def _all_keys(storage):
    import os

    found = []
    for directory, _subdirs, files in os.walk(storage.root):
        for name in files:
            found.append(os.path.join(directory, name))
    return found


def test_deleting_a_task_deletes_its_attachment_rows(client, setup):
    headers, org, project, task = setup
    _upload(client, headers, org, project, task)

    client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks/{task['id']}",
        headers=headers,
    )

    listed = client.get(_url(org["id"], project["id"], task["id"]), headers=headers)
    assert listed.status_code == 404


def test_download_of_an_unknown_attachment_is_404(client, setup):
    headers, org, project, task = setup

    response = client.get(
        _url(
            org["id"],
            project["id"],
            task["id"],
            "/00000000-0000-0000-0000-000000000000/download",
        ),
        headers=headers,
    )

    assert response.status_code == 404


def test_attachments_require_authentication(client, setup):
    _headers, org, project, task = setup

    assert client.get(_url(org["id"], project["id"], task["id"])).status_code == 401


def test_a_viewer_can_read_but_not_upload(client, setup):
    owner_headers, org, project, task = setup
    viewer_headers = _register_and_login(client, email="viewer@example.com")
    _add_org_member(client, owner_headers, org["id"], "viewer@example.com")
    client.patch(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}",
        json={"visibility": "restricted"},
        headers=owner_headers,
    )
    viewer = client.get("/api/v1/users/me", headers=viewer_headers).json()
    client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/members",
        json={"email": viewer["email"], "role": "viewer"},
        headers=owner_headers,
    )
    _upload(client, owner_headers, org, project, task)

    assert (
        client.get(_url(org["id"], project["id"], task["id"]), headers=viewer_headers).status_code
        == 200
    )
    assert _upload(client, viewer_headers, org, project, task).status_code == 403


def test_a_non_member_cannot_see_attachments(client, setup):
    _headers, org, project, task = setup
    outsider_headers = _register_and_login(client, email="outsider@example.com")

    response = client.get(_url(org["id"], project["id"], task["id"]), headers=outsider_headers)

    assert response.status_code == 404


# --- purge must not leak stored objects -------------------------------------


def test_purging_a_task_deletes_its_stored_objects(client, setup, storage):
    """The attachment rows go with the cascade; the bytes must go too.

    Without this the only record of which objects belonged to the task is
    destroyed alongside it, and the blobs are stranded in the bucket forever.
    """
    headers, org, project, task = setup
    _upload(client, headers, org, project, task)
    assert _all_keys(storage)

    client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks/{task['id']}",
        headers=headers,
    )
    purged = client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}"
        f"/tasks/{task['id']}/purge",
        headers=headers,
    )

    assert purged.status_code == 204
    assert _all_keys(storage) == []


def test_purging_a_project_deletes_every_tasks_stored_objects(client, setup, storage):
    headers, org, project, task = setup
    second_task = client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks",
        json={"title": "Another"},
        headers=headers,
    ).json()
    _upload(client, headers, org, project, task, name="first.txt")
    _upload(client, headers, org, project, second_task, name="second.txt")
    assert len(_all_keys(storage)) == 2

    client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}", headers=headers
    )
    purged = client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/purge", headers=headers
    )

    assert purged.status_code == 204
    assert _all_keys(storage) == []


def test_a_soft_delete_keeps_the_stored_objects(client, setup, storage):
    """Restoring has to bring the files back with it, so nothing is removed."""
    headers, org, project, task = setup
    _upload(client, headers, org, project, task)

    client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks/{task['id']}",
        headers=headers,
    )

    assert len(_all_keys(storage)) == 1


def test_restoring_a_task_brings_its_attachments_back(client, setup, storage):
    headers, org, project, task = setup
    attachment = _upload(client, headers, org, project, task).json()
    client.delete(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}/tasks/{task['id']}",
        headers=headers,
    )

    client.post(
        f"/api/v1/organizations/{org['id']}/projects/{project['id']}"
        f"/tasks/{task['id']}/restore",
        headers=headers,
    )

    listed = client.get(_url(org["id"], project["id"], task["id"]), headers=headers).json()
    assert [item["id"] for item in listed] == [attachment["id"]]
    download = client.get(
        _url(org["id"], project["id"], task["id"], f"/{attachment['id']}/download"),
        headers=headers,
    )
    assert download.content == b"hello"


def test_delete_objects_survives_a_failing_backend(storage, caplog):
    """One key failing must not abort the rest — the rows are already gone."""
    from app.services.attachment_service import delete_objects

    class _Flaky:
        def __init__(self):
            self.deleted = []

        def delete(self, key):
            if key == "bad":
                raise OSError("bucket unavailable")
            self.deleted.append(key)

    flaky = _Flaky()

    removed = delete_objects(flaky, ["good-1", "bad", "good-2"])

    assert removed == 2
    assert flaky.deleted == ["good-1", "good-2"]
