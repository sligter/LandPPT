"""
MinerU API client - convert PDFs to Markdown via MinerU cloud API.
Based on https://mineru.net/apiManage/docs

Endpoints (base: https://mineru.net/api/v4):
- POST /file-urls/batch                     (request presigned upload url + create batch)
- GET  /extract-results/batch/{batch_id}    (poll batch results)
- POST /extract/task                        (create task from a public URL)
- GET  /extract/task/{task_id}              (poll task result)

Auth: Bearer token (MINERU_API_KEY)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class MineruAPIClient:
    """
    MinerU cloud API client.

    Configure via env vars:
      - MINERU_API_KEY: API token from https://mineru.net/apiManage
      - MINERU_BASE_URL: optional, defaults to official base url
    """

    DEFAULT_BASE_URL = "https://mineru.net/api/v4"

    TASK_ENDPOINT = "/extract/task"
    RESULT_ENDPOINT = "/extract/task/{task_id}"
    FILE_URLS_BATCH_ENDPOINT = "/file-urls/batch"
    BATCH_RESULTS_ENDPOINT = "/extract-results/batch/{batch_id}"

    DEFAULT_POLL_INTERVAL = 3  # seconds
    DEFAULT_MAX_WAIT_TIME = 300  # seconds (5 minutes)

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ):
        raw_key = api_key or os.getenv("MINERU_API_KEY", "")
        raw_key = (raw_key or "").strip().strip("\"'").strip()
        # Users sometimes paste "Bearer xxx" or a full header line.
        if raw_key.lower().startswith("bearer "):
            raw_key = raw_key[7:].strip()
        if raw_key.lower().startswith("authorization:"):
            raw_key = raw_key.split(":", 1)[1].strip()
            if raw_key.lower().startswith("bearer "):
                raw_key = raw_key[7:].strip()

        self.api_key = raw_key
        self.base_url = base_url or os.getenv("MINERU_BASE_URL", "") or self.DEFAULT_BASE_URL
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._pending_file_urls: Dict[str, Dict[str, str]] = {}
        self._db_loaded = False
        self._db_loaded_user_id: Optional[int] = None

        if self.api_key:
            logger.info(f"MinerU API client initialized. Base URL: {self.base_url}")
        else:
            logger.info("MINERU_API_KEY not set in environment; MinerU credentials will be loaded from DB config when available.")

    @property
    def is_available(self) -> bool:
        # Keep sync availability checks side-effect free. This property is used from
        # synchronous code paths (including executor threads), and trying to reach into
        # the async DB layer here can trigger asyncpg cross-event-loop failures.
        #
        # Callers that need DB-backed per-user MinerU config should load it in their
        # async context first and pass api_key/base_url explicitly.
        return bool(self.api_key)

    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _get_current_user_id(self) -> Optional[int]:
        try:
            from landppt.auth.request_context import current_user_id

            return current_user_id.get()
        except Exception:
            return None

    @staticmethod
    def _sanitize_api_key(raw_key: Any) -> str:
        value = ("" if raw_key is None else str(raw_key)).strip().strip("\"'").strip()
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        if value.lower().startswith("authorization:"):
            value = value.split(":", 1)[1].strip()
            if value.lower().startswith("bearer "):
                value = value[7:].strip()
        return value

    @staticmethod
    def _sanitize_base_url(raw_url: Any, default: str) -> str:
        value = ("" if raw_url is None else str(raw_url)).strip().strip("\"'").strip()
        return value or default

    async def _load_db_mineru_config(self, user_id: Optional[int]) -> Tuple[Optional[str], Optional[str]]:
        """
        Load MinerU credentials from LandPPT's DB-backed config service (per-user),
        falling back to system defaults when user-specific values are missing.
        """
        try:
            from landppt.services.db_config_service import get_db_config_service
        except Exception:
            return None, None

        try:
            svc = get_db_config_service()
            api_key = await svc.get_config_value("mineru_api_key", user_id=user_id)
            base_url = await svc.get_config_value("mineru_base_url", user_id=user_id)
            return api_key, base_url
        except Exception as e:
            logger.debug(f"Failed to load MinerU config from DB (user_id={user_id}): {e}")
            return None, None

    async def _ensure_db_config_loaded(self) -> None:
        user_id = self._get_current_user_id()
        if self._db_loaded and self._db_loaded_user_id == user_id:
            return

        db_key, db_base_url = await self._load_db_mineru_config(user_id)

        updated = False
        if db_key:
            sanitized_key = self._sanitize_api_key(db_key)
            if sanitized_key and sanitized_key != self.api_key:
                self.api_key = sanitized_key
                updated = True

        if db_base_url:
            sanitized_url = self._sanitize_base_url(db_base_url, self.DEFAULT_BASE_URL)
            if sanitized_url and sanitized_url != self.base_url:
                self.base_url = sanitized_url
                updated = True

        self._db_loaded = True
        self._db_loaded_user_id = user_id

        # If credentials/base_url changed, rebuild client so headers/base_url are consistent.
        if updated and self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        await self._ensure_db_config_loaded()
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self._get_headers(),
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def create_task_from_file(
        self,
        file_path: str,
        enable_ocr: bool = True,
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
    ) -> str:
        """
        Create an extraction job from a local PDF file.

        Note: MinerU does NOT accept direct file bytes at /extract/task.
        The correct flow is:
          1) POST /file-urls/batch to obtain a presigned upload URL and a batch_id
          2) PUT file bytes to the presigned URL (no MinerU headers)
          3) Poll /extract-results/batch/{batch_id} until done

        Returns:
            batch_id
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_name = path.name
        batch_id = await self._apply_upload_url_for_file(
            file_name=file_name,
            enable_ocr=enable_ocr,
            enable_formula=enable_formula,
            enable_table=enable_table,
            language=language,
        )
        await self._upload_file_to_batch(batch_id=batch_id, file_path=file_path, file_name=file_name)
        return batch_id

    async def _apply_upload_url_for_file(
        self,
        *,
        file_name: str,
        enable_ocr: bool,
        enable_formula: bool,
        enable_table: bool,
        language: str,
        model_version: str = "pipeline",
    ) -> str:
        await self._ensure_db_config_loaded()
        if not self.api_key:
            raise ValueError("MinerU API key is not configured. Set mineru_api_key in DB config (preferred) or MINERU_API_KEY.")

        client = await self._get_client()
        payload: Dict[str, Any] = {
            "files": [{"name": file_name, "is_ocr": bool(enable_ocr)}],
            "model_version": model_version,
            "enable_formula": bool(enable_formula),
            "enable_table": bool(enable_table),
            "language": language,
        }

        try:
            response = await client.post(self.FILE_URLS_BATCH_ENDPOINT, json=payload)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as e:
            body = None
            try:
                body = e.response.text
            except Exception:
                body = None
            logger.error(f"MinerU API HTTP error: {e.response.status_code}, body={body}")
            raise ValueError(f"MinerU API request failed: HTTP {e.response.status_code}")

        if result.get("code") != 0:
            raise ValueError(f"MinerU API error: {result.get('msg', 'unknown error')}")

        data = result.get("data") or {}
        batch_id = data.get("batch_id")
        if not batch_id:
            raise ValueError("MinerU API returned an invalid batch_id")

        file_urls = data.get("file_urls") or []
        if not file_urls or not isinstance(file_urls, list):
            raise ValueError("MinerU API did not return file_urls upload URL(s)")

        self._pending_file_urls[str(batch_id)] = {file_name: file_urls[0]}
        return str(batch_id)

    async def _upload_file_to_batch(self, *, batch_id: str, file_path: str, file_name: str) -> None:
        upload_url = (self._pending_file_urls.get(batch_id) or {}).get(file_name)
        if not upload_url:
            raise ValueError("Upload URL not found; call /file-urls/batch first.")

        async def _iter_file_bytes(path: str, chunk_size: int = 1024 * 1024):
            import anyio

            async with await anyio.open_file(path, "rb") as f:
                while True:
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        timeout = httpx.Timeout(self.timeout)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as upload_client:
            resp = await upload_client.put(upload_url, content=_iter_file_bytes(file_path))
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                body = None
                try:
                    body = e.response.text
                except Exception:
                    body = None
                logger.error(f"MinerU upload failed: HTTP {e.response.status_code}, body={body}")
                raise ValueError(f"MinerU upload failed: HTTP {e.response.status_code}")

    async def create_task_from_url(
        self,
        pdf_url: str,
        enable_ocr: bool = True,
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
    ) -> str:
        logger.info(f"Creating MinerU extraction task from URL: {pdf_url}")
        payload: Dict[str, Any] = {
            "url": pdf_url,
            "is_ocr": enable_ocr,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
            "language": language,
            "model_version": "pipeline",
        }
        return await self._create_task(payload)

    async def _create_task(self, payload: Dict[str, Any]) -> str:
        await self._ensure_db_config_loaded()
        if not self.api_key:
            raise ValueError("MinerU API key is not configured. Set mineru_api_key in DB config (preferred) or MINERU_API_KEY.")

        client = await self._get_client()
        try:
            response = await client.post(self.TASK_ENDPOINT, json=payload)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as e:
            body = None
            try:
                body = e.response.text
            except Exception:
                body = None
            logger.error(f"MinerU API HTTP error: {e.response.status_code}, body={body}")
            raise ValueError(f"MinerU API request failed: HTTP {e.response.status_code}")

        if result.get("code") != 0:
            raise ValueError(f"MinerU API error: {result.get('msg', 'unknown error')}")

        task_id = (result.get("data") or {}).get("task_id")
        if not task_id:
            raise ValueError("MinerU API returned an invalid task_id")

        logger.info(f"MinerU task created: {task_id}")
        return str(task_id)

    async def get_task_result(self, task_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        try:
            endpoint = self.RESULT_ENDPOINT.format(task_id=task_id)
            response = await client.get(endpoint)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to fetch task result: {e}")
            raise ValueError(f"Failed to fetch task result: {e}")

    async def get_batch_results(self, batch_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        endpoint = self.BATCH_RESULTS_ENDPOINT.format(batch_id=batch_id)
        try:
            response = await client.get(endpoint)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            body = None
            try:
                body = e.response.text
            except Exception:
                body = None
            logger.error(f"MinerU API HTTP error: {e.response.status_code}, body={body}")
            raise ValueError(f"MinerU API request failed: HTTP {e.response.status_code}")
        except Exception as e:
            logger.error(f"Failed to fetch batch results: {e}")
            raise ValueError(f"Failed to fetch batch results: {e}")

    async def wait_for_batch_result(
        self,
        batch_id: str,
        *,
        file_name: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_wait_time: float = DEFAULT_MAX_WAIT_TIME,
    ) -> Dict[str, Any]:
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait_time:
                raise TimeoutError(f"Timed out waiting for batch result ({max_wait_time}s)")

            result = await self.get_batch_results(batch_id)
            if result.get("code") != 0:
                raise ValueError(f"MinerU API error: {result.get('msg', 'unknown error')}")

            data = result.get("data") or {}
            extract_results = data.get("extract_result") or []

            entry = None
            for item in extract_results:
                if isinstance(item, dict) and item.get("file_name") == file_name:
                    entry = item
                    break

            if not entry:
                await asyncio.sleep(poll_interval)
                continue

            state = entry.get("state")
            if state == "done":
                return entry
            if state == "failed":
                raise ValueError(f"MinerU extraction failed: {entry.get('err_msg', 'unknown error')}")

            await asyncio.sleep(poll_interval)

    async def wait_for_result(
        self,
        task_id: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        max_wait_time: float = DEFAULT_MAX_WAIT_TIME,
    ) -> Dict[str, Any]:
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait_time:
                raise TimeoutError(f"Timed out waiting for task result ({max_wait_time}s)")

            result = await self.get_task_result(task_id)
            if result.get("code") != 0:
                raise ValueError(f"MinerU API error: {result.get('msg', 'unknown error')}")

            data = result.get("data") or {}
            status = data.get("state")

            if status == "done":
                logger.info(f"MinerU task done: {task_id} ({elapsed:.1f}s)")
                return data
            if status == "failed":
                raise ValueError(f"MinerU extraction failed: {data.get('err_msg', 'unknown error')}")

            logger.debug(f"MinerU task running: {task_id}, state={status}, elapsed={elapsed:.1f}s")
            await asyncio.sleep(poll_interval)

    async def extract_markdown(
        self,
        file_path: Optional[str] = None,
        pdf_url: Optional[str] = None,
        enable_ocr: bool = True,
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
    ) -> Tuple[str, Dict[str, Any]]:
        if not file_path and not pdf_url:
            raise ValueError("Either file_path or pdf_url must be provided.")

        if file_path:
            batch_id = await self.create_task_from_file(
                file_path=file_path,
                enable_ocr=enable_ocr,
                enable_formula=enable_formula,
                enable_table=enable_table,
                language=language,
            )
            file_name = Path(file_path).name
            entry = await self.wait_for_batch_result(batch_id, file_name=file_name)
            md_url = entry.get("full_zip_url") or entry.get("md_url")
            markdown_content = await self._download_markdown(md_url) if md_url else ""
            extra_info = {"batch_id": batch_id, "file_name": file_name, "state": entry.get("state")}
            return markdown_content, extra_info

        task_id = await self.create_task_from_url(
            pdf_url=pdf_url,
            enable_ocr=enable_ocr,
            enable_formula=enable_formula,
            enable_table=enable_table,
            language=language,
        )
        result = await self.wait_for_result(task_id)
        md_url = result.get("full_zip_url") or result.get("md_url")
        markdown_content = await self._download_markdown(md_url) if md_url else result.get("markdown", "")
        extra_info = {
            "task_id": task_id,
            "pages": result.get("pages", 0),
            "processing_time": result.get("processing_time"),
        }
        return markdown_content, extra_info

    async def _download_markdown(self, url: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                response.raise_for_status()

                content_type = (response.headers.get("content-type") or "").lower()
                is_zip = url.endswith(".zip") or "zip" in content_type or response.content[:2] == b"PK"
                if not is_zip:
                    return response.text

                import io
                import zipfile

                zip_buffer = io.BytesIO(response.content)
                with zipfile.ZipFile(zip_buffer, "r") as zip_file:
                    names = [n for n in zip_file.namelist() if n and not n.endswith("/")]

                    md_candidates = [n for n in names if n.lower().endswith(".md")]
                    if not md_candidates:
                        return ""

                    md_name = sorted(md_candidates, key=lambda n: (len(n.split("/")), len(n), n))[0]
                    markdown_content = zip_file.read(md_name).decode("utf-8", errors="replace")

                    image_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")
                    images: Dict[str, bytes] = {}
                    for name in names:
                        lower = name.lower()
                        if lower.endswith(image_exts):
                            try:
                                images[name.replace("\\", "/")] = zip_file.read(name)
                            except Exception:
                                continue

                if images:
                    markdown_content = await self._upload_zip_images_to_local_gallery_and_replace_links(
                        markdown_content, images
                    )

                return markdown_content
        except Exception as e:
            logger.error(f"Failed to download markdown: {e}")
            return ""

    async def _upload_zip_images_to_local_gallery_and_replace_links(
        self,
        markdown_content: str,
        images: Dict[str, bytes],
    ) -> str:
        """
        Best-effort: upload images extracted from MinerU zip into LandPPT local image gallery and
        replace links in markdown. If LandPPT image service isn't available, returns unchanged.
        """
        try:
            from landppt.services.image.image_service import get_image_service
            from landppt.services.image.models import ImageUploadRequest
            from landppt.services.url_service import build_image_url
        except Exception:
            return markdown_content

        import hashlib
        import mimetypes

        image_service = get_image_service()

        def _candidate_refs(zip_path: str) -> set[str]:
            p = (zip_path or "").replace("\\", "/").lstrip("/")
            candidates = {p}
            if p.startswith("./"):
                candidates.add(p[2:])
            else:
                candidates.add("./" + p)

            base = Path(p).name
            if base:
                candidates.add("images/" + base)
                candidates.add("./images/" + base)
                candidates.add(base)
            return {c for c in candidates if c}

        def _append_size_to_alt(alt: str, width: int, height: int) -> str:
            clean_alt = (alt or "").strip() or "图片"
            if width <= 0 or height <= 0:
                return clean_alt
            if "图片大小" in clean_alt or "尺寸" in clean_alt:
                return clean_alt
            if re.search(r"\b\d+\s*[xX×]\s*\d+\s*(?:px)?\b", clean_alt):
                return clean_alt
            return f"{clean_alt}（图片大小：{width}x{height}px）"

        def _replace_ref(text: str, old: str, new: str, width: int = 0, height: int = 0) -> str:
            if old not in text:
                return text

            escaped_old = re.escape(old)

            image_pattern = re.compile(
                rf"!\[(?P<alt>[^\]]*)\]\((?P<url>{escaped_old})(?P<title>\s+(?:\"[^\"]*\"|'[^']*'))?\)"
            )

            def _replace_image(match: re.Match[str]) -> str:
                alt = _append_size_to_alt(match.group("alt"), width, height)
                title = match.group("title") or ""
                return f"![{alt}]({new}{title})"

            text = image_pattern.sub(_replace_image, text)

            link_pattern = re.compile(
                rf"(?<!!)\[(?P<label>[^\]]+)\]\((?P<url>{escaped_old})(?P<title>\s+(?:\"[^\"]*\"|'[^']*'))?\)"
            )
            text = link_pattern.sub(
                lambda match: f"[{match.group('label')}]({new}{match.group('title') or ''})",
                text,
            )

            html_src_pattern = re.compile(rf"(?P<prefix>src=[\"']){escaped_old}(?P<suffix>[\"'])")
            return html_src_pattern.sub(rf"\g<prefix>{new}\g<suffix>", text)

        for zip_path, data in images.items():
            if not data:
                continue

            candidates = _candidate_refs(zip_path)
            if not any(c in markdown_content for c in candidates):
                continue

            content_hash = hashlib.sha256(data).hexdigest()[:16]
            ext = Path(zip_path).suffix.lower() or ".png"
            filename = f"mineru_{content_hash}{ext}"
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            if not content_type.startswith("image/"):
                content_type = "image/" + (ext.lstrip(".") or "png")

            upload_request = ImageUploadRequest(
                filename=filename,
                content_type=content_type,
                file_size=len(data),
                title=Path(filename).stem,
                description="Imported from MinerU zip",
                tags=["mineru"],
                category="local_storage",
            )

            try:
                result = await image_service.upload_image(upload_request, data)
            except Exception as e:
                logger.warning(f"Failed to upload MinerU image {zip_path}: {e}")
                continue

            if not result or not getattr(result, "success", False) or not getattr(result, "image_info", None):
                logger.warning(f"Failed to upload MinerU image {zip_path}: {getattr(result, 'message', '')}")
                continue

            metadata = getattr(result.image_info, "metadata", None)
            width = int(getattr(metadata, "width", 0) or 0)
            height = int(getattr(metadata, "height", 0) or 0)
            new_url = build_image_url(
                result.image_info.image_id,
                width=width or None,
                height=height or None,
            )
            for old in sorted(candidates, key=len, reverse=True):
                markdown_content = _replace_ref(markdown_content, old, new_url, width=width, height=height)

        return markdown_content

    def extract_markdown_sync(
        self,
        file_path: Optional[str] = None,
        pdf_url: Optional[str] = None,
        enable_ocr: bool = True,
        enable_formula: bool = True,
        enable_table: bool = True,
        language: str = "ch",
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Synchronous wrapper for extract_markdown.

        Safe to call from within an already-running event loop (runs in a thread).
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.extract_markdown(
                    file_path=file_path,
                    pdf_url=pdf_url,
                    enable_ocr=enable_ocr,
                    enable_formula=enable_formula,
                    enable_table=enable_table,
                    language=language,
                )
            )

        result_container: Dict[str, Any] = {}
        error_container: Dict[str, BaseException] = {}

        # Propagate contextvars (e.g. current_user_id) into the thread.
        ctx = contextvars.copy_context()

        def _runner() -> None:
            try:
                result_container["result"] = asyncio.run(
                    self.extract_markdown(
                        file_path=file_path,
                        pdf_url=pdf_url,
                        enable_ocr=enable_ocr,
                        enable_formula=enable_formula,
                        enable_table=enable_table,
                        language=language,
                    )
                )
            except BaseException as e:
                error_container["error"] = e

        t = threading.Thread(target=lambda: ctx.run(_runner), daemon=True)
        t.start()
        t.join()

        if "error" in error_container:
            raise error_container["error"]

        return result_container["result"]


def get_mineru_client() -> MineruAPIClient:
    return MineruAPIClient()


def is_mineru_available() -> bool:
    return MineruAPIClient().is_available
