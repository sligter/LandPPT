"""Browser-facing handling of inherited research credentials."""

from typing import Any, Dict

from ..core.config import ai_config


async def redact_inherited_research_keys(
    config: Dict[str, Any], user: Any, config_service: Any
) -> Dict[str, Any]:
    """Expose configuration signals while keeping shared API keys on the server."""
    redacted = dict(config)
    for provider in ("tavily", "deepseek"):
        key = f"{provider}_api_key"
        value = redacted.get(key)
        if provider == "deepseek" and not value:
            value = ai_config.deepseek_api_key
        configured = bool(str(value or "").strip())
        user_has_override = False
        if not getattr(user, "is_admin", False):
            try:
                user_has_override = await config_service.is_user_override(user.id, key)
            except Exception:
                pass
        if getattr(user, "is_admin", False) or not user_has_override:
            redacted.pop(key, None)
        redacted[f"{provider}_api_key_configured"] = configured
        redacted[f"{provider}_uses_admin_default"] = bool(
            configured
            and not getattr(user, "is_admin", False)
            and not user_has_override
        )
    return redacted
