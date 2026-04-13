"""
Configuration management service for LandPPT
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path
from dotenv import load_dotenv, set_key, unset_key

logger = logging.getLogger(__name__)


class ConfigService:
    """Configuration management service"""
    
    def __init__(self, env_file: str = ".env"):
        self.env_file = env_file
        self.env_path = Path(env_file)
        
        # Ensure .env file exists
        if not self.env_path.exists():
            self.env_path.touch()
        
        # Load environment variables with error handling
        try:
            load_dotenv(self.env_file)
        except (PermissionError, FileNotFoundError) as e:
            logger.warning(f"Could not load .env file {self.env_file}: {e}")
        except Exception as e:
            logger.warning(f"Error loading .env file {self.env_file}: {e}")
        
        # Configuration schema
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
            
            "default_ai_provider": {"type": "select", "category": "ai_providers", "default": "openai"},
            
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
            
            # Feature Flags
            "enable_network_mode": {"type": "boolean", "category": "feature_flags", "default": "true"},
            "enable_local_models": {"type": "boolean", "category": "feature_flags", "default": "false"},
            "enable_streaming": {"type": "boolean", "category": "feature_flags", "default": "true"},
            "enable_auto_layout_repair": {"type": "boolean", "category": "generation_params", "default": "false"},
            "log_level": {"type": "select", "category": "feature_flags", "default": "INFO"},
            "log_ai_requests": {"type": "boolean", "category": "feature_flags", "default": "false"},
            "debug": {"type": "boolean", "category": "feature_flags", "default": "true"},
            
            # App Configuration
            "host": {"type": "text", "category": "app_config", "default": "0.0.0.0"},
            "port": {"type": "number", "category": "app_config", "default": "8000"},
            "base_url": {"type": "url", "category": "app_config", "default": "http://localhost:8000"},
            "reload": {"type": "boolean", "category": "app_config", "default": "true"},
            "secret_key": {"type": "password", "category": "app_config", "default": "your-very-secure-secret-key"},
            "access_token_expire_minutes": {"type": "number", "category": "app_config", "default": "20160"},  # 2 weeks
            "max_file_size": {"type": "number", "category": "app_config", "default": "10485760"},
            "upload_dir": {"type": "text", "category": "app_config", "default": "uploads"},
            "cache_ttl": {"type": "number", "category": "app_config", "default": "3600"},
            "database_url": {"type": "text", "category": "app_config", "default": "sqlite:///./landppt.db"},

            # Image Service Configuration
            "enable_image_service": {"type": "boolean", "category": "image_service", "default": "false"},

            # Multi-source Image Configuration
            "enable_local_images": {"type": "boolean", "category": "image_service", "default": "true"},
            "enable_network_search": {"type": "boolean", "category": "image_service", "default": "false"},
            "enable_ai_generation": {"type": "boolean", "category": "image_service", "default": "false"},

            # Local Images Configuration
            "local_images_smart_selection": {"type": "boolean", "category": "image_service", "default": "true"},
            "max_local_images_per_slide": {"type": "number", "category": "image_service", "default": "2"},

            # Network Search Configuration
            "default_network_search_provider": {"type": "select", "category": "image_service", "default": "unsplash"},
            "max_network_images_per_slide": {"type": "number", "category": "image_service", "default": "2"},

            # AI Generation Configuration
            "default_ai_image_provider": {"type": "select", "category": "image_service", "default": "dalle"},
            "max_ai_images_per_slide": {"type": "number", "category": "image_service", "default": "1"},
            "ai_image_quality": {"type": "select", "category": "image_service", "default": "standard"},
            "ai_image_resolution_presets": {
                "type": "text",
                "category": "image_service",
                # provider => list of allowed WxH strings, single-line JSON to keep .env tidy
                "default": "{\"dalle\":[\"1792x1024\",\"1024x1792\",\"1024x1024\"],\"openai_image\":[\"1536x1024\",\"1024x1536\",\"1024x1024\"],\"siliconflow\":[\"1024x1024\",\"1024x2048\",\"1536x1024\",\"2048x1152\",\"1152x2048\"],\"gemini\":[\"1024x1024\",\"1344x768\",\"768x1344\"],\"pollinations\":[\"1024x1024\",\"1344x768\",\"768x1344\",\"1536x1024\",\"1024x1536\"]}"
            },

            # Global Image Configuration
            "max_total_images_per_slide": {"type": "number", "category": "image_service", "default": "3"},
            "enable_smart_image_selection": {"type": "boolean", "category": "image_service", "default": "true"},

            # Image Generation Providers
            "openai_api_key_image": {"type": "password", "category": "image_service"},
            "stability_api_key": {"type": "password", "category": "image_service"},
            "siliconflow_api_key": {"type": "password", "category": "image_service"},
            "default_ai_image_provider": {"type": "select", "category": "image_service", "default": "dalle"},

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

            # OpenAI Image Generation Configuration (supports custom endpoints)
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
            "siliconflow_steps": {"type": "number", "category": "image_service", "default": 20},
            "siliconflow_guidance_scale": {"type": "number", "category": "image_service", "default": 7.5},
        }
        

    
    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration values"""
        config = {}
        
        for key, schema in self.config_schema.items():
            env_key = key.upper()
            value = os.getenv(env_key)
            
            if value is None:
                value = schema.get("default", "")
            
            # Convert boolean strings
            if schema["type"] == "boolean":
                if isinstance(value, str):
                    value = value.lower() in ("true", "1", "yes", "on")
            
            config[key] = value
        
        return config
    
    def get_config_by_category(self, category: str) -> Dict[str, Any]:
        """Get configuration values by category"""
        config = {}
        
        for key, schema in self.config_schema.items():
            if schema["category"] == category:
                env_key = key.upper()
                value = os.getenv(env_key)
                
                if value is None:
                    value = schema.get("default", "")
                
                # Convert boolean strings
                if schema["type"] == "boolean":
                    if isinstance(value, str):
                        value = value.lower() in ("true", "1", "yes", "on")
                
                config[key] = value
        
        return config
    
    def update_config(self, config: Dict[str, Any]) -> bool:
        """Update configuration values"""
        try:
            for key, value in config.items():
                if key in self.config_schema:
                    env_key = key.upper()

                    # Convert boolean values to strings
                    if isinstance(value, bool):
                        value = "true" if value else "false"
                    else:
                        value = str(value)

                    # Update .env file (without quotes)
                    set_key(self.env_file, env_key, value, quote_mode="never")

                    # Update current environment
                    os.environ[env_key] = value

            # Reload environment variables with error handling
            try:
                load_dotenv(self.env_file, override=True)
            except (PermissionError, FileNotFoundError) as e:
                logger.warning(f"Could not reload .env file {self.env_file}: {e}")
            except Exception as e:
                logger.warning(f"Error reloading .env file {self.env_file}: {e}")

            # Reload AI configuration if any AI-related config was updated
            ai_related_keys = [
                k for k in config.keys()
                if k in self.config_schema and self.config_schema[k]["category"] in {
                    "ai_providers",
                    "generation_params",
                    "model_roles",
                    "feature_flags",
                }
            ]
            if ai_related_keys:
                self._reload_ai_config()

            # Reload app configuration if any app-related config was updated
            app_related_keys = [k for k in config.keys() if k in self.config_schema and
                              self.config_schema[k]["category"] == "app_config"]
            if app_related_keys:
                self._reload_app_config()

            # Reload image service configuration if any image-related config was updated
            image_related_keys = [k for k in config.keys() if k in self.config_schema and
                                self.config_schema[k]["category"] == "image_service"]
            if image_related_keys:
                self._reload_image_config()

            logger.info(f"Updated {len(config)} configuration values")
            return True

        except Exception as e:
            logger.error(f"Failed to update configuration: {e}")
            return False

    def _reload_ai_config(self):
        """Reload AI configuration"""
        try:
            from ..core.config import reload_ai_config, ai_config
            from ..ai.providers import reload_ai_providers
            from .service_instances import reload_services

            logger.info("Starting AI configuration reload process...")

            # Reload AI configuration
            reload_ai_config()
            logger.info(f"AI config reloaded. Tavily API key: {'***' + ai_config.tavily_api_key[-4:] if ai_config.tavily_api_key and len(ai_config.tavily_api_key) > 4 else 'None'}")

            # Clear AI provider cache to force reload with new config
            reload_ai_providers()
            logger.info("AI providers reloaded")

            # Reload service instances to pick up new configuration
            reload_services()
            logger.info("Service instances reloaded")

            logger.info("AI configuration, providers, and services reloaded successfully")
        except Exception as e:
            logger.error(f"Failed to reload AI configuration: {e}")
            import traceback
            logger.error(f"Reload traceback: {traceback.format_exc()}")

    def _reload_app_config(self):
        """Reload application configuration"""
        try:
            from ..core.config import app_config

            # Force reload of app configuration
            app_config.__init__()

            logger.info("Application configuration reloaded successfully")
        except Exception as e:
            logger.error(f"Failed to reload application configuration: {e}")

    def _reload_image_config(self):
        """Reload image service configuration"""
        try:
            from ..services.image.config.image_config import image_config

            # 重新加载环境变量配置
            image_config._load_env_config()


            # 更新Gemini图片生成配置
            gemini_updates = {}
            if 'gemini_image_api_key' in current_config and current_config['gemini_image_api_key']:
                gemini_updates['api_key'] = current_config['gemini_image_api_key']
            if 'gemini_image_api_base' in current_config and current_config['gemini_image_api_base']:
                gemini_updates['api_base'] = current_config['gemini_image_api_base']
            if 'gemini_image_model' in current_config and current_config['gemini_image_model']:
                gemini_updates['model'] = current_config['gemini_image_model']

            if gemini_updates:
                image_config.update_config({'gemini': gemini_updates})

            # 更新OpenAI图片生成配置
            openai_image_updates = {}
            if 'openai_image_api_key' in current_config and current_config['openai_image_api_key']:
                openai_image_updates['api_key'] = current_config['openai_image_api_key']
            if 'openai_image_api_base' in current_config and current_config['openai_image_api_base']:
                openai_image_updates['api_base'] = current_config['openai_image_api_base']
            if 'openai_image_model' in current_config and current_config['openai_image_model']:
                openai_image_updates['model'] = current_config['openai_image_model']
            if 'openai_image_quality' in current_config and current_config['openai_image_quality']:
                openai_image_updates['default_quality'] = current_config['openai_image_quality']

            if openai_image_updates:
                image_config.update_config({'openai_image': openai_image_updates})

            logger.info("Image service configuration reloaded")
        except Exception as e:
            logger.error(f"Failed to reload image service configuration: {e}")

    def update_config_by_category(self, category: str, config: Dict[str, Any]) -> bool:
        """Update configuration values for a specific category"""
        # Filter config to only include keys from the specified category
        filtered_config = {}
        
        for key, value in config.items():
            if key in self.config_schema and self.config_schema[key]["category"] == category:
                filtered_config[key] = value
        
        return self.update_config(filtered_config)
    
    def get_config_schema(self) -> Dict[str, Any]:
        """Get configuration schema"""
        return self.config_schema
    
    def validate_config(self, config: Dict[str, Any]) -> Dict[str, List[str]]:
        """Validate configuration values"""
        errors = {}
        
        for key, value in config.items():
            if key not in self.config_schema:
                if "unknown" not in errors:
                    errors["unknown"] = []
                errors["unknown"].append(f"Unknown configuration key: {key}")
                continue
            
            schema = self.config_schema[key]
            field_errors = []
            
            # Type validation
            if schema["type"] == "number":
                try:
                    num_value = float(value)
                    # Special validation for access_token_expire_minutes - allow 0 for never expire
                    if key == "access_token_expire_minutes" and num_value < 0:
                        field_errors.append(f"{key} must be 0 (never expire) or a positive number")
                except (ValueError, TypeError):
                    field_errors.append(f"{key} must be a number")
            
            elif schema["type"] == "boolean":
                if isinstance(value, str):
                    if value.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                        field_errors.append(f"{key} must be a boolean value")
            
            elif schema["type"] == "url":
                if value and not (value.startswith("http://") or value.startswith("https://")):
                    field_errors.append(f"{key} must be a valid URL")
            
            if field_errors:
                errors[key] = field_errors
        
        return errors
    
    def reset_to_defaults(self, category: Optional[str] = None) -> bool:
        """Reset configuration to default values"""
        try:
            config_to_reset = {}
            
            for key, schema in self.config_schema.items():
                if category is None or schema["category"] == category:
                    default_value = schema.get("default", "")
                    config_to_reset[key] = default_value
            
            return self.update_config(config_to_reset)
            
        except Exception as e:
            logger.error(f"Failed to reset configuration: {e}")
            return False
    
    def backup_config(self, backup_file: str) -> bool:
        """Backup current configuration"""
        try:
            config = self.get_all_config()
            
            with open(backup_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            logger.info(f"Configuration backed up to {backup_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to backup configuration: {e}")
            return False
    
    def restore_config(self, backup_file: str) -> bool:
        """Restore configuration from backup"""
        try:
            with open(backup_file, 'r') as f:
                config = json.load(f)
            
            return self.update_config(config)
            
        except Exception as e:
            logger.error(f"Failed to restore configuration: {e}")
            return False


# Global config service instance
config_service = ConfigService()


def get_config_service() -> ConfigService:
    """Get config service instance"""
    return config_service
