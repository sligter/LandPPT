"""
Shared helpers for extracted web route modules.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import Response
from fastapi.templating import Jinja2Templates

from ...core.config import app_config
from ...database.database import AsyncSessionLocal
from ...services.service_instances import get_ppt_service_for_user, ppt_service

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="src/landppt/web/templates")


def _apply_no_store_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


def _timestamp_to_datetime(timestamp: Any) -> str:
    try:
        if isinstance(timestamp, (int, float)):
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        return str(timestamp)
    except (ValueError, OSError):
        return "Invalid timestamp"


def _strftime_filter(timestamp: Any, format_string: str = "%Y-%m-%d %H:%M") -> str:
    try:
        if isinstance(timestamp, (int, float)):
            return datetime.fromtimestamp(timestamp).strftime(format_string)
        return str(timestamp)
    except (ValueError, OSError):
        return "Invalid timestamp"


templates.env.filters["timestamp_to_datetime"] = _timestamp_to_datetime
templates.env.filters["strftime"] = _strftime_filter
templates.env.globals["credits_enabled"] = app_config.enable_credits_system


async def consume_credits_for_operation(
    user_id: int,
    operation_type: str,
    quantity: int = 1,
    description: str | None = None,
    reference_id: str | None = None,
    provider_name: str | None = None,
) -> tuple[bool, str]:
    if not app_config.enable_credits_system:
        return True, "Credits system disabled"

    if (provider_name or "").strip().lower() != "landppt":
        return True, "Non-billable provider"

    try:
        from ...services.credits_service import CreditsService

        async with AsyncSessionLocal() as session:
            credits_service = CreditsService(session)
            return await credits_service.consume_credits(
                user_id=user_id,
                operation_type=operation_type,
                quantity=quantity,
                description=description,
                reference_id=reference_id,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Credits consumption error: %s", exc)
        return False, f"Credits consumption failed: {exc}"


async def check_credits_for_operation(
    user_id: int,
    operation_type: str,
    quantity: int = 1,
    provider_name: str | None = None,
) -> tuple[bool, int, int]:
    if not app_config.enable_credits_system:
        return True, 0, 0

    if (provider_name or "").strip().lower() != "landppt":
        return True, 0, 0

    try:
        from ...services.credits_service import CreditsService

        async with AsyncSessionLocal() as session:
            credits_service = CreditsService(session)
            required = credits_service.get_operation_cost(operation_type, quantity)
            balance = await credits_service.get_balance(user_id)
            return balance >= required, required, balance
    except Exception as exc:  # noqa: BLE001
        logger.error("Credits check error: %s", exc)
        return False, 0, 0

