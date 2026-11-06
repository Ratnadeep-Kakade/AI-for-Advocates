from __future__ import annotations

from typing import Any

from google.cloud.sql.connector import IPTypes, create_async_connector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cicero.auth.google_credentials import (
    GoogleCredentialsConfigurationError,
    GoogleCredentialsProvider,
)
from cicero.core.config import Settings


class DatabaseConfigurationError(RuntimeError):
    """Raised when Cloud SQL settings are incomplete or invalid."""


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when database access is requested but Cloud SQL is not configured."""


class DatabaseManager:
    """Owns the async Cloud SQL Connector, SQLAlchemy engine and session factory.

    The Connector is created during FastAPI's running event loop. SQLAlchemy owns
    connection pooling; the Cloud SQL Connector creates each underlying asyncpg
    connection with its managed TLS configuration.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.connector: Any | None = None
        self.engine: AsyncEngine | None = None
        self.session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def is_configured(self) -> bool:
        return self._settings.database_configured

    @property
    def is_started(self) -> bool:
        return self.engine is not None

    def _load_google_credentials(self) -> Any | None:
        """Load the shared Modal WIF credentials or local Application Default Credentials."""
        try:
            return GoogleCredentialsProvider(self._settings).load()
        except GoogleCredentialsConfigurationError as exc:
            # Keep the database-specific exception contract for existing callers.
            raise DatabaseConfigurationError(str(exc)) from exc

    async def start(self) -> None:
        if self._settings.database_partially_configured:
            raise DatabaseConfigurationError(
                "Cloud SQL configuration is incomplete. Set instance connection name, "
                "database name, database user and database password."
            )

        if not self.is_configured:
            return

        credentials = self._load_google_credentials()

        ip_type = {
            "public": IPTypes.PUBLIC,
            "private": IPTypes.PRIVATE,
            "psc": IPTypes.PSC,
        }[self._settings.database_ip_type]

        self.connector = await create_async_connector(
            ip_type=ip_type,
            refresh_strategy=self._settings.database_refresh_strategy,
            credentials=credentials,
        )

        async def connect() -> Any:
            assert self.connector is not None
            return await self.connector.connect_async(
                self._settings.database_instance_connection_name,
                "asyncpg",
                user=self._settings.database_user,
                password=self._settings.database_password.get_secret_value(),
                db=self._settings.database_name,
            )

        try:
            self.engine = create_async_engine(
                "postgresql+asyncpg://",
                async_creator=connect,
                pool_size=self._settings.database_pool_size,
                max_overflow=self._settings.database_max_overflow,
                pool_timeout=self._settings.database_pool_timeout_seconds,
                pool_recycle=self._settings.database_pool_recycle_seconds,
                pool_pre_ping=True,
            )
            self.session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        except Exception:
            await self.close()
            raise

    async def ping(self) -> bool:
        if self.engine is None:
            raise DatabaseNotConfiguredError("Cloud SQL is not configured or has not started.")
        async with self.engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            return result.scalar_one() == 1

    async def diagnostics(self) -> dict[str, str]:
        """Return connection diagnostics for an authenticated developer smoke test."""
        if self.engine is None:
            raise DatabaseNotConfiguredError("Cloud SQL is not configured or has not started.")
        query = text(
            "SELECT current_database() AS database_name, "
            "current_user AS database_user, version() AS server_version"
        )
        async with self.engine.connect() as connection:
            row = (await connection.execute(query)).mappings().one()
            return {
                "database_name": str(row["database_name"]),
                "database_user": str(row["database_user"]),
                "server_version": str(row["server_version"]),
            }

    async def close(self) -> None:
        try:
            if self.engine is not None:
                await self.engine.dispose()
        finally:
            self.engine = None
            self.session_factory = None
            if self.connector is not None:
                await self.connector.close_async()
                self.connector = None
