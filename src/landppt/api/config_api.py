"""
Configuration management API for LandPPT
Supports per-user isolated configuration and system-level defaults
"""

from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
import logging

from ..services.db_config_service import (
    get_db_config_service,
    DatabaseConfigService,
    get_user_llm_timeout_seconds,
)
from ..auth.middleware import get_current_admin_user, get_current_user_required
from ..database.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


# Pydantic models
class ConfigUpdateRequest(BaseModel):
    config: Dict[str, Any]


class DefaultProviderRequest(BaseModel):
    provider: str


# ==================== User Config Endpoints ====================
# These endpoints allow users to manage their own configuration

@router.get("/api/config/user")
async def get_user_config(
    user: User = Depends(get_current_user_required)
):
    """Get current user's configuration (merged with system defaults, excluding admin-only categories)"""
    try:
        config_service = get_db_config_service()
        # Use get_all_config_for_user which filters admin-only categories for non-admins
        config = await config_service.get_all_config_for_user(user_id=user.id, is_admin=user.is_admin)
        return {
            "success": True,
            "config": config,
            "user_id": user.id,
            "is_admin": user.is_admin
        }
    except Exception as e:
        logger.error(f"Failed to get user configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user configuration")


@router.get("/api/config/user/{category}")
async def get_user_config_by_category(
    category: str,
    user: User = Depends(get_current_user_required)
):
    """Get user's configuration for a specific category"""
    try:
        config_service = get_db_config_service()
        schema = config_service.get_config_schema(include_admin_only=True)
        config = await config_service.get_all_config_for_user(user_id=user.id, is_admin=user.is_admin)
        config = {
            key: value
            for key, value in config.items()
            if schema.get(key, {}).get("category") == category
        }
        return {
            "success": True,
            "config": config,
            "category": category
        }
    except Exception as e:
        logger.error(f"Failed to get user configuration for category {category}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get configuration for category {category}")


