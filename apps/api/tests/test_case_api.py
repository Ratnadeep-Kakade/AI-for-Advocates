from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from cicero_api.main import create_app
from cicero_api.schemas import CaseCreate
from cicero.config import Settings
from cicero.db.repositories.case import CaseRepository


def test_case_routes_are_registered() -> None:
    app = create_app(settings=Settings(_env_file=None))
    paths = set(app.openapi()["paths"].keys())
    assert "/api/cases" in paths
    assert "/api/cases/{case_id}" in paths


def test_demo_case_api_fails_closed_when_demo_mode_is_disabled() -> None:
    app = create_app(settings=Settings(_env_file=None))
    response = TestClient(app).get("/api/cases")
    assert response.status_code == 503
    assert "Demo API is disabled" in response.json()["detail"]


def test_demo_identity_requires_both_ids() -> None:
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        demo_user_id=uuid4(),
    )
    assert settings.demo_identity_configured is False


def test_demo_identity_is_enabled_only_with_explicit_configuration() -> None:
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        demo_user_id=uuid4(),
        demo_organization_id=uuid4(),
    )
    assert settings.demo_identity_configured is True


@pytest.mark.asyncio
async def test_user_case_list_query_is_scoped_to_org_and_case_membership() -> None:
    organization_id, user_id = uuid4(), uuid4()
    result = SimpleNamespace(
        scalars=MagicMock(return_value=SimpleNamespace(all=MagicMock(return_value=[])))
    )
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    cases = await CaseRepository(session).list_for_user_in_organization(
        organization_id, user_id
    )

    assert cases == []
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "cases.case_members.user_id" in str(compiled)
    assert "cases.cases.organization_id" in str(compiled)
    assert organization_id in compiled.params.values()
    assert user_id in compiled.params.values()


def test_case_create_rejects_whitespace_only_name() -> None:
    with pytest.raises(ValidationError):
        CaseCreate(case_name="   ")


def test_demo_identity_is_never_enabled_in_production() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        demo_mode=True,
        demo_user_id=uuid4(),
        demo_organization_id=uuid4(),
    )
    assert settings.demo_identity_configured is False
