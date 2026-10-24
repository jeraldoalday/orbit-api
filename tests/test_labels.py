import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.label import Label
from app.models.organization import Organization
from app.services import label_service


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


def _labels_url(org_id, suffix=""):
    return f"/api/v1/organizations/{org_id}/labels{suffix}"


def test_create_label_defaults_to_gray(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    response = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Bug"
    assert body["color"] == "#6b7280"


def test_create_label_with_custom_color(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    response = client.post(
        _labels_url(org["id"]), json={"name": "Urgent", "color": "#ff0000"}, headers=headers
    )

    assert response.status_code == 201
    assert response.json()["color"] == "#ff0000"


def test_create_label_rejects_invalid_color(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    response = client.post(
        _labels_url(org["id"]), json={"name": "Urgent", "color": "not-a-color"}, headers=headers
    )

    assert response.status_code == 422


def test_create_label_requires_membership(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)

    response = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=outsider_headers)

    assert response.status_code == 404


def test_create_duplicate_label_name_rejected(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers)

    response = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers)

    assert response.status_code == 409


def test_create_duplicate_label_name_rejected_case_insensitively(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers)

    response = client.post(_labels_url(org["id"]), json={"name": "bug"}, headers=headers)

    assert response.status_code == 409


def test_concurrent_case_insensitive_label_names_rejected_at_the_database(client, db):
    """The service's pre-check only stops a case-insensitive repeat when
    nothing else is racing it; two requests that both read before either
    commits would otherwise both pass it. Bypassing the service the way a
    second such request would proves the database itself refuses the second
    row rather than relying on the pre-check alone.
    """
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers)

    db.add(Label(organization_id=uuid.UUID(org["id"]), name="bug"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_create_label_turns_a_lost_race_into_duplicate_label_error(client, db, monkeypatch):
    """The test above proves the database rejects the second row; this one
    proves `create_label` itself survives losing that race. The pre-check is
    forced to miss the existing name, the way it would if the other request's
    commit lands in the gap between this call's check and its own commit, and
    the IntegrityError that `db.commit()` then raises must come out as the
    ordinary DuplicateLabelError rather than an unhandled database error — and
    the session must still be usable afterwards.
    """
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    org_id = uuid.UUID(org["id"])

    db.add(Label(organization_id=org_id, name="Bug", color="#888888"))
    db.commit()

    monkeypatch.setattr(label_service, "_find_by_name_ci", lambda *_args, **_kwargs: None)

    organization = db.get(Organization, org_id)
    with pytest.raises(label_service.DuplicateLabelError):
        label_service.create_label(db, organization, "bug", "#000000")

    # A commit that failed and was rolled back inside create_label must leave
    # the session able to query normally rather than stuck in a failed state.
    names = db.execute(select(Label.name).where(Label.organization_id == org_id)).scalars().all()
    assert names == ["Bug"]


def test_same_label_name_allowed_in_different_orgs(client):
    headers = _register_and_login(client)
    org_a = _create_org(client, headers, name="Org A")
    org_b = _create_org(client, headers, name="Org B")
    client.post(_labels_url(org_a["id"]), json={"name": "Bug"}, headers=headers)

    response = client.post(_labels_url(org_b["id"]), json={"name": "Bug"}, headers=headers)

    assert response.status_code == 201


def test_list_labels_scoped_to_org(client):
    headers = _register_and_login(client)
    org_a = _create_org(client, headers, name="Org A")
    org_b = _create_org(client, headers, name="Org B")
    client.post(_labels_url(org_a["id"]), json={"name": "Bug"}, headers=headers)
    client.post(_labels_url(org_b["id"]), json={"name": "Feature"}, headers=headers)

    response = client.get(_labels_url(org_a["id"]), headers=headers)

    assert response.status_code == 200
    names = [label["name"] for label in response.json()]
    assert names == ["Bug"]


def test_list_labels_sorted_by_name(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    client.post(_labels_url(org["id"]), json={"name": "Zeta"}, headers=headers)
    client.post(_labels_url(org["id"]), json={"name": "Alpha"}, headers=headers)

    response = client.get(_labels_url(org["id"]), headers=headers)

    assert response.status_code == 200
    names = [label["name"] for label in response.json()]
    assert names == ["Alpha", "Zeta"]


def test_list_labels_paginates_with_limit_and_offset(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    for name in ["Alpha", "Bravo", "Charlie"]:
        client.post(_labels_url(org["id"]), json={"name": name}, headers=headers)

    response = client.get(_labels_url(org["id"], "?limit=2&offset=1"), headers=headers)

    assert response.status_code == 200
    names = [label["name"] for label in response.json()]
    assert names == ["Bravo", "Charlie"]


def test_admin_can_rename_and_recolor_label(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    label = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers).json()

    response = client.patch(
        _labels_url(org["id"], f"/{label['id']}"),
        json={"name": "Defect", "color": "#ff0000"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Defect"
    assert body["color"] == "#ff0000"


def test_rename_label_keeps_its_own_name_case_unchanged(client):
    """Renaming a label to the same name it already has (perhaps with a
    different color) must not reject itself as a case-insensitive duplicate.
    """
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    label = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers).json()

    response = client.patch(
        _labels_url(org["id"], f"/{label['id']}"),
        json={"name": "Bug", "color": "#00ff00"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["color"] == "#00ff00"


def test_rename_label_to_existing_name_rejected_case_insensitively(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers)
    feature = client.post(
        _labels_url(org["id"]), json={"name": "Feature"}, headers=headers
    ).json()

    response = client.patch(
        _labels_url(org["id"], f"/{feature['id']}"), json={"name": "bug"}, headers=headers
    )

    assert response.status_code == 409


def test_member_cannot_rename_label(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    label = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=owner_headers).json()

    response = client.patch(
        _labels_url(org["id"], f"/{label['id']}"),
        json={"name": "Defect"},
        headers=member_headers,
    )

    assert response.status_code == 403


def test_update_label_rejects_invalid_color(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    label = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers).json()

    response = client.patch(
        _labels_url(org["id"], f"/{label['id']}"),
        json={"color": "not-a-color"},
        headers=headers,
    )

    assert response.status_code == 422


def test_member_cannot_delete_label(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    client.post(
        f"/api/v1/organizations/{org['id']}/members",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    label = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=owner_headers).json()

    response = client.delete(_labels_url(org["id"], f"/{label['id']}"), headers=member_headers)

    assert response.status_code == 403


def test_admin_can_delete_label(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    label = client.post(_labels_url(org["id"]), json={"name": "Bug"}, headers=headers).json()

    response = client.delete(_labels_url(org["id"], f"/{label['id']}"), headers=headers)

    assert response.status_code == 204
    assert client.get(_labels_url(org["id"]), headers=headers).json() == []


def test_delete_label_not_found(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)

    response = client.delete(
        _labels_url(org["id"], "/00000000-0000-0000-0000-000000000000"), headers=headers
    )

    assert response.status_code == 404
