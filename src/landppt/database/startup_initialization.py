"""
One-time application startup initialization for multi-worker deployments.

Why:
- Uvicorn/Gunicorn workers each run FastAPI startup handlers.
- Database init, migrations, and default-template bootstrap should run once per app startup,
  not once per worker.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from contextlib import contextmanager
from typing import Iterator

from ..core.config import app_config
from .create_default_template import ensure_default_templates_exist
from .database import init_db
from .startup_migrations import run_startup_migrations

logger = logging.getLogger(__name__)
_PROCESS_START_TS = time.time()


def _startup_lock_settings() -> tuple[int, int]:
    timeout_seconds = int(getattr(app_config, "auto_migrate_lock_timeout_seconds", 300) or 300)
    stale_seconds = int(getattr(app_config, "auto_migrate_lock_stale_seconds", 900) or 900)
    return timeout_seconds, stale_seconds


def _startup_done_for_current_process(done_path: str) -> bool:
    try:
        return os.path.getmtime(done_path) >= (_PROCESS_START_TS - 1.0)
    except OSError:
        return False


@contextmanager
def _startup_owner_gate(
    lock_path: str,
    *,
    done_path: str,
    timeout_seconds: int,
    stale_seconds: int,
) -> Iterator[bool]:
    """
    Yield True only for the worker that should run one-time startup tasks.

    Other workers wait for the current owner to finish and then skip the one-time work.
    """
    lock_path = os.path.abspath(lock_path)
    done_path = os.path.abspath(done_path)

    if _startup_done_for_current_process(done_path):
        yield False
        return

    deadline = time.time() + max(1, int(timeout_seconds))
    owner = False

    while True:
        if _startup_done_for_current_process(done_path):
            yield False
            return

        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()} {time.time()}\n".encode("utf-8", errors="ignore"))
            finally:
                os.close(fd)
            owner = True
            break
        except FileExistsError:
            try:
                st = os.stat(lock_path)
                if (time.time() - st.st_mtime) > max(30, int(stale_seconds)):
                    try:
                        os.unlink(lock_path)
                        continue
                    except OSError:
                        pass
            except OSError:
                pass

            if time.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for startup initialization lock: {lock_path}")
            time.sleep(0.5)

    try:
        if _startup_done_for_current_process(done_path):
            yield False
            return

        yield True

        try:
            with open(done_path, "w", encoding="utf-8") as f:
                f.write(f"{os.getpid()} {time.time()}\n")
        except OSError:
            logger.warning("Startup initialization: failed to write done marker", exc_info=True)
    finally:
        if owner:
            try:
                os.unlink(lock_path)
            except OSError:
                pass


async def run_startup_initialization() -> bool:
    """Run one-time startup initialization exactly once across local workers."""
    timeout_seconds, stale_seconds = _startup_lock_settings()
    temp_dir = tempfile.gettempdir()
    lock_path = os.path.join(temp_dir, "landppt_startup_init.lock")
    done_path = os.path.join(temp_dir, "landppt_startup_init.done")

    with _startup_owner_gate(
        lock_path,
        done_path=done_path,
        timeout_seconds=timeout_seconds,
        stale_seconds=stale_seconds,
    ) as is_owner:
        if not is_owner:
            logger.info("Startup initialization: another worker already completed one-time startup tasks")
            return False

        logger.info(
            "Startup initialization: initializing database (configured=%s)",
            getattr(app_config, "database_url", ""),
        )
        await init_db()
        logger.info("Startup initialization: database initialized successfully")

        await run_startup_migrations()

        template_ids = await ensure_default_templates_exist()
        logger.info(
            "Startup initialization: template bootstrap completed, available=%s",
            len(template_ids or []),
        )
        return True
