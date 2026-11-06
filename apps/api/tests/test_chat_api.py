from uuid import uuid4
from fastapi.testclient import TestClient
from cicero_api.main import create_app
from cicero.core.config import Settings


def test_chat_stream_without_case():
    settings = Settings(
        app_name="cicero-test",
        environment="development",
        demo_user_id=uuid4(),
        demo_organization_id=uuid4(),
        database_instance_connection_name=None,
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.post(
        "/api/chat/stream",
        json={"prompt": "What is Section 138 of the Negotiable Instruments Act?"},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    assert "data: " in response.text
    assert '"type": "token"' in response.text
    assert '"type": "done"' in response.text