@router.post("/api/config/user")
async def update_user_config(
    request: ConfigUpdateRequest,
    user: User = Depends(get_current_user_required)
):
    """Update current user's configuration"""
    try:
        config_service = get_db_config_service()

        # Prevent non-admin users from updating admin-only keys (which are stored at system scope).
        schema = config_service.get_config_schema(include_admin_only=True)
        admin_only_keys = {
            key for key, settings in schema.items()
            if settings.get("admin_only", False)
        }

        filtered_config = request.config
        if not user.is_admin:
            filtered_config = {
                key: value for key, value in (request.config or {}).items()
                if key not in admin_only_keys
            }

        success = await config_service.update_config(filtered_config, user_id=user.id)
        
        if success:
            return {
                "success": True,
                "message": "User configuration updated successfully"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update user configuration")
            
    except Exception as e:
        logger.error(f"Failed to update user configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to update user configuration")


@router.post("/api/config/user/{category}")
async def update_user_config_by_category(
    category: str,
    request: ConfigUpdateRequest,
    user: User = Depends(get_current_user_required)
):
    """Update user's configuration for a specific category"""
    try:
        config_service = get_db_config_service()

        # Disallow updates to admin-only categories for non-admin users.
        if not user.is_admin and category in getattr(config_service, "ADMIN_ONLY_CATEGORIES", set()):
            raise HTTPException(status_code=403, detail="Not authorized to update this category")
        
        # Filter config to only include keys from the specified category
        schema = config_service.get_config_schema()
        filtered_config = {
            key: value
            for key, value in request.config.items()
            if key in schema
            and schema[key].get("category") == category
            and (user.is_admin or not schema[key].get("admin_only", False))
        }
        
        success = await config_service.update_config(filtered_config, user_id=user.id)
        
        if success:
            return {
                "success": True,
                "message": f"User configuration for {category} updated successfully"
            }
        else:
            raise HTTPException(status_code=500, detail=f"Failed to update configuration for {category}")
            
    except Exception as e:
        logger.error(f"Failed to update user configuration for category {category}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update configuration for {category}")


@router.post("/api/config/user/reset")
async def reset_user_config(
    user: User = Depends(get_current_user_required)
):
    """Reset user's configuration to system defaults"""
    try:
        config_service = get_db_config_service()
        success = await config_service.reset_user_config(user.id)
        
        if success:
            return {
                "success": True,
                "message": "User configuration reset to system defaults"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to reset user configuration")
            
    except Exception as e:
        logger.error(f"Failed to reset user configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset user configuration")


@router.post("/api/config/user/reset/{category}")
async def reset_user_config_by_category(
    category: str,
    user: User = Depends(get_current_user_required)
):
    """Reset user's configuration for a specific category to system defaults"""
    try:
        config_service = get_db_config_service()
        success = await config_service.reset_user_config(user.id, category=category)
        
        if success:
            return {
                "success": True,
                "message": f"User configuration for {category} reset to system defaults"
            }
        else:
            raise HTTPException(status_code=500, detail=f"Failed to reset configuration for {category}")
            
    except Exception as e:
        logger.error(f"Failed to reset user configuration for category {category}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset configuration for {category}")


# Set default AI provider for user
@router.post("/api/config/default-provider")
async def set_user_default_provider(
    request: DefaultProviderRequest,
    user: User = Depends(get_current_user_required)
):
    """Set default AI provider for current user"""
    try:
        config_service = get_db_config_service()
        success = await config_service.update_config(
            {"default_ai_provider": request.provider},
            user_id=user.id
        )

        if success:
            return {
                "success": True,
                "message": f"Default provider set to {request.provider}",
                "provider": request.provider
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to set default provider")

    except Exception as e:
        logger.error(f"Failed to set default provider: {e}")
        raise HTTPException(status_code=500, detail="Failed to set default provider")


@router.get("/api/config/current-provider")
async def get_user_current_provider(
    user: User = Depends(get_current_user_required)
):
    """Get current user's default AI provider"""
    try:
        config_service = get_db_config_service()
        provider = await config_service.get_config_value("default_ai_provider", user_id=user.id)
        
        return {
            "success": True,
            "current_provider": provider
        }
    except Exception as e:
        logger.error(f"Failed to get current provider: {e}")
        raise HTTPException(status_code=500, detail="Failed to get current provider")


@router.get("/api/config/schema")
async def get_config_schema(
    user: User = Depends(get_current_user_required)
):
    """Get configuration schema (excluding admin-only categories for non-admins)"""
    try:
        config_service = get_db_config_service()
        # Filter out admin-only categories for non-admin users
        schema = config_service.get_config_schema(include_admin_only=user.is_admin)
        return {
            "success": True,
            "schema": schema,
            "is_admin": user.is_admin
        }
    except Exception as e:
        logger.error(f"Failed to get configuration schema: {e}")
        raise HTTPException(status_code=500, detail="Failed to get configuration schema")


# ==================== Admin System Config Endpoints ====================
# These endpoints allow admins to manage system-wide default configuration

@router.get("/api/config/system")
async def get_system_config(
    user: User = Depends(get_current_admin_user)
):
    """Get system default configuration (admin only)"""
    try:
        config_service = get_db_config_service()
        await config_service.initialize_system_defaults()
        config = await config_service.get_all_config(user_id=None)  # None = system defaults
        return {
            "success": True,
            "config": config,
            "is_system": True
        }
    except Exception as e:
        logger.error(f"Failed to get system configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to get system configuration")


@router.post("/api/config/system")
async def update_system_config(
    request: ConfigUpdateRequest,
    user: User = Depends(get_current_admin_user)
):
    """Update system default configuration (admin only)"""
    try:
        config_service = get_db_config_service()
        success = await config_service.update_config(request.config, user_id=None)  # None = system
        
        if success:
            return {
                "success": True,
                "message": "System configuration updated successfully"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update system configuration")
            
    except Exception as e:
        logger.error(f"Failed to update system configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to update system configuration")


@router.post("/api/config/system/{category}")
async def update_system_config_by_category(
    category: str,
    request: ConfigUpdateRequest,
    user: User = Depends(get_current_admin_user)
):
    """Update system configuration for a specific category (admin only)"""
    try:
        config_service = get_db_config_service()
        
        # Filter config to only include keys from the specified category
        schema = config_service.get_config_schema()
        filtered_config = {
            key: value
            for key, value in request.config.items()
            if key in schema and schema[key].get("category") == category
        }
        
        success = await config_service.update_config(filtered_config, user_id=None)
        
        if success:
            return {
                "success": True,
                "message": f"System configuration for {category} updated successfully"
            }
        else:
            raise HTTPException(status_code=500, detail=f"Failed to update system configuration for {category}")
            
    except Exception as e:
        logger.error(f"Failed to update system configuration for category {category}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update system configuration for {category}")


@router.post("/api/config/system/initialize")
async def initialize_system_config(
    user: User = Depends(get_current_admin_user)
):
    """Initialize system default configurations from schema defaults (admin only)"""
    try:
        config_service = get_db_config_service()
        count = await config_service.initialize_system_defaults()
        
        return {
            "success": True,
            "message": f"Initialized {count} system default configurations",
            "count": count
        }
    except Exception as e:
        logger.error(f"Failed to initialize system configurations: {e}")
        raise HTTPException(status_code=500, detail="Failed to initialize system configurations")


# ==================== Legacy Compatibility Endpoints ====================
# These maintain backward compatibility with old API calls

@router.get("/api/config/all")
async def get_all_config(
    user: User = Depends(get_current_user_required)
):
    """Get all configuration values for current user (legacy compatibility)"""
    try:
        config_service = get_db_config_service()

        # Backward-compatible promotion: if an admin previously saved a Tavily key as a user override,
        # promote it to system scope so other users can use research without configuring their own key.
        if getattr(user, "is_admin", False):
            try:
                system_tavily = await config_service.get_config_value("tavily_api_key", user_id=None)
                if not system_tavily and await config_service.is_user_override(user.id, "tavily_api_key"):
                    admin_config = await config_service.get_all_config(user_id=user.id)
                    admin_tavily = admin_config.get("tavily_api_key")
                    if admin_tavily:
                        await config_service.update_config({"tavily_api_key": admin_tavily}, user_id=None)
            except Exception:
                pass

        config = await config_service.get_all_config(user_id=user.id)
        
        # Filter out admin_only fields for non-admin users
        if not user.is_admin:
            schema = config_service.get_config_schema()
            admin_only_keys = [
                key for key, settings in schema.items()
                if settings.get("admin_only", False)
            ]
            for key in admin_only_keys:
                if key in config:
                    del config[key]

        # Redact sensitive values so system/admin defaults are never sent to the browser.
        # If a normal user has their own override, it's OK to return it to that user.
        tavily_value = config.get("tavily_api_key")
        tavily_configured = bool(str(tavily_value).strip()) if tavily_value is not None else False

        user_has_override = False
        if not getattr(user, "is_admin", False):
            try:
                user_has_override = await config_service.is_user_override(user.id, "tavily_api_key")
            except Exception:
                user_has_override = False

        if getattr(user, "is_admin", False) or not user_has_override:
            config.pop("tavily_api_key", None)

        config["tavily_api_key_configured"] = tavily_configured
        config["tavily_uses_admin_default"] = bool(tavily_configured and (not user.is_admin) and (not user_has_override))
        
        return {
            "success": True,
            "config": config
        }
    except Exception as e:
        logger.error(f"Failed to get configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to get configuration")


@router.post("/api/config/all")
async def update_all_config(
    request: ConfigUpdateRequest,
    user: User = Depends(get_current_user_required)
):
    """Update all configuration values for current user (legacy compatibility)"""
    try:
        config_service = get_db_config_service()

        # Prevent non-admin users from updating admin-only keys (which are stored at system scope).
        schema = config_service.get_config_schema(include_admin_only=True)
        admin_only_keys = {
            key for key, settings in schema.items()
            if settings.get("admin_only", False)
        }

        filtered_config = request.config
        if not user.is_admin:
            filtered_config = {
                key: value for key, value in (request.config or {}).items()
                if key not in admin_only_keys
            }

        # For sensitive settings, admins act as the "system default" so other users can use
        # the feature without configuring their own key.
        system_scoped = {}
        user_scoped = dict(filtered_config or {})
        if getattr(user, "is_admin", False) and "tavily_api_key" in user_scoped:
            system_scoped["tavily_api_key"] = user_scoped.pop("tavily_api_key")

        if system_scoped:
            ok = await config_service.update_config(system_scoped, user_id=None)
            if not ok:
                raise HTTPException(status_code=500, detail="Failed to update configuration")

        success = True
        if user_scoped:
            success = await config_service.update_config(user_scoped, user_id=user.id)
        
        if success:
            return {
                "success": True,
                "message": "Configuration updated successfully"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to update configuration")
            
    except Exception as e:
        logger.error(f"Failed to update configuration: {e}")
        raise HTTPException(status_code=500, detail="Failed to update configuration")


@router.get("/api/config/landppt/models")
async def get_landppt_models(
    user: User = Depends(get_current_user_required)
):
    """
    Fetch available models for LandPPT using system-level config.
    The API key is used on the backend and never exposed to the frontend.
    """
    import aiohttp
    
    try:
        config_service = get_db_config_service()
        
        # Get system-level config (user_id=None)
        api_key = await config_service.get_config_value("landppt_api_key", user_id=None)
        base_url = await config_service.get_config_value("landppt_base_url", user_id=None)
        
        if not api_key:
            return {
                "success": False,
                "error": "管理员尚未配置 LandPPT API Key"
            }
        
        if not base_url:
            base_url = "https://api.openai.com/v1"
        
        # Ensure base URL ends with /v1
        if not base_url.endswith('/v1'):
            base_url = base_url.rstrip('/') + '/v1'
        
        # Fetch models from the API
        models_url = f"{base_url}/models"
        timeout_seconds = await get_user_llm_timeout_seconds(user.id)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                models_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                timeout=aiohttp.ClientTimeout(total=timeout_seconds)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    models = data.get("data", [])
                    # Filter and sort models
                    model_ids = sorted([m.get("id", "") for m in models if m.get("id")])
                    return {
                        "success": True,
                        "models": model_ids
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to fetch LandPPT models: {response.status} - {error_text}")
                    return {
                        "success": False,
                        "error": f"获取模型列表失败: HTTP {response.status}"
                    }
                    
    except Exception as e:
        logger.error(f"Failed to get LandPPT models: {e}")
        return {
            "success": False,
            "error": f"获取模型列表失败: {str(e)}"
        }


@router.post("/api/config/landppt/test")
async def test_landppt_provider(
    user: User = Depends(get_current_user_required)
):
    """
    Test LandPPT provider using system-level config.
    The API key is used on the backend and never exposed to the frontend.
    """
    import aiohttp
    
    try:
        config_service = get_db_config_service()
        
        # Get system-level config (user_id=None)
        api_key = await config_service.get_config_value("landppt_api_key", user_id=None)
        base_url = await config_service.get_config_value("landppt_base_url", user_id=None)
        model = await config_service.get_config_value("landppt_model", user_id=user.id)
        
        if not api_key:
            return {
                "success": False,
                "error": "管理员尚未配置 LandPPT API Key"
            }
        
        if not base_url:
            base_url = "https://api.openai.com/v1"
        
        if not model:
            model = "gpt-4o"
        
        # Ensure base URL ends with /v1
        if not base_url.endswith('/v1'):
            base_url = base_url.rstrip('/') + '/v1'
        
        # Test with a simple chat completion
        test_url = f"{base_url}/chat/completions"
        timeout_seconds = await get_user_llm_timeout_seconds(user.id)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                test_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "max_tokens": 5
                },
                timeout=aiohttp.ClientTimeout(total=timeout_seconds)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "success": True,
                        "message": "LandPPT 提供者测试成功",
                        "model": model,
                        "response_preview": data.get("choices", [{}])[0].get("message", {}).get("content", "")[:50]
                    }
                else:
                    error_text = await response.text()
                    logger.error(f"LandPPT test failed: {response.status} - {error_text}")
                    return {
                        "success": False,
                        "error": f"测试失败: HTTP {response.status}"
                    }
                    
    except Exception as e:
        logger.error(f"Failed to test LandPPT provider: {e}")
        return {
            "success": False,
            "error": f"测试失败: {str(e)}"
        }


# Generic category routes last
@router.get("/api/config/{category}")
async def get_config_by_category(
    category: str,
    user: User = Depends(get_current_user_required)
):
    """Get configuration values by category for current user"""
    try:
        config_service = get_db_config_service()
        if not user.is_admin and category in getattr(config_service, "ADMIN_ONLY_CATEGORIES", set()):
            raise HTTPException(status_code=403, detail="Forbidden")

        config = await config_service.get_config_by_category(category, user_id=user.id)
        
        # Filter out admin_only fields for non-admin users
        if not user.is_admin:
            schema = config_service.get_config_schema()
            admin_only_keys = [
                key for key, settings in schema.items()
                if settings.get("admin_only", False)
            ]
            for key in admin_only_keys:
                if key in config:
                    del config[key]

        # Redact sensitive values so system/admin defaults are never sent to the browser.
        # If a normal user has their own override, it's OK to return it to that user.
        tavily_value = config.get("tavily_api_key")
        tavily_configured = bool(str(tavily_value).strip()) if tavily_value is not None else False

        user_has_override = False
        if not getattr(user, "is_admin", False):
            try:
                user_has_override = await config_service.is_user_override(user.id, "tavily_api_key")
            except Exception:
                user_has_override = False

        if getattr(user, "is_admin", False) or not user_has_override:
            config.pop("tavily_api_key", None)

        config["tavily_api_key_configured"] = tavily_configured
        config["tavily_uses_admin_default"] = bool(tavily_configured and (not user.is_admin) and (not user_has_override))
        
        return {
            "success": True,
            "config": config,
            "category": category
        }
    except Exception as e:
        logger.error(f"Failed to get configuration for category {category}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get configuration for category {category}")


@router.post("/api/config/{category}")
async def update_config_by_category(
    category: str,
    request: ConfigUpdateRequest,
    user: User = Depends(get_current_user_required)
):
    """Update configuration values for a specific category for current user"""
    try:
        config_service = get_db_config_service()
        if not user.is_admin and category in getattr(config_service, "ADMIN_ONLY_CATEGORIES", set()):
            raise HTTPException(status_code=403, detail="Forbidden")
         
        # Filter config to only include keys from the specified category
        schema = config_service.get_config_schema()
        filtered_config = {
            key: value
            for key, value in request.config.items()
            if key in schema and schema[key].get("category") == category
        }

        # For sensitive settings (e.g. Tavily key), admins set the system default.
        system_scoped = {}
        user_scoped = dict(filtered_config or {})
        if category == "generation_params" and getattr(user, "is_admin", False) and "tavily_api_key" in user_scoped:
            system_scoped["tavily_api_key"] = user_scoped.pop("tavily_api_key")

        if system_scoped:
            ok = await config_service.update_config(system_scoped, user_id=None)
            if not ok:
                raise HTTPException(status_code=500, detail=f"Failed to update configuration for {category}")

        success = True
        if user_scoped:
            success = await config_service.update_config(user_scoped, user_id=user.id)
        
        if success:
            return {
                "success": True,
                "message": f"Configuration for {category} updated successfully"
            }
        else:
            raise HTTPException(status_code=500, detail=f"Failed to update configuration for {category}")
            
    except Exception as e:
        logger.error(f"Failed to update configuration for category {category}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update configuration for {category}")
