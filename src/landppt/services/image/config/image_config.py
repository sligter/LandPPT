"""
图片服务配置管理
"""

import os
from typing import Dict, Any, Optional, List
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class ImageServiceConfig:
    """图片服务配置管理器"""
    
    def __init__(self):
        self._config = self._load_default_config()
        self._load_env_config()
    
    def _load_default_config(self) -> Dict[str, Any]:
        """加载默认配置"""
        return {
            # DALL-E配置
            'dalle': {
                'api_key': '',
                'api_base': 'https://api.openai.com/v1',
                'model': 'dall-e-3',
                'default_size': '1792x1024',  # 16:9比例，适合PPT
                'default_quality': 'standard',  # standard, hd
                'default_style': 'natural',  # vivid, natural
                'rate_limit_requests': 50,  # 每分钟请求数
                'rate_limit_window': 60,  # 时间窗口（秒）
                'timeout': 180  # 请求超时（秒）
            },
            
            # Stable Diffusion配置
            'stable_diffusion': {
                'api_key': '',
                'api_base': 'https://api.stability.ai/v1',
                'engine_id': 'stable-diffusion-xl-1024-v1-0',
                'default_width': 1024,
                'default_height': 576,  # 16:9比例
                'default_steps': 30,
                'default_cfg_scale': 7.0,
                'default_sampler': 'K_DPM_2_ANCESTRAL',
                'rate_limit_requests': 150,  # 每分钟请求数
                'rate_limit_window': 60,  # 时间窗口（秒）
                'timeout': 180  # 请求超时（秒）
            },

            # SiliconFlow配置
            'siliconflow': {
                'api_key': '',
                'api_base': 'https://api.siliconflow.cn/v1',
                'model': 'Kwai-Kolors/Kolors',
                'default_size': '1024x1024',
                'default_batch_size': 1,
                'default_steps': 20,
                'default_guidance_scale': 7.5,
                'rate_limit_requests': 60,  # 每分钟请求数
                'rate_limit_window': 60,  # 时间窗口（秒）
                'timeout': 120  # 请求超时（秒）
            },


            # Gemini图片生成配置
            'gemini': {
                'api_key': '',
                'api_base': 'https://generativelanguage.googleapis.com/v1beta',
                'model': 'gemini-2.0-flash-exp-image-generation',
                'default_size': '1024x1024',
                'rate_limit_requests': 60,  # 每分钟请求数
                'rate_limit_window': 60,  # 时间窗口（秒）
                'timeout': 180  # 请求超时（秒）
            },

            # OpenAI图片生成配置（支持自定义端点）
            'openai_image': {
                'api_key': '',
                'api_base': 'https://api.openai.com/v1',
                'model': 'gpt-image-1',
                'default_size': '1024x1024',
                'default_quality': 'auto',  # auto, low, medium, high
                'rate_limit_requests': 50,  # 每分钟请求数
                'rate_limit_window': 60,  # 时间窗口（秒）
                'timeout': 180  # 请求超时（秒）
            },

            # Pollinations 图片生成配置（gen.pollinations.ai）
            'pollinations': {
                'api_key': '',
                'api_base': 'https://gen.pollinations.ai',
                'model': 'flux',
                'default_negative_prompt': 'worst quality, blurry',
                'default_enhance': False,
                'default_safe': False,
                'rate_limit_requests': 60,  # 每分钟请求数
                'rate_limit_window': 60,  # 时间窗口（秒）
                'timeout': 180  # 请求超时（秒）
            },
            
            # Unsplash配置（网络搜索）
            'unsplash': {
                'api_key': '',
                'api_base': 'https://api.unsplash.com',
                'per_page': 20,
                'rate_limit_requests': 50,
                'rate_limit_window': 3600,  # 1小时
                'timeout': 30
            },
            
            # Pixabay配置（网络搜索）- 根据官方API文档
            'pixabay': {
                'api_key': '',
                'api_base': 'https://pixabay.com/api',
                'per_page': 20,  # 默认20，最大200
                'rate_limit_requests': 100,  # 官方文档：100请求/60秒
                'rate_limit_window': 60,  # 官方文档：60秒窗口
                'timeout': 30,
                'cache_duration': 86400  # 官方要求：缓存24小时
            },

            # SearXNG配置（网络搜索）
            'searxng': {
                'host': '',  # SearXNG实例的主机地址，如 http://209.135.170.113:8888
                'per_page': 20,
                'rate_limit_requests': 60,  # 每分钟请求限制
                'rate_limit_window': 60,  # 60秒窗口
                'timeout': 30,
                'language': 'auto',  # 搜索语言
                'theme': 'simple'  # 主题
            },
            
            # 缓存配置 - 简化配置，图片永久有效
            'cache': {
                'base_dir': 'temp/images_cache',
                'max_size_gb': 5.0,  # 默认最大缓存大小5GB
                'cleanup_interval_hours': 24,  # 默认24小时清理一次（虽然图片永久有效，但保留配置项）
                # Per-user image hosting quota (MB). Set <= 0 to disable quota.
                'user_quota_mb': 100
            },
            
            # 图片处理配置
            'processing': {
                'max_file_size_mb': 50,
                'supported_formats': ['jpg', 'jpeg', 'png', 'webp', 'gif'],
                'default_quality': 85,
                # Store uploads/generations as WebP to reduce storage usage
                'upload_convert_to_webp': True,
                'upload_webp_quality': 80,
                'upload_webp_method': 6,
                'upload_skip_animated': True,
                'thumbnail_size': (300, 200),
                'watermark_enabled': False,
                'watermark_text': 'LandPPT',
                'watermark_opacity': 0.3
            },
            
            # 智能匹配配置
            'matching': {
                'similarity_threshold': 0.3,
                'max_suggestions': 10,
                'keyword_weight': 0.4,
                'tag_weight': 0.3,
                'usage_weight': 0.2,
                'freshness_weight': 0.1
            },
            
            # PPT适配器配置
            'ppt_adapter': {
                'default_size': '1792x1024',
                'quality_mode': 'standard',
                'style_preference': 'natural',
                'enable_negative_prompts': True,
                'prompt_enhancement': True
            }
        }
    
    def _load_env_config(self):
        """从环境变量加载配置"""
        # DALL-E配置
        if os.getenv('OPENAI_API_KEY'):
            self._config['dalle']['api_key'] = os.getenv('OPENAI_API_KEY')
        
        if os.getenv('DALLE_API_BASE'):
            self._config['dalle']['api_base'] = os.getenv('DALLE_API_BASE')
        
        # Stable Diffusion配置
        if os.getenv('STABILITY_API_KEY'):
            self._config['stable_diffusion']['api_key'] = os.getenv('STABILITY_API_KEY')

        if os.getenv('STABILITY_API_BASE'):
            self._config['stable_diffusion']['api_base'] = os.getenv('STABILITY_API_BASE')

        # SiliconFlow配置
        if os.getenv('SILICONFLOW_API_KEY'):
            self._config['siliconflow']['api_key'] = os.getenv('SILICONFLOW_API_KEY')

        if os.getenv('SILICONFLOW_API_BASE'):
            self._config['siliconflow']['api_base'] = os.getenv('SILICONFLOW_API_BASE')

        # Pollinations 配置
        if os.getenv('POLLINATIONS_API_KEY'):
            self._config['pollinations']['api_key'] = os.getenv('POLLINATIONS_API_KEY')
        if os.getenv('POLLINATIONS_API_BASE'):
            self._config['pollinations']['api_base'] = os.getenv('POLLINATIONS_API_BASE')
        if os.getenv('POLLINATIONS_MODEL'):
            self._config['pollinations']['model'] = os.getenv('POLLINATIONS_MODEL')
        if os.getenv('POLLINATIONS_NEGATIVE_PROMPT'):
            self._config['pollinations']['default_negative_prompt'] = os.getenv('POLLINATIONS_NEGATIVE_PROMPT')
        if os.getenv('POLLINATIONS_ENHANCE') is not None:
            self._config['pollinations']['default_enhance'] = str(os.getenv('POLLINATIONS_ENHANCE')).lower() in ("true", "1", "yes", "on")
        if os.getenv('POLLINATIONS_SAFE') is not None:
            self._config['pollinations']['default_safe'] = str(os.getenv('POLLINATIONS_SAFE')).lower() in ("true", "1", "yes", "on")

        # 从配置服务加载SiliconFlow配置
        try:
            from ...config_service import get_config_service
            config_service = get_config_service()
            all_config = config_service.get_all_config()

            # 加载SiliconFlow API密钥
            siliconflow_api_key = all_config.get('siliconflow_api_key')
            if siliconflow_api_key:
                self._config['siliconflow']['api_key'] = siliconflow_api_key

            # 加载SiliconFlow生成参数
            siliconflow_size = all_config.get('siliconflow_image_size')
            if siliconflow_size:
                self._config['siliconflow']['default_size'] = siliconflow_size

            siliconflow_steps = all_config.get('siliconflow_steps')
            if siliconflow_steps:
                self._config['siliconflow']['default_steps'] = int(siliconflow_steps)

            siliconflow_guidance = all_config.get('siliconflow_guidance_scale')
            if siliconflow_guidance:
                self._config['siliconflow']['default_guidance_scale'] = float(siliconflow_guidance)

            # 加载 Pollinations 配置
            pollinations_api_key = all_config.get('pollinations_api_key')
            if pollinations_api_key:
                self._config['pollinations']['api_key'] = pollinations_api_key
            pollinations_api_base = all_config.get('pollinations_api_base')
            if pollinations_api_base:
                self._config['pollinations']['api_base'] = pollinations_api_base
            pollinations_model = all_config.get('pollinations_model')
            if pollinations_model:
                self._config['pollinations']['model'] = pollinations_model
            pollinations_negative_prompt = all_config.get('pollinations_negative_prompt')
            if pollinations_negative_prompt:
                self._config['pollinations']['default_negative_prompt'] = pollinations_negative_prompt
            if 'pollinations_enhance' in all_config:
                self._config['pollinations']['default_enhance'] = bool(all_config.get('pollinations_enhance'))
            if 'pollinations_safe' in all_config:
                self._config['pollinations']['default_safe'] = bool(all_config.get('pollinations_safe'))

            # 加载Unsplash配置
            unsplash_access_key = all_config.get('unsplash_access_key')
            if unsplash_access_key:
                self._config['unsplash']['api_key'] = unsplash_access_key

            # 加载Pixabay配置
            pixabay_api_key = all_config.get('pixabay_api_key')
            if pixabay_api_key:
                self._config['pixabay']['api_key'] = pixabay_api_key

        except Exception as e:
            logger.warning(f"Failed to load config from config service: {e}")

        # Unsplash配置（环境变量）
        if os.getenv('UNSPLASH_ACCESS_KEY'):
            self._config['unsplash']['api_key'] = os.getenv('UNSPLASH_ACCESS_KEY')

        # Pixabay配置（环境变量）
        if os.getenv('PIXABAY_API_KEY'):
            self._config['pixabay']['api_key'] = os.getenv('PIXABAY_API_KEY')

        # SearXNG配置（环境变量）
        if os.getenv('SEARXNG_HOST'):
            self._config['searxng']['host'] = os.getenv('SEARXNG_HOST')

        # Per-user image hosting quota (MB). Set <= 0 to disable quota.
        quota_mb = os.getenv('IMAGE_USER_STORAGE_QUOTA_MB')
        if quota_mb is not None and str(quota_mb).strip() != "":
            try:
                self._config['cache']['user_quota_mb'] = int(float(quota_mb))
            except Exception:
                logger.warning("Invalid IMAGE_USER_STORAGE_QUOTA_MB=%r, using default=%r", quota_mb, self._config['cache'].get('user_quota_mb'))


        # Gemini图片生成配置（环境变量）- 使用独立的配置，不与文本生成共用
        if os.getenv('GEMINI_IMAGE_API_KEY'):
            self._config['gemini']['api_key'] = os.getenv('GEMINI_IMAGE_API_KEY')
        if os.getenv('GEMINI_IMAGE_API_BASE'):
            self._config['gemini']['api_base'] = os.getenv('GEMINI_IMAGE_API_BASE')
        if os.getenv('GEMINI_IMAGE_MODEL'):
            self._config['gemini']['model'] = os.getenv('GEMINI_IMAGE_MODEL')

        # OpenAI图片生成配置（环境变量）- 使用独立的配置，不与文本生成共用
        if os.getenv('OPENAI_IMAGE_API_KEY'):
            self._config['openai_image']['api_key'] = os.getenv('OPENAI_IMAGE_API_KEY')
        if os.getenv('OPENAI_IMAGE_API_BASE'):
            self._config['openai_image']['api_base'] = os.getenv('OPENAI_IMAGE_API_BASE')
        if os.getenv('OPENAI_IMAGE_MODEL'):
            self._config['openai_image']['model'] = os.getenv('OPENAI_IMAGE_MODEL')

        # 从配置服务加载Gemini和OpenAI图片生成配置
        try:
            from ...config_service import get_config_service
            config_service = get_config_service()
            all_config = config_service.get_all_config()

            # 加载Gemini图片生成配置 - 使用独立配置，不与文本生成共用
            gemini_api_key = all_config.get('gemini_image_api_key')
            if gemini_api_key:
                self._config['gemini']['api_key'] = gemini_api_key

            gemini_api_base = all_config.get('gemini_image_api_base')
            if gemini_api_base:
                self._config['gemini']['api_base'] = gemini_api_base

            gemini_model = all_config.get('gemini_image_model')
            if gemini_model:
                self._config['gemini']['model'] = gemini_model

            # 加载OpenAI图片生成配置 - 使用独立配置，不与文本生成共用
            openai_image_api_key = all_config.get('openai_image_api_key')
            if openai_image_api_key:
                self._config['openai_image']['api_key'] = openai_image_api_key

            openai_image_api_base = all_config.get('openai_image_api_base')
            if openai_image_api_base:
                self._config['openai_image']['api_base'] = openai_image_api_base

            openai_image_model = all_config.get('openai_image_model')
            if openai_image_model:
                self._config['openai_image']['model'] = openai_image_model

            openai_image_quality = all_config.get('openai_image_quality')
            if openai_image_quality:
                self._config['openai_image']['default_quality'] = openai_image_quality

        except Exception as e:
            logger.debug(f"Could not load Gemini/OpenAI image config from config service: {e}")


        # 缓存目录配置
        if os.getenv('IMAGE_CACHE_DIR'):
            self._config['cache']['base_dir'] = os.getenv('IMAGE_CACHE_DIR')
    
    def get_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self._config.copy()
    
    async def load_config_from_db_async(self, user_id: Optional[int] = None):
        """
        从数据库异步加载用户特定的配置。
        这会覆盖环境变量中加载的配置，以用户在UI中配置的值为准。
        
        Args:
            user_id: 用户ID，如果为None则加载系统级配置
        """
        try:
            from ...db_config_service import get_db_config_service
            db_config_service = get_db_config_service()
            all_config = await db_config_service.get_all_config(user_id)
            
            logger.info(f"Loading image config from database for user {user_id}")
            
            # 加载SiliconFlow配置
            siliconflow_api_key = all_config.get('siliconflow_api_key')
            if siliconflow_api_key and str(siliconflow_api_key).strip():
                self._config['siliconflow']['api_key'] = siliconflow_api_key
                logger.info(f"Loaded SiliconFlow API key from database for user {user_id}: ***{siliconflow_api_key[-4:] if len(siliconflow_api_key) > 4 else '****'}")
            else:
                logger.warning(f"SiliconFlow API key not found or empty in database for user {user_id}")
            
            siliconflow_size = all_config.get('siliconflow_image_size')
            if siliconflow_size:
                self._config['siliconflow']['default_size'] = siliconflow_size
            
            siliconflow_steps = all_config.get('siliconflow_steps')
            if siliconflow_steps:
                try:
                    self._config['siliconflow']['default_steps'] = int(siliconflow_steps)
                except (ValueError, TypeError):
                    pass
            
            siliconflow_guidance = all_config.get('siliconflow_guidance_scale')
            if siliconflow_guidance:
                try:
                    self._config['siliconflow']['default_guidance_scale'] = float(siliconflow_guidance)
                except (ValueError, TypeError):
                    pass
            
            # 加载DALL-E配置
            dalle_api_key = all_config.get('openai_api_key_image')
            if dalle_api_key:
                self._config['dalle']['api_key'] = dalle_api_key
                logger.debug(f"Loaded DALL-E API key from database for user {user_id}")
            
            dalle_size = all_config.get('dalle_image_size')
            if dalle_size:
                self._config['dalle']['default_size'] = dalle_size
            
            dalle_quality = all_config.get('dalle_image_quality')
            if dalle_quality:
                self._config['dalle']['default_quality'] = dalle_quality
            
            dalle_style = all_config.get('dalle_image_style')
            if dalle_style:
                self._config['dalle']['default_style'] = dalle_style
            
            # 加载Stable Diffusion配置
            stability_api_key = all_config.get('stability_api_key')
            if stability_api_key:
                self._config['stable_diffusion']['api_key'] = stability_api_key
                logger.debug(f"Loaded Stability API key from database for user {user_id}")
            
            # 加载Gemini图片生成配置
            gemini_api_key = all_config.get('gemini_image_api_key')
            if gemini_api_key:
                self._config['gemini']['api_key'] = gemini_api_key
                logger.debug(f"Loaded Gemini Image API key from database for user {user_id}")
            
            gemini_api_base = all_config.get('gemini_image_api_base')
            if gemini_api_base:
                self._config['gemini']['api_base'] = gemini_api_base
            
            gemini_model = all_config.get('gemini_image_model')
            if gemini_model:
                self._config['gemini']['model'] = gemini_model
            
            # 加载OpenAI图片生成配置
            openai_image_api_key = all_config.get('openai_image_api_key')
            if openai_image_api_key:
                self._config['openai_image']['api_key'] = openai_image_api_key
                logger.debug(f"Loaded OpenAI Image API key from database for user {user_id}")
            
            openai_image_api_base = all_config.get('openai_image_api_base')
            if openai_image_api_base:
                self._config['openai_image']['api_base'] = openai_image_api_base
            
            openai_image_model = all_config.get('openai_image_model')
            if openai_image_model:
                self._config['openai_image']['model'] = openai_image_model
            
            openai_image_quality = all_config.get('openai_image_quality')
            if openai_image_quality:
                self._config['openai_image']['default_quality'] = openai_image_quality

            # 加载 Pollinations 图片生成配置
            pollinations_api_key = all_config.get('pollinations_api_key')
            if pollinations_api_key and str(pollinations_api_key).strip():
                self._config['pollinations']['api_key'] = pollinations_api_key

            pollinations_api_base = all_config.get('pollinations_api_base')
            if pollinations_api_base and str(pollinations_api_base).strip():
                self._config['pollinations']['api_base'] = pollinations_api_base

            pollinations_model = all_config.get('pollinations_model')
            if pollinations_model and str(pollinations_model).strip():
                self._config['pollinations']['model'] = pollinations_model

            pollinations_negative_prompt = all_config.get('pollinations_negative_prompt')
            if pollinations_negative_prompt and str(pollinations_negative_prompt).strip():
                self._config['pollinations']['default_negative_prompt'] = pollinations_negative_prompt

            if 'pollinations_enhance' in all_config:
                self._config['pollinations']['default_enhance'] = bool(all_config.get('pollinations_enhance'))
            if 'pollinations_safe' in all_config:
                self._config['pollinations']['default_safe'] = bool(all_config.get('pollinations_safe'))
             
            # 加载Unsplash配置
            unsplash_access_key = all_config.get('unsplash_access_key')
            if unsplash_access_key:
                self._config['unsplash']['api_key'] = unsplash_access_key
            
            # 加载Pixabay配置
            pixabay_api_key = all_config.get('pixabay_api_key')
            if pixabay_api_key:
                self._config['pixabay']['api_key'] = pixabay_api_key

            # 加载 SearXNG 配置
            searxng_host = all_config.get('searxng_host')
            if searxng_host and str(searxng_host).strip():
                self._config['searxng']['host'] = searxng_host
             
            logger.info(f"Successfully loaded image service config from database for user {user_id}")
             
        except Exception as e:
            logger.warning(f"Failed to load image config from database for user {user_id}: {e}")

    def load_config_from_db_sync(self, user_id: Optional[int] = None):
        """Sync variant of DB-backed image config loading."""
        try:
            from ...db_config_service import get_db_config_service

            db_config_service = get_db_config_service()
            all_config = db_config_service.get_all_config_sync(user_id)

            logger.info(f"Loading image config from database for user {user_id}")

            siliconflow_api_key = all_config.get('siliconflow_api_key')
            if siliconflow_api_key and str(siliconflow_api_key).strip():
                self._config['siliconflow']['api_key'] = siliconflow_api_key
                logger.info(
                    "Loaded SiliconFlow API key from database for user %s: ***%s",
                    user_id,
                    siliconflow_api_key[-4:] if len(siliconflow_api_key) > 4 else "****",
                )
            else:
                logger.warning(f"SiliconFlow API key not found or empty in database for user {user_id}")

            siliconflow_size = all_config.get('siliconflow_image_size')
            if siliconflow_size:
                self._config['siliconflow']['default_size'] = siliconflow_size

            siliconflow_steps = all_config.get('siliconflow_steps')
            if siliconflow_steps:
                try:
                    self._config['siliconflow']['default_steps'] = int(siliconflow_steps)
                except (ValueError, TypeError):
                    pass

            siliconflow_guidance = all_config.get('siliconflow_guidance_scale')
            if siliconflow_guidance:
                try:
                    self._config['siliconflow']['default_guidance_scale'] = float(siliconflow_guidance)
                except (ValueError, TypeError):
                    pass

            dalle_api_key = all_config.get('openai_api_key_image')
            if dalle_api_key:
                self._config['dalle']['api_key'] = dalle_api_key
                logger.debug(f"Loaded DALL-E API key from database for user {user_id}")

            dalle_size = all_config.get('dalle_image_size')
            if dalle_size:
                self._config['dalle']['default_size'] = dalle_size

            dalle_quality = all_config.get('dalle_image_quality')
            if dalle_quality:
                self._config['dalle']['default_quality'] = dalle_quality

            dalle_style = all_config.get('dalle_image_style')
            if dalle_style:
                self._config['dalle']['default_style'] = dalle_style

            stability_api_key = all_config.get('stability_api_key')
            if stability_api_key:
                self._config['stable_diffusion']['api_key'] = stability_api_key
                logger.debug(f"Loaded Stability API key from database for user {user_id}")

            gemini_api_key = all_config.get('gemini_image_api_key')
            if gemini_api_key:
                self._config['gemini']['api_key'] = gemini_api_key
                logger.debug(f"Loaded Gemini Image API key from database for user {user_id}")

            gemini_api_base = all_config.get('gemini_image_api_base')
            if gemini_api_base:
                self._config['gemini']['api_base'] = gemini_api_base

            gemini_model = all_config.get('gemini_image_model')
            if gemini_model:
                self._config['gemini']['model'] = gemini_model

            openai_image_api_key = all_config.get('openai_image_api_key')
            if openai_image_api_key:
                self._config['openai_image']['api_key'] = openai_image_api_key
                logger.debug(f"Loaded OpenAI Image API key from database for user {user_id}")

            openai_image_api_base = all_config.get('openai_image_api_base')
            if openai_image_api_base:
                self._config['openai_image']['api_base'] = openai_image_api_base

            openai_image_model = all_config.get('openai_image_model')
            if openai_image_model:
                self._config['openai_image']['model'] = openai_image_model

            openai_image_quality = all_config.get('openai_image_quality')
            if openai_image_quality:
                self._config['openai_image']['default_quality'] = openai_image_quality

            pollinations_api_key = all_config.get('pollinations_api_key')
            if pollinations_api_key and str(pollinations_api_key).strip():
                self._config['pollinations']['api_key'] = pollinations_api_key

            pollinations_api_base = all_config.get('pollinations_api_base')
            if pollinations_api_base and str(pollinations_api_base).strip():
                self._config['pollinations']['api_base'] = pollinations_api_base

            pollinations_model = all_config.get('pollinations_model')
            if pollinations_model and str(pollinations_model).strip():
                self._config['pollinations']['model'] = pollinations_model

            pollinations_negative_prompt = all_config.get('pollinations_negative_prompt')
            if pollinations_negative_prompt and str(pollinations_negative_prompt).strip():
                self._config['pollinations']['default_negative_prompt'] = pollinations_negative_prompt

            if 'pollinations_enhance' in all_config:
                self._config['pollinations']['default_enhance'] = bool(all_config.get('pollinations_enhance'))
            if 'pollinations_safe' in all_config:
                self._config['pollinations']['default_safe'] = bool(all_config.get('pollinations_safe'))

            unsplash_access_key = all_config.get('unsplash_access_key')
            if unsplash_access_key:
                self._config['unsplash']['api_key'] = unsplash_access_key

            pixabay_api_key = all_config.get('pixabay_api_key')
            if pixabay_api_key:
                self._config['pixabay']['api_key'] = pixabay_api_key

            searxng_host = all_config.get('searxng_host')
            if searxng_host and str(searxng_host).strip():
                self._config['searxng']['host'] = searxng_host

            logger.info(f"Successfully loaded image service config from database for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to load image config from database for user {user_id}: {e}")

    
    def get_provider_config(self, provider: str) -> Dict[str, Any]:
        """获取特定提供者的配置"""
        return self._config.get(provider, {}).copy()
    
    def update_config(self, updates: Dict[str, Any]):
        """更新配置"""
        def deep_update(base_dict, update_dict):
            for key, value in update_dict.items():
                if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                    deep_update(base_dict[key], value)
                else:
                    base_dict[key] = value
        
        deep_update(self._config, updates)
    
    def is_provider_configured(self, provider: str) -> bool:
        """检查提供者是否已配置"""
        provider_config = self._config.get(provider, {})

        # SearXNG使用host而不是api_key
        if provider == 'searxng':
            host = provider_config.get('host', '')
            return bool(host and host.strip())


        # 其他提供者检查API密钥是否存在
        api_key = provider_config.get('api_key', '')
        return bool(api_key and api_key.strip())

    def should_enable_search_provider(self, provider: str) -> bool:
        """检查是否应该启用指定的搜索提供者"""
        # 首先检查API密钥是否配置
        if not self.is_provider_configured(provider):
            return False

        # 获取默认网络搜索提供商配置
        try:
            from ...config_service import get_config_service
            config_service = get_config_service()
            all_config = config_service.get_all_config()
            default_provider = all_config.get('default_network_search_provider', 'unsplash')

            # 如果是默认提供商，则启用
            return provider.lower() == default_provider.lower()

        except Exception as e:
            logger.warning(f"Failed to get default network search provider config: {e}")
            # 如果获取配置失败，回退到检查API密钥
            return self.is_provider_configured(provider)
    
    def get_configured_providers(self) -> List[str]:
        """获取已配置的提供者列表"""
        providers = []

        for provider in ['dalle', 'stable_diffusion', 'siliconflow', 'gemini', 'openai_image', 'pollinations', 'unsplash', 'pixabay', 'searxng']:
            if self.is_provider_configured(provider):
                providers.append(provider)

        return providers

    def get_all_config(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self._config
    
    def validate_config(self) -> Dict[str, List[str]]:
        """验证配置并返回错误信息"""
        errors = {}

        # 验证缓存配置
        cache_config = self._config.get('cache', {})
        cache_errors = []

        # 检查max_size_gb（如果存在的话）
        max_size_gb = cache_config.get('max_size_gb')
        if max_size_gb is not None and max_size_gb <= 0:
            cache_errors.append("max_size_gb must be greater than 0")

        # 检查cleanup_interval_hours（如果存在的话）
        cleanup_interval = cache_config.get('cleanup_interval_hours')
        if cleanup_interval is not None and cleanup_interval <= 0:
            cache_errors.append("cleanup_interval_hours must be greater than 0")

        # 检查base_dir是否存在
        if not cache_config.get('base_dir'):
            cache_errors.append("base_dir is required")

        if cache_errors:
            errors['cache'] = cache_errors
        
        # 验证处理配置
        processing_config = self._config.get('processing', {})
        processing_errors = []
        
        if processing_config.get('max_file_size_mb', 0) <= 0:
            processing_errors.append("max_file_size_mb must be greater than 0")
        
        if not processing_config.get('supported_formats'):
            processing_errors.append("supported_formats cannot be empty")
        
        if processing_errors:
            errors['processing'] = processing_errors
        
        return errors
    
    def save_to_file(self, file_path: str):
        """保存配置到文件"""
        import json
        
        config_path = Path(file_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2, ensure_ascii=False)
    
    def load_from_file(self, file_path: str):
        """从文件加载配置"""
        import json
        
        config_path = Path(file_path)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                file_config = json.load(f)
                self.update_config(file_config)


# 创建全局配置实例
image_config = ImageServiceConfig()


def get_image_config() -> ImageServiceConfig:
    """获取图片服务配置实例"""
    return image_config


def update_image_config(updates: Dict[str, Any]):
    """更新图片服务配置"""
    image_config.update_config(updates)


def get_provider_config(provider: str) -> Dict[str, Any]:
    """获取特定提供者的配置"""
    return image_config.get_provider_config(provider)


def is_provider_configured(provider: str) -> bool:
    """检查提供者是否已配置"""
    return image_config.is_provider_configured(provider)
