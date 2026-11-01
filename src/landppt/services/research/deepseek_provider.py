"""DeepSeek's standalone Search and Fetch JSON APIs.

References: https://api-docs.deepseek.com/zh-cn/api/search and /api/fetch.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from ...core.config import ai_config

logger = logging.getLogger(__name__)
_MASKED_KEYS = {"********", "••••••••", "***"}


class DeepSeekContentProvider:
    """Search for sources and fetch Markdown using the user's research settings."""

    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id

    def _resolve_config(self, saved: Dict[str, Any]) -> Dict[str, Any]:
        config = {}
        for name in ("api_key", "base_url", "max_results", "timeout"):
            key = f"deepseek_{name}"
            config[name] = saved.get(key) or getattr(ai_config, key)
        config["api_key"] = str(config["api_key"] or "").strip()
        if config["api_key"] in _MASKED_KEYS:
            config["api_key"] = ""
        config["base_url"] = (
            str(config["base_url"]).strip().rstrip("/") or "https://api.deepseek.com"
        )
        # Accept both the API origin and the commonly used OpenAI-style /v1 base.
        if config["base_url"].endswith("/v1"):
            config["base_url"] = config["base_url"][:-3]
        config["max_results"] = self._bounded_int(config["max_results"], 10, 1, 50)
        config["timeout"] = self._bounded_int(config["timeout"], 30, 1, 300)
        return config

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            return max(minimum, min(maximum, int(value)))
        except (TypeError, ValueError):
            return default

    def get_config_sync(self) -> Dict[str, Any]:
        from ..db_config_service import get_db_config_service

        try:
            service = get_db_config_service()
            saved = service.get_all_config_sync(user_id=self.user_id)
            system = (
                service.get_all_config_sync(user_id=None)
                if self.user_id is not None
                else saved
            )
        except Exception:
            saved = {}
            system = {}
        return self._protect_shared_endpoint(saved, system)

    async def get_config(self) -> Dict[str, Any]:
        from ..db_config_service import get_db_config_service

        try:
            service = get_db_config_service()
            saved = await service.get_all_config(user_id=self.user_id)
            system = (
                await service.get_all_config(user_id=None)
                if self.user_id is not None
                else saved
            )
        except Exception:
            logger.warning(
                "Could not load DeepSeek research settings; using environment"
            )
            saved = {}
            system = {}
        return self._protect_shared_endpoint(saved, system)

    def _protect_shared_endpoint(
        self, saved: Dict[str, Any], system: Dict[str, Any]
    ) -> Dict[str, Any]:
        config = self._resolve_config(saved)
        system_config = self._resolve_config(system)
        # A user may customize the endpoint only with their own key. Otherwise
        # a user-controlled gateway could capture the inherited system secret.
        if config["api_key"] == system_config["api_key"]:
            config["base_url"] = system_config["base_url"]
        return config

    def is_available(self) -> bool:
        return bool(self.get_config_sync()["api_key"])

    async def _post(
        self, operation: str, payload: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not config["api_key"]:
            raise ValueError("DeepSeek API Key is not configured")
        endpoint = f"{config['base_url']}/v1/tools/{operation}"
        headers = {
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        }
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=config["timeout"])
        ) as session:
            for attempt in range(3):
                async with session.post(
                    endpoint, json=payload, headers=headers
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    status = response.status
                    # Do not include response bodies or request headers in errors: they
                    # may echo credentials from a custom gateway.
                    if status not in {408, 429} and status < 500:
                        raise RuntimeError(
                            f"DeepSeek {operation} failed (HTTP {status})"
                        )
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
            raise RuntimeError(f"DeepSeek {operation} failed (HTTP {status})")

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        *,
        ori_question: Optional[str] = None,
        need_content: bool = False,
    ) -> List[Dict[str, Any]]:
        query = str(query or "").strip()
        if not query or len(query) > 128:
            raise ValueError("DeepSeek query must contain 1–128 Unicode characters")
        config = await self.get_config()
        payload = {
            "query": query,
            "count": self._bounded_int(max_results, config["max_results"], 1, 50),
            "need_content": need_content,
        }
        if ori_question and ori_question.strip():
            payload["ori_question"] = ori_question.strip()[:128]
        response = await self._post("search", payload, config)
        results = []
        for item in response.get("results", []):
            results.append(
                {
                    **item,
                    "content": item.get("content")
                    or item.get("summary")
                    or item.get("snippet")
                    or "",
                    "score": item.get("rerank_score", 0),
                    "published_date": item.get("date") or "",
                    "provider": "deepseek",
                }
            )
        return results

    async def fetch(self, url: str) -> Dict[str, Any]:
        url = str(url or "").strip()
        parsed = urlparse(url)
        if (
            not url
            or len(url) > 8192
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError(
                "DeepSeek fetch requires an HTTP(S) URL without credentials, at most 8192 characters"
            )
        response = await self._post("fetch", {"url": url}, await self.get_config())
        return {
            "url": url,
            "title": response.get("title") or "",
            "content": response.get("content") or "",
        }
