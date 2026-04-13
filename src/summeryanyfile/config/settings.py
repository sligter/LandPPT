"""
设置管理 - 处理配置文件和环境变量
"""

import os
from typing import Optional, Dict, Any
from pathlib import Path
import json
import logging
from dataclasses import dataclass, asdict
from dotenv import load_dotenv

from ..core.models import ProcessingConfig, ChunkStrategy

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """应用设置"""
    # LLM配置
    llm_model: str = "gpt-4o-mini"
    llm_provider: str = "openai"
    temperature: float = 0.7
    max_tokens: int = 4000
    
    # 处理配置
    max_slides: int = 25
    min_slides: int = 5  # 新增：最小页数
    chunk_size: int = 3000
    chunk_overlap: int = 200
    chunk_strategy: str = "paragraph"
    
    # API配置
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_use_responses_api: bool = False
    openai_enable_reasoning: bool = False
    openai_reasoning_effort: str = "medium"
    anthropic_api_key: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_version: str = "2024-02-15-preview"
    
    # 输出配置
    output_format: str = "json"
    output_file: Optional[str] = None
    
    # 日志配置
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    # 其他配置
    progress_bar: bool = True
    debug_mode: bool = False
    
    def to_processing_config(self, target_language: str = "zh") -> ProcessingConfig:
        """转换为处理配置"""
        return ProcessingConfig(
            max_slides=self.max_slides,
            min_slides=self.min_slides,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            chunk_strategy=ChunkStrategy(self.chunk_strategy),
            llm_model=self.llm_model,
            llm_provider=self.llm_provider,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            target_language=target_language,
            use_responses_api=self.openai_use_responses_api if self.llm_provider == "openai" else False,
            enable_reasoning=self.openai_enable_reasoning if self.llm_provider == "openai" else False,
            reasoning_effort=self.openai_reasoning_effort if self.llm_provider == "openai" else "medium",
        )
    
    def get_llm_kwargs(self) -> Dict[str, Any]:
        """获取LLM相关的参数"""
        kwargs = {}

        if self.llm_provider == "openai":
            if self.openai_api_key:
                kwargs["api_key"] = self.openai_api_key
            if self.openai_base_url:
                kwargs["base_url"] = self.openai_base_url
            if self.openai_use_responses_api:
                kwargs["use_responses_api"] = True
            if self.openai_enable_reasoning:
                kwargs["enable_reasoning"] = True
                kwargs["reasoning_effort"] = self.openai_reasoning_effort
        elif self.llm_provider == "anthropic":
            if self.anthropic_api_key:
                kwargs["api_key"] = self.anthropic_api_key
            # 检查环境变量中的ANTHROPIC_BASE_URL
            anthropic_base_url = os.getenv("ANTHROPIC_BASE_URL")
            if anthropic_base_url:
                kwargs["base_url"] = anthropic_base_url
        elif self.llm_provider == "azure":
            if self.azure_openai_api_key:
                kwargs["api_key"] = self.azure_openai_api_key
            if self.azure_openai_endpoint:
                kwargs["azure_endpoint"] = self.azure_openai_endpoint
            kwargs["api_version"] = self.azure_openai_api_version

        return kwargs
    
    def save_to_file(self, file_path: str):
        """保存设置到文件"""
        config_dict = asdict(self)
        # 移除敏感信息
        sensitive_keys = [
            "openai_api_key", 
            "anthropic_api_key", 
            "azure_openai_api_key"
        ]
        for key in sensitive_keys:
            if key in config_dict:
                config_dict[key] = "***"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(config_dict, f, indent=2, ensure_ascii=False)
        
        logger.info(f"设置已保存到: {file_path}")
    
    @classmethod
    def load_from_file(cls, file_path: str) -> "Settings":
        """从文件加载设置"""
        if not os.path.exists(file_path):
            logger.warning(f"配置文件不存在: {file_path}")
            return cls()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config_dict = json.load(f)
            
            # 过滤掉不存在的字段
            valid_fields = {field.name for field in cls.__dataclass_fields__.values()}
            filtered_config = {k: v for k, v in config_dict.items() if k in valid_fields}
            
            return cls(**filtered_config)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return cls()


