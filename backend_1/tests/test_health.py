from fastapi.testclient import TestClient

from cicero.api.app import create_app


def test_root_returns_service_metadata() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "cicero-api"
    assert body["status"] == "ok"
    assert body["health"] == "/health"
    assert "version" in body


def test_health_is_a_liveness_check() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_documentation_is_available() -> None:
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
