"""
Configuration management for LandPPT AI features
"""

import os
from typing import Optional, Dict, Any, ClassVar, List, Tuple
from pydantic import Field as PydanticField, field_validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load environment variables with error handling
# Try multiple paths for Docker and local development
env_paths = [
    '/app/.env',  # Docker container path
    '.env',       # Current directory
]

for env_path in env_paths:
    try:
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
            break
    except (PermissionError, FileNotFoundError):
        continue
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not load {env_path}: {e}")


def resolve_timeout_seconds(value: Any, default: int = 600, minimum: int = 1) -> int:
    """Normalize timeout values loaded from env/DB/UI into a positive integer."""
    try:
        if value is None or value == "":
            raise ValueError
        parsed = int(float(value))
    except (TypeError, ValueError):
        try:
            parsed = int(float(default))
        except (TypeError, ValueError):
            parsed = 600
    return max(int(minimum), parsed)


def Field(*args, env: Optional[str] = None, **kwargs):
    """
    Backward-compatible settings field wrapper.

    Pydantic v2 deprecated passing `env=` directly into `Field`. This wrapper
    keeps the existing declarations intact while translating the setting name
    into `validation_alias`.
    """
    if env is not None and "validation_alias" not in kwargs:
        kwargs["validation_alias"] = env
    return PydanticField(*args, **kwargs)