def load_settings(
    config_file: Optional[str] = None,
    env_file: Optional[str] = None,
    **overrides
) -> Settings:
    """
    加载设置
    
    Args:
        config_file: 配置文件路径
        env_file: 环境变量文件路径
        **overrides: 覆盖参数
        
    Returns:
        设置对象
    """
    # 加载环境变量
    if env_file and os.path.exists(env_file):
        load_dotenv(env_file)
    else:
        # 尝试加载默认的.env文件
        default_env_files = [".env", ".env.local"]
        for env_path in default_env_files:
            if os.path.exists(env_path):
                load_dotenv(env_path)
                break
    
    # 从配置文件加载
    if config_file:
        settings = Settings.load_from_file(config_file)
    else:
        # 尝试加载默认配置文件
        default_config_files = [
            "config.json",
            "settings.json", 
            os.path.expanduser("~/.summeryanyfile/config.json")
        ]
        settings = Settings()
        for config_path in default_config_files:
            if os.path.exists(config_path):
                settings = Settings.load_from_file(config_path)
                break
    
    # 从环境变量覆盖
    env_mappings = {
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_BASE_URL": "openai_base_url",
        "OPENAI_USE_RESPONSES_API": "openai_use_responses_api",
        "OPENAI_ENABLE_REASONING": "openai_enable_reasoning",
        "OPENAI_REASONING_EFFORT": "openai_reasoning_effort",
        "OPENAI_MODEL": "llm_model",  # 支持OPENAI_MODEL环境变量
        "ANTHROPIC_API_KEY": "anthropic_api_key",
        "AZURE_OPENAI_API_KEY": "azure_openai_api_key",
        "AZURE_OPENAI_ENDPOINT": "azure_openai_endpoint",
        "AZURE_OPENAI_API_VERSION": "azure_openai_api_version",
        "LLM_MODEL": "llm_model",
        "LLM_PROVIDER": "llm_provider",
        "MAX_SLIDES": "max_slides",
        "MIN_SLIDES": "min_slides",
        "CHUNK_SIZE": "chunk_size",
        "CHUNK_OVERLAP": "chunk_overlap",
        "CHUNK_STRATEGY": "chunk_strategy",
        "TEMPERATURE": "temperature",
        "MAX_TOKENS": "max_tokens",
        "LOG_LEVEL": "log_level",
        "DEBUG_MODE": "debug_mode",
    }
    
    for env_key, attr_name in env_mappings.items():
        env_value = os.getenv(env_key)
        if env_value is not None:
            # 类型转换
            if attr_name in ["max_slides", "min_slides", "chunk_size", "chunk_overlap", "max_tokens"]:
                try:
                    env_value = int(env_value)
                except ValueError:
                    logger.warning(f"无效的整数值 {env_key}={env_value}")
                    continue
            elif attr_name == "temperature":
                try:
                    env_value = float(env_value)
                except ValueError:
                    logger.warning(f"无效的浮点值 {env_key}={env_value}")
                    continue
            elif attr_name in {"debug_mode", "openai_use_responses_api", "openai_enable_reasoning"}:
                env_value = env_value.lower() in ("true", "1", "yes", "on")
            
            setattr(settings, attr_name, env_value)
    
    # 应用覆盖参数
    for key, value in overrides.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
        else:
            logger.warning(f"未知的设置参数: {key}")
    
    return settings


def get_default_config_dir() -> Path:
    """获取默认配置目录"""
    config_dir = Path.home() / ".summeryanyfile"
    config_dir.mkdir(exist_ok=True)
    return config_dir


def create_default_config():
    """创建默认配置文件"""
    config_dir = get_default_config_dir()
    config_file = config_dir / "config.json"
    
    if not config_file.exists():
        settings = Settings()
        settings.save_to_file(str(config_file))
        print(f"默认配置文件已创建: {config_file}")
    else:
        print(f"配置文件已存在: {config_file}")


def create_env_template():
    """创建环境变量模板文件"""
    template_content = """# LLM API Keys
OPENAI_API_KEY=your_openai_api_key_here
# OPENAI_BASE_URL=https://api.openai.com/v1  # 自定义OpenAI API端点（可选）
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Azure OpenAI (if using Azure)
AZURE_OPENAI_API_KEY=your_azure_openai_api_key_here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-02-15-preview

# LLM Configuration
LLM_MODEL=gpt-4o-mini
LLM_PROVIDER=openai
TEMPERATURE=0.7
MAX_TOKENS=4000

# Processing Configuration
MAX_SLIDES=25
MIN_SLIDES=5
CHUNK_SIZE=3000
CHUNK_OVERLAP=200
CHUNK_STRATEGY=paragraph

# Logging
LOG_LEVEL=INFO
DEBUG_MODE=false
"""
    
    env_file = Path(".env.template")
    with open(env_file, 'w', encoding='utf-8') as f:
        f.write(template_content)
    
    print(f"环境变量模板已创建: {env_file}")
    print("请复制为 .env 文件并填入您的API密钥")
