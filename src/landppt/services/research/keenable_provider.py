"""
Keenable Search provider for research functionality.

Opt-in: only used when RESEARCH_PROVIDER=keenable. An API key is optional.
Keyless calls use the public endpoint and send X-Keenable-Title.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from ...core.config import ai_config

logger = logging.getLogger(__name__)

PUBLIC_SEARCH_URL = "https://api.keenable.ai/v1/search/public"
KEYED_SEARCH_URL = "https://api.keenable.ai/v1/search"
APP_TITLE = "LandPPT"
_MASKED_KEYS = {"********", "••••••••", "***"}


class KeenableSearchError(RuntimeError):
    """Keenable could not complete a research search."""


class KeenableContentProvider:
    """Keenable content search provider for research functionality."""

    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id

    async def _load_user_config(self) -> Dict[str, Any]:
        """Saved settings for this scope: the user's values over the system values.

        A system-scope caller reads the defaults saved by an admin.
        """
        try:
            from ..db_config_service import get_db_config_service

            db_config_service = get_db_config_service()
            return await db_config_service.get_all_config(user_id=self.user_id) or {}
        except Exception as e:
            logger.warning("Failed to load Keenable config: %s", e)
            return {}

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(value)))
        except (TypeError, ValueError):
            return default

    def _settings(self, user_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Saved value (user, then system), then the environment, then the built-in default.

        Same order as the DeepSeek provider. The schema defaults for count and timeout
        come from the environment, so an unsaved value never overrides it.
        """
        user_config = user_config or {}
        api_key = str(user_config.get("keenable_api_key") or ai_config.keenable_api_key or "").strip()
        if api_key in _MASKED_KEYS:
            api_key = str(ai_config.keenable_api_key or "").strip()
        max_results = self._bounded_int(
            user_config.get("keenable_max_results") or ai_config.keenable_max_results, 10, 1, 50
        )
        timeout = self._bounded_int(
            user_config.get("keenable_timeout") or ai_config.keenable_timeout, 20, 1, 300
        )
        return {"api_key": api_key, "max_results": max_results, "timeout": timeout}

    def is_available(self) -> bool:
        """Keyless search works without a key; availability is not a credential check."""
        return True

    async def get_status(self) -> Dict[str, Any]:
        settings = self._settings(await self._load_user_config())
        return {
            "provider": "keenable",
            "available": self.is_available(),
            "has_api_key": bool(settings["api_key"]),
            "max_results": settings["max_results"],
            "timeout": settings["timeout"],
        }

    @staticmethod
    def _normalize_results(payload: Any, max_results: int) -> List[Dict[str, Any]]:
        items = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link") or ""
            if not url:
                continue
            out.append(
                {
                    "title": item.get("title") or "",
                    "url": url,
                    "content": item.get("snippet") or item.get("content") or item.get("description") or "",
                }
            )
            if len(out) >= max_results:
                break
        return out

    async def search(self, query: str, language: Optional[str] = None) -> List[Dict[str, Any]]:
        settings = self._settings(await self._load_user_config())
        api_key = settings["api_key"]
        url = KEYED_SEARCH_URL if api_key else PUBLIC_SEARCH_URL
        headers = {
            "Content-Type": "application/json",
            "X-Keenable-Title": APP_TITLE,
        }
        if api_key:
            headers["X-API-Key"] = api_key
        timeout = aiohttp.ClientTimeout(total=settings["timeout"])
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json={"query": query, "max_results": settings["max_results"]},
                headers=headers,
            ) as resp:
                if resp.status >= 400:
                    raise KeenableSearchError(f"Keenable search returned HTTP {resp.status}")
                try:
                    payload = await resp.json(content_type=None)
                except (ValueError, aiohttp.ClientError):
                    raise KeenableSearchError("Keenable returned an unreadable response") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise KeenableSearchError("Keenable returned an invalid search response")
        return self._normalize_results(payload, settings["max_results"])
