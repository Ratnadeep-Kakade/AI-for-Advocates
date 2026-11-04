import pytest
from pydantic import SecretStr

from cicero.config import Settings
from cicero.db.connection import DatabaseConfigurationError, DatabaseManager


def test_database_is_not_configured_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.database_configured is False
    assert settings.database_partially_configured is False


def test_database_configured_when_all_required_values_exist() -> None:
    settings = Settings(
        _env_file=None,
        database_instance_connection_name="project:region:instance",
        database_name="cicero",
        database_user="cicero_app",
        database_password=SecretStr("not-a-real-password"),
    )
    assert settings.database_configured is True
    assert settings.database_partially_configured is False


def test_partial_database_configuration_is_detected() -> None:
    settings = Settings(
        _env_file=None,
        database_instance_connection_name="project:region:instance",
    )
    assert settings.database_configured is False
    assert settings.database_partially_configured is True


@pytest.mark.asyncio
async def test_partial_configuration_fails_fast() -> None:
    settings = Settings(
        _env_file=None,
        database_instance_connection_name="project:region:instance",
    )
    manager = DatabaseManager(settings)
    with pytest.raises(DatabaseConfigurationError, match="configuration is incomplete"):
        await manager.start()
