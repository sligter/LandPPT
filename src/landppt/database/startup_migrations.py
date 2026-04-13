"""
Startup migration runner.

Why:
- LandPPT uses a lightweight custom migration system in `landppt.database.migrations`.
- `init_db()` creates tables but won't evolve existing schemas (except a few ad-hoc columns).
- Running `migration_manager.migrate_up()` at startup keeps schema consistent without manual steps.

Safety:
- Protected by a filesystem lock to prevent multiple workers in the same container/process group
  from racing migrations on startup.
- For multi-node deployments sharing one DB, you may want to disable auto-migrate and run a
  single dedicated migration job instead.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from contextlib import contextmanager
from typing import Iterator

from ..core.config import app_config

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _get_startup_migration_settings() -> dict[str, int | bool]:
    return {
        "enabled": bool(
            getattr(
                app_config,
                "auto_migrate_on_startup",
                _env_bool("LANDPPT_AUTO_MIGRATE_ON_STARTUP", True),
            )
        ),
        "fail_fast": bool(
            getattr(
                app_config,
                "auto_migrate_fail_fast",
                _env_bool("LANDPPT_AUTO_MIGRATE_FAIL_FAST", True),
            )
        ),
        "lock_timeout": int(
            getattr(
                app_config,
                "auto_migrate_lock_timeout_seconds",
                _env_int("LANDPPT_AUTO_MIGRATE_LOCK_TIMEOUT_SECONDS", 300),
            )
            or 300
        ),
        "lock_stale": int(
            getattr(
                app_config,
                "auto_migrate_lock_stale_seconds",
                _env_int("LANDPPT_AUTO_MIGRATE_LOCK_STALE_SECONDS", 900),
            )
            or 900
        ),
    }


def _get_migration_manager():
    from .migrations import migration_manager

    return migration_manager


@contextmanager
def _file_lock(path: str, *, timeout_seconds: int = 300, stale_seconds: int = 900) -> Iterator[None]:
    """
    Cross-platform best-effort file lock using O_EXCL.

    Note: this coordinates only processes that share the same filesystem.
    """
    deadline = time.time() + max(1, int(timeout_seconds))
    path = os.path.abspath(path)

    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()} {time.time()}\n".encode("utf-8", errors="ignore"))
            finally:
                os.close(fd)
            break
        except FileExistsError:
            # Stale lock detection
            try:
                st = os.stat(path)
                if (time.time() - st.st_mtime) > max(30, int(stale_seconds)):
                    try:
                        os.unlink(path)
                        continue
                    except Exception:
                        pass
            except Exception:
                pass

            if time.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for migration lock: {path}")
            time.sleep(0.5)

    try:
        yield
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


async def run_startup_migrations() -> bool:
    """
    Run pending migrations on startup if enabled.

    Env:
    - LANDPPT_AUTO_MIGRATE_ON_STARTUP (default: true)
    - LANDPPT_AUTO_MIGRATE_FAIL_FAST (default: true)
    - LANDPPT_AUTO_MIGRATE_LOCK_TIMEOUT_SECONDS (default: 300)
    - LANDPPT_AUTO_MIGRATE_LOCK_STALE_SECONDS (default: 900)
    """
    settings = _get_startup_migration_settings()
    enabled = bool(settings["enabled"])
    if not enabled:
        logger.info("Startup migrations: disabled by LANDPPT_AUTO_MIGRATE_ON_STARTUP")
        return False

    fail_fast = bool(settings["fail_fast"])
    lock_timeout = int(settings["lock_timeout"])
    lock_stale = int(settings["lock_stale"])

    lock_path = os.path.join(tempfile.gettempdir(), "landppt_migration.lock")
    try:
        with _file_lock(lock_path, timeout_seconds=lock_timeout, stale_seconds=lock_stale):
            migration_manager = _get_migration_manager()
            status = await migration_manager.get_migration_status()
            pending = status.get("pending_migrations") or []
            if not pending:
                logger.info("Startup migrations: no pending migrations")
                return True

            logger.info(f"Startup migrations: pending={pending}, running migrate_up()")
            ok = await migration_manager.migrate_up()
            if ok:
                logger.info("Startup migrations: completed")
            else:
                logger.error("Startup migrations: migrate_up() returned False")
                if fail_fast:
                    raise RuntimeError("Startup migrations failed (migrate_up returned False)")
            return bool(ok)
    except Exception as e:
        logger.error(f"Startup migrations: failed: {e}")
        if fail_fast:
            raise
        return False
