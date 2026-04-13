"""
Database-backed configuration management service for LandPPT
Supports per-user isolated configuration settings
"""

import os
import json
import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from ..core.config import ai_config, resolve_timeout_seconds


class DatabaseConfigService:
    """
    Database-backed configuration management service with per-user isolation.
    
    Configuration hierarchy:
    1. User-specific config (stored in DB with user_id)
    2. System default config (stored in DB with user_id=NULL)
    3. Schema default (hardcoded in config_schema)
    4. Environment variables (only for SYSTEM_ONLY_KEYS)
    """
    
    # System-only keys that should not be stored in database
    # These are read from environment variables only
    SYSTEM_ONLY_KEYS = {
        "database_url", "secret_key", "host", "port", "base_url"
    }
    
    # Categories that should only be visible/editable by admins
    ADMIN_ONLY_CATEGORIES = {
        "app_config", "feature_flags"
    }
    
    def __init__(self):
        # Configuration schema (same as original ConfigService)
        self.config_schema = {
            # AI Provider Configuration
            "openai_api_key": {"type": "password", "category": "ai_providers"},
            "openai_base_url": {"type": "url", "category": "ai_providers", "default": "https://api.openai.com/v1"},
            "openai_model": {"type": "select", "category": "ai_providers", "default": "gpt-4.1"},
            "openai_use_responses_api": {"type": "boolean", "category": "ai_providers", "default": "false"},
            "openai_enable_reasoning": {"type": "boolean", "category": "ai_providers", "default": "false"},
            "openai_reasoning_effort": {"type": "select", "category": "ai_providers", "default": "medium"},
            
            "anthropic_api_key": {"type": "password", "category": "ai_providers"},
            "anthropic_base_url": {"type": "url", "category": "ai_providers", "default": "https://api.anthropic.com"},
            "anthropic_model": {"type": "select", "category": "ai_providers", "default": "claude-3.5-haiku-20240307"},

            "google_api_key": {"type": "password", "category": "ai_providers"},
            "google_base_url": {"type": "url", "category": "ai_providers", "default": "https://generativelanguage.googleapis.com"},
            "google_model": {"type": "text", "category": "ai_providers", "default": "gemini-2.5-flash"},
            
            "ollama_base_url": {"type": "url", "category": "ai_providers", "default": "http://localhost:11434"},
            "ollama_model": {"type": "text", "category": "ai_providers", "default": "llama2"},
            
            # LandPPT Official Provider (system-level, admin-only for API key and base_url)
            "landppt_api_key": {"type": "password", "category": "ai_providers", "admin_only": True},
            "landppt_base_url": {"type": "url", "category": "ai_providers", "default": "https://api.openai.com/v1", "admin_only": True},
            "landppt_model": {"type": "text", "category": "ai_providers", "default": "MODEL1"},
            
            "default_ai_provider": {"type": "select", "category": "ai_providers", "default": "landppt"},
            
            # Model Role Overrides
            "default_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "default_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "outline_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "outline_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "creative_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "creative_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "image_prompt_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "image_prompt_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "slide_generation_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "slide_generation_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "editor_assistant_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "editor_assistant_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "template_generation_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "template_generation_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "speech_script_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "speech_script_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "vision_analysis_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "vision_analysis_model_name": {"type": "text", "category": "model_roles", "default": ""},
            "polish_model_provider": {"type": "select", "category": "model_roles", "default": ""},
            "polish_model_name": {"type": "text", "category": "model_roles", "default": ""},
            
            # Generation Parameters
            "max_tokens": {"type": "number", "category": "generation_params", "default": "16384"},
            "temperature": {"type": "number", "category": "generation_params", "default": "0.7"},
            "top_p": {"type": "number", "category": "generation_params", "default": "1.0"},
            "llm_timeout_seconds": {"type": "number", "category": "generation_params", "default": "600"},
            "tts_voice_zh": {"type": "text", "category": "generation_params", "default": "zh-CN-XiaoxiaoNeural"},
            "tts_voice_en": {"type": "text", "category": "generation_params", "default": "en-US-JennyNeural"},
            "comfyui_base_url": {"type": "url", "category": "generation_params", "default": "http://127.0.0.1:8188"},
            "comfyui_tts_workflow_path": {"type": "text", "category": "generation_params", "default": "tests/Qwen3-TD-TTS.json"},
            "comfyui_tts_timeout_seconds": {"type": "number", "category": "generation_params", "default": "600"},
            "comfyui_tts_chunk_chars": {"type": "number", "category": "generation_params", "default": "120"},
            "comfyui_tts_force_precision": {"type": "text", "category": "generation_params", "default": ""},
            
            # Parallel Generation Configuration
            "enable_parallel_generation": {"type": "boolean", "category": "generation_params", "default": "true"},
            "parallel_slides_count": {"type": "number", "category": "generation_params", "default": "3"},
            "enable_per_slide_creative_guidance": {"type": "boolean", "category": "generation_params", "default": "true"},
            
            "tavily_api_key": {"type": "password", "category": "generation_params"},
            "tavily_max_results": {"type": "number", "category": "generation_params", "default": "10"},
            "tavily_search_depth": {"type": "select", "category": "generation_params", "default": "advanced"},

            # SearXNG Configuration
            "searxng_host": {"type": "url", "category": "generation_params"},
            "searxng_max_results": {"type": "number", "category": "generation_params", "default": "10"},
            "searxng_language": {"type": "text", "category": "generation_params", "default": "auto"},
            "searxng_timeout": {"type": "number", "category": "generation_params", "default": "30"},

            # Research Configuration
            "research_provider": {"type": "select", "category": "generation_params", "default": "tavily"},
            "research_enable_content_extraction": {"type": "boolean", "category": "generation_params", "default": "true"},
            "research_max_content_length": {"type": "number", "category": "generation_params", "default": "5000"},
            "research_extraction_timeout": {"type": "number", "category": "generation_params", "default": "30"},

            "enable_apryse_pptx_export": {
                "type": "boolean",
                "category": "generation_params",
                "default": "false",
                "admin_only": True,
            },
            "apryse_license_key": {"type": "password", "category": "generation_params", "admin_only": True},
            
            # Mineru API Configuration
            "mineru_api_key": {"type": "password", "category": "generation_params"},
            "mineru_base_url": {"type": "url", "category": "generation_params", "default": "https://mineru.net/api/v4"},
            
            # Feature Flags
            "enable_network_mode": {"type": "boolean", "category": "feature_flags", "default": "true"},
            "enable_local_models": {"type": "boolean", "category": "feature_flags", "default": "false"},
            "enable_streaming": {"type": "boolean", "category": "feature_flags", "default": "true"},
            "enable_auto_layout_repair": {"type": "boolean", "category": "generation_params", "default": "false"},
            "log_level": {"type": "select", "category": "feature_flags", "default": "INFO"},
            "log_ai_requests": {"type": "boolean", "category": "feature_flags", "default": "false"},
            "debug": {"type": "boolean", "category": "feature_flags", "default": "true"},
            
            # App Configuration (system-only keys are handled separately)
            # NOTE: base_url is system-only (stored in env/.env) but is included in schema so admin UI can
            # load/save it via `/api/config/app_config`.
            "base_url": {"type": "url", "category": "app_config", "default": "http://localhost:8000", "admin_only": True},
            "reload": {"type": "boolean", "category": "app_config", "default": "true"},
            "access_token_expire_minutes": {"type": "number", "category": "app_config", "default": "20160"},  # 2 weeks
            "max_file_size": {"type": "number", "category": "app_config", "default": "10485760"},
            "upload_dir": {"type": "text", "category": "app_config", "default": "uploads"},
            "cache_ttl": {"type": "number", "category": "app_config", "default": "3600"},

            # OAuth Login Configuration
            "github_oauth_enabled": {"type": "boolean", "category": "oauth_settings", "default": "false", "admin_only": True},
            "github_client_id": {"type": "text", "category": "oauth_settings", "default": "", "admin_only": True},
            "github_client_secret": {"type": "password", "category": "oauth_settings", "default": "", "admin_only": True},
            "github_callback_url": {"type": "url", "category": "oauth_settings", "default": "", "admin_only": True},
            "github_callback_use_request_host": {"type": "boolean", "category": "oauth_settings", "default": "false", "admin_only": True},
            "linuxdo_oauth_enabled": {"type": "boolean", "category": "oauth_settings", "default": "false", "admin_only": True},
            "linuxdo_client_id": {"type": "text", "category": "oauth_settings", "default": "", "admin_only": True},
            "linuxdo_client_secret": {"type": "password", "category": "oauth_settings", "default": "", "admin_only": True},
            "linuxdo_callback_url": {"type": "url", "category": "oauth_settings", "default": "", "admin_only": True},

            # Image Service Configuration
            "enable_image_service": {"type": "boolean", "category": "image_service", "default": "false"},
            "enable_local_images": {"type": "boolean", "category": "image_service", "default": "true"},
            "enable_network_search": {"type": "boolean", "category": "image_service", "default": "false"},
            "enable_ai_generation": {"type": "boolean", "category": "image_service", "default": "false"},
            "local_images_smart_selection": {"type": "boolean", "category": "image_service", "default": "true"},
            "max_local_images_per_slide": {"type": "number", "category": "image_service", "default": "2"},
            "default_network_search_provider": {"type": "select", "category": "image_service", "default": "unsplash"},
            "max_network_images_per_slide": {"type": "number", "category": "image_service", "default": "2"},
            "default_ai_image_provider": {"type": "select", "category": "image_service", "default": "dalle"},
            "max_ai_images_per_slide": {"type": "number", "category": "image_service", "default": "1"},
            "ai_image_quality": {"type": "select", "category": "image_service", "default": "standard"},
            "ai_image_resolution_presets": {
                "type": "text",
                "category": "image_service",
                "default": "{\"dalle\":[\"1792x1024\",\"1024x1792\",\"1024x1024\"],\"openai_image\":[\"1536x1024\",\"1024x1536\",\"1024x1024\"],\"siliconflow\":[\"1024x1024\",\"1024x2048\",\"1536x1024\",\"2048x1152\",\"1152x2048\"],\"gemini\":[\"1024x1024\",\"1344x768\",\"768x1344\"],\"pollinations\":[\"1024x1024\",\"1344x768\",\"768x1344\",\"1536x1024\",\"1024x1536\"]}"
            },
            "max_total_images_per_slide": {"type": "number", "category": "image_service", "default": "3"},
            "enable_smart_image_selection": {"type": "boolean", "category": "image_service", "default": "true"},

            # Image Generation Providers
            "openai_api_key_image": {"type": "password", "category": "image_service"},
            "stability_api_key": {"type": "password", "category": "image_service"},
            "siliconflow_api_key": {"type": "password", "category": "image_service"},

            # Pollinations Image Generation Configuration
            "pollinations_api_key": {"type": "password", "category": "image_service"},
            "pollinations_api_base": {"type": "url", "category": "image_service", "default": "https://gen.pollinations.ai"},
            "pollinations_model": {"type": "text", "category": "image_service", "default": "flux"},
            "pollinations_negative_prompt": {"type": "text", "category": "image_service", "default": "worst quality, blurry"},
            "pollinations_enhance": {"type": "boolean", "category": "image_service", "default": "false"},
            "pollinations_safe": {"type": "boolean", "category": "image_service", "default": "false"},




            # Gemini Image Generation Configuration
            "gemini_image_api_key": {"type": "password", "category": "image_service"},
            "gemini_image_api_base": {"type": "url", "category": "image_service", "default": "https://generativelanguage.googleapis.com/v1beta"},
            "gemini_image_model": {"type": "text", "category": "image_service", "default": "gemini-2.0-flash-exp-image-generation"},

            # OpenAI Image Generation Configuration
            "openai_image_api_key": {"type": "password", "category": "image_service"},
            "openai_image_api_base": {"type": "url", "category": "image_service", "default": "https://api.openai.com/v1"},
            "openai_image_model": {"type": "text", "category": "image_service", "default": "gpt-image-1"},
            "openai_image_quality": {"type": "select", "category": "image_service", "default": "auto"},

            # Image Search Providers
            "unsplash_access_key": {"type": "password", "category": "image_service"},
            "pixabay_api_key": {"type": "password", "category": "image_service"},
            "searxng_host": {"type": "url", "category": "image_service"},
            "dalle_image_size": {"type": "select", "category": "image_service", "default": "1792x1024"},
            "dalle_image_quality": {"type": "select", "category": "image_service", "default": "standard"},
            "dalle_image_style": {"type": "select", "category": "image_service", "default": "natural"},
            "siliconflow_image_size": {"type": "select", "category": "image_service", "default": "1024x1024"},
            "siliconflow_steps": {"type": "number", "category": "image_service", "default": "20"},
            "siliconflow_guidance_scale": {"type": "number", "category": "image_service", "default": "7.5"},
        }
    
    def _convert_type(self, value: Optional[str], value_type: str) -> Any:
        """Convert string value to appropriate type"""
        if value is None:
            return None
        
        if value_type == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes", "on")
        elif value_type == "number":
            try:
                if "." in str(value):
                    return float(value)
                return int(value)
            except (ValueError, TypeError):
                return 0
        else:
            return value
    
    def _serialize_value(self, value: Any, value_type: str) -> str:
        """Serialize value to string for storage"""
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _resolve_config_values(
        self,
        db_configs_user: Dict[str, Dict[str, Any]],
        db_configs_system: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Resolve the final config map from user, system and schema defaults."""
        config: Dict[str, Any] = {}

        for key, schema in self.config_schema.items():
            if key in self.SYSTEM_ONLY_KEYS:
                env_key = key.upper()
                value = os.getenv(env_key, schema.get("default", ""))
            elif schema.get("admin_only", False):
                system_value = db_configs_system.get(key)
                merged_value = db_configs_user.get(key)
                if system_value is not None:
                    value = system_value["value"]
                elif merged_value is not None and not merged_value.get("is_user_override", False):
                    # System-scope reads pass system rows through db_configs_user with is_user_override=False.
                    value = merged_value["value"]
                else:
                    value = schema.get("default", "")
            elif key in db_configs_user:
                value = db_configs_user[key]["value"]
            elif key in db_configs_system:
                value = db_configs_system[key]["value"]
            else:
                value = schema.get("default", "")

            config[key] = self._convert_type(value, schema["type"])

        return config

    def _load_db_configs_sync(self, session, user_id: Optional[int]) -> Dict[str, Dict[str, Any]]:
        """Load raw config rows for one scope using the sync SQLAlchemy session."""
        from sqlalchemy import select

        from ..database.models import UserConfig

        stmt = select(UserConfig)
        if user_id is None:
            stmt = stmt.where(UserConfig.user_id.is_(None))
        else:
            stmt = stmt.where(UserConfig.user_id == user_id)

        result = session.execute(stmt)
        configs: Dict[str, Dict[str, Any]] = {}
        for item in result.scalars().all():
            configs[item.config_key] = {
                "value": item.config_value,
                "type": item.config_type,
                "category": item.category,
            }
        return configs
    
    async def get_all_config(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Get all configuration values for a user"""
        from ..database.database import AsyncSessionLocal
        from ..database.repositories import UserConfigRepository

        async with AsyncSessionLocal() as session:
            repo = UserConfigRepository(session)
            # Load both user-specific and system-level defaults (user_id=None).
            # User-specific values override system defaults.
            db_configs_user = await repo.get_all_configs(user_id)
            db_configs_system = {} if user_id is None else await repo.get_all_configs(None)

        return self._resolve_config_values(db_configs_user, db_configs_system)

    def get_all_config_sync(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Get all configuration values for a user using the sync database session."""
        from ..database.database import SessionLocal

        with SessionLocal() as session:
            db_configs_user = self._load_db_configs_sync(session, user_id)
            db_configs_system = {} if user_id is None else self._load_db_configs_sync(session, None)

        return self._resolve_config_values(db_configs_user, db_configs_system)
    
    async def get_config_by_category(self, category: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Get configuration values by category for a user"""
        all_config = await self.get_all_config(user_id)
        return {
            key: value
            for key, value in all_config.items()
            if self.config_schema.get(key, {}).get("category") == category
        }
    
    async def update_config(self, config: Dict[str, Any], user_id: Optional[int] = None) -> bool:
        """Update configuration values for a user"""
        from ..database.database import AsyncSessionLocal
        from ..database.repositories import UserConfigRepository
        
        try:
            # Track which categories were updated for selective reload
            updated_categories = set()
            updated_system_scope = False
            system_only_updates: Dict[str, Any] = {}
             
            async with AsyncSessionLocal() as session:
                repo = UserConfigRepository(session)
                 
                for key, value in config.items():
                    if key in self.SYSTEM_ONLY_KEYS:
                        # Some system-only keys are designed to be updated via admin UI, but must be persisted
                        # to environment/.env rather than DB (e.g., BASE_URL for reverse-proxy absolute URLs).
                        if key == "base_url":
                            system_only_updates[key] = value
                            updated_categories.add("app_config")
                            updated_system_scope = True
                            continue

                        logger.warning(f"Skipping system-only key: {key}")
                        continue
                     
                    if key in self.config_schema:
                        schema = self.config_schema[key]
                        
                        # For admin_only keys, always save to system-level config (user_id=None)
                        # This ensures keys like landppt_api_key are accessible to all users
                        effective_user_id = user_id
                        if schema.get("admin_only", False):
                            effective_user_id = None
                            logger.info(f"Saving admin-only key '{key}' to system-level config")
                            updated_system_scope = True
                        
                        await repo.set_config(
                            user_id=effective_user_id,
                            key=key,
                            value=self._serialize_value(value, schema["type"]),
                            config_type=schema["type"],
                            category=schema["category"]
                        )
                        updated_categories.add(schema["category"])
                
                await session.commit()
            
            # Apply system-only updates to .env / process environment
            if system_only_updates:
                try:
                    from .config_service import get_config_service
                    env_config_service = get_config_service()
                    env_config_service.update_config(system_only_updates)
                    logger.info(f"Applied system-only config updates to environment: {list(system_only_updates.keys())}")
                except Exception as e:
                    logger.error(f"Failed to apply system-only config updates: {e}")

            logger.info(f"Updated {len(config)} config values for user {user_id}, categories: {updated_categories}")
             
            # Reload global services when system-scope values changed (user_id=None or admin-only keys saved to system scope).
            # Per-user config is otherwise read dynamically from DB when services are used.
            if user_id is None or updated_system_scope:
                self._reload_services_for_categories(updated_categories)
            else:
                logger.info(f"Per-user config saved for user {user_id}, will be applied on next service request")
             
            return True
            
        except Exception as e:
            logger.error(f"Failed to update config for user {user_id}: {e}")
            return False
    
    def _reload_services_for_categories(self, categories: set):
        """Reload relevant services based on which config categories were updated"""
        try:
            if "ai_providers" in categories or "model_roles" in categories:
                # Reload AI configuration
                from ..core.config import reload_ai_config, ai_config
                from ..ai.providers import reload_ai_providers
                
                logger.info("Reloading AI configuration due to provider/model changes...")
                reload_ai_config()
                reload_ai_providers()
                logger.info("AI configuration and providers reloaded")
            
            if "generation_params" in categories:
                # Reload research and generation services
                from .service_instances import reload_services
                logger.info("Reloading service instances due to generation param changes...")
                reload_services()
                logger.info("Service instances reloaded")
            
            if "image_service" in categories:
                # Reload image service configuration
                logger.info("Image service config updated, will take effect on next request")
                
        except Exception as e:
            logger.error(f"Failed to reload services after config update: {e}")
            import traceback
            logger.error(f"Reload traceback: {traceback.format_exc()}")
    
    async def reset_user_config(self, user_id: int, category: Optional[str] = None) -> bool:
        """Reset user config to system defaults"""
        from ..database.database import AsyncSessionLocal
        from ..database.repositories import UserConfigRepository
        
        if user_id is None:
            return False
        
        try:
            async with AsyncSessionLocal() as session:
                repo = UserConfigRepository(session)
                count = await repo.reset_user_configs(user_id, category)
                await session.commit()
                logger.info(f"Reset {count} configs for user {user_id}")
                return True
        except Exception as e:
            logger.error(f"Failed to reset config for user {user_id}: {e}")
            return False
    
    async def get_config_value(self, key: str, user_id: Optional[int] = None) -> Any:
        """Get a single config value for a user"""
        from ..database.database import AsyncSessionLocal
        from ..database.repositories import UserConfigRepository
        
        if key in self.SYSTEM_ONLY_KEYS:
            env_key = key.upper()
            default = self.config_schema.get(key, {}).get("default", "")
            return os.getenv(env_key, default)
        
        schema = self.config_schema.get(key, {"type": "text"})
        effective_user_id = None if schema.get("admin_only", False) else user_id

        async with AsyncSessionLocal() as session:
            repo = UserConfigRepository(session)
            value = await repo.get_config(effective_user_id, key)
             
            # Fall back to system defaults (user_id=None) when user-specific is missing
            if value is None and effective_user_id is not None:
                value = await repo.get_config(None, key)

            if value is None:
                value = self.config_schema.get(key, {}).get("default", "")
             
            return self._convert_type(value, schema["type"])

    def get_config_value_sync(self, key: str, user_id: Optional[int] = None) -> Any:
        """Get a single config value for a user using the sync database session."""
        from sqlalchemy import select

        from ..database.database import SessionLocal
        from ..database.models import UserConfig

        if key in self.SYSTEM_ONLY_KEYS:
            env_key = key.upper()
            default = self.config_schema.get(key, {}).get("default", "")
            return os.getenv(env_key, default)

        schema = self.config_schema.get(key, {"type": "text"})
        effective_user_id = None if schema.get("admin_only", False) else user_id

        def _query_value(session, scope_user_id: Optional[int]):
            stmt = select(UserConfig.config_value).where(UserConfig.config_key == key)
            if scope_user_id is None:
                stmt = stmt.where(UserConfig.user_id.is_(None))
            else:
                stmt = stmt.where(UserConfig.user_id == scope_user_id)
            return session.execute(stmt).scalar_one_or_none()

        with SessionLocal() as session:
            value = _query_value(session, effective_user_id)
            if value is None and effective_user_id is not None:
                value = _query_value(session, None)

        if value is None:
            value = self.config_schema.get(key, {}).get("default", "")

        return self._convert_type(value, schema["type"])

    async def is_user_override(self, user_id: int, key: str) -> bool:
        """
        Return True if the given key is explicitly set for the user (not inherited from system defaults).

        Note: This checks DB storage only (not env/schema fallbacks).
        """
        from sqlalchemy import select

        from ..database.database import AsyncSessionLocal
        from ..database.models import UserConfig

        async with AsyncSessionLocal() as session:
            stmt = select(UserConfig.id).where(
                UserConfig.user_id == user_id,
                UserConfig.config_key == key,
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None
    
    def get_config_schema(self, include_admin_only: bool = True) -> Dict[str, Any]:
        """Get configuration schema, optionally excluding admin-only keys/categories."""
        if include_admin_only:
            return self.config_schema
        
        # Filter out admin-only categories and individual admin-only keys for regular users.
        return {
            key: schema
            for key, schema in self.config_schema.items()
            if schema.get("category") not in self.ADMIN_ONLY_CATEGORIES
            and not schema.get("admin_only", False)
        }
    
    async def get_all_config_for_user(self, user_id: int, is_admin: bool = False) -> Dict[str, Any]:
        """Get all configuration values for a user, filtering admin-only keys/categories if not admin."""
        all_config = await self.get_all_config(user_id)
        
        if is_admin:
            return all_config
        
        # Filter out admin-only categories and individual admin-only keys.
        return {
            key: value
            for key, value in all_config.items()
            if self.config_schema.get(key, {}).get("category") not in self.ADMIN_ONLY_CATEGORIES
            and not self.config_schema.get(key, {}).get("admin_only", False)
        }
    
    async def initialize_system_defaults(self) -> int:
        """
        Initialize system default configs from schema defaults.
        Safe to call multiple times:
        - Creates missing system default keys from schema defaults
        - Applies small default-value migrations when needed
        """
        from ..database.database import AsyncSessionLocal
        from ..database.repositories import UserConfigRepository
         
        try:
            async with AsyncSessionLocal() as session:
                repo = UserConfigRepository(session)
                 
                count = 0
                existing = await repo.get_all_configs(user_id=None)
                existing_values = {
                    key: (info or {}).get("value")
                    for key, info in (existing or {}).items()
                }

                for key, schema in self.config_schema.items():
                    if key in self.SYSTEM_ONLY_KEYS:
                        continue

                    if key in existing_values:
                        continue

                    default_value = schema.get("default", "")
                    await repo.set_config(
                        user_id=None,  # System default
                        key=key,
                        value=str(default_value) if default_value else "",
                        config_type=schema["type"],
                        category=schema["category"],
                    )
                    count += 1

                # Legacy default migration: LandPPT default model used to be gpt-4o; update to MODEL1
                try:
                    legacy_value = (existing_values.get("landppt_model") or "").strip()
                    desired_default = str(self.config_schema.get("landppt_model", {}).get("default", "MODEL1")).strip()
                    if legacy_value == "gpt-4o" and desired_default:
                        await repo.set_config(
                            user_id=None,
                            key="landppt_model",
                            value=desired_default,
                            config_type=self.config_schema["landppt_model"]["type"],
                            category=self.config_schema["landppt_model"]["category"],
                        )
                        count += 1
                except Exception:
                    pass

                # Legacy default migration: real-time creative guidance used to default to false.
                # Promote untouched historical system defaults to the new default true.
                try:
                    legacy_value = str(existing_values.get("enable_per_slide_creative_guidance") or "").strip().lower()
                    desired_default = str(
                        self.config_schema.get("enable_per_slide_creative_guidance", {}).get("default", "true")
                    ).strip().lower()
                    if legacy_value == "false" and desired_default == "true":
                        await repo.set_config(
                            user_id=None,
                            key="enable_per_slide_creative_guidance",
                            value=desired_default,
                            config_type=self.config_schema["enable_per_slide_creative_guidance"]["type"],
                            category=self.config_schema["enable_per_slide_creative_guidance"]["category"],
                        )
                        count += 1
                except Exception:
                    pass

                if count:
                    await session.commit()

                logger.info(f"Initialized/updated {count} system default configs")
                return count
                 
        except Exception as e:
            logger.error(f"Failed to initialize system defaults: {e}")
            return 0


# Global instance
_db_config_service: Optional[DatabaseConfigService] = None


def get_db_config_service() -> DatabaseConfigService:
    """Get database config service instance"""
    global _db_config_service
    if _db_config_service is None:
        _db_config_service = DatabaseConfigService()
    return _db_config_service


def _build_user_ai_provider_config(
    user_config: Dict[str, Any],
    provider_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Build provider config from a resolved user config map."""
    resolved_provider = provider_name or user_config.get("default_ai_provider") or "openai"

    provider_configs = {
        "openai": {
            "api_key": user_config.get("openai_api_key"),
            "base_url": user_config.get("openai_base_url"),
            "model": user_config.get("openai_model"),
            "use_responses_api": user_config.get("openai_use_responses_api"),
            "enable_reasoning": user_config.get("openai_enable_reasoning"),
            "reasoning_effort": user_config.get("openai_reasoning_effort"),
            "llm_timeout_seconds": user_config.get("llm_timeout_seconds"),
        },
        "anthropic": {
            "api_key": user_config.get("anthropic_api_key"),
            "base_url": user_config.get("anthropic_base_url"),
            "model": user_config.get("anthropic_model"),
            "llm_timeout_seconds": user_config.get("llm_timeout_seconds"),
        },
        "google": {
            "api_key": user_config.get("google_api_key"),
            "base_url": user_config.get("google_base_url"),
            "model": user_config.get("google_model"),
            "llm_timeout_seconds": user_config.get("llm_timeout_seconds"),
        },
        "ollama": {
            "base_url": user_config.get("ollama_base_url"),
            "model": user_config.get("ollama_model"),
            "llm_timeout_seconds": user_config.get("llm_timeout_seconds"),
        },
        "landppt": {
            "api_key": user_config.get("landppt_api_key"),
            "base_url": user_config.get("landppt_base_url"),
            "model": user_config.get("landppt_model"),
            "llm_timeout_seconds": user_config.get("llm_timeout_seconds"),
        },
    }
    provider_configs["gemini"] = dict(provider_configs["google"])

    config = dict(provider_configs.get(resolved_provider, provider_configs["landppt"]))
    config["provider_name"] = resolved_provider

    if resolved_provider == "landppt":
        logger.info(
            "LandPPT config retrieved - api_key present: %s, base_url: %s, model: %s",
            bool(config.get("api_key")),
            config.get("base_url"),
            config.get("model"),
        )

    return config


async def get_user_ai_provider_config(user_id: int, provider_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get AI provider configuration for a specific user.
    
    Args:
        user_id: The user ID
        provider_name: Optional provider name (if None, get default provider)
        
    Returns:
        Dictionary with provider configuration
    """
    config_service = get_db_config_service()

    user_config = await config_service.get_all_config(user_id=user_id)
    return _build_user_ai_provider_config(user_config, provider_name)


def get_user_ai_provider_config_sync(user_id: int, provider_name: Optional[str] = None) -> Dict[str, Any]:
    """Get AI provider configuration for a specific user using the sync DB session."""
    config_service = get_db_config_service()
    user_config = config_service.get_all_config_sync(user_id=user_id)
    return _build_user_ai_provider_config(user_config, provider_name)


async def get_user_llm_timeout_seconds(user_id: Optional[int] = None) -> int:
    """Resolve the effective LLM request timeout for a user or system scope."""
    config_service = get_db_config_service()
    raw_timeout = await config_service.get_config_value("llm_timeout_seconds", user_id=user_id)
    return resolve_timeout_seconds(raw_timeout, ai_config.llm_timeout_seconds)


async def get_user_ai_provider(user_id: int, provider_name: Optional[str] = None):
    """
    Get an AI provider instance configured for a specific user.
    
    Args:
        user_id: The user ID
        provider_name: Optional provider name (if None, uses user's default)
        
    Returns:
        AIProvider instance configured with user's settings
    """
    from ..ai.providers import AIProviderFactory
    
    config = await get_user_ai_provider_config(user_id, provider_name)
    actual_provider = config.pop("provider_name")
    
    return AIProviderFactory.create_provider(actual_provider, config)


def get_user_ai_provider_sync(user_id: int, provider_name: Optional[str] = None):
    """Get a sync AI provider instance configured for a specific user."""
    from ..ai.providers import AIProviderFactory

    config = get_user_ai_provider_config_sync(user_id, provider_name)
    actual_provider = config.pop("provider_name")
    return AIProviderFactory.create_provider(actual_provider, config)


async def get_user_role_provider(
    user_id: int,
    role: str,
    provider_override: Optional[str] = None,
) -> Tuple[Any, Dict[str, Optional[str]]]:
    """
    Get provider + role settings for a user, using DB config (with system-default fallback).
    """
    config_service = get_db_config_service()
    user_config = await config_service.get_all_config(user_id=user_id)

    role_key = (role or "default").lower()
    role_provider_key, role_model_key = ai_config.MODEL_ROLE_FIELDS.get(
        role_key,
        ("default_model_provider", "default_model_name") if role_key == "default"
        else (f"{role_key}_model_provider", f"{role_key}_model_name"),
    )

    provider_name = provider_override or user_config.get(role_provider_key)
    # If the role provider isn't explicitly set, fall back to the user's default provider.
    # (If the user has no default provider configured, fall back to LandPPT.)
    if not provider_name:
        provider_name = user_config.get("default_ai_provider") or "landppt"

    if isinstance(provider_name, str) and provider_name.strip().lower() == "gemini":
        provider_name = "google"
    model = user_config.get(role_model_key)

    if not model:
        provider_model_key = f"{provider_name}_model"
        model = user_config.get(provider_model_key)

    settings: Dict[str, Optional[str]] = {
        "role": role_key,
        "provider": provider_name,
        "model": model,
    }

    from ..ai.providers import AIProviderFactory

    provider_config = _build_user_ai_provider_config(user_config, provider_name)
    actual_provider = provider_config.pop("provider_name")
    provider = AIProviderFactory.create_provider(actual_provider, provider_config)
    return provider, settings


def get_user_role_provider_sync(
    user_id: int,
    role: str,
    provider_override: Optional[str] = None,
) -> Tuple[Any, Dict[str, Optional[str]]]:
    """Sync variant of get_user_role_provider using the sync DB session."""
    from ..ai.providers import AIProviderFactory

    config_service = get_db_config_service()
    user_config = config_service.get_all_config_sync(user_id=user_id)

    role_key = (role or "default").lower()
    role_provider_key, role_model_key = ai_config.MODEL_ROLE_FIELDS.get(
        role_key,
        ("default_model_provider", "default_model_name") if role_key == "default"
        else (f"{role_key}_model_provider", f"{role_key}_model_name"),
    )

    provider_name = provider_override or user_config.get(role_provider_key)
    if not provider_name:
        provider_name = user_config.get("default_ai_provider") or "landppt"

    if isinstance(provider_name, str) and provider_name.strip().lower() == "gemini":
        provider_name = "google"

    model = user_config.get(role_model_key)
    if not model:
        provider_model_key = f"{provider_name}_model"
        model = user_config.get(provider_model_key)

    settings: Dict[str, Optional[str]] = {
        "role": role_key,
        "provider": provider_name,
        "model": model,
    }

    provider_config = _build_user_ai_provider_config(user_config, provider_name)
    actual_provider = provider_config.pop("provider_name")
    provider = AIProviderFactory.create_provider(actual_provider, provider_config)
    return provider, settings
