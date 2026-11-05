from fastapi import Request
from fastapi.testclient import TestClient

from cicero.api.app import create_app
from cicero.api.dependencies import get_model_gateway


def test_root_returns_service_metadata() -> None:
    response = TestClient(create_app()).get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "cicero-api"


def test_health_returns_ok() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_is_available() -> None:
    response = TestClient(create_app()).get("/openapi.json")
    assert response.status_code == 200


def test_gateway_is_attached_to_application_state() -> None:
    app = create_app()
    TestClient(app)
    request = Request({"type": "http", "app": app, "headers": [], "query_string": b""})
    assert get_model_gateway(request) is app.state.model_gateway
