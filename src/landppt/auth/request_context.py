"""
Request-scoped context for enforcing per-user data isolation.

This module intentionally contains no FastAPI/DB imports to avoid circular dependencies.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional
from urllib.parse import urlsplit

# Sentinel value: pass this as user_id to explicitly disable user scoping (admin/system paths).
USER_SCOPE_ALL = -1

# The current authenticated user's ID for the active request/task.
current_user_id: ContextVar[Optional[int]] = ContextVar("landppt_current_user_id", default=None)

# The current request's externally reachable base URL, when available.
current_base_url: ContextVar[Optional[str]] = ContextVar("landppt_current_base_url", default=None)


def _strip_default_port(host: str, scheme: str) -> str:
    """Strip default port from a host string."""
    raw_host = (host or "").strip()
    normalized_scheme = (scheme or "").strip().lower()
    if not raw_host:
        return raw_host

    try:
        parsed = urlsplit(f"{normalized_scheme or 'http'}://{raw_host}")
        hostname = parsed.hostname or raw_host
        port = parsed.port
        if port is None:
            return raw_host
        if (normalized_scheme == "http" and port == 80) or (normalized_scheme == "https" and port == 443):
            if ":" in hostname and not hostname.startswith("["):
                return f"[{hostname}]"
            return hostname
    except Exception:
        return raw_host

    return raw_host


def _normalize_base_url_candidate(raw_url: Optional[str], default_scheme: str = "https") -> Optional[str]:
    """Normalize a request-derived base URL candidate to scheme://host[:port]."""
    value = (str(raw_url).strip() if raw_url is not None else "")
    if not value:
        return None

    if value.startswith("//"):
        value = f"{default_scheme}:{value}"
    elif "://" not in value:
        value = f"{default_scheme}://{value.lstrip('/')}"

    parsed = urlsplit(value)
    scheme = (parsed.scheme or default_scheme or "https").strip().lower()
    host = (parsed.netloc or "").strip()
    if not host:
        return None

    if "," in host:
        host = host.split(",", 1)[0].strip()
    host = _strip_default_port(host, scheme)
    if not host:
        return None
    return f"{scheme}://{host}"


def resolve_request_base_url(request) -> Optional[str]:
    """
    Resolve the externally reachable base URL for the active request.

    Uses proxy/origin headers first so reverse-proxy deployments do not fall back
    to internal container hosts.
    """
    if request is None:
        return None

    candidates = []

    def add_candidate(raw_url: Optional[str], *, default_scheme: str = "https") -> None:
        normalized = _normalize_base_url_candidate(raw_url, default_scheme=default_scheme)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    try:
        headers = request.headers
        request_scheme = (getattr(request.url, "scheme", None) or "https").strip().lower()

        add_candidate(headers.get("origin"), default_scheme=request_scheme)

        referer = headers.get("referer")
        if referer:
            try:
                referer_parts = urlsplit(referer)
                add_candidate(f"{referer_parts.scheme}://{referer_parts.netloc}", default_scheme=request_scheme)
            except Exception:
                pass

        forwarded_host = (headers.get("x-forwarded-host") or "").strip()
        forwarded_proto = (headers.get("x-forwarded-proto") or request_scheme).strip().lower()
        forwarded_port = (headers.get("x-forwarded-port") or "").strip()
        if "," in forwarded_host:
            forwarded_host = forwarded_host.split(",", 1)[0].strip()
        if "," in forwarded_proto:
            forwarded_proto = forwarded_proto.split(",", 1)[0].strip()
        if forwarded_host and forwarded_port and ":" not in forwarded_host:
            forwarded_host = f"{forwarded_host}:{forwarded_port}"
        add_candidate(forwarded_host, default_scheme=forwarded_proto or request_scheme)

        host = (headers.get("host") or getattr(request.url, "netloc", "") or "").strip()
        add_candidate(host, default_scheme=request_scheme)

        if getattr(request, "base_url", None):
            add_candidate(str(request.base_url), default_scheme=request_scheme)
    except Exception:
        return None

    return candidates[0] if candidates else None