class AIConfig(BaseSettings):
    """AI configuration settings"""
    
    # OpenAI Configuration
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-3.5-turbo", env="OPENAI_MODEL")
    openai_use_responses_api: bool = Field(default=False, env="OPENAI_USE_RESPONSES_API")
    openai_enable_reasoning: bool = Field(default=False, env="OPENAI_ENABLE_REASONING")
    openai_reasoning_effort: str = Field(default="medium", env="OPENAI_REASONING_EFFORT")

    # Azure OpenAI Configuration
    azure_openai_api_key: Optional[str] = Field(default=None, env="AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: Optional[str] = Field(default=None, env="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_version: str = Field(default="2024-02-15-preview", env="AZURE_OPENAI_API_VERSION")
    azure_openai_deployment_name: Optional[str] = Field(default=None, env="AZURE_OPENAI_DEPLOYMENT_NAME")
    
    # Anthropic Configuration
    anthropic_api_key: Optional[str] = Field(default=None, env="ANTHROPIC_API_KEY")
    anthropic_base_url: str = Field(default="https://api.anthropic.com", env="ANTHROPIC_BASE_URL")
    anthropic_model: str = Field(default="claude-3-haiku-20240307", env="ANTHROPIC_MODEL")

    # Google Gemini Configuration
    google_api_key: Optional[str] = Field(default=None, env="GOOGLE_API_KEY")
    google_base_url: str = Field(default="https://generativelanguage.googleapis.com", env="GOOGLE_BASE_URL")
    google_model: str = Field(default="gemini-1.5-flash", env="GOOGLE_MODEL")
    
    # Ollama Configuration
    ollama_base_url: str = Field(default="http://localhost:11434", env="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama2", env="OLLAMA_MODEL")
    
    # Hugging Face Configuration
    huggingface_api_token: Optional[str] = Field(default=None, env="HUGGINGFACE_API_TOKEN")

    # Tavily API Configuration (for research functionality)
    tavily_api_key: Optional[str] = Field(default=None, env="TAVILY_API_KEY")
    tavily_max_results: int = Field(default=10, env="TAVILY_MAX_RESULTS")
    tavily_search_depth: str = Field(default="advanced", env="TAVILY_SEARCH_DEPTH")
    tavily_include_domains: Optional[str] = Field(default=None, env="TAVILY_INCLUDE_DOMAINS")
    tavily_exclude_domains: Optional[str] = Field(default=None, env="TAVILY_EXCLUDE_DOMAINS")

    # SearXNG Configuration (for research functionality)
    searxng_host: Optional[str] = Field(default=None, env="SEARXNG_HOST")
    searxng_max_results: int = Field(default=10, env="SEARXNG_MAX_RESULTS")
    searxng_language: str = Field(default="auto", env="SEARXNG_LANGUAGE")
    searxng_timeout: int = Field(default=30, env="SEARXNG_TIMEOUT")

    # Research Configuration
    research_provider: str = Field(default="tavily", env="RESEARCH_PROVIDER")  # tavily, searxng, both
    research_enable_content_extraction: bool = Field(default=True, env="RESEARCH_ENABLE_CONTENT_EXTRACTION")
    research_max_content_length: int = Field(default=5000, env="RESEARCH_MAX_CONTENT_LENGTH")
    research_extraction_timeout: int = Field(default=30, env="RESEARCH_EXTRACTION_TIMEOUT")

    # Apryse SDK Configuration (for PPTX export functionality)
    apryse_license_key: Optional[str] = Field(default=None, env="APRYSE_LICENSE_KEY")
    enable_apryse_pptx_export: bool = Field(default=False, env="ENABLE_APRYSE_PPTX_EXPORT")

    # Provider Selection
    default_ai_provider: str = Field(default="openai", env="DEFAULT_AI_PROVIDER")
    
    # Model Role Configuration
    default_model_provider: Optional[str] = Field(default=None, env="DEFAULT_MODEL_PROVIDER")
    default_model_name: Optional[str] = Field(default=None, env="DEFAULT_MODEL_NAME")
    outline_model_provider: Optional[str] = Field(default=None, env="OUTLINE_MODEL_PROVIDER")
    outline_model_name: Optional[str] = Field(default=None, env="OUTLINE_MODEL_NAME")
    creative_model_provider: Optional[str] = Field(default=None, env="CREATIVE_MODEL_PROVIDER")
    creative_model_name: Optional[str] = Field(default=None, env="CREATIVE_MODEL_NAME")
    image_prompt_model_provider: Optional[str] = Field(default=None, env="IMAGE_PROMPT_MODEL_PROVIDER")
    image_prompt_model_name: Optional[str] = Field(default=None, env="IMAGE_PROMPT_MODEL_NAME")
    slide_generation_model_provider: Optional[str] = Field(default=None, env="SLIDE_GENERATION_MODEL_PROVIDER")
    slide_generation_model_name: Optional[str] = Field(default=None, env="SLIDE_GENERATION_MODEL_NAME")
    editor_assistant_model_provider: Optional[str] = Field(default=None, env="EDITOR_ASSISTANT_MODEL_PROVIDER")
    editor_assistant_model_name: Optional[str] = Field(default=None, env="EDITOR_ASSISTANT_MODEL_NAME")
    template_generation_model_provider: Optional[str] = Field(default=None, env="TEMPLATE_GENERATION_MODEL_PROVIDER")
    template_generation_model_name: Optional[str] = Field(default=None, env="TEMPLATE_GENERATION_MODEL_NAME")
    speech_script_model_provider: Optional[str] = Field(default=None, env="SPEECH_SCRIPT_MODEL_PROVIDER")
    speech_script_model_name: Optional[str] = Field(default=None, env="SPEECH_SCRIPT_MODEL_NAME")
    vision_analysis_model_provider: Optional[str] = Field(default=None, env="VISION_ANALYSIS_MODEL_PROVIDER")
    vision_analysis_model_name: Optional[str] = Field(default=None, env="VISION_ANALYSIS_MODEL_NAME")
    polish_model_provider: Optional[str] = Field(default=None, env="POLISH_MODEL_PROVIDER")
    polish_model_name: Optional[str] = Field(default=None, env="POLISH_MODEL_NAME")

    # Generation Parameters
    # NOTE: `MAX_TOKENS` is used as the maximum *chunk/splitting* tokens in this project.
    # Do not forward it to model providers as an output length limit.
    max_tokens: int = Field(default=16384, env="MAX_TOKENS")
    temperature: float = Field(default=0.7, env="TEMPERATURE")
    top_p: float = Field(default=1.0, env="TOP_P")
    llm_timeout_seconds: int = Field(default=600, env="LLM_TIMEOUT_SECONDS")
    
    # Parallel Generation Configuration
    enable_parallel_generation: bool = Field(default=True, env="ENABLE_PARALLEL_GENERATION")
    parallel_slides_count: int = Field(default=3, env="PARALLEL_SLIDES_COUNT")
    
    # Feature Flags
    enable_network_mode: bool = Field(default=True, env="ENABLE_NETWORK_MODE")
    enable_local_models: bool = Field(default=False, env="ENABLE_LOCAL_MODELS")
    enable_streaming: bool = Field(default=True, env="ENABLE_STREAMING")
    enable_auto_layout_repair: bool = Field(default=False, env="ENABLE_AUTO_LAYOUT_REPAIR")
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_ai_requests: bool = Field(default=False, env="LOG_AI_REQUESTS")
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "extra": "ignore",
        "populate_by_name": True,
    }



    MODEL_ROLE_FIELDS: ClassVar[dict[str, tuple[str, str]]] = {
        "default": ("default_model_provider", "default_model_name"),
        "outline": ("outline_model_provider", "outline_model_name"),
        "creative": ("creative_model_provider", "creative_model_name"),
        "image_prompt": ("image_prompt_model_provider", "image_prompt_model_name"),
        "slide_generation": ("slide_generation_model_provider", "slide_generation_model_name"),
        "editor": ("editor_assistant_model_provider", "editor_assistant_model_name"),
        "template": ("template_generation_model_provider", "template_generation_model_name"),
        "speech_script": ("speech_script_model_provider", "speech_script_model_name"),
        "vision_analysis": ("vision_analysis_model_provider", "vision_analysis_model_name"),
        "polish": ("polish_model_provider", "polish_model_name"),
    }

    MODEL_ROLE_LABELS: ClassVar[dict[str, str]] = {
        "default": "默认模型",
        "outline": "大纲生成 / 要点增强模型",
        "creative": "创意指导模型",
        "image_prompt": "配图与提示词模型",
        "slide_generation": "幻灯片生成模型",
        "editor": "AI编辑助手模型",
        "template": "AI模板生成模型",
        "speech_script": "演讲稿生成模型",
        "vision_analysis": "多模态视觉分析模型",
        "polish": "AI雕琢模型",
    }



    @staticmethod
    def _normalize_optional_str(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        return value or None

    def _normalize_provider(self, provider: Optional[str]) -> Optional[str]:
        normalized = self._normalize_optional_str(provider)
        return normalized.lower() if normalized else None

    def _get_default_model_for_provider(self, provider: Optional[str]) -> Optional[str]:
        provider_key = self._normalize_provider(provider)
        if provider_key == "openai":
            return self._normalize_optional_str(self.openai_model)
        if provider_key == "anthropic":
            return self._normalize_optional_str(self.anthropic_model)
        if provider_key in ("google", "gemini"):
            return self._normalize_optional_str(self.google_model)
        if provider_key == "ollama":
            return self._normalize_optional_str(self.ollama_model)
        return self._normalize_optional_str(self.openai_model)

    def get_model_config_for_role(self, role: str, provider_override: Optional[str] = None) -> Dict[str, Optional[str]]:
        role_key = (role or "default").lower()
        if role_key not in self.MODEL_ROLE_FIELDS:
            raise ValueError(f"Unknown model role: {role}")

        provider_field, model_field = self.MODEL_ROLE_FIELDS[role_key]
        configured_provider = self._normalize_provider(getattr(self, provider_field, None))
        configured_model = self._normalize_optional_str(getattr(self, model_field, None))
        override_provider = self._normalize_provider(provider_override)

        effective_provider = override_provider or configured_provider or self._normalize_provider(self.default_ai_provider) or "openai"

        if override_provider:
            if override_provider == configured_provider and configured_model:
                effective_model = configured_model
            else:
                effective_model = self._get_default_model_for_provider(override_provider)
        else:
            effective_model = configured_model or self._get_default_model_for_provider(effective_provider)

        return {
            "role": role_key,
            "provider": effective_provider,
            "model": effective_model
        }

    def get_all_model_roles(self) -> Dict[str, Dict[str, Optional[str]]]:
        roles = {}
        for role_key, (provider_field, model_field) in self.MODEL_ROLE_FIELDS.items():
            roles[role_key] = {
                "provider": self._normalize_optional_str(getattr(self, provider_field, None)),
                "model": self._normalize_optional_str(getattr(self, model_field, None)),
                "label": self.MODEL_ROLE_LABELS.get(role_key)
            }
        return roles


    def get_provider_config(self, provider: Optional[str] = None) -> Dict[str, Any]:
        """Get configuration for a specific AI provider"""
        provider = provider or self.default_ai_provider

        # Built-in providers
        configs = {
            "openai": {
                "api_key": self.openai_api_key,
                "base_url": self.openai_base_url,
                "model": self.openai_model,
                "use_responses_api": self.openai_use_responses_api,
                "enable_reasoning": self.openai_enable_reasoning,
                "reasoning_effort": self.openai_reasoning_effort,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
            "azure_openai": {
                "api_key": self.azure_openai_api_key,
                "azure_endpoint": self.azure_openai_endpoint,
                "api_version": self.azure_openai_api_version,
                "model": self.azure_openai_deployment_name,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
            "azure": {  # Alias for azure_openai
                "api_key": self.azure_openai_api_key,
                "azure_endpoint": self.azure_openai_endpoint,
                "api_version": self.azure_openai_api_version,
                "model": self.azure_openai_deployment_name,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
            "anthropic": {
                "api_key": self.anthropic_api_key,
                "base_url": self.anthropic_base_url,
                "model": self.anthropic_model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
            "google": {
                "api_key": self.google_api_key,
                "base_url": self.google_base_url,
                "model": self.google_model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
            "gemini": {  # Alias for google
                "api_key": self.google_api_key,
                "base_url": self.google_base_url,
                "model": self.google_model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            },
            "ollama": {
                "base_url": self.ollama_base_url,
                "model": self.ollama_model,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            }
        }

        timeout_seconds = resolve_timeout_seconds(self.llm_timeout_seconds, 600)
        for provider_config in configs.values():
            provider_config["llm_timeout_seconds"] = timeout_seconds

        return configs.get(provider, configs.get("openai", {}))
    
    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider is properly configured"""
        config = self.get_provider_config(provider)

        # Built-in providers
        if provider == "openai":
            return bool(config.get("api_key"))
        elif provider in ("azure_openai", "azure"):
            return bool(config.get("api_key") and config.get("azure_endpoint") and config.get("model"))
        elif provider == "anthropic":
            return bool(config.get("api_key"))
        elif provider == "google" or provider == "gemini":
            return bool(config.get("api_key"))
        elif provider == "ollama":
            return self.enable_local_models

        return False
    
    def get_available_providers(self) -> list[str]:
        """Get list of available AI providers"""
        providers: list[str] = []
        seen: set[str] = set()

        # Add built-in providers. Note: "gemini" is an alias for "google" (same config),
        # so we only expose a single canonical provider name here to avoid duplicates in UIs.
        for provider in ["openai", "azure_openai", "azure", "anthropic", "google", "gemini", "ollama"]:
            if not self.is_provider_available(provider):
                continue

            canonical = "google" if provider == "gemini" else provider
            canonical = "azure_openai" if provider == "azure" else canonical
            if canonical in seen:
                continue

            providers.append(canonical)
            seen.add(canonical)

        return providers

# Global configuration instance
ai_config = AIConfig()

def reload_ai_config():
    """Reload AI configuration from environment variables"""
    global ai_config
    # Force reload environment variables with error handling
    from dotenv import load_dotenv
    import os
    from pathlib import Path

    # Use the same .env file path as config_service (relative to project root)
    # Try to find the project root by looking for pyproject.toml or .env
    project_root = Path(__file__).parent.parent.parent
    env_file = project_root / '.env'

    # Fallback to cwd if the project root .env doesn't exist
    if not env_file.exists():
        env_file = Path('.env')

    try:
        load_dotenv(str(env_file), override=True)
    except (PermissionError, FileNotFoundError) as e:
        # Silently continue if .env file is not accessible
        pass
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not reload .env file: {e}")

    # Force update the existing instance with new values from environment
    ai_config.openai_model = os.environ.get('OPENAI_MODEL', ai_config.openai_model)
    ai_config.openai_base_url = os.environ.get('OPENAI_BASE_URL', ai_config.openai_base_url)
    ai_config.openai_api_key = os.environ.get('OPENAI_API_KEY', ai_config.openai_api_key)
    ai_config.openai_use_responses_api = os.environ.get(
        'OPENAI_USE_RESPONSES_API',
        str(ai_config.openai_use_responses_api),
    ).lower() == 'true'
    ai_config.openai_enable_reasoning = os.environ.get(
        'OPENAI_ENABLE_REASONING',
        str(ai_config.openai_enable_reasoning),
    ).lower() == 'true'
    ai_config.openai_reasoning_effort = os.environ.get(
        'OPENAI_REASONING_EFFORT',
        ai_config.openai_reasoning_effort,
    )
    ai_config.azure_openai_api_key = os.environ.get('AZURE_OPENAI_API_KEY', ai_config.azure_openai_api_key)
    ai_config.azure_openai_endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT', ai_config.azure_openai_endpoint)
    ai_config.azure_openai_api_version = os.environ.get('AZURE_OPENAI_API_VERSION', ai_config.azure_openai_api_version)
    ai_config.azure_openai_deployment_name = os.environ.get('AZURE_OPENAI_DEPLOYMENT_NAME', ai_config.azure_openai_deployment_name)
    ai_config.anthropic_api_key = os.environ.get('ANTHROPIC_API_KEY', ai_config.anthropic_api_key)
    ai_config.anthropic_base_url = os.environ.get('ANTHROPIC_BASE_URL', ai_config.anthropic_base_url)
    ai_config.anthropic_model = os.environ.get('ANTHROPIC_MODEL', ai_config.anthropic_model)
    ai_config.google_api_key = os.environ.get('GOOGLE_API_KEY', ai_config.google_api_key)
    ai_config.google_base_url = os.environ.get('GOOGLE_BASE_URL', ai_config.google_base_url)
    ai_config.google_model = os.environ.get('GOOGLE_MODEL', ai_config.google_model)
    ai_config.default_ai_provider = os.environ.get('DEFAULT_AI_PROVIDER', ai_config.default_ai_provider)
    model_provider_env = os.environ.get('DEFAULT_MODEL_PROVIDER')
    ai_config.default_model_provider = (ai_config._normalize_optional_str(model_provider_env)
                                        if model_provider_env is not None else ai_config.default_model_provider)
    model_name_env = os.environ.get('DEFAULT_MODEL_NAME')
    ai_config.default_model_name = (ai_config._normalize_optional_str(model_name_env)
                                    if model_name_env is not None else ai_config.default_model_name)

    outline_provider_env = os.environ.get('OUTLINE_MODEL_PROVIDER')
    ai_config.outline_model_provider = (ai_config._normalize_optional_str(outline_provider_env)
                                        if outline_provider_env is not None else ai_config.outline_model_provider)
    outline_model_env = os.environ.get('OUTLINE_MODEL_NAME')
    ai_config.outline_model_name = (ai_config._normalize_optional_str(outline_model_env)
                                    if outline_model_env is not None else ai_config.outline_model_name)

    creative_provider_env = os.environ.get('CREATIVE_MODEL_PROVIDER')
    ai_config.creative_model_provider = (ai_config._normalize_optional_str(creative_provider_env)
                                         if creative_provider_env is not None else ai_config.creative_model_provider)
    creative_model_env = os.environ.get('CREATIVE_MODEL_NAME')
    ai_config.creative_model_name = (ai_config._normalize_optional_str(creative_model_env)
                                     if creative_model_env is not None else ai_config.creative_model_name)

    image_prompt_provider_env = os.environ.get('IMAGE_PROMPT_MODEL_PROVIDER')
    ai_config.image_prompt_model_provider = (ai_config._normalize_optional_str(image_prompt_provider_env)
                                             if image_prompt_provider_env is not None else ai_config.image_prompt_model_provider)
    image_prompt_model_env = os.environ.get('IMAGE_PROMPT_MODEL_NAME')
    ai_config.image_prompt_model_name = (ai_config._normalize_optional_str(image_prompt_model_env)
                                         if image_prompt_model_env is not None else ai_config.image_prompt_model_name)

    slide_provider_env = os.environ.get('SLIDE_GENERATION_MODEL_PROVIDER')
    ai_config.slide_generation_model_provider = (ai_config._normalize_optional_str(slide_provider_env)
                                                 if slide_provider_env is not None else ai_config.slide_generation_model_provider)
    slide_model_env = os.environ.get('SLIDE_GENERATION_MODEL_NAME')
    ai_config.slide_generation_model_name = (ai_config._normalize_optional_str(slide_model_env)
                                             if slide_model_env is not None else ai_config.slide_generation_model_name)

    editor_provider_env = os.environ.get('EDITOR_ASSISTANT_MODEL_PROVIDER')
    ai_config.editor_assistant_model_provider = (ai_config._normalize_optional_str(editor_provider_env)
                                                 if editor_provider_env is not None else ai_config.editor_assistant_model_provider)
    editor_model_env = os.environ.get('EDITOR_ASSISTANT_MODEL_NAME')
    ai_config.editor_assistant_model_name = (ai_config._normalize_optional_str(editor_model_env)
                                             if editor_model_env is not None else ai_config.editor_assistant_model_name)

    template_provider_env = os.environ.get('TEMPLATE_GENERATION_MODEL_PROVIDER')
    ai_config.template_generation_model_provider = (ai_config._normalize_optional_str(template_provider_env)
                                                   if template_provider_env is not None else ai_config.template_generation_model_provider)
    template_model_env = os.environ.get('TEMPLATE_GENERATION_MODEL_NAME')
    ai_config.template_generation_model_name = (ai_config._normalize_optional_str(template_model_env)
                                               if template_model_env is not None else ai_config.template_generation_model_name)

    speech_provider_env = os.environ.get('SPEECH_SCRIPT_MODEL_PROVIDER')
    ai_config.speech_script_model_provider = (ai_config._normalize_optional_str(speech_provider_env)
                                              if speech_provider_env is not None else ai_config.speech_script_model_provider)
    speech_model_env = os.environ.get('SPEECH_SCRIPT_MODEL_NAME')
    ai_config.speech_script_model_name = (ai_config._normalize_optional_str(speech_model_env)
                                         if speech_model_env is not None else ai_config.speech_script_model_name)

    vision_provider_env = os.environ.get('VISION_ANALYSIS_MODEL_PROVIDER')
    ai_config.vision_analysis_model_provider = (ai_config._normalize_optional_str(vision_provider_env)
                                               if vision_provider_env is not None else ai_config.vision_analysis_model_provider)
    vision_model_env = os.environ.get('VISION_ANALYSIS_MODEL_NAME')
    ai_config.vision_analysis_model_name = (ai_config._normalize_optional_str(vision_model_env)
                                            if vision_model_env is not None else ai_config.vision_analysis_model_name)

    polish_provider_env = os.environ.get('POLISH_MODEL_PROVIDER')
    ai_config.polish_model_provider = (ai_config._normalize_optional_str(polish_provider_env)
                                       if polish_provider_env is not None else ai_config.polish_model_provider)
    polish_model_env = os.environ.get('POLISH_MODEL_NAME')
    ai_config.polish_model_name = (ai_config._normalize_optional_str(polish_model_env)
                                   if polish_model_env is not None else ai_config.polish_model_name)

    ai_config.max_tokens = int(os.environ.get('MAX_TOKENS', str(ai_config.max_tokens)))
    ai_config.temperature = float(os.environ.get('TEMPERATURE', str(ai_config.temperature)))
    ai_config.top_p = float(os.environ.get('TOP_P', str(ai_config.top_p)))
    ai_config.llm_timeout_seconds = resolve_timeout_seconds(
        os.environ.get('LLM_TIMEOUT_SECONDS', ai_config.llm_timeout_seconds),
        ai_config.llm_timeout_seconds,
    )
    
    # Update parallel generation configuration
    ai_config.enable_parallel_generation = os.environ.get('ENABLE_PARALLEL_GENERATION', str(ai_config.enable_parallel_generation)).lower() == 'true'
    ai_config.parallel_slides_count = int(os.environ.get('PARALLEL_SLIDES_COUNT', str(ai_config.parallel_slides_count)))
    ai_config.enable_auto_layout_repair = os.environ.get('ENABLE_AUTO_LAYOUT_REPAIR', str(ai_config.enable_auto_layout_repair)).lower() == 'true'
    ai_config.enable_apryse_pptx_export = os.environ.get('ENABLE_APRYSE_PPTX_EXPORT', str(ai_config.enable_apryse_pptx_export)).lower() == 'true'

    # Update Tavily configuration
    ai_config.tavily_api_key = os.environ.get('TAVILY_API_KEY', ai_config.tavily_api_key)
    ai_config.tavily_max_results = int(os.environ.get('TAVILY_MAX_RESULTS', str(ai_config.tavily_max_results)))
    ai_config.tavily_search_depth = os.environ.get('TAVILY_SEARCH_DEPTH', ai_config.tavily_search_depth)
    ai_config.tavily_include_domains = os.environ.get('TAVILY_INCLUDE_DOMAINS', ai_config.tavily_include_domains)
    ai_config.tavily_exclude_domains = os.environ.get('TAVILY_EXCLUDE_DOMAINS', ai_config.tavily_exclude_domains)

    # Update SearXNG configuration
    ai_config.searxng_host = os.environ.get('SEARXNG_HOST', ai_config.searxng_host)
    ai_config.searxng_max_results = int(os.environ.get('SEARXNG_MAX_RESULTS', str(ai_config.searxng_max_results)))
    ai_config.searxng_language = os.environ.get('SEARXNG_LANGUAGE', ai_config.searxng_language)
    ai_config.searxng_timeout = int(os.environ.get('SEARXNG_TIMEOUT', str(ai_config.searxng_timeout)))

    # Update Research configuration
    ai_config.research_provider = os.environ.get('RESEARCH_PROVIDER', ai_config.research_provider)
    ai_config.research_enable_content_extraction = os.environ.get('RESEARCH_ENABLE_CONTENT_EXTRACTION', str(ai_config.research_enable_content_extraction)).lower() == 'true'
    ai_config.research_max_content_length = int(os.environ.get('RESEARCH_MAX_CONTENT_LENGTH', str(ai_config.research_max_content_length)))
    ai_config.research_extraction_timeout = int(os.environ.get('RESEARCH_EXTRACTION_TIMEOUT', str(ai_config.research_extraction_timeout)))

    ai_config.apryse_license_key = os.environ.get('APRYSE_LICENSE_KEY', ai_config.apryse_license_key)

class AppConfig(BaseSettings):
    """Application configuration"""

    BOOL_TRUE_VALUES: ClassVar[set[str]] = {"1", "true", "yes", "on", "debug", "dev", "development"}
    BOOL_FALSE_VALUES: ClassVar[set[str]] = {"0", "false", "no", "off", "release", "prod", "production"}
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", env="HOST")
    port: int = Field(default=8000, env="PORT")
    debug: bool = Field(default=True, env="DEBUG")
    reload: bool = Field(default=True, env="RELOAD")
    
    # Database Configuration - default to SQLite for standalone/local startup
    database_url: str = Field(default="sqlite:///./landppt.db", env="DATABASE_URL")
    auto_migrate_on_startup: bool = Field(default=True, env="LANDPPT_AUTO_MIGRATE_ON_STARTUP")
    auto_migrate_fail_fast: bool = Field(default=True, env="LANDPPT_AUTO_MIGRATE_FAIL_FAST")
    auto_migrate_lock_timeout_seconds: int = Field(default=300, env="LANDPPT_AUTO_MIGRATE_LOCK_TIMEOUT_SECONDS")
    auto_migrate_lock_stale_seconds: int = Field(default=900, env="LANDPPT_AUTO_MIGRATE_LOCK_STALE_SECONDS")

    
    # Security Configuration
    secret_key: str = Field(default="your-secret-key-here", env="SECRET_KEY")
    access_token_expire_minutes: int = Field(default=20160, env="ACCESS_TOKEN_EXPIRE_MINUTES")  # 2 weeks
    enable_api_docs: bool = Field(default=True, env="LANDPPT_ENABLE_API_DOCS")
    bootstrap_admin_enabled: bool = Field(default=False, env="LANDPPT_BOOTSTRAP_ADMIN_ENABLED")
    bootstrap_admin_username: Optional[str] = Field(default=None, env="LANDPPT_BOOTSTRAP_ADMIN_USERNAME")
    bootstrap_admin_password: Optional[str] = Field(default=None, env="LANDPPT_BOOTSTRAP_ADMIN_PASSWORD")

    # Machine-to-machine API authentication (for n8n / automation)
    # Single key mode: LANDPPT_API_KEY + LANDPPT_API_KEY_USER
    # Multi key mode: LANDPPT_API_KEYS="user1:key1,user2:key2" (also supports user=key)
    api_key: Optional[str] = Field(default=None, env="LANDPPT_API_KEY")
    api_key_user: str = Field(default="admin", env="LANDPPT_API_KEY_USER")
    api_keys: Optional[str] = Field(default=None, env="LANDPPT_API_KEYS")
    allow_header_session_auth: bool = Field(default=False, env="LANDPPT_ALLOW_HEADER_SESSION_AUTH")
    
    # File Upload Configuration
    max_file_size: int = Field(default=10 * 1024 * 1024, env="MAX_FILE_SIZE")  # 10MB
    upload_dir: str = Field(default="uploads", env="UPLOAD_DIR")

    # ComfyUI (optional, for TTS via ComfyUI API)
    comfyui_base_url: str = Field(default="http://127.0.0.1:8188", env="COMFYUI_BASE_URL")
    comfyui_tts_workflow_path: str = Field(default="tests/Qwen3-TD-TTS.json", env="COMFYUI_TTS_WORKFLOW_PATH")
    comfyui_tts_timeout_seconds: int = Field(default=600, env="COMFYUI_TTS_TIMEOUT_SECONDS")
    
    # Cache Configuration
    cache_ttl: int = Field(default=3600, env="CACHE_TTL")  # 1 hour
    cache_backend: str = Field(default="memory", env="CACHE_BACKEND")  # memory, valkey
    valkey_url: str = Field(default="valkey://localhost:6379", env="VALKEY_URL")
    
    # Credits System Configuration
    enable_credits_system: bool = Field(default=False, env="ENABLE_CREDITS_SYSTEM")
    default_credits_for_new_users: int = Field(default=100, env="DEFAULT_CREDITS_FOR_NEW_USERS")

    # Email SMTP Configuration
    email_provider: str = Field(default="smtp", env="EMAIL_PROVIDER")  # smtp | resend
    smtp_host: str = Field(default="", env="SMTP_HOST")
    smtp_port: int = Field(default=465, env="SMTP_PORT")
    smtp_user: str = Field(default="", env="SMTP_USER")
    smtp_password: str = Field(default="", env="SMTP_PASSWORD")
    smtp_from_email: str = Field(default="", env="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(default="LandPPT", env="SMTP_FROM_NAME")
    smtp_use_ssl: bool = Field(default=True, env="SMTP_USE_SSL")

    # Resend Email Configuration (https://resend.com/)
    resend_api_key: str = Field(default="", env="RESEND_API_KEY")
    resend_from_email: str = Field(default="", env="RESEND_FROM_EMAIL")
    resend_from_name: str = Field(default="LandPPT", env="RESEND_FROM_NAME")
    
    # User Registration Configuration
    enable_user_registration: bool = Field(default=True, env="ENABLE_USER_REGISTRATION")
    verification_code_expire_minutes: int = Field(default=10, env="VERIFICATION_CODE_EXPIRE_MINUTES")
    registration_ip_rate_limit_per_hour: int = Field(default=100, env="REGISTRATION_IP_RATE_LIMIT_PER_HOUR")

    # Cloudflare Turnstile (anti-bot) for registration flow
    turnstile_enabled: bool = Field(default=False, env="TURNSTILE_ENABLED")
    turnstile_site_key: Optional[str] = Field(default=None, env="TURNSTILE_SITE_KEY")
    turnstile_secret_key: Optional[str] = Field(default=None, env="TURNSTILE_SECRET_KEY")
    
    # GitHub OAuth Configuration (with PKCE)
    github_oauth_enabled: bool = Field(default=False, env="GITHUB_OAUTH_ENABLED")
    github_client_id: Optional[str] = Field(default=None, env="GITHUB_CLIENT_ID")
    github_client_secret: Optional[str] = Field(default=None, env="GITHUB_CLIENT_SECRET")
    github_callback_url: Optional[str] = Field(default=None, env="GITHUB_CALLBACK_URL")  # e.g. https://yourdomain.com/auth/github/callback
    github_callback_use_request_host: bool = Field(default=False, env="GITHUB_CALLBACK_USE_REQUEST_HOST")
    
    # Linux Do OAuth Configuration
    linuxdo_oauth_enabled: bool = Field(default=False, env="LINUXDO_OAUTH_ENABLED")
    linuxdo_client_id: Optional[str] = Field(default=None, env="LINUXDO_CLIENT_ID")
    linuxdo_client_secret: Optional[str] = Field(default=None, env="LINUXDO_CLIENT_SECRET")
    linuxdo_callback_url: Optional[str] = Field(default=None, env="LINUXDO_CALLBACK_URL")  # e.g. https://yourdomain.com/auth/linuxdo/callback
    
    model_config = {
        "case_sensitive": False,
        "extra": "ignore",
        "populate_by_name": True,
    }

    @classmethod
    def _normalize_bool_env(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in cls.BOOL_TRUE_VALUES:
                return True
            if normalized in cls.BOOL_FALSE_VALUES:
                return False
        return value

    @field_validator(
        "debug",
        "reload",
        "auto_migrate_on_startup",
        "auto_migrate_fail_fast",
        "enable_api_docs",
        "bootstrap_admin_enabled",
        "allow_header_session_auth",
        "enable_credits_system",
        "turnstile_enabled",
        "github_oauth_enabled",
        "linuxdo_oauth_enabled",
        "smtp_use_ssl",
        "enable_user_registration",
        mode="before",
    )
    @classmethod
    def normalize_bool_fields(cls, value: Any) -> Any:
        return cls._normalize_bool_env(value)

    def get_api_key_bindings(self) -> List[Tuple[str, str]]:
        """
        Return configured API key bindings as (username, api_key) pairs.
        Supports:
        - LANDPPT_API_KEY + LANDPPT_API_KEY_USER
        - LANDPPT_API_KEYS="user1:key1,user2:key2" (also accepts user=key)
        """
        bindings: List[Tuple[str, str]] = []
        default_user = str(self.api_key_user or "admin").strip() or "admin"

        def _append_binding(username: Optional[str], key: Optional[str]) -> None:
            user = str(username or "").strip() or default_user
            token = str(key or "").strip()
            if not token:
                return
            pair = (user, token)
            if pair not in bindings:
                bindings.append(pair)

        raw_multi = str(self.api_keys or "").strip()
        if raw_multi:
            normalized = raw_multi.replace("\n", ",").replace(";", ",")
            for item in normalized.split(","):
                token_spec = item.strip()
                if not token_spec:
                    continue
                if "=" in token_spec:
                    user, key = token_spec.split("=", 1)
                    _append_binding(user, key)
                elif ":" in token_spec:
                    user, key = token_spec.split(":", 1)
                    _append_binding(user, key)
                else:
                    _append_binding(default_user, token_spec)

        _append_binding(default_user, self.api_key)
        return bindings

# Global app configuration instance
app_config = AppConfig()
