from importlib import import_module
from typing import Any

__all__ = [
    'engine',
    'SessionLocal',
    'get_db',
    'get_async_db',
    'init_db',
    'Project',
    'TodoBoard',
    'TodoStage',
    'ProjectVersion',
    'SlideData',
    'PPTTemplate',
    'migration_manager',
    'health_checker',
    'DatabaseService',
    'ProjectRepository',
    'TodoBoardRepository',
    'TodoStageRepository',
    'ProjectVersionRepository',
    'SlideDataRepository',
    'PPTTemplateRepository'
]


def __getattr__(name: str) -> Any:
    """
    Lazy attribute loader.

    Importing this package should not eagerly create DB engines (which can require optional drivers
    like psycopg2). Import the underlying submodules on demand instead.
    """
    if name in {"engine", "SessionLocal", "get_db", "get_async_db", "init_db"}:
        module = import_module(".database", __name__)
        return getattr(module, name)

    if name in {"Project", "TodoBoard", "TodoStage", "ProjectVersion", "SlideData", "PPTTemplate"}:
        module = import_module(".models", __name__)
        return getattr(module, name)

    if name == "migration_manager":
        module = import_module(".migrations", __name__)
        return getattr(module, name)

    if name == "health_checker":
        module = import_module(".health_check", __name__)
        return getattr(module, name)

    if name == "DatabaseService":
        module = import_module(".service", __name__)
        return getattr(module, name)

    if name in {
        "ProjectRepository",
        "TodoBoardRepository",
        "TodoStageRepository",
        "ProjectVersionRepository",
        "SlideDataRepository",
        "PPTTemplateRepository",
    }:
        module = import_module(".repositories", __name__)
        return getattr(module, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
