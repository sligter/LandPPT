"""
Generated route module extracted from the legacy web router.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
import uuid
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from ...ai import AIMessage, MessageRole, get_ai_provider, get_role_provider
from ...api.models import FileOutlineGenerationRequest, PPTGenerationRequest, PPTProject, TodoBoard
from ...auth.middleware import get_current_user_optional, get_current_user_required
from ...core.config import ai_config, app_config, resolve_timeout_seconds
from ...database.database import AsyncSessionLocal, get_db
from ...database.models import User
from ...services.provider_test_utils import (
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_GOOGLE_BASE_URL,
    DEFAULT_GOOGLE_MODEL,
    build_anthropic_messages_url,
    build_anthropic_test_payload,
    build_google_generate_content_url,
    build_google_test_payload,
    extract_anthropic_test_result,
    extract_google_test_result,
    extract_openai_compatible_test_result,
    normalize_provider_name,
)
from ...services.enhanced_ppt_service import EnhancedPPTService
from ...services.pdf_to_pptx_converter import get_pdf_to_pptx_converter
from ...services.pyppeteer_pdf_converter import get_pdf_converter
from ...utils.thread_pool import run_blocking_io, to_thread
from .support import (
    _apply_no_store_headers,
    check_credits_for_operation,
    consume_credits_for_operation,
    get_ppt_service_for_user,
    logger,
    ppt_service,
    templates,
)

router = APIRouter()


async def _get_llm_timeout_seconds_for_user(user_id: Optional[int]) -> int:
    """Resolve the effective LLM timeout with DB-config fallback."""
    try:
        from ...services.db_config_service import get_user_llm_timeout_seconds

        return await get_user_llm_timeout_seconds(user_id=user_id)
    except Exception as exc:
        logger.debug("Falling back to global LLM timeout for user %s: %s", user_id, exc)
        return resolve_timeout_seconds(None, ai_config.llm_timeout_seconds)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@router.get("/home", response_class=HTMLResponse)
async def web_home(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Main web interface home page - redirect to dashboard for existing users"""
    # Check if user has projects, if so redirect to dashboard
    try:
        projects_response = await ppt_service.project_manager.list_projects(page=1, page_size=1, user_id=user.id)
        if projects_response.total > 0:
            # User has projects, redirect to dashboard
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/dashboard", status_code=302)
    except:
        pass  # If error, show index page

    from ...services.db_config_service import get_db_config_service
    config_service = get_db_config_service()
    current_config = await config_service.get_all_config(user_id=user.id)

    current_provider = current_config.get("default_ai_provider") or ai_config.default_ai_provider
    if (isinstance(current_provider, str) and current_provider.strip().lower() == "gemini"):
        current_provider = "google"

    # New user or error, show index page
    return templates.TemplateResponse("pages/home/index.html", {
        "request": request,
        "ai_provider": current_provider,
        "available_providers": ai_config.get_available_providers()
    })


