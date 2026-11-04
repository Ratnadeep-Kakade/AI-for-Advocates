from fastapi.testclient import TestClient

from cicero.api.app import create_app
from cicero.config import Settings


def test_database_health_reports_not_configured_without_cloud_sql_settings() -> None:
    app = create_app(settings=Settings(_env_file=None))
    response = TestClient(app).get("/health/database")
    assert response.status_code == 503
    assert response.json()["status"] == "not_configured"
