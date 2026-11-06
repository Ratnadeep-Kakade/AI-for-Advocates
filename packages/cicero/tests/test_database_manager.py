import os

import pytest
from pydantic import SecretStr

from cicero.auth import google_credentials
from cicero.config import Settings
from cicero.persistence import database as db_connection
from cicero.persistence.database import DatabaseConfigurationError


class FakeConnector:
    def __init__(self) -> None:
        self.connect_args = None
        self.closed = False

    async def connect_async(self, *args, **kwargs):
        self.connect_args = (args, kwargs)
        return object()

    async def close_async(self) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


async def test_manager_builds_async_engine_and_closes_resources(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_instance_connection_name="project:region:instance",
        database_name="cicero",
        database_user="cicero_app",
        database_password=SecretStr("not-a-real-password"),
    )
    connector = FakeConnector()
    engine = FakeEngine()
    captured = {}

    async def fake_create_connector(**kwargs):
        captured["connector_kwargs"] = kwargs
        return connector

    def fake_create_engine(url, **kwargs):
        captured["engine_url"] = url
        captured["engine_kwargs"] = kwargs
        return engine

    monkeypatch.setattr(db_connection, "create_async_connector", fake_create_connector)
    monkeypatch.setattr(db_connection, "create_async_engine", fake_create_engine)
    monkeypatch.setattr(db_connection, "async_sessionmaker", lambda **kwargs: object())

    manager = db_connection.DatabaseManager(settings)
    await manager.start()

    assert manager.is_started
    assert captured["engine_url"] == "postgresql+asyncpg://"
    assert captured["engine_kwargs"]["pool_size"] == settings.database_pool_size

    await captured["engine_kwargs"]["async_creator"]()
    args, kwargs = connector.connect_args
    assert args == ("project:region:instance", "asyncpg")
    assert kwargs["user"] == "cicero_app"
    assert kwargs["password"] == "not-a-real-password"
    assert kwargs["db"] == "cicero"

    await manager.close()
    assert engine.disposed is True
    assert connector.closed is True
    assert manager.is_started is False


def test_modal_wif_credentials_use_modal_oidc_executable(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_wif_project_number="116460390489",
        database_wif_pool_id="cicero-modal-pool",
        database_wif_provider_id="modal-oidc",
        database_wif_service_account_email=(
            "cicero-backend@project-d05a24bb-cf47-4351-b6e.iam.gserviceaccount.com"
        ),
    )
    monkeypatch.setenv("MODAL_IDENTITY_TOKEN", "header.payload.signature")
    captured = {}
    sentinel_credentials = object()

    def fake_load_credentials_from_dict(info, scopes):
        captured["info"] = info
        captured["scopes"] = scopes
        return sentinel_credentials, None

    monkeypatch.setattr(
        google_credentials.google.auth,
        "load_credentials_from_dict",
        fake_load_credentials_from_dict,
    )

    manager = db_connection.DatabaseManager(settings)
    credentials = manager._load_google_credentials()

    assert credentials is sentinel_credentials
    assert captured["info"]["audience"] == (
        "//iam.googleapis.com/projects/116460390489/locations/global/"
        "workloadIdentityPools/cicero-modal-pool/providers/modal-oidc"
    )
    assert captured["info"]["subject_token_type"] == "urn:ietf:params:oauth:token-type:id_token"
    assert captured["info"]["service_account_impersonation_url"] == (
        "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
        "cicero-backend@project-d05a24bb-cf47-4351-b6e.iam.gserviceaccount.com:generateAccessToken"
    )
    assert captured["info"]["credential_source"]["executable"]["command"] == (
        "python -m cicero.auth.modal_oidc_token"
    )
    assert captured["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
    assert os.environ["GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES"] == "1"


def test_modal_wif_requires_all_federation_settings(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    monkeypatch.setenv("MODAL_IDENTITY_TOKEN", "header.payload.signature")
    manager = db_connection.DatabaseManager(settings)

    with pytest.raises(DatabaseConfigurationError, match="settings are incomplete"):
        manager._load_google_credentials()
