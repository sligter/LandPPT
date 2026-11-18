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


class KeenableContentProvider:
    """Keenable content search provider for research functionality."""

    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id
        self._config_initialized = False

    async def _load_user_config(self) -> Dict[str, Any]:
        if self.user_id is None:
            return {}
        try:
            from ..db_config_service import get_db_config_service

            db_config_service = get_db_config_service()
            return await db_config_service.get_all_config(user_id=self.user_id) or {}
        except Exception as e:
            logger.warning("Failed to load user Keenable config: %s", e)
            return {}

    def _settings(self, user_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        user_config = user_config or {}
        api_key = (user_config.get("keenable_api_key") or ai_config.keenable_api_key or "").strip()
        try:
            max_results = int(user_config.get("keenable_max_results") or ai_config.keenable_max_results or 10)
        except (TypeError, ValueError):
            max_results = 10
        try:
            timeout = int(user_config.get("keenable_timeout") or ai_config.keenable_timeout or 20)
        except (TypeError, ValueError):
            timeout = 20
        return {"api_key": api_key, "max_results": max_results, "timeout": timeout}

    def is_available(self) -> bool:
        """Keyless search works without a key; availability is not a credential check."""
        return True

    def get_status(self) -> Dict[str, Any]:
        settings = self._settings()
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
                body = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"Keenable search HTTP {resp.status}: {body[:300]}")
                try:
                    payload = await resp.json(content_type=None)
                except Exception as e:
                    raise RuntimeError(f"Keenable returned a non-JSON body: {body[:300]}") from e
        return self._normalize_results(payload, settings["max_results"])
