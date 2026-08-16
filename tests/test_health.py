def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_response_includes_generated_request_id(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers["x-request-id"]


def test_response_reuses_inbound_request_id(client):
    response = client.get("/api/v1/health", headers={"X-Request-ID": "test-request-id"})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-id"
