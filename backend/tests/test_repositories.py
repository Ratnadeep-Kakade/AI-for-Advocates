from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.sql import Select

from cicero.db.models import User
from cicero.db.repositories import BaseRepository


@pytest.mark.asyncio
async def test_get_by_id_executes_primary_key_query() -> None:
    user_id = uuid4()
    expected_user = User(
        user_id=user_id,
        firebase_uid="firebase-123",
        name="Test User",
        email="test@example.com",
    )
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected_user
    session.execute = AsyncMock(return_value=result)

    repository = BaseRepository(session, User, "user_id")
    actual_user = await repository.get_by_id(user_id)

    assert actual_user is expected_user
    statement = session.execute.await_args.args[0]
    assert isinstance(statement, Select)
    assert "auth.users" in str(statement)
    assert str(user_id) in str(statement.compile().params.values())


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=result)

    repository = BaseRepository(session, User, "user_id")
    assert await repository.get_by_id(uuid4()) is None


def test_repository_rejects_unknown_identifier_attribute() -> None:
    with pytest.raises(ValueError, match="no mapped identifier attribute"):
        BaseRepository(MagicMock(), User, "not_a_column")


@pytest.mark.asyncio
async def test_add_stages_entity_without_committing() -> None:
    session = MagicMock()
    user = User(
        firebase_uid="firebase-456",
        name="Another User",
        email="another@example.com",
    )
    repository = BaseRepository(session, User, "user_id")

    assert repository.add(user) is user
    session.add.assert_called_once_with(user)
    session.commit.assert_not_called()
