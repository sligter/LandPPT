"""
URL generation helpers.

This module centralizes absolute URL building so server-side callers can emit
stable public links that respect the configured BASE_URL.
"""

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from dotenv import load_dotenv
from ..auth.request_context import current_base_url

logger = logging.getLogger(__name__)


class URLService:
    """Build absolute URLs for app resources."""

    def __init__(self):
        self._base_url = None
        self._base_url_env_mtime: Optional[float] = None
        self._config_service = None

    def _get_config_service(self):
        """Load config lazily to avoid circular imports."""
        if self._config_service is None:
            from .config_service import config_service

            self._config_service = config_service
        return self._config_service

    def _get_base_url(self) -> str:
        """Return the current configured base URL."""
        request_base_url = (current_base_url.get() or "").strip()
        if request_base_url:
            return request_base_url.rstrip("/")

        try:
            config_service = self._get_config_service()

            # Reload BASE_URL from .env when it changes so multi-worker deployments
            # can pick up reverse-proxy domain updates without process restart.
            env_path: Optional[Path] = getattr(config_service, "env_path", None)
            mtime = None
            if env_path and env_path.exists():
                try:
                    mtime = env_path.stat().st_mtime
                except Exception:
                    mtime = None

            if self._base_url and mtime is not None and self._base_url_env_mtime == mtime:
                return self._base_url

            try:
                env_file = getattr(config_service, "env_file", ".env")
                load_dotenv(env_file, override=True)
            except Exception:
                pass

            app_config = config_service.get_config_by_category("app_config")
            base_url = str(app_config.get("base_url") or "").strip()

            if self.validate_base_url(base_url):
                if base_url.endswith("/"):
                    base_url = base_url[:-1]

                logger.debug(f"Using configured base URL: {base_url}")
                self._base_url = base_url
                self._base_url_env_mtime = mtime
                return base_url

            raise ValueError("App base_url is not configured")

        except Exception as e:
            logger.warning(f"Failed to load base URL config: {e}")
            raise ValueError("Public base URL is unavailable for absolute URL generation") from e

    def build_absolute_url(self, relative_path: str) -> str:
        """Build an absolute URL from a relative app path."""
        base_url = self._get_base_url()
        if not relative_path.startswith("/"):
            relative_path = "/" + relative_path

        absolute_url = f"{base_url}{relative_path}"
        logger.debug(f"Built absolute URL: {relative_path} -> {absolute_url}")
        return absolute_url

    def build_image_url(
        self,
        image_id: str,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> str:
        """Build an absolute image-view URL, optionally carrying size hints."""
        image_url = self.build_absolute_url(f"/api/image/view/{image_id}")
        query_params = {}
        if width and width > 0:
            query_params["width"] = f"{width}px"
        if height and height > 0:
            query_params["height"] = f"{height}px"
        if not query_params:
            return image_url
        return f"{image_url}?{urlencode(query_params)}"

    def build_image_thumbnail_url(self, image_id: str) -> str:
        """Build an absolute image thumbnail URL."""
        return self.build_absolute_url(f"/api/image/thumbnail/{image_id}")

    def build_image_download_url(self, image_id: str) -> str:
        """Build an absolute image download URL."""
        return self.build_absolute_url(f"/api/image/download/{image_id}")

    def build_static_url(self, static_path: str) -> str:
        """Build an absolute static asset URL."""
        if static_path.startswith("/"):
            static_path = static_path[1:]
        return self.build_absolute_url(f"/static/{static_path}")

    def build_temp_url(self, temp_path: str) -> str:
        """Build an absolute temp-file URL."""
        if temp_path.startswith("/"):
            temp_path = temp_path[1:]
        return self.build_absolute_url(f"/temp/{temp_path}")

    def get_current_base_url(self) -> str:
        """Return the configured base URL."""
        return self._get_base_url()

    def is_localhost_url(self, url: str) -> bool:
        """Check whether a URL points at localhost."""
        return "localhost" in url or "127.0.0.1" in url

    def validate_base_url(self, base_url: str) -> bool:
        """Validate base URL format."""
        try:
            if not base_url:
                return False
            if not (base_url.startswith("http://") or base_url.startswith("https://")):
                return False
            if base_url.endswith("/"):
                return False
            return True
        except Exception as e:
            logger.error(f"URL validation error: {e}")
            return False


_url_service = None


def get_url_service() -> URLService:
    """Return the shared URL service instance."""
    global _url_service
    if _url_service is None:
        _url_service = URLService()
    return _url_service


def build_absolute_url(relative_path: str) -> str:
    """Convenience helper for absolute URLs."""
    return get_url_service().build_absolute_url(relative_path)


def build_image_url(
    image_id: str,
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> str:
    """Convenience helper for absolute image URLs."""
    return get_url_service().build_image_url(image_id, width=width, height=height)


def build_image_thumbnail_url(image_id: str) -> str:
    """Convenience helper for image thumbnail URLs."""
    return get_url_service().build_image_thumbnail_url(image_id)


def build_image_download_url(image_id: str) -> str:
    """Convenience helper for image download URLs."""
    return get_url_service().build_image_download_url(image_id)


def get_current_base_url() -> str:
    """Convenience helper for the configured base URL."""
    return get_url_service().get_current_base_url()
