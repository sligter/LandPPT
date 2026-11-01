"""Upgrade old API-key schemas without invalidating existing salted hashes."""

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from landppt.auth.auth_service import AuthService
from landppt.database.migrations import DatabaseMigration
from landppt.database.models import User, UserAPIKey


@pytest_asyncio.fixture(params=["sqlite", "postgresql"])
async def migration_engine(request):
    admin = None
    schema = "landppt_api_key_test_" + uuid4().hex
    if request.param == "postgresql":
        url = os.environ.get("LANDPPT_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("Set LANDPPT_TEST_POSTGRES_URL for PostgreSQL upgrade coverage")
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(CreateSchema(schema))
        engine = create_async_engine(
            url, connect_args={"server_settings": {"search_path": schema}}
        )
    else:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        yield engine
    finally:
        await engine.dispose()
        if admin:
            async with admin.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
            await admin.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_api_key_migration_preserves_legacy_rows_and_enforces_uniqueness(
    migration_engine, legacy, monkeypatch
):
    from landppt.core.config import app_config

    monkeypatch.setattr(app_config, "api_key", None)
    monkeypatch.setattr(app_config, "api_keys", None)
    engine = migration_engine
    key = "test-migration-key-00000001"
    salted_hash = AuthService.hash_api_key(key, "legacy-salt")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(User.__table__.create)
            if legacy:
                await conn.execute(
                    text(
                        """
                    CREATE TABLE user_api_keys (
                        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                        name VARCHAR(100) NOT NULL, key_prefix VARCHAR(24) NOT NULL,
                        key_hash VARCHAR(128) NOT NULL UNIQUE, salt VARCHAR(64) NOT NULL,
                        is_active BOOLEAN, created_at FLOAT, last_used_at FLOAT, expires_at FLOAT
                    )
                """
                    )
                )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            user = User(
                username="migration-user", password_hash="unused", is_active=True
            )
            session.add(user)
            await session.commit()
            if legacy:
                await session.execute(
                    text(
                        """
                    INSERT INTO user_api_keys (id, user_id, name, key_prefix, key_hash, salt, is_active)
                    VALUES (1, :user_id, 'legacy', :prefix, :hash, 'legacy-salt', TRUE)
                """
                    ),
                    {"user_id": user.id, "prefix": key[:12], "hash": salted_hash},
                )
                await session.commit()
            migrations = DatabaseMigration()
            assert migrations.migrations[-1]["version"] == "022"
            await migrations._migration_022_up(session)
            await session.commit()
            await migrations._migration_022_up(session)
            await session.commit()
            conn = await session.connection()
            indexes = await conn.run_sync(
                lambda sync: inspect(sync).get_indexes("user_api_keys")
            )
            assert any(
                i["unique"] and i["column_names"] == ["key_fingerprint"]
                for i in indexes
            )
            if legacy:
                saved = await session.scalar(select(UserAPIKey))
                assert saved.key_hash == salted_hash
                assert saved.key_fingerprint is None
                resolved = await session.run_sync(
                    lambda sync: AuthService().get_user_by_api_key(sync, key)
                )
                assert resolved.id == user.id
                assert saved.key_fingerprint == AuthService.fingerprint_api_key(key)
            else:
                session.add(
                    UserAPIKey(
                        id=1,
                        user_id=user.id,
                        name="first",
                        key_prefix=key[:12],
                        key_hash=salted_hash,
                        salt="legacy-salt",
                        key_fingerprint=AuthService.fingerprint_api_key(key),
                    )
                )
                await session.commit()
            session.add(
                UserAPIKey(
                    id=2,
                    user_id=user.id,
                    name="duplicate",
                    key_prefix=key[:12],
                    key_hash=AuthService.hash_api_key(key, "different-salt"),
                    salt="different-salt",
                    key_fingerprint=AuthService.fingerprint_api_key(key),
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()
            assert (
                await session.scalars(select(UserAPIKey))
            ).one().key_hash == salted_hash
    finally:
        await engine.dispose()
