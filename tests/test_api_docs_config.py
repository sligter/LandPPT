import importlib
import sys


def _reload_main_module(monkeypatch, enabled: bool):
    from landppt.core.config import app_config

    monkeypatch.setattr(app_config, "enable_api_docs", enabled)
    sys.modules.pop("landppt.main", None)
    return importlib.import_module("landppt.main")


def test_main_app_enables_api_docs_by_default(monkeypatch):
    pytest = __import__("pytest")
    pytest.importorskip("fastapi")

    module = _reload_main_module(monkeypatch, True)

    assert module.app.docs_url == "/docs"
    assert module.app.redoc_url == "/redoc"
    assert module.app.openapi_url == "/openapi.json"


def test_main_app_can_disable_api_docs(monkeypatch):
    pytest = __import__("pytest")
    pytest.importorskip("fastapi")

    module = _reload_main_module(monkeypatch, False)

    assert module.app.docs_url is None
    assert module.app.redoc_url is None
    assert module.app.openapi_url is None
