from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from cicero.db.models.cases import Case, CaseMember, CaseParty
from cicero.db.repositories import CaseRepository


def _session_with_result(result: object) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_case_lookup_requires_organization_scope() -> None:
    case_id, organization_id = uuid4(), uuid4()
    result = SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))
    session = _session_with_result(result)

    assert await CaseRepository(session).get_by_id(
        case_id, organization_id=organization_id
    ) is None

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "cases.cases.case_id" in sql
    assert "cases.cases.organization_id" in sql
    assert case_id in compiled.params.values()
    assert organization_id in compiled.params.values()


@pytest.mark.asyncio
async def test_case_list_is_scoped_and_can_filter_status() -> None:
    organization_id = uuid4()
    result = SimpleNamespace(
        scalars=MagicMock(return_value=SimpleNamespace(all=MagicMock(return_value=[])))
    )
    session = _session_with_result(result)

    assert await CaseRepository(session).list_for_organization(
        organization_id, status="active"
    ) == []

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "cases.cases.organization_id" in str(compiled)
    assert "cases.cases.status" in str(compiled)
    assert organization_id in compiled.params.values()
    assert "active" in compiled.params.values()


@pytest.mark.asyncio
async def test_case_member_lookup_uses_case_organization_and_user() -> None:
    case_id, organization_id, user_id = uuid4(), uuid4(), uuid4()
    result = SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))
    session = _session_with_result(result)

    await CaseRepository(session).get_member(case_id, organization_id, user_id)

    compiled = session.execute.await_args.args[0].compile(
        dialect=postgresql.dialect()
    )
    assert all(
        value in compiled.params.values()
        for value in (case_id, organization_id, user_id)
    )


def test_add_case_member_stages_without_commit() -> None:
    session = MagicMock()
    case_id, organization_id, user_id = uuid4(), uuid4(), uuid4()

    member = CaseRepository(session).add_member(
        case_id, organization_id, user_id, role="editor"
    )

    assert isinstance(member, CaseMember)
    assert member.case_id == case_id
    assert member.organization_id == organization_id
    assert member.user_id == user_id
    assert member.role == "editor"
    session.add.assert_called_once_with(member)
    session.commit.assert_not_called()


def test_add_party_stages_party_without_commit() -> None:
    session = MagicMock()
    case_id = uuid4()

    party = CaseRepository(session).add_party(
        case_id,
        party_name="Acme Ltd",
        party_type="company",
        party_position="claimant",
    )

    assert isinstance(party, CaseParty)
    assert party.case_id == case_id
    assert party.party_name == "Acme Ltd"
    session.add.assert_called_once_with(party)
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_delete_party_returns_false_when_scoped_party_missing() -> None:
    result = SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))
    session = _session_with_result(result)

    deleted = await CaseRepository(session).delete_party(
        uuid4(), uuid4(), uuid4()
    )

    assert deleted is False
    session.delete.assert_not_called()
    session.commit.assert_not_called()


def test_repository_is_bound_to_case_model() -> None:
    assert CaseRepository(AsyncMock()).model is Case
