import asyncio
from types import SimpleNamespace


def test_get_system_config_will_initialize_system_defaults(monkeypatch):
    import landppt.api.config_api as config_api

    calls = {
        "initialized": False,
        "get_all_config_called": False,
    }

    class FakeConfigService:
        async def initialize_system_defaults(self):
            calls["initialized"] = True
            return 3

        async def get_all_config(self, user_id=None):
            calls["get_all_config_called"] = True
            assert calls["initialized"] is True
            assert user_id is None
            return {
                "default_ai_provider": "landppt",
                "landppt_model": "MODEL1",
            }

    monkeypatch.setattr(config_api, "get_db_config_service", lambda: FakeConfigService(), raising=True)

    result = asyncio.run(config_api.get_system_config(user=SimpleNamespace(is_admin=True)))

    assert calls["initialized"] is True
    assert calls["get_all_config_called"] is True
    assert result["success"] is True
    assert result["config"]["default_ai_provider"] == "landppt"
    assert result["config"]["landppt_model"] == "MODEL1"
