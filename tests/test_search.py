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


def _create_project(client, headers, org_id, name="Website Revamp", **extra):
    return client.post(
        f"/api/v1/organizations/{org_id}/projects",
        json={"name": name, **extra},
        headers=headers,
    ).json()


def _create_task(client, headers, org_id, project_id, title, description=None):
    payload = {"title": title}
    if description is not None:
        payload["description"] = description
    return client.post(
        f"/api/v1/organizations/{org_id}/projects/{project_id}/tasks",
        json=payload,
        headers=headers,
    ).json()


def _search(client, headers, org_id, query):
    return client.get(f"/api/v1/organizations/{org_id}/search?{query}", headers=headers)


def _setup(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project = _create_project(client, headers, org["id"])
    return headers, org, project


def test_search_finds_task_by_title(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Fix the login bug")
    _create_task(client, headers, org["id"], project["id"], "Write docs")

    response = _search(client, headers, org["id"], "q=login")

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "login"
    titles = [hit["task"]["title"] for hit in body["results"] if hit["kind"] == "task"]
    assert titles == ["Fix the login bug"]


def test_search_finds_task_by_description(client):
    headers, org, project = _setup(client)
    _create_task(
        client, headers, org["id"], project["id"], "Untitled", description="Refresh token expiry"
    )

    response = _search(client, headers, org["id"], "q=expiry")

    titles = [hit["task"]["title"] for hit in response.json()["results"]]
    assert titles == ["Untitled"]


def test_search_finds_project_by_name(client):
    headers, org, _project = _setup(client)

    response = _search(client, headers, org["id"], "q=Website")

    hits = [hit for hit in response.json()["results"] if hit["kind"] == "project"]
    assert [hit["project"]["name"] for hit in hits] == ["Website Revamp"]


def test_search_is_case_insensitive(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Fix the LOGIN bug")

    response = _search(client, headers, org["id"], "q=login")

    assert response.json()["total"] == 1


def test_search_requires_every_term_to_match(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Fix the login bug")
    _create_task(client, headers, org["id"], project["id"], "Login page redesign")

    response = _search(client, headers, org["id"], "q=login+bug")

    titles = [hit["task"]["title"] for hit in response.json()["results"]]
    assert titles == ["Fix the login bug"]


def test_search_matches_terms_across_title_and_description(client):
    headers, org, project = _setup(client)
    _create_task(
        client, headers, org["id"], project["id"], "Login page", description="Broken on Safari"
    )

    response = _search(client, headers, org["id"], "q=login+safari")

    assert response.json()["total"] == 1


def test_exact_title_match_ranks_above_partial(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Deployment checklist for login")
    _create_task(client, headers, org["id"], project["id"], "login")

    response = _search(client, headers, org["id"], "q=login")

    titles = [hit["task"]["title"] for hit in response.json()["results"]]
    assert titles[0] == "login"


def test_prefix_match_ranks_above_contains(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Fix the login form")
    _create_task(client, headers, org["id"], project["id"], "Login form rewrite")

    response = _search(client, headers, org["id"], "q=login")

    titles = [hit["task"]["title"] for hit in response.json()["results"]]
    assert titles == ["Login form rewrite", "Fix the login form"]


def test_title_match_ranks_above_description_match(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Housekeeping", description="login")
    _create_task(client, headers, org["id"], project["id"], "Repair login")

    response = _search(client, headers, org["id"], "q=login")

    titles = [hit["task"]["title"] for hit in response.json()["results"]]
    assert titles == ["Repair login", "Housekeeping"]


def test_search_scoped_to_organization(client):
    headers = _register_and_login(client)
    org_a = _create_org(client, headers, name="Org A")
    org_b = _create_org(client, headers, name="Org B")
    project_a = _create_project(client, headers, org_a["id"], name="Alpha")
    project_b = _create_project(client, headers, org_b["id"], name="Beta")
    _create_task(client, headers, org_a["id"], project_a["id"], "shared keyword")
    _create_task(client, headers, org_b["id"], project_b["id"], "shared keyword")

    response = _search(client, headers, org_a["id"], "q=shared")

    task_hits = [hit for hit in response.json()["results"] if hit["kind"] == "task"]
    assert len(task_hits) == 1
    assert task_hits[0]["task"]["project_id"] == project_a["id"]


def test_search_requires_membership(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    outsider_headers = _register_and_login(client, email="outsider@example.com")
    org = _create_org(client, owner_headers)

    response = _search(client, outsider_headers, org["id"], "q=anything")

    assert response.status_code == 404


def test_search_hides_restricted_projects_from_non_members(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    _add_org_member(client, owner_headers, org["id"], "member@example.com")
    secret = _create_project(
        client, owner_headers, org["id"], name="Secret Sauce", visibility="restricted"
    )
    _create_task(client, owner_headers, org["id"], secret["id"], "Secret task")

    response = _search(client, member_headers, org["id"], "q=secret")

    assert response.json()["results"] == []


def test_search_includes_restricted_project_for_its_members(client):
    owner_headers = _register_and_login(client, email="owner@example.com")
    member_headers = _register_and_login(client, email="member@example.com")
    org = _create_org(client, owner_headers)
    _add_org_member(client, owner_headers, org["id"], "member@example.com")
    secret = _create_project(
        client, owner_headers, org["id"], name="Secret Sauce", visibility="restricted"
    )
    _create_task(client, owner_headers, org["id"], secret["id"], "Secret task")
    client.post(
        f"/api/v1/organizations/{org['id']}/projects/{secret['id']}/members",
        json={"email": "member@example.com", "role": "viewer"},
        headers=owner_headers,
    )

    response = _search(client, member_headers, org["id"], "q=secret")

    kinds = sorted(hit["kind"] for hit in response.json()["results"])
    assert kinds == ["project", "task"]


def test_search_filter_by_kind(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Website audit")

    tasks_only = _search(client, headers, org["id"], "q=website&kind=task").json()
    projects_only = _search(client, headers, org["id"], "q=website&kind=project").json()

    assert {hit["kind"] for hit in tasks_only["results"]} == {"task"}
    assert {hit["kind"] for hit in projects_only["results"]} == {"project"}


def test_search_filter_by_project(client):
    headers = _register_and_login(client)
    org = _create_org(client, headers)
    project_a = _create_project(client, headers, org["id"], name="Alpha")
    project_b = _create_project(client, headers, org["id"], name="Beta")
    _create_task(client, headers, org["id"], project_a["id"], "shared keyword")
    _create_task(client, headers, org["id"], project_b["id"], "shared keyword")

    response = _search(client, headers, org["id"], f"q=shared&project_id={project_b['id']}")

    results = response.json()["results"]
    assert {hit["kind"] for hit in results} == {"task"}
    assert [hit["task"]["project_id"] for hit in results] == [project_b["id"]]


def test_search_respects_limit(client):
    headers, org, project = _setup(client)
    for index in range(5):
        _create_task(client, headers, org["id"], project["id"], f"widget {index}")

    response = _search(client, headers, org["id"], "q=widget&limit=2")

    assert len(response.json()["results"]) == 2


def test_search_requires_a_query(client):
    headers, org, _project = _setup(client)

    assert _search(client, headers, org["id"], "q=").status_code == 422
    assert (
        client.get(f"/api/v1/organizations/{org['id']}/search", headers=headers).status_code == 422
    )


def test_blank_query_returns_no_results(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Something")

    response = _search(client, headers, org["id"], "q=+++")

    assert response.json()["results"] == []


def test_wildcard_characters_are_treated_literally(client):
    """A bare % must not match everything the way a raw LIKE pattern would."""
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Ordinary task")
    _create_task(client, headers, org["id"], project["id"], "100% coverage")

    response = _search(client, headers, org["id"], "q=%25")

    titles = [hit["task"]["title"] for hit in response.json()["results"]]
    assert titles == ["100% coverage"]


def test_underscore_is_treated_literally(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "snake_case rename")
    _create_task(client, headers, org["id"], project["id"], "camelCase rename")

    response = _search(client, headers, org["id"], "q=snake_case")

    titles = [hit["task"]["title"] for hit in response.json()["results"]]
    assert titles == ["snake_case rename"]


def test_search_returns_no_results_for_unknown_term(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Ordinary task")

    response = _search(client, headers, org["id"], "q=zzzznotfound")

    assert response.json() == {"query": "zzzznotfound", "total": 0, "results": []}


def test_the_total_counts_the_hits_that_were_returned(client):
    """The count beside a result set has to describe that result set.

    Each half of the search is capped at `limit` by its own query, so the
    merged list can be twice as long as the page that comes back. Reporting
    the pre-cut length as the total told a caller there were two matches while
    handing them one — and search is capped rather than paginated, so there is
    no offset that would ever reach the other.
    """
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Website copy")

    response = _search(client, headers, org["id"], "q=website&limit=1")

    body = response.json()
    assert len(body["results"]) == 1
    assert body["total"] == 1


def test_the_total_still_counts_both_kinds_together(client):
    headers, org, project = _setup(client)
    _create_task(client, headers, org["id"], project["id"], "Website copy")

    body = _search(client, headers, org["id"], "q=website").json()

    assert {hit["kind"] for hit in body["results"]} == {"project", "task"}
    assert body["total"] == 2
