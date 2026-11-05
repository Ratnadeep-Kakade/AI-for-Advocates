from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from cicero.db.models.auth import Organization, OrganizationMember, User
from cicero.db.repositories import OrganizationRepository, UserRepository


def _session_with_result(result: object) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_user_repository_looks_up_firebase_uid() -> None:
    expected = User(firebase_uid="firebase-123", name="A", email="a@example.com")
    result = SimpleNamespace(scalar_one_or_none=MagicMock(return_value=expected))
    session = _session_with_result(result)

    actual = await UserRepository(session).get_by_firebase_uid("firebase-123")

    assert actual is expected
    statement = session.execute.await_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "auth.users.firebase_uid" in compiled


@pytest.mark.asyncio
async def test_user_repository_normalizes_email_lookup() -> None:
    result = SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))
    session = _session_with_result(result)

    await UserRepository(session).get_by_email("  PERSON@Example.COM ")

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "lower(auth.users.email)" in str(compiled)
    assert "person@example.com" in compiled.params.values()


@pytest.mark.asyncio
async def test_organization_repository_lists_only_user_memberships() -> None:
    result = SimpleNamespace(
        scalars=MagicMock(return_value=SimpleNamespace(all=MagicMock(return_value=[])))
    )
    session = _session_with_result(result)
    user_id = uuid4()

    assert await OrganizationRepository(session).list_for_user(user_id) == []

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "auth.organization_members.user_id" in str(compiled)
    assert user_id in compiled.params.values()


def test_add_member_stages_membership_without_committing() -> None:
    session = MagicMock()
    session.execute = AsyncMock()
    organization_id, user_id = uuid4(), uuid4()

    membership = OrganizationRepository(session).add_member(organization_id, user_id, role="lawyer")

    assert isinstance(membership, OrganizationMember)
    assert membership.organization_id == organization_id
    assert membership.user_id == user_id
    assert membership.role == "lawyer"
    session.add.assert_called_once_with(membership)
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_remove_member_returns_false_when_membership_missing() -> None:
    result = SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))
    session = _session_with_result(result)

    removed = await OrganizationRepository(session).remove_member(uuid4(), uuid4())

    assert removed is False
    session.delete.assert_not_called()
    session.commit.assert_not_called()


def test_repository_models_are_expected_tables() -> None:
    assert UserRepository(AsyncMock()).model is User
    assert OrganizationRepository(AsyncMock()).model is Organization