@router.get("/ai-config", response_class=HTMLResponse)
async def web_ai_config(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """AI configuration page"""
    from ...services.db_config_service import get_db_config_service

    config_service = get_db_config_service()
    # Keep system defaults in sync (admin only).
    if getattr(user, "is_admin", False):
        try:
            await config_service.initialize_system_defaults()
        except Exception:
            pass

        # Backward-compatible promotion: if an admin previously saved a Tavily key as a user override,
        # promote it to system scope so other users can use research without configuring their own key.
        try:
            system_tavily = await config_service.get_config_value("tavily_api_key", user_id=None)
            if not system_tavily and await config_service.is_user_override(user.id, "tavily_api_key"):
                admin_config = await config_service.get_all_config(user_id=user.id)
                admin_tavily = admin_config.get("tavily_api_key")
                if admin_tavily:
                    await config_service.update_config({"tavily_api_key": admin_tavily}, user_id=None)
        except Exception:
            pass
    # Get user-specific config (merged with system defaults)
    current_config = await config_service.get_all_config(user_id=user.id)
    system_config = await config_service.get_all_config(user_id=None)
    schema = config_service.get_config_schema(include_admin_only=True)
    current_config = _filter_config_for_user(full_config=current_config, schema=schema, user=user)
    # Never expose sensitive system defaults (e.g. admin Tavily key) in rendered HTML.
    current_config = await _redact_sensitive_config_for_frontend(
        full_config=current_config,
        user=user,
        config_service=config_service,
    )

    # "gemini" is an alias for the Google provider; the UI exposes it as "google".
    current_provider = current_config.get("default_ai_provider") or ai_config.default_ai_provider
    if (isinstance(current_provider, str) and current_provider.strip().lower() == "gemini"):
        current_provider = "google"

    def _is_provider_configured(provider: str) -> bool:
        name = (provider or "").strip().lower()

        def _has_value(value: Any) -> bool:
            if value is None:
                return False
            if isinstance(value, bool):
                return value
            return bool(str(value).strip())

        if name == "openai":
            return _has_value(current_config.get("openai_api_key"))
        if name == "anthropic":
            return _has_value(current_config.get("anthropic_api_key"))
        if name in {"google", "gemini"}:
            return _has_value(current_config.get("google_api_key"))
        if name == "ollama":
            # Ollama is a local provider; treat it as configured when local models are enabled.
            return _has_value(current_config.get("enable_local_models"))
        if name == "landppt":
            # LandPPT credentials are system-scoped; non-admin users can still use it if configured.
            return _has_value(system_config.get("landppt_api_key")) and _has_value(system_config.get("landppt_base_url"))

        return False

    provider_status = {
        provider: _is_provider_configured(provider)
        for provider in ["landppt", "openai", "anthropic", "google", "ollama"]
    }

    return templates.TemplateResponse("pages/settings/ai_config.html", {
        "request": request,
        "current_provider": current_provider,
        "available_providers": ai_config.get_available_providers(),
        "provider_status": provider_status,
        "current_config": current_config,
        "user": user.to_dict()
    })


@router.get("/api/config/ai_providers")
async def get_ai_providers_config(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Get AI providers configuration for the current user (LandPPT system credentials are hidden for non-admins)."""
    from ...services.db_config_service import get_db_config_service

    config_service = get_db_config_service()
    # Get user-specific config (merged with system defaults)
    current_config = await config_service.get_all_config(user_id=user.id)
    
    # Return the config with the relevant provider keys.
    # LandPPT API key / base URL are system-level admin-only values and should not be exposed to non-admin users.
    config: Dict[str, Any] = {
        "openai_api_key": current_config.get("openai_api_key", ""),
        "openai_base_url": current_config.get("openai_base_url", ""),
        "openai_model": current_config.get("openai_model", ""),
        "openai_use_responses_api": current_config.get("openai_use_responses_api", False),
        "openai_enable_reasoning": current_config.get("openai_enable_reasoning", False),
        "openai_reasoning_effort": current_config.get("openai_reasoning_effort", "medium"),
        "anthropic_api_key": current_config.get("anthropic_api_key", ""),
        "anthropic_base_url": current_config.get("anthropic_base_url", ""),
        "anthropic_model": current_config.get("anthropic_model", ""),
        "google_api_key": current_config.get("google_api_key", ""),
        "google_base_url": current_config.get("google_base_url", ""),
        "google_model": current_config.get("google_model", ""),
        "ollama_base_url": current_config.get("ollama_base_url", ""),
        "ollama_model": current_config.get("ollama_model", ""),
        "landppt_model": current_config.get("landppt_model", ""),
    }
    if user.is_admin:
        config["landppt_api_key"] = current_config.get("landppt_api_key", "")
        config["landppt_base_url"] = current_config.get("landppt_base_url", "")

    return {
        "success": True,
        "config": config,
    }


@router.post("/api/config/ai_providers")
async def update_ai_providers_config(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """
    Update AI provider configuration.

    - Normal users can only update their own provider keys.
    - Admin-only keys (e.g. LandPPT API key/base URL) are accepted only for admins and are stored at system scope.
    """
    from ...services.db_config_service import get_db_config_service

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    config = payload.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Invalid request: 'config' must be an object")

    config_service = get_db_config_service()
    schema = config_service.get_config_schema(include_admin_only=True)

    filtered_config: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    for key, value in config.items():
        if key not in schema:
            errors[key] = "Unknown config key"
            continue

        settings = schema[key]
        if settings.get("category") != "ai_providers":
            errors[key] = "Key is not part of ai_providers category"
            continue

        if settings.get("admin_only", False) and not user.is_admin:
            errors[key] = "Admin-only key"
            continue

        filtered_config[key] = value

    if not filtered_config:
        return {
            "success": False if errors else True,
            "message": "No valid configuration keys to update",
            "errors": errors or None,
        }

    success = await config_service.update_config(filtered_config, user_id=user.id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update AI provider configuration")

    return {
        "success": True,
        "message": "AI provider configuration updated successfully",
        "errors": errors or None,
    }


def _filter_config_for_user(
    *,
    full_config: Dict[str, Any],
    schema: Dict[str, Any],
    user: User,
) -> Dict[str, Any]:
    """Hide admin-only keys for non-admin users."""
    if getattr(user, "is_admin", False):
        return full_config

    filtered: Dict[str, Any] = {}
    for key, value in full_config.items():
        settings = schema.get(key) or {}
        if settings.get("admin_only", False):
            continue
        filtered[key] = value
    return filtered


async def _redact_sensitive_config_for_frontend(
    *,
    full_config: Dict[str, Any],
    user: User,
    config_service: Any,
) -> Dict[str, Any]:
    """
    Redact sensitive values so they are never sent to the browser.

    We keep "configured" signals so the UI can show masked placeholders without
    exposing the actual secret. This is especially important for system-scoped
    defaults that apply to all users (e.g. admin Tavily key).
    """
    redacted: Dict[str, Any] = dict(full_config)

    # Tavily: never expose the system/admin default key to the frontend.
    # If a normal user has their own override, it's OK to return it to *that* user.
    tavily_value = redacted.get("tavily_api_key")
    tavily_configured = bool(str(tavily_value).strip()) if tavily_value is not None else False

    user_has_override = False
    if not getattr(user, "is_admin", False):
        try:
            user_has_override = await config_service.is_user_override(user.id, "tavily_api_key")
        except Exception:
            user_has_override = False

    if getattr(user, "is_admin", False) or not user_has_override:
        # Admin/system value (or inherited value): never return to browser.
        redacted.pop("tavily_api_key", None)

    redacted["tavily_api_key_configured"] = tavily_configured
    redacted["tavily_uses_admin_default"] = bool(
        tavily_configured and (not getattr(user, "is_admin", False)) and (not user_has_override)
    )

    return redacted


async def _update_config_category(
    *,
    category: str,
    request: Request,
    user: User,
) -> Dict[str, Any]:
    from ...services.db_config_service import get_db_config_service

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    config = payload.get("config")
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="Invalid request: 'config' must be an object")

    config_service = get_db_config_service()
    schema = config_service.get_config_schema(include_admin_only=True)

    filtered_config: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    for key, value in config.items():
        if key not in schema:
            errors[key] = "Unknown config key"
            continue

        settings = schema[key]
        if settings.get("category") != category:
            errors[key] = f"Key is not part of {category} category"
            continue

        if settings.get("admin_only", False) and not getattr(user, "is_admin", False):
            errors[key] = "Admin-only key"
            continue

        filtered_config[key] = value

    if not filtered_config:
        return {
            "success": False if errors else True,
            "message": "No valid configuration keys to update",
            "errors": errors or None,
        }

    # For some sensitive settings (e.g. Tavily key), admins act as the "system default"
    # so other users can use research without entering their own key. Store those
    # values at system scope (user_id=None) without ever exposing them to the UI.
    system_scoped: Dict[str, Any] = {}
    user_scoped: Dict[str, Any] = dict(filtered_config)

    if category == "generation_params" and getattr(user, "is_admin", False):
        if "tavily_api_key" in user_scoped:
            system_scoped["tavily_api_key"] = user_scoped.pop("tavily_api_key")

    if system_scoped:
        ok = await config_service.update_config(system_scoped, user_id=None)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to update {category} configuration")

    if user_scoped:
        ok = await config_service.update_config(user_scoped, user_id=user.id)
        if not ok:
            raise HTTPException(status_code=500, detail=f"Failed to update {category} configuration")

    return {
        "success": True,
        "message": f"{category} configuration updated successfully",
        "errors": errors or None,
    }


@router.get("/api/config/all")
async def get_all_config(
    user: User = Depends(get_current_user_required),
):
    """Get merged user config (user overrides system defaults)."""
    from ...services.db_config_service import get_db_config_service

    config_service = get_db_config_service()
    schema = config_service.get_config_schema(include_admin_only=True)
    config = await config_service.get_all_config(user_id=user.id)
    config = _filter_config_for_user(full_config=config, schema=schema, user=user)
    config = await _redact_sensitive_config_for_frontend(full_config=config, user=user, config_service=config_service)
    return {"success": True, "config": config}


@router.get("/api/config/{category}")
async def get_config_by_category(
    category: str,
    user: User = Depends(get_current_user_required),
):
    """Get config values by category for the current user."""
    from ...services.db_config_service import get_db_config_service

    config_service = get_db_config_service()
    schema = config_service.get_config_schema(include_admin_only=True)
    # Validate category
    allowed_categories = {v.get("category") for v in schema.values() if isinstance(v, dict) and v.get("category")}
    if category not in allowed_categories:
        raise HTTPException(status_code=404, detail="Unknown config category")

    config = await config_service.get_config_by_category(category, user_id=user.id)
    config = _filter_config_for_user(full_config=config, schema=schema, user=user)
    config = await _redact_sensitive_config_for_frontend(full_config=config, user=user, config_service=config_service)
    return {"success": True, "config": config}


@router.post("/api/config/default-provider")
async def set_default_ai_provider(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    """Set user's default AI provider."""
    from ...services.db_config_service import get_db_config_service

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    provider = payload.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise HTTPException(status_code=400, detail="Invalid request: 'provider' must be a non-empty string")

    normalized = provider.strip().lower()
    # "gemini" is an alias for Google in this project
    if normalized == "gemini":
        normalized = "google"

    allowed = {p.strip().lower() for p in ai_config.get_available_providers()}
    if normalized not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    config_service = get_db_config_service()
    ok = await config_service.update_config({"default_ai_provider": normalized}, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to set default provider")

    return {"success": True, "provider": normalized}


@router.post("/api/config/generation_params")
async def update_generation_params(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    return await _update_config_category(category="generation_params", request=request, user=user)


@router.post("/api/config/app_config")
async def update_app_config(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    return await _update_config_category(category="app_config", request=request, user=user)


@router.post("/api/config/image_service")
async def update_image_service_config(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    return await _update_config_category(category="image_service", request=request, user=user)


@router.post("/api/config/model_roles")
async def update_model_roles_config(
    request: Request,
    user: User = Depends(get_current_user_required),
):
    return await _update_config_category(category="model_roles", request=request, user=user)


@router.get("/api/ai/providers/landppt/models")
async def get_landppt_models(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Get LandPPT models - fetched server-side using system config (no credentials exposed)"""
    import aiohttp
    from ...services.db_config_service import get_db_config_service

    try:
        config_service = get_db_config_service()
        # Get system config (user_id=None for system level)
        system_config = await config_service.get_all_config(user_id=None)
        
        api_key = system_config.get("landppt_api_key", "")
        base_url = system_config.get("landppt_base_url", "")
        
        if not api_key or not base_url:
            return {"success": False, "error": "LandPPT 系统配置未设置", "models": []}
        
        # Ensure base URL ends with /v1
        if not base_url.endswith('/v1'):
            base_url = base_url.rstrip('/') + '/v1'
        
        models_url = f"{base_url}/models"
        logger.info(f"Fetching LandPPT models from: {models_url}")
        timeout_seconds = await _get_llm_timeout_seconds_for_user(user.id)
        
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            
            async with session.get(
                models_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    models = []
                    if 'data' in data and isinstance(data['data'], list):
                        models = sorted([m['id'] for m in data['data'] if m.get('id')])
                    
                    logger.info(f"Successfully fetched {len(models)} LandPPT models")
                    return {"success": True, "models": models}
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to fetch LandPPT models: {response.status} - {error_text}")
                    return {"success": False, "error": f"请求失败: {response.status}", "models": []}
    except Exception as e:
        logger.error(f"Error fetching LandPPT models: {e}")
        return {"success": False, "error": str(e), "models": []}


@router.post("/api/ai/providers/test")
async def test_provider_connection(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """按提供商协议测试连接，避免把非 OpenAI 服务误判为兼容接口。"""
    import aiohttp
    from ...services.db_config_service import get_db_config_service

    try:
        data = await request.json()
        provider = normalize_provider_name(data.get('provider', ''))

        if not provider:
            return {"success": False, "error": "未指定提供者"}

        config_service = get_db_config_service()

        # LandPPT 使用系统级配置，其余提供商使用用户配置。
        if provider == 'landppt':
            config = await config_service.get_all_config(user_id=None)
        else:
            config = await config_service.get_all_config(user_id=user.id)

        def _normalize_reasoning_effort(value: Any) -> str:
            normalized = str(value or "medium").strip().lower()
            return normalized if normalized in {"none", "minimal", "low", "medium", "high", "xhigh"} else "medium"

        api_key = data.get('api_key') or config.get(f"{provider}_api_key", "")
        base_url = data.get('base_url') or config.get(f"{provider}_base_url", "")
        model = data.get('model') or config.get(f"{provider}_model", "")
        use_responses_api = (
            _coerce_bool(data.get("use_responses_api"))
            if "use_responses_api" in data
            else _coerce_bool(config.get("openai_use_responses_api"))
        )
        enable_reasoning = (
            _coerce_bool(data.get("enable_reasoning"))
            if "enable_reasoning" in data
            else _coerce_bool(config.get("openai_enable_reasoning"))
        )
        reasoning_effort = (
            _normalize_reasoning_effort(data.get("reasoning_effort"))
            if "reasoning_effort" in data
            else _normalize_reasoning_effort(config.get("openai_reasoning_effort"))
        )

        if not api_key:
            return {"success": False, "error": "API Key 未配置"}

        if not base_url:
            default_urls = {
                'openai': 'https://api.openai.com/v1',
                'anthropic': DEFAULT_ANTHROPIC_BASE_URL,
                'google': DEFAULT_GOOGLE_BASE_URL,
                'landppt': 'https://api.openai.com/v1',
            }
            base_url = default_urls.get(provider, '')
            if not base_url:
                return {"success": False, "error": "Base URL 未配置"}

        if not model:
            default_models = {
                'openai': 'gpt-3.5-turbo',
                'anthropic': DEFAULT_ANTHROPIC_MODEL,
                'google': DEFAULT_GOOGLE_MODEL,
                'landppt': 'gpt-4o',
            }
            model = default_models.get(provider, 'gpt-3.5-turbo')

        timeout_seconds = resolve_timeout_seconds(
            config.get("llm_timeout_seconds"),
            ai_config.llm_timeout_seconds,
        )
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        async with aiohttp.ClientSession() as session:
            # Google/Gemini 和 Anthropic 不是 OpenAI 兼容协议，必须按原生接口测试。
            if provider == "google":
                request_url = build_google_generate_content_url(base_url, model)
                payload = build_google_test_payload("Hi")
                logger.info("Testing %s connection at: %s (transport=gemini_generate_content)", provider, request_url)

                primary_status = None
                primary_error_text = ""
                async with session.post(
                    request_url,
                    params={"key": api_key},
                    json=payload,
                    timeout=timeout,
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        response_preview, usage = extract_google_test_result(response_data)
                        logger.info("%s connection test successful", provider)
                        return {
                            "success": True,
                            "message": "连接成功！",
                            "provider": provider,
                            "model": model,
                            "response_preview": response_preview or "连接成功，模型已响应",
                            "usage": usage,
                        }
                    primary_status = response.status
                    primary_error_text = await response.text()

                fallback_status = None
                fallback_error_text = ""
                async with session.post(
                    request_url,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": api_key,
                    },
                    json=payload,
                    timeout=timeout,
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        response_preview, usage = extract_google_test_result(response_data)
                        logger.info("%s connection test successful via x-goog-api-key fallback", provider)
                        return {
                            "success": True,
                            "message": "连接成功！",
                            "provider": provider,
                            "model": model,
                            "response_preview": response_preview or "连接成功，模型已响应",
                            "usage": usage,
                        }
                    fallback_status = response.status
                    fallback_error_text = await response.text()

                logger.error(
                    "%s connection test failed: primary=%s - %s; fallback=%s - %s",
                    provider,
                    primary_status,
                    primary_error_text,
                    fallback_status,
                    fallback_error_text,
                )
                return {"success": False, "error": f"请求失败: {fallback_status or primary_status}"}

            if provider == "anthropic":
                request_url = build_anthropic_messages_url(base_url)
                payload = build_anthropic_test_payload("Hi")
                payload["model"] = model
                logger.info("Testing %s connection at: %s (transport=anthropic_messages)", provider, request_url)

                async with session.post(
                    request_url,
                    headers={
                        "x-api-key": api_key,
                        "Content-Type": "application/json",
                        "anthropic-version": "2023-06-01",
                    },
                    json=payload,
                    timeout=timeout,
                ) as response:
                    if response.status == 200:
                        response_data = await response.json()
                        response_preview, usage = extract_anthropic_test_result(response_data)
                        logger.info("%s connection test successful", provider)
                        return {
                            "success": True,
                            "message": "连接成功！",
                            "provider": provider,
                            "model": model,
                            "response_preview": response_preview or "连接成功，模型已响应",
                            "usage": usage,
                        }

                    error_text = await response.text()
                    logger.error("%s connection test failed: %s - %s", provider, response.status, error_text)
                    return {"success": False, "error": f"请求失败: {response.status}"}

            # OpenAI、LandPPT 等兼容服务继续沿用 OpenAI 协议。
            if not base_url.endswith('/v1'):
                base_url = base_url.rstrip('/') + '/v1'

            use_openai_responses_api = provider == "openai" and use_responses_api
            request_url = f"{base_url}/responses" if use_openai_responses_api else f"{base_url}/chat/completions"
            logger.info(
                "Testing %s connection at: %s (responses_api=%s)",
                provider,
                request_url,
                use_openai_responses_api,
            )

            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }

            if use_openai_responses_api:
                payload = {
                    "model": model,
                    "input": "Hi",
                    "max_output_tokens": 500,
                    "temperature": 0,
                }
                if enable_reasoning:
                    payload["reasoning"] = {"effort": reasoning_effort}
            else:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 500
                }
                if provider == "openai" and enable_reasoning:
                    payload["reasoning_effort"] = reasoning_effort

            async with session.post(
                request_url,
                headers=headers,
                json=payload,
                timeout=timeout,
            ) as response:
                if response.status == 200:
                    response_data = await response.json()
                    response_preview, usage = extract_openai_compatible_test_result(
                        response_data,
                        use_responses_api=use_openai_responses_api,
                    )
                    logger.info("%s connection test successful", provider)
                    return {
                        "success": True,
                        "message": "连接成功！",
                        "provider": provider,
                        "model": model,
                        "response_preview": response_preview or "连接成功，模型已响应",
                        "usage": usage,
                    }

                error_text = await response.text()
                logger.error("%s connection test failed: %s - %s", provider, response.status, error_text)
                return {"success": False, "error": f"请求失败: {response.status}"}
    except Exception as e:
        logger.error(f"Error testing provider connection: {e}")
        return {"success": False, "error": str(e)}


@router.get("/image-generation-test", response_class=HTMLResponse)
async def web_image_generation_test(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """AI图片生成测试页面"""
    return templates.TemplateResponse("pages/image/image_generation_test.html", {
        "request": request,
        "user": user.to_dict()
    })


@router.post("/api/ai/providers/openai/models")
async def get_openai_models(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Proxy endpoint to get OpenAI models list, avoiding CORS issues - uses frontend provided config"""
    try:
        import aiohttp
        import json
        
        # Get configuration from frontend request
        data = await request.json()
        base_url = data.get('base_url', 'https://api.openai.com/v1')
        api_key = data.get('api_key', '')
        
        logger.info(f"Frontend requested models from: {base_url}")
        
        if not api_key:
            return {"success": False, "error": "API Key is required"}
        
        # Ensure base URL ends with /v1
        if not base_url.endswith('/v1'):
            base_url = base_url.rstrip('/') + '/v1'
        
        models_url = f"{base_url}/models"
        logger.info(f"Fetching models from: {models_url}")
        timeout_seconds = resolve_timeout_seconds(
            data.get("llm_timeout_seconds"),
            await _get_llm_timeout_seconds_for_user(user.id),
        )
        
        # Make request to OpenAI API using frontend provided credentials
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            
            async with session.get(
                models_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Filter and sort models
                    models = []
                    if 'data' in data and isinstance(data['data'], list):
                        for model in data['data']:
                            if model.get('id'):
                                models.append({
                                    'id': model['id'],
                                    'created': model.get('created', 0),
                                    'owned_by': model.get('owned_by', 'unknown')
                                })
                        
                        # Sort models with GPT-4 first, then GPT-3.5, then others
                        def get_priority(model_id):
                            if 'gpt-4' in model_id:
                                return 0
                            elif 'gpt-3.5' in model_id:
                                return 1
                            else:
                                return 2
                        
                        models.sort(key=lambda x: (get_priority(x['id']), x['id']))
                    logger.info(f"Successfully fetched {len(models)} models from {base_url}")
                    return {"success": True, "models": models}
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to fetch models from {base_url}: {response.status} - {error_text}")
                    return {"success": False, "error": f"API returned status {response.status}: {error_text}"}
                    
    except Exception as e:
        logger.error(f"Error fetching OpenAI models from frontend config: {e}")
        return {"success": False, "error": str(e)}


@router.post("/api/ai/providers/openai/test")
async def test_openai_provider_proxy(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Proxy endpoint to test OpenAI provider, avoiding CORS issues - uses frontend provided config"""
    try:
        import aiohttp
        import json
        
        # Get configuration from frontend request
        data = await request.json()
        base_url = data.get('base_url', 'https://api.openai.com/v1')
        api_key = data.get('api_key', '')
        model = data.get('model', 'gpt-4o')
        max_tokens = 500
        use_responses_api = str(data.get("use_responses_api", "")).strip().lower() in {"1", "true", "yes", "on"}
        enable_reasoning = str(data.get("enable_reasoning", "")).strip().lower() in {"1", "true", "yes", "on"}
        reasoning_effort = str(data.get("reasoning_effort") or "medium").strip().lower()
        if reasoning_effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}:
            reasoning_effort = "medium"
        
        logger.info(f"Frontend requested test with: base_url={base_url}, model={model}")
        
        if not api_key:
            return {"success": False, "error": "API Key is required"}
        
        # Ensure base URL ends with /v1
        if not base_url.endswith('/v1'):
            base_url = base_url.rstrip('/') + '/v1'
        
        request_url = f"{base_url}/responses" if use_responses_api else f"{base_url}/chat/completions"
        logger.info(f"Testing OpenAI provider at: {request_url} (responses_api={use_responses_api})")
        timeout_seconds = resolve_timeout_seconds(
            data.get("llm_timeout_seconds"),
            await _get_llm_timeout_seconds_for_user(user.id),
        )
        
        # Make test request to OpenAI API using frontend provided credentials
        async with aiohttp.ClientSession() as session:
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            
            if use_responses_api:
                payload = {
                    "model": model,
                    "input": "Say 'Hello, I am working!' in exactly 5 words.",
                    "temperature": 0,
                    "max_output_tokens": max_tokens,
                }
                if enable_reasoning:
                    payload["reasoning"] = {"effort": reasoning_effort}
            else:
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "user",
                            "content": "Say 'Hello, I am working!' in exactly 5 words."
                        }
                    ],
                    "temperature": 0,
                    "max_tokens": max_tokens
                }
                if enable_reasoning:
                    payload["reasoning_effort"] = reasoning_effort
            
            async with session.post(
                request_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    logger.info(f"Test successful for {base_url} with model {model}")
                    
                    if use_responses_api:
                        message_text = data.get("output_text", "")
                        usage_data = data.get("usage") or {}
                        usage = {
                            "prompt_tokens": usage_data.get("input_tokens", 0),
                            "completion_tokens": usage_data.get("output_tokens", 0),
                            "total_tokens": usage_data.get("total_tokens", 0),
                        }
                    else:
                        choices = data.get('choices') or []
                        message_text = ""
                        if choices and choices[0].get('message') and choices[0]['message'].get('content'):
                            message_text = choices[0]['message']['content']
                        usage = data.get('usage', {
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0
                        })

                    return {
                        "success": True,
                        "status": "success",  # Add status field for compatibility
                        "provider": "openai",
                        "model": model,
                        "response_preview": message_text,
                        "usage": usage
                    }
                else:
                    error_text = await response.text()
                    try:
                        error_data = json.loads(error_text)
                        error_message = error_data.get('error', {}).get('message', f"API returned status {response.status}")
                    except:
                        error_message = f"API returned status {response.status}: {error_text}"
                    
                    logger.error(f"Test failed for {base_url}: {error_message}")
                    
                    return {
                        "success": False,
                        "status": "error",  # Add status field for compatibility
                        "error": error_message
                    }

    except Exception as e:
        logger.error(f"Error testing OpenAI provider with frontend config: {e}")
        return {
            "success": False,
            "status": "error",  # Add status field for compatibility
            "error": str(e)
        }


@router.post("/api/ai/providers/anthropic/test")
async def test_anthropic_provider_proxy(
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Proxy endpoint to test Anthropic provider, avoiding CORS issues - uses frontend provided config"""
    try:
        import aiohttp

        # Get configuration from frontend request
        data = await request.json()
        base_url = data.get('base_url', 'https://api.anthropic.com')
        api_key = data.get('api_key', '')
        model = data.get('model', 'claude-3-5-sonnet-20241022')

        logger.info(f"Frontend requested Anthropic test with: base_url={base_url}, model={model}")

        if not api_key:
            return {"success": False, "error": "API Key is required"}

        # Ensure base URL format
        base_url = base_url.rstrip('/')
        if not base_url.endswith('/v1'):
            base_url = base_url + '/v1'

        messages_url = f"{base_url}/messages"
        logger.info(f"Testing Anthropic provider at: {messages_url}")
        timeout_seconds = resolve_timeout_seconds(
            data.get("llm_timeout_seconds"),
            await _get_llm_timeout_seconds_for_user(user.id),
        )

        # Make test request to Anthropic API using frontend provided credentials
        async with aiohttp.ClientSession() as session:
            headers = {
                'x-api-key': api_key,
                'Content-Type': 'application/json',
                'anthropic-version': '2023-06-01'
            }

            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": "Say 'Hello, I am working!' in exactly 5 words."
                    }
                ],
                "max_tokens": 1024,
                "temperature": 0
            }

            async with session.post(
                messages_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as response:
                if response.status == 200:
                    data = await response.json()

                    logger.info(f"Anthropic test successful for {base_url} with model {model}")

                    # Anthropic response format: data.content[0].text
                    content = data.get('content', [])
                    response_text = content[0].get('text', '') if content else ''

                    # Anthropic usage format: input_tokens, output_tokens
                    # Frontend expects: prompt_tokens, completion_tokens, total_tokens
                    anthropic_usage = data.get('usage', {})
                    usage = {
                        "prompt_tokens": anthropic_usage.get('input_tokens', 0),
                        "completion_tokens": anthropic_usage.get('output_tokens', 0),
                        "total_tokens": anthropic_usage.get('input_tokens', 0) + anthropic_usage.get('output_tokens', 0)
                    }

                    # Return with consistent format that frontend expects
                    return {
                        "success": True,
                        "status": "success",
                        "provider": "anthropic",
                        "model": model,
                        "response_preview": response_text,
                        "usage": usage
                    }
                else:
                    error_text = await response.text()
                    try:
                        error_data = json.loads(error_text)
                        error_message = error_data.get('error', {}).get('message', f"API returned status {response.status}")
                    except:
                        error_message = f"API returned status {response.status}: {error_text}"

                    logger.error(f"Anthropic test failed for {base_url}: {error_message}")

                    return {
                        "success": False,
                        "status": "error",
                        "error": error_message
                    }

    except Exception as e:
        logger.error(f"Error testing Anthropic provider with frontend config: {e}")
        return {
            "success": False,
            "status": "error",
            "error": str(e)
        }
