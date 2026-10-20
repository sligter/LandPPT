"""Anonymous Parallel Search MCP for one presentation research run."""

import asyncio
import ipaddress
import json
import uuid
from contextvars import ContextVar
from functools import wraps
from importlib.metadata import PackageNotFoundError, version
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


_research_session: ContextVar[str | None] = ContextVar("parallel_research_session", default=None)
MCP_URL = "https://search.parallel.ai/mcp"


class ParallelSearchError(RuntimeError):
    """A provider error that must not trigger a switch to legacy research."""


def parallel_research_run(func):
    """Keep task-local identity separate from shared providers and MCP connections."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        token = _research_session.set(str(uuid.uuid4()))
        try:
            return await func(*args, **kwargs)
        finally:
            _research_session.reset(token)
    return wrapper


def public_http_url(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password:
            return False
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


class ParallelSearchProvider:
    """Use the maintained MCP SDK without reading API keys or saved credentials."""

    def _http_client(self, timeout: float) -> httpx.AsyncClient:
        try:
            project_version = version("landppt")
        except PackageNotFoundError:
            project_version = "0.4.0"
        return httpx.AsyncClient(
            headers={"User-Agent": f"LandPPT/{project_version}"},
            timeout=timeout,
        )

    async def _call(self, name: str, arguments: dict, timeout: float) -> dict:
        session_id = _research_session.get()
        if session_id is None:
            raise RuntimeError("Parallel search requires a research run context")
        try:
            async with asyncio.timeout(timeout):
                async with self._http_client(timeout) as http_client:
                    async with streamable_http_client(MCP_URL, http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool(name, {**arguments, "session_id": session_id})
            if result.isError:
                message = " ".join(getattr(item, "text", "") for item in result.content)
                raise ValueError(message or "MCP tool returned an error")
            data = result.structuredContent
            if data is None:
                data = json.loads("\n".join(getattr(item, "text", "") for item in result.content))
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ValueError("Invalid Parallel result")
            if data.get("errors"):
                raise ValueError(f"Page extraction failed: {data['errors']}")
            return data
        except TimeoutError as exc:
            raise ParallelSearchError("Error from provider Parallel: research request timed out") from exc
        except Exception as exc:
            raise ParallelSearchError(f"Error from provider Parallel: {exc}") from exc

    @staticmethod
    def _results(data: dict) -> list[dict]:
        results = []
        for item in data["results"]:
            if not isinstance(item, dict) or not public_http_url(item.get("url")):
                continue
            excerpts = item.get("excerpts") or []
            if not isinstance(excerpts, list) or any(not isinstance(text, str) for text in excerpts):
                raise ParallelSearchError("Error from provider Parallel: invalid excerpts")
            results.append({
                "url": item["url"],
                "title": item.get("title") or item["url"],
                "content": "\n".join(excerpts),
                "published_date": item.get("publish_date"),
            })
        return results

    async def search(self, query: str, language: str, *, timeout: float) -> list[dict]:
        data = await self._call("web_search", {
            "objective": f"Find evidence for presentation research. Language: {language}. {query}",
            "search_queries": [query],
        }, timeout)
        return self._results(data)

    async def fetch(self, urls: list[str], query: str, *, timeout: float) -> list[dict]:
        urls = [url for url in urls if public_http_url(url)][:10]
        if not urls:
            return []
        data = await self._call("web_fetch", {
            "urls": urls,
            "objective": query[:200],
            "search_queries": [query],
            "full_content": False,
        }, timeout)
        return self._results(data)
