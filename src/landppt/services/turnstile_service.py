"""
Cloudflare Turnstile verification helpers.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import httpx

from ..core.config import app_config

logger = logging.getLogger(__name__)


def is_turnstile_active() -> bool:
    return bool(
        getattr(app_config, "turnstile_enabled", False)
        and getattr(app_config, "turnstile_site_key", None)
        and getattr(app_config, "turnstile_secret_key", None)
    )


async def verify_turnstile(token: Optional[str], remote_ip: Optional[str] = None) -> Tuple[bool, str]:
    """
    Verify Turnstile response token.

    Returns (ok, message).
    """
    if not is_turnstile_active():
        return True, "Turnstile disabled"

    token = (token or "").strip()
    if not token:
        return False, "请先完成人机验证"

    data = {
        "secret": app_config.turnstile_secret_key,
        "response": token,
    }
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data=data,
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception as e:
        logger.warning(f"Turnstile verify request failed: {e}")
        return False, "人机验证服务不可用，请稍后重试"

    if payload.get("success") is True:
        return True, "ok"

    # Avoid leaking internal error codes to end-users; keep it simple.
    return False, "人机验证失败，请刷新后重试"

