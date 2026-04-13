"""
PPT图片处理器
负责在PPT生成过程中处理图片相关逻辑，包括本地图片选择、网络图片搜索、AI图片生成
支持多图片处理，由AI决定每种来源的图片数量
"""

import logging
from typing import Dict, Any, Optional, List
import aiohttp
import json
import asyncio
from pathlib import Path
import re

from ..ai import get_role_provider
from ..core.config import ai_config

from .models.slide_image_info import (
    SlideImageInfo, SlideImagesCollection, SlideImageRequirements,
    ImageRequirement, ImageSource, ImagePurpose
)
from .image.models import ImageSourceType

logger = logging.getLogger(__name__)


class PPTImageProcessor:
    """PPT图片处理器"""
    
    def __init__(self, image_service=None, ai_provider=None, user_id: Optional[int] = None, provider_override: Optional[str] = None):
        self.image_service = image_service
        self.ai_provider = ai_provider
        self.user_id = user_id
        self.provider_override = provider_override
        self._base_url = None
        # 搜索缓存，避免重复搜索
        self._search_cache = {}
        self._search_lock = asyncio.Lock()

    async def _text_completion(self, *, prompt: str, **kwargs):
        """调用角色为图片分析的模型"""
        # 优先使用用户数据库配置获取模型设置
        if self.user_id is not None:
            from .db_config_service import get_user_role_provider
            provider, role_settings = await get_user_role_provider(
                self.user_id, "image_prompt", provider_override=self.provider_override
            )
            if role_settings.get("model"):
                kwargs.setdefault("model", role_settings["model"])
        elif self.ai_provider:
            provider = self.ai_provider
            if "model" not in kwargs:
                role_settings = ai_config.get_model_config_for_role("image_prompt", provider_override=self.provider_override)
                if role_settings.get("model"):
                    kwargs["model"] = role_settings["model"]
        else:
            provider, role_settings = get_role_provider("image_prompt", provider_override=self.provider_override)
            if role_settings.get("model"):
                kwargs.setdefault("model", role_settings["model"])
        return await provider.text_completion(prompt=prompt, **kwargs)


    def _get_base_url(self) -> str:
        """获取基础URL，用于构建绝对图片链接"""
        from .url_service import get_current_base_url
        return get_current_base_url()

    def _build_absolute_image_url(self, relative_path: str) -> str:
        """构建绝对图片URL"""
        from .url_service import build_absolute_url
        return build_absolute_url(relative_path)

    def _get_enabled_image_sources(self, image_config: Dict[str, Any]) -> List[ImageSource]:
        """获取启用的图像来源"""
        enabled_sources = []
        if image_config.get('enable_local_images', True):
            enabled_sources.append(ImageSource.LOCAL)
        if image_config.get('enable_network_search', False):
            enabled_sources.append(ImageSource.NETWORK)
        if image_config.get('enable_ai_generation', False):
            enabled_sources.append(ImageSource.AI_GENERATED)
        return enabled_sources

    def _normalize_network_search_provider(self, provider: Optional[str]) -> str:
        """Normalize provider string from config/UI."""
        if not provider:
            return ""
        value = str(provider).strip().lower()
        aliases = {
            "pixbay": "pixabay",
            "pxabay": "pixabay",
            "unspalsh": "unsplash",
        }
        return aliases.get(value, value)

    def _is_network_provider_configured(self, provider: str, image_config: Dict[str, Any]) -> bool:
        """Check whether the given provider has usable credentials in the provided config."""
        provider = self._normalize_network_search_provider(provider)
        if provider == "unsplash":
            key = image_config.get("unsplash_access_key")
            return bool(key and str(key).strip())
        if provider == "pixabay":
            key = image_config.get("pixabay_api_key")
            return bool(key and str(key).strip())
        if provider == "searxng":
            host = image_config.get("searxng_host")
            return bool(host and str(host).strip())
        return False

    def _select_network_search_provider(self, image_config: Dict[str, Any]) -> Optional[str]:
        """
        Pick a working network search provider based on DB config:
        - Prefer `default_network_search_provider` when configured.
        - Otherwise fall back to any configured provider.
        """
        desired = self._normalize_network_search_provider(image_config.get("default_network_search_provider"))
        if desired and self._is_network_provider_configured(desired, image_config):
            return desired

        for candidate in ("pixabay", "unsplash", "searxng"):
            if self._is_network_provider_configured(candidate, image_config):
                return candidate

        return None

    async def process_slide_image(self, slide_data: Dict[str, Any], confirmed_requirements: Dict[str, Any],
                                 page_number: int, total_pages: int, template_html: str = "") -> Optional[SlideImagesCollection]:
        """处理幻灯片多图片生成/搜索/选择逻辑"""
        try:
            # 检查是否启用图片生成服务 - 从用户数据库配置读取（非环境变量）
            from .db_config_service import get_db_config_service
            db_config_service = get_db_config_service()
            image_config = await db_config_service.get_config_by_category('image_service', user_id=self.user_id)

            enable_image_service = image_config.get('enable_image_service', False)
            logger.info(f"图片服务配置 (user_id={self.user_id}): enable_image_service={enable_image_service}")
            if not enable_image_service:
                logger.info(f"第{page_number}页: 图片生成服务未启用，跳过图片处理")
                return None

            # 获取项目信息
            project_topic = confirmed_requirements.get('project_topic', '')
            project_scenario = confirmed_requirements.get('project_scenario', 'general')
            slide_title = slide_data.get('title', f'第{page_number}页')
            slide_content = slide_data.get('content_points', [])
            slide_content_text = '\n'.join(slide_content) if isinstance(slide_content, list) else str(slide_content)

            # 检查启用的图片来源
            enabled_sources = self._get_enabled_image_sources(image_config)

            if not enabled_sources:
                logger.info(f"第{page_number}页没有启用任何图片来源，跳过图片处理")
                return None

            # 让AI分析并决定图片需求（只考虑启用的来源）
            image_requirements = await self._ai_analyze_image_requirements(
                slide_data, project_topic, project_scenario, page_number, total_pages, template_html, enabled_sources, image_config
            )

            if not image_requirements or not image_requirements.requirements:
                logger.info(f"AI判断第{page_number}页不需要添加图片，跳过图片处理")
                return None

            logger.info(f"第{page_number}页图片需求: 总计{image_requirements.total_images_needed}张图片")

            # 创建图片集合
            images_collection = SlideImagesCollection(page_number=page_number, images=[])

            # 根据需求处理各种来源的图片
            for requirement in image_requirements.requirements:
                if requirement.source == ImageSource.LOCAL and ImageSource.LOCAL in enabled_sources:
                    local_images = await self._process_local_images(
                        requirement, project_topic, project_scenario, slide_title, slide_content_text
                    )
                    images_collection.images.extend(local_images)

                elif requirement.source == ImageSource.NETWORK and ImageSource.NETWORK in enabled_sources:
                    network_images = await self._process_network_images(
                        requirement, project_topic, project_scenario, slide_title, slide_content_text, image_config
                    )
                    images_collection.images.extend(network_images)

                elif requirement.source == ImageSource.AI_GENERATED and ImageSource.AI_GENERATED in enabled_sources:
                    ai_images = await self._process_ai_generated_images(
                        requirement, project_topic, project_scenario, slide_title, slide_content_text,
                        image_config, page_number, total_pages, template_html
                    )
                    images_collection.images.extend(ai_images)

            # 重新计算统计信息
            images_collection.__post_init__()

            if images_collection.total_count > 0:
                logger.info(f"第{page_number}页成功处理{images_collection.total_count}张图片: "
                          f"本地{images_collection.local_count}张, "
                          f"网络{images_collection.network_count}张, "
                          f"AI生成{images_collection.ai_generated_count}张")
                return images_collection
            else:
                logger.info(f"第{page_number}页未能获取到任何图片")
                return None

        except Exception as e:
            logger.error(f"处理幻灯片图片失败: {e}")
            return None

    async def _ai_analyze_image_requirements(self, slide_data: Dict[str, Any], project_topic: str,
                                           project_scenario: str, page_number: int, total_pages: int,
                                           template_html: str = "", enabled_sources: List[ImageSource] = None,
                                           image_config: Dict[str, Any] = None) -> Optional[SlideImageRequirements]:
        """使用AI分析幻灯片的图片需求"""
        # 提取幻灯片内容信息
        slide_title = slide_data.get('title', '')
        slide_content = slide_data.get('content_points', [])
        slide_content_text = '\n'.join(slide_content) if isinstance(slide_content, list) else str(slide_content)
        content_length = len(slide_content_text.strip())
        content_points_count = len(slide_content) if isinstance(slide_content, list) else 0

        # 处理启用的来源和配置限制
        if not enabled_sources:
            enabled_sources = [ImageSource.LOCAL, ImageSource.NETWORK, ImageSource.AI_GENERATED]

        if not image_config:
            image_config = {}

        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 获取各来源的最大数量限制
                max_local = image_config.get('max_local_images_per_slide', 2)
                max_network = image_config.get('max_network_images_per_slide', 2)
                max_ai = image_config.get('max_ai_images_per_slide', 1)
                max_total = image_config.get('max_total_images_per_slide', 3)

                # 构建启用来源的说明
                enabled_sources_desc = []
                if ImageSource.LOCAL in enabled_sources:
                    enabled_sources_desc.append(f"local: 本地图床中的图片，适合通用性图片 (最多{max_local}张)")
                if ImageSource.NETWORK in enabled_sources:
                    enabled_sources_desc.append(f"network: 网络搜索图片，适合特定主题的高质量图片 (最多{max_network}张)")
                if ImageSource.AI_GENERATED in enabled_sources:
                    enabled_sources_desc.append(f"ai_generated: AI生成图片，适合定制化、创意性图片 (最多{max_ai}张)")

                # 构建包含模板HTML的提示词
                template_context = ""
                if template_html.strip():
                    template_context = f"""
当前PPT模板HTML参考：
{template_html[:500]}...
"""

                prompt = f"""作为专业的PPT设计师，请分析以下幻灯片的图片需求。首先判断该页面内容是否需要或适合配图，如果不需要或不适合配图则返回0。

【项目信息】
- 主题：{project_topic}
- 场景：{project_scenario}
- 当前页：{page_number}/{total_pages}

【幻灯片内容】
- 标题：{slide_title}
- 内容要点数量：{content_points_count}个
- 内容字数：{content_length}字
- 具体内容：
{slide_content_text}

{template_context}

【可用图片来源及限制】
{chr(10).join(enabled_sources_desc)}

【图片用途说明】
1. decoration: 装饰性图片，美化页面
2. illustration: 说明性图片，辅助理解内容
3. background: 背景图片，营造氛围
4. icon: 图标，简化表达
5. chart_support: 图表辅助，支持数据展示
6. content_visual: 内容可视化，直观展示概念

【配图适用性判断标准】
请首先判断该页面是否需要或适合配图，考虑以下因素：
1. 内容类型：纯文字列表、目录页、致谢页等通常不需要配图
2. 内容密度：文字过多的页面可能不适合添加图片
3. 页面功能：导航页、索引页、参考文献页等功能性页面通常不需要配图
4. 内容抽象度：过于抽象或概念性的内容可能不适合配图
5. 版面空间：内容已经很满的页面不适合再添加图片

【不适合配图的典型情况】
- 纯文字列表或条目
- 目录、索引、导航页面
- 致谢、参考文献页面
- 纯数据表格页面
- 文字密集的详细说明页面
- 过于抽象的理论概念页面

【分析要求】
如果判断适合配图，请综合考虑以下因素来决定图片需求：
1. 内容复杂度：复杂内容需要更多说明性图片
2. 页面类型：封面页、章节页通常需要装饰性图片
3. 视觉平衡：文字密集的页面需要图片调节
4. 主题匹配：根据主题选择合适的图片来源
5. 设计风格：根据模板风格决定图片类型

【重要限制】
- 总图片数量不能超过{max_total}张
- 只能使用已启用的图片来源
- 每种来源都有数量限制，请严格遵守

请以JSON格式返回分析结果，格式如下：
{{
    "needs_images": true/false,
    "total_images": 数字,
    "requirements": [
        {{
            "source": "仅限已启用的来源",
            "count": 数字,
            "purpose": "decoration/illustration/background/icon/chart_support/content_visual",
            "description": "具体需求描述",
            "priority": 1-5
        }}
    ],
    "reasoning": "分析理由，包括是否适合配图的判断依据"
}}

【重要要求】：
- 如果不需要或不适合配图，设置needs_images为false，total_images为0，requirements为空数组
- 每种来源可以有多个需求项，支持不同用途
- 优先级1-5，5为最高优先级
- 严格遵守数量限制，避免页面过于拥挤
- 必须返回有效的JSON格式，不要添加任何解释文字
- 不要使用markdown代码块包装
- 确保所有字符串值都用双引号包围
- 确保布尔值使用true/false（小写）

请直接返回纯JSON格式的结果："""

                response = await self._text_completion(
                    prompt=prompt,
                    temperature=0.7
                )

                # 解析AI响应
                # 清理AI响应内容
                raw_content = response.content.strip()
                logger.debug(f"AI原始响应内容: {raw_content}")

                # 尝试提取JSON部分
                json_content = self._extract_json_from_response(raw_content)
                if not json_content:
                    logger.error(f"无法从AI响应中提取有效JSON: {raw_content}")
                    raise json.JSONDecodeError("无法提取有效JSON", raw_content, 0)

                result = json.loads(json_content)

                if not result.get('needs_images', False) or result.get('total_images', 0) == 0:
                    reasoning = result.get('reasoning', '未提供理由')
                    logger.info(f"AI判断第{page_number}页不需要或不适合配图: {reasoning}")
                    return None

                # 创建需求对象
                requirements = SlideImageRequirements(page_number=page_number, requirements=[])

                for req_data in result.get('requirements', []):
                    requirement = ImageRequirement(
                        source=ImageSource(req_data['source']),
                        count=req_data['count'],
                        purpose=ImagePurpose(req_data['purpose']),
                        description=req_data['description'],
                        priority=req_data.get('priority', 1)
                    )
                    requirements.add_requirement(requirement)

                logger.info(f"AI分析第{page_number}页图片需求: {result.get('reasoning', '')}")
                return requirements

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning(f"第{attempt + 1}次尝试解析AI图片需求分析结果失败: {e}")
                logger.debug(f"AI响应内容: {response.content}")
                if attempt < max_retries - 1:
                    logger.info(f"等待1秒后进行第{attempt + 2}次重试...")
                    import asyncio
                    await asyncio.sleep(1)
                    continue
                else:
                    logger.error(f"所有{max_retries}次尝试都失败，放弃图片需求分析")
                    return None

            except Exception as e:
                logger.warning(f"第{attempt + 1}次尝试AI分析图片需求失败: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"等待1秒后进行第{attempt + 2}次重试...")
                    import asyncio
                    await asyncio.sleep(1)
                    continue
                else:
                    logger.error(f"所有{max_retries}次尝试都失败，放弃图片需求分析")
                    return None

        # 如果所有重试都失败了
        logger.error("AI分析图片需求失败，已达到最大重试次数")
        return None

    def _extract_json_from_response(self, content: str) -> Optional[str]:
        """从AI响应中提取JSON内容"""
        try:
            # 移除可能的 think 内容
            content = content.split("</think>")[-1]

            # 移除可能的markdown代码块标记
            content = content.strip()

            # 如果内容被```json包围，提取其中的内容
            if content.startswith('```json') and content.endswith('```'):
                content = content[7:-3].strip()
            elif content.startswith('```') and content.endswith('```'):
                content = content[3:-3].strip()

            # 查找第一个{和最后一个}
            start_idx = content.find('{')
            end_idx = content.rfind('}')

            if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                json_content = content[start_idx:end_idx + 1]
                # 验证是否为有效JSON
                json.loads(json_content)
                return json_content

            # 如果直接是JSON格式
            json.loads(content)
            return content

        except (json.JSONDecodeError, ValueError):
            pass

        return None

    async def _process_local_images(self, requirement: ImageRequirement, project_topic: str,
                                  project_scenario: str, slide_title: str, slide_content: str) -> List[SlideImageInfo]:
        """处理本地图片需求"""
        images = []
        try:
            if not self.image_service:
                logger.warning("图片服务未初始化")
                return images

            # 获取本地图片库信息
            cache_stats = await self.image_service.get_cache_stats()
            total_images = 0
            if 'categories' in cache_stats:
                for _, count in cache_stats['categories'].items():
                    total_images += count

            if total_images == 0:
                logger.info("本地图片库为空，跳过本地图片选择")
                return images

            # 让AI生成搜索关键词
            search_keywords = await self._ai_generate_local_search_keywords(
                slide_title, slide_content, project_topic, project_scenario, requirement
            )

            if not search_keywords:
                logger.warning("无法生成本地搜索关键词")
                return images

            # 搜索并选择多张图片
            selected_images = await self._search_multiple_local_images(search_keywords, requirement.count)

            for image_id in selected_images:
                relative_url = f"/api/image/view/{image_id}"
                absolute_url = self._build_absolute_image_url(relative_url)

                # 获取图片详细信息
                image_info = await self._get_local_image_details(image_id)

                slide_image = SlideImageInfo(
                    image_id=image_id,
                    absolute_url=absolute_url,
                    source=ImageSource.LOCAL,
                    purpose=requirement.purpose,
                    content_description=requirement.description,
                    search_keywords=search_keywords,
                    alt_text=image_info.get('title', ''),
                    title=image_info.get('title', ''),
                    width=image_info.get('width'),
                    height=image_info.get('height'),
                    file_size=image_info.get('file_size'),
                    format=image_info.get('format')
                )
                images.append(slide_image)

            logger.info(f"成功选择{len(images)}张本地图片")
            return images

        except Exception as e:
            logger.error(f"处理本地图片失败: {e}")
            return images

    async def _process_network_images(self, requirement: ImageRequirement, project_topic: str,
                                    project_scenario: str, slide_title: str, slide_content: str,
                                    image_config: Dict[str, Any]) -> List[SlideImageInfo]:
        """处理网络图片需求"""
        images = []
        try:
            desired_provider = self._normalize_network_search_provider(
                image_config.get("default_network_search_provider") or "unsplash"
            )
            provider = self._select_network_search_provider(image_config)

            # 检查是否有可用的网络搜索提供商
            if not provider:
                logger.warning("没有配置可用的网络搜索提供商")
                # 添加详细的配置检查信息
                logger.warning(f"默认网络搜索提供商: {desired_provider}")
                logger.warning(f"Unsplash API Key: {'已配置' if image_config.get('unsplash_access_key') else '未配置'}")
                logger.warning(f"Pixabay API Key: {'已配置' if image_config.get('pixabay_api_key') else '未配置'}")
                logger.warning(f"SearXNG Host: {'已配置' if image_config.get('searxng_host') else '未配置'}")
                return images
            if provider != desired_provider:
                logger.warning(f"默认网络搜索提供商'{desired_provider}'不可用，降级使用'{provider}'")

            # 让AI生成搜索关键词
            search_query = await self._ai_generate_search_query(
                slide_title, slide_content, project_topic, project_scenario, requirement, default_provider=provider
            )

            if not search_query:
                logger.warning("无法生成搜索关键词")
                return images

            # logger.info(f"网络搜索关键词: {search_query}")

            # 搜索更多图片以便在下载失败时有备选
            search_count = min(requirement.count * 3, 20)  # 搜索3倍数量，但不超过20张
            # logger.info(f"开始网络搜索，关键词: {search_query}, 搜索数量: {search_count}")
            network_images = await self._search_images_directly(
                search_query, search_count, image_config=image_config, default_provider=provider
            )
            # logger.info(f"网络搜索返回 {len(network_images)} 张图片")

            # 下载网络图片到本地缓存文件夹，带重试机制
            successful_downloads = 0
            image_index = 0

            while successful_downloads < requirement.count and image_index < len(network_images):
                image_data = network_images[image_index]
                image_index += 1

                try:
                    # 生成有意义的图片标题
                    meaningful_title = self._generate_meaningful_image_title(image_data, slide_title, successful_downloads + 1)

                    # 下载图片到本地缓存，带重试机制
                    cached_image_info = await self._download_network_image_to_cache_with_retry(image_data, meaningful_title)

                    if cached_image_info:
                        slide_image = SlideImageInfo(
                            image_id=cached_image_info['image_id'],
                            absolute_url=cached_image_info['absolute_url'],
                            source=ImageSource.NETWORK,
                            purpose=requirement.purpose,
                            content_description=requirement.description,
                            search_keywords=search_query,
                            alt_text=image_data.get('tags', ''),
                            title=f"网络图片 {successful_downloads + 1}",
                            width=image_data.get('imageWidth'),
                            height=image_data.get('imageHeight'),
                            format=cached_image_info.get('format', 'jpg')
                        )
                        images.append(slide_image)
                        successful_downloads += 1
                        logger.info(f"网络图片缓存成功: {cached_image_info['absolute_url']}")
                    else:
                        logger.warning(f"网络图片缓存失败，尝试下一张图片")

                except Exception as e:
                    logger.error(f"处理网络图片失败: {e}，尝试下一张图片")
                    continue

            logger.info(f"成功获取{len(images)}张网络图片")
            return images

        except Exception as e:
            logger.error(f"处理网络图片失败: {e}")
            return images

    def _has_network_search_providers(self, image_config: Dict[str, Any]) -> bool:
        """检查是否有可用的网络搜索提供商"""
        return bool(self._select_network_search_provider(image_config))

    async def _search_images_with_service(self, query: str, count: int) -> List[Dict[str, Any]]:
        """使用图片服务搜索图片"""
        # 创建搜索缓存键
        search_key = f"{query}_{count}"

        # 检查缓存
        async with self._search_lock:
            if search_key in self._search_cache:
                logger.debug(f"使用缓存的搜索结果: {query}")
                return self._search_cache[search_key]

        try:
            # 检查图片服务是否可用
            if not self.image_service:
                logger.error("图片服务未初始化，无法使用图片服务搜索")
                return []

            image_service = self.image_service

            from .image.models import ImageSearchRequest

            # 创建搜索请求
            search_request = ImageSearchRequest(
                query=query,
                per_page=max(3, min(count * 2, 20)),  # 搜索更多以便筛选，确保>=3
                page=1
            )

            # 执行搜索
            search_result = await image_service.search_images(search_request)

            # 转换为旧格式以兼容现有代码
            images = []
            for image_info in search_result.images[:count]:
                image_data = {
                    'id': image_info.image_id,
                    'webformatURL': image_info.original_url,
                    'largeImageURL': image_info.original_url,
                    'tags': ', '.join([tag.name for tag in (image_info.tags or [])]),
                    'user': image_info.author or 'Unknown',
                    'pageURL': image_info.source_url or '',
                    'imageWidth': image_info.metadata.width if image_info.metadata else 0,
                    'imageHeight': image_info.metadata.height if image_info.metadata else 0
                }
                images.append(image_data)

            # 缓存结果
            async with self._search_lock:
                self._search_cache[search_key] = images
                # 限制缓存大小，避免内存泄漏
                if len(self._search_cache) > 50:
                    # 删除最旧的缓存项
                    oldest_key = next(iter(self._search_cache))
                    del self._search_cache[oldest_key]

            return images

        except Exception as e:
            logger.error(f"使用图片服务搜索失败: {e}")
            return []

    async def _process_ai_generated_images(self, requirement: ImageRequirement, project_topic: str,
                                         project_scenario: str, slide_title: str, slide_content: str,
                                         image_config: Dict[str, Any], page_number: int, total_pages: int,
                                         template_html: str = "") -> List[SlideImageInfo]:
        """处理AI生成图片需求"""
        images = []
        try:
            if not self.image_service:
                logger.warning("图片服务未初始化")
                return images

            # 重新加载用户特定的图片提供者配置（从数据库读取API密钥）
            if self.user_id is not None:
                await self.image_service.reload_providers_for_user(self.user_id)
                logger.debug(f"已为用户 {self.user_id} 重新加载图片提供者配置")

            # 获取默认AI图片提供商
            default_provider = (image_config.get('default_ai_image_provider') or 'dalle').lower()
            logger.info(f"使用AI图片提供商: {default_provider}")

            # 让AI决定图片尺寸（对于多张图片，使用相同尺寸保持一致性）
            width, height = await self._ai_decide_image_dimensions(
                slide_title, slide_content, project_topic, project_scenario, requirement, default_provider, image_config
            )

            # 为每张图片生成不同的提示词
            for i in range(requirement.count):
                # 让AI生成图片提示词
                image_prompt = await self._ai_generate_image_prompt(
                    slide_title, slide_content, project_topic, project_scenario,
                    page_number, total_pages, template_html, requirement, i + 1
                )

                if not image_prompt:
                    logger.warning(f"无法生成第{i+1}张图片的提示词")
                    continue

                # 创建图片生成请求
                from .image.models import ImageGenerationRequest, ImageProvider

                # 解析提供商
                provider = ImageProvider.DALLE
                if default_provider == 'siliconflow':
                    provider = ImageProvider.SILICONFLOW
                elif default_provider == 'stable_diffusion':
                    provider = ImageProvider.STABLE_DIFFUSION

                elif default_provider == 'gemini':
                    provider = ImageProvider.GEMINI
                elif default_provider == 'openai_image':
                    provider = ImageProvider.OPENAI_IMAGE
                elif default_provider == 'pollinations':
                    provider = ImageProvider.POLLINATIONS
      
                generation_request = ImageGenerationRequest(
                    prompt=image_prompt,
                    provider=provider,
                    width=width,
                    height=height,
                    quality="standard"
                )

                # 生成图片
                result = await self.image_service.generate_image(generation_request)

                if result.success and result.image_info:
                    from .url_service import build_image_url
                    absolute_url = build_image_url(
                        result.image_info.image_id,
                        width=result.image_info.metadata.width,
                        height=result.image_info.metadata.height,
                    )

                    slide_image = SlideImageInfo(
                        image_id=result.image_info.image_id,
                        absolute_url=absolute_url,
                        source=ImageSource.AI_GENERATED,
                        purpose=requirement.purpose,
                        content_description=requirement.description,
                        generation_prompt=image_prompt,
                        alt_text=f"AI生成图片 {i+1}",
                        title=f"AI生成图片 {i+1}",
                        width=width,
                        height=height,
                        format=getattr(result.image_info, 'format', 'png')
                    )
                    images.append(slide_image)
                    logger.info(f"AI生成第{i+1}张图片成功: {absolute_url}")
                else:
                    logger.error(f"AI生成第{i+1}张图片失败: {result.message}")

            logger.info(f"成功生成{len(images)}张AI图片")
            return images

        except Exception as e:
            logger.error(f"处理AI生成图片失败: {e}")
            return images







    async def _search_multiple_local_images(self, keywords: str, count: int) -> List[str]:
        """搜索多张本地图片"""
        try:
            if not self.image_service:
                return []

            # 获取所有本地图片
            gallery_result = await self.image_service.list_cached_images(page=1, per_page=100)
            if not gallery_result.get('images'):
                return []

            # 将关键词分割成列表
            keyword_list = keywords.lower().split()

            # 计算所有图片的匹配分数
            scored_images = []
            for img in gallery_result['images']:
                score = self._calculate_image_match_score(img, keyword_list)
                if score > 0:
                    scored_images.append((img.get('image_id'), score))

            # 按分数排序并选择前N张
            scored_images.sort(key=lambda x: x[1], reverse=True)
            selected_images = [img_id for img_id, _ in scored_images[:count]]

            logger.info(f"从{len(gallery_result['images'])}张本地图片中选择了{len(selected_images)}张")
            return selected_images

        except Exception as e:
            logger.error(f"搜索多张本地图片失败: {e}")
            return []



    async def _search_images_directly(
        self,
        query: str,
        count: int,
        *,
        image_config: Optional[Dict[str, Any]] = None,
        default_provider: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """使用配置的默认网络搜索提供商搜索图片"""
        # 创建搜索缓存键
        search_key = f"direct_{query}_{count}"

        # 检查缓存
        async with self._search_lock:
            if search_key in self._search_cache:
                logger.debug(f"使用缓存的直接搜索结果: {query}")
                return self._search_cache[search_key]

        try:
            from .image.models import ImageSearchRequest
            from .image.config.image_config import ImageServiceConfig

            # 获取配置
            config_manager = ImageServiceConfig()
            config = config_manager.get_config()

            provider_name = self._normalize_network_search_provider(
                default_provider
                or (image_config or {}).get("default_network_search_provider")
                or "unsplash"
            )

            logger.debug(f"使用默认网络搜索提供商: {provider_name}")

            # 根据配置的默认提供商创建相应的提供者
            provider = None
            if provider_name == 'pixabay':
                pixabay_config = dict(config.get('pixabay', {}) or {})
                pixabay_config['api_key'] = (image_config or {}).get('pixabay_api_key') or pixabay_config.get('api_key')
                if not pixabay_config.get('api_key'):
                    logger.warning("Pixabay API key not configured")
                    return []
                from .image.providers.pixabay_provider import PixabaySearchProvider
                provider = PixabaySearchProvider(pixabay_config)
            elif provider_name == 'searxng':
                searxng_config = dict(config.get('searxng', {}) or {})
                searxng_config['host'] = (image_config or {}).get('searxng_host') or searxng_config.get('host')
                if not searxng_config.get('host'):
                    logger.warning("SearXNG host not configured")
                    return []
                from .image.providers.searxng_image_provider import SearXNGSearchProvider
                provider = SearXNGSearchProvider(searxng_config)
            else:  # 默认使用unsplash
                unsplash_config = dict(config.get('unsplash', {}) or {})
                unsplash_config['api_key'] = (image_config or {}).get('unsplash_access_key') or unsplash_config.get('api_key')
                if not unsplash_config.get('api_key'):
                    logger.warning("Unsplash API key not configured")
                    return []

                from .image.providers.unsplash_provider import UnsplashSearchProvider
                provider = UnsplashSearchProvider(unsplash_config)

            if not provider:
                logger.error("无法创建网络搜索提供商")
                return []

            # 创建搜索请求
            # 根据不同提供商调整per_page参数
            if provider_name == 'pixabay':
                # Pixabay API 要求 per_page 范围为 3-200
                per_page = max(3, min(count, 200))
            else:
                # 其他提供商使用更宽松的限制
                per_page = max(1, min(count, 50))

            search_request = ImageSearchRequest(
                query=query,
                per_page=per_page,
                page=1
            )

            # 执行搜索
            search_result = await provider.search(search_request)

            # 转换为旧格式以兼容现有代码
            images = []
            if search_result and search_result.images:
                for image_info in search_result.images[:count]:
                    image_data = {
                        'id': image_info.image_id,
                        'webformatURL': image_info.original_url,
                        'largeImageURL': image_info.original_url,
                        'tags': ', '.join([tag.name for tag in (image_info.tags or [])]),
                        'user': image_info.author or 'Unknown',
                        'pageURL': image_info.source_url or '',
                        'imageWidth': image_info.metadata.width if image_info.metadata else 0,
                        'imageHeight': image_info.metadata.height if image_info.metadata else 0
                    }
                    images.append(image_data)
                    logger.debug(f"转换图片{len(images)}: {image_info.title[:50] if image_info.title else 'N/A'}...")

            # 缓存结果
            async with self._search_lock:
                self._search_cache[search_key] = images
                # 限制缓存大小
                if len(self._search_cache) > 50:
                    oldest_key = next(iter(self._search_cache))
                    del self._search_cache[oldest_key]

            logger.info(f"直接搜索获得{len(images)}张图片: {query}")
            return images

        except Exception as e:
            logger.error(f"直接搜索失败: {e}")
            import traceback
            logger.error(f"搜索异常详情: {traceback.format_exc()}")
            return []

    async def _download_network_image_to_cache(self, image_data: Dict[str, Any], title: str) -> Optional[Dict[str, Any]]:
        """下载网络图片并上传到图床系统"""
        try:
            # 检查图片服务是否可用
            if not self.image_service:
                logger.error("图片服务未初始化，无法下载网络图片到缓存")
                return None

            # 获取图片URL
            image_url = (image_data.get('webformatURL') or 
                        image_data.get('url') or
                        image_data.get('largeImageURL') or
                        image_data.get('original_url'))

            if not image_url:
                logger.warning(f"网络图片URL为空，图片数据: {image_data}")
                return None

            # 下载图片数据
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    if response.status == 200:
                        image_data_bytes = await response.read()

                        # 获取文件扩展名
                        content_type = response.headers.get('content-type', 'image/jpeg')
                        if 'jpeg' in content_type or 'jpg' in content_type:
                            file_extension = 'jpg'
                        elif 'png' in content_type:
                            file_extension = 'png'
                        elif 'webp' in content_type:
                            file_extension = 'webp'
                        else:
                            file_extension = 'jpg'  # 默认

                        # 创建上传请求
                        from .image.models import ImageUploadRequest

                        # 生成更好的描述和标签
                        description, tags = self._generate_image_metadata(image_data, title)

                        upload_request = ImageUploadRequest(
                            filename=f"{title}.{file_extension}",
                            content_type=content_type,
                            file_size=len(image_data_bytes),
                            title=title,
                            description=description,
                            tags=tags,
                            category="network_search",
                            source_type=ImageSourceType.WEB_SEARCH,
                            original_url=image_url
                        )

                        # 上传到图床系统
                        result = await self.image_service.upload_image(upload_request, image_data_bytes)

                        if result.success and result.image_info:
                            # 构建图床API的绝对URL
                            from .url_service import build_image_url
                            absolute_url = build_image_url(
                                result.image_info.image_id,
                                width=result.image_info.metadata.width,
                                height=result.image_info.metadata.height,
                            )

                            return {
                                'image_id': result.image_info.image_id,
                                'absolute_url': absolute_url,
                                'format': result.image_info.metadata.format.value,
                                'width': result.image_info.metadata.width,
                                'height': result.image_info.metadata.height
                            }
                        else:
                            logger.error(f"上传网络图片到图床失败: {result.message}")
                            return None
                    else:
                        logger.error(f"下载网络图片失败，状态码: {response.status}")
                        return None

        except Exception as e:
            logger.error(f"下载网络图片到图床失败: {e}")
            return None

    async def _download_network_image_to_cache_with_retry(self, image_data: Dict[str, Any], title: str, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """下载网络图片并上传到图床系统，带重试机制"""
        for attempt in range(max_retries):
            try:
                result = await self._download_network_image_to_cache(image_data, title)
                if result:
                    return result
                else:
                    logger.warning(f"第{attempt + 1}次下载网络图片失败，准备重试")
                    if attempt < max_retries - 1:
                        # 等待一段时间后重试
                        await asyncio.sleep(1 * (attempt + 1))  # 递增等待时间
                        continue

            except Exception as e:
                logger.warning(f"第{attempt + 1}次下载网络图片异常: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (attempt + 1))  # 递增等待时间
                    continue
                else:
                    logger.error(f"所有{max_retries}次下载尝试都失败")

        return None

    def _generate_meaningful_image_title(self, image_data: Dict[str, Any], slide_title: str, index: int) -> str:
        """生成有意义的图片标题"""
        try:
            # 获取图片标签或描述
            tags = image_data.get('tags', '')
            description = image_data.get('description', '')

            # 清理幻灯片标题，移除特殊字符
            clean_slide_title = ''.join(c for c in slide_title if c.isalnum() or c in ' -_')
            clean_slide_title = clean_slide_title.strip().replace(' ', '_')

            # 如果有标签，使用前2个标签
            if tags:
                if isinstance(tags, str):
                    tag_list = [tag.strip() for tag in tags.split(',')[:2] if tag.strip()]
                elif isinstance(tags, list):
                    tag_list = [str(tag).strip() for tag in tags[:2] if str(tag).strip()]
                else:
                    tag_list = []

                if tag_list:
                    # 清理标签
                    clean_tags = []
                    for tag in tag_list:
                        clean_tag = ''.join(c for c in tag if c.isalnum() or c in ' -_')
                        clean_tag = clean_tag.strip().replace(' ', '_')
                        if clean_tag and len(clean_tag) > 1:
                            clean_tags.append(clean_tag)

                    if clean_tags:
                        tags_part = '_'.join(clean_tags)
                        # 组合：幻灯片标题_标签_序号
                        if clean_slide_title:
                            title = f"{clean_slide_title}_{tags_part}_{index}"
                        else:
                            title = f"slide_{tags_part}_{index}"

                        # 限制长度
                        max_length = 60
                        if len(title) > max_length:
                            title = title[:max_length].rstrip('_')

                        return title

            # 如果有描述但没有标签
            if description:
                clean_desc = ''.join(c for c in description[:20] if c.isalnum() or c in ' -_')
                clean_desc = clean_desc.strip().replace(' ', '_')
                if clean_desc:
                    if clean_slide_title:
                        return f"{clean_slide_title}_{clean_desc}_{index}"
                    else:
                        return f"slide_{clean_desc}_{index}"

            # 默认命名
            if clean_slide_title:
                return f"{clean_slide_title}_image_{index}"
            else:
                return f"slide_image_{index}"

        except Exception as e:
            logger.warning(f"生成有意义图片标题失败: {e}")
            # 回退到简单命名
            return f"slide_image_{index}"

    def _generate_image_metadata(self, image_data: Dict[str, Any], title: str) -> tuple[str, list]:
        """生成图片的描述和标签"""
        try:
            # 获取图片来源信息
            source_info = ""
            if 'user' in image_data:
                source_info = f"作者: {image_data['user']}"
            elif 'author' in image_data:
                source_info = f"作者: {image_data['author']}"

            # 获取图片统计信息
            stats_info = ""
            if 'views' in image_data or 'downloads' in image_data or 'likes' in image_data:
                stats = []
                if 'views' in image_data:
                    stats.append(f"浏览: {image_data['views']}")
                if 'downloads' in image_data:
                    stats.append(f"下载: {image_data['downloads']}")
                if 'likes' in image_data:
                    stats.append(f"点赞: {image_data['likes']}")
                stats_info = " | ".join(stats)

            # 获取尺寸信息
            size_info = ""
            width = image_data.get('webformatWidth') or image_data.get('imageWidth') or image_data.get('width')
            height = image_data.get('webformatHeight') or image_data.get('imageHeight') or image_data.get('height')
            if width and height:
                size_info = f"尺寸: {width}x{height}"

            # 组合描述
            description_parts = [f"网络搜索图片: {title}"]
            if source_info:
                description_parts.append(source_info)
            if size_info:
                description_parts.append(size_info)
            if stats_info:
                description_parts.append(stats_info)

            description = " | ".join(description_parts)

            # 处理标签
            tags = []
            raw_tags = image_data.get('tags', '')
            if raw_tags:
                if isinstance(raw_tags, str):
                    # 分割字符串标签
                    tag_list = [tag.strip() for tag in raw_tags.replace(',', ' ').split() if tag.strip()]
                elif isinstance(raw_tags, list):
                    # 处理列表标签
                    tag_list = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
                else:
                    tag_list = []

                # 清理和去重标签
                seen_tags = set()
                for tag in tag_list:
                    clean_tag = tag.lower().strip()
                    if clean_tag and len(clean_tag) > 1 and clean_tag not in seen_tags:
                        seen_tags.add(clean_tag)
                        tags.append(clean_tag)

                # 限制标签数量
                tags = tags[:10]

            # 添加默认标签
            default_tags = ['网络图片', 'ppt素材']
            for default_tag in default_tags:
                if default_tag not in tags:
                    tags.append(default_tag)

            return description, tags

        except Exception as e:
            logger.warning(f"生成图片元数据失败: {e}")
            # 回退到简单元数据
            simple_description = f"网络搜索图片: {title}"
            simple_tags = ['网络图片', 'ppt素材']
            return simple_description, simple_tags

    async def _get_local_image_details(self, image_id: str) -> Dict[str, Any]:
        """获取本地图片详细信息"""
        try:
            if not self.image_service:
                return {}

            # 这里可以调用图片服务的方法获取详细信息
            # 暂时返回基本信息
            return {
                'title': f'本地图片 {image_id}',
                'width': None,
                'height': None,
                'file_size': None,
                'format': None
            }
        except Exception as e:
            logger.error(f"获取本地图片详细信息失败: {e}")
            return {}

    def _calculate_image_match_score(self, img: Dict[str, Any], keyword_list: List[str]) -> int:
        """计算图片匹配分数"""
        score = 0

        # 处理标题、文件名、标签
        title = (img.get('title') or '').lower()
        filename = (img.get('filename') or '').lower()

        tags = img.get('tags', [])
        if tags and len(tags) > 0 and hasattr(tags[0], 'name'):
            tag_names = [tag.name.lower() for tag in tags]
        else:
            tag_names = [str(tag).lower() for tag in tags if tag]

        # 标题匹配（权重最高）
        for keyword in keyword_list:
            if keyword in title:
                score += 3

        # 标签匹配（权重中等）
        for keyword in keyword_list:
            for tag in tag_names:
                if keyword in tag or tag in keyword:
                    score += 2
                    break  # 每个关键词只匹配一次

        # 文件名匹配（权重较低）
        for keyword in keyword_list:
            if keyword in filename:
                score += 1

        return score

    async def _ai_generate_local_search_keywords(self, slide_title: str, slide_content: str,
                                               project_topic: str, project_scenario: str,
                                               requirement: ImageRequirement = None) -> Optional[str]:
        """使用AI生成本地图片搜索关键词"""
        try:
            # 构建需求信息
            requirement_info = ""
            if requirement:
                requirement_info = f"""
图片需求信息：
- 用途：{requirement.purpose.value}
- 描述：{requirement.description}
- 优先级：{requirement.priority}
"""

            prompt = f"""作为专业的图片搜索专家，请为以下PPT幻灯片生成本地图片搜索关键词。

项目主题：{project_topic}
项目场景：{project_scenario}
幻灯片标题：{slide_title}
幻灯片内容：{slide_content}
{requirement_info}

要求：
1. 生成3-5个中英文关键词，用空格分隔
2. 关键词要准确描述所需图片的内容和主题
3. 考虑项目场景和图片用途，选择合适的图片风格
4. 优先选择具体的视觉元素和概念
5. 适合在本地图片库中进行标题、描述、标签匹配

示例格式：商务 会议 图表 business chart
请只回复关键词，不要其他内容："""

            response = await self._text_completion(
                prompt=prompt,
                temperature=0.5
            )

            search_keywords = response.content.strip()
            logger.info(f"AI生成本地搜索关键词: {search_keywords}")
            return search_keywords

        except Exception as e:
            logger.error(f"AI生成本地搜索关键词失败: {e}")
            return None

    async def _search_local_images_by_keywords(self, keywords: str) -> Optional[str]:
        """使用关键词搜索本地图片，返回相关度最高的图片ID"""
        try:
            if not self.image_service:
                logger.warning("图片服务未初始化")
                return None

            # 将关键词分割成列表
            keyword_list = keywords.lower().split()

            # 获取所有本地图片
            gallery_result = await self.image_service.list_cached_images(page=1, per_page=100)
            if not gallery_result.get('images'):
                return None

            best_match = None
            best_score = 0

            for img in gallery_result['images']:
                score = 0
                image_id = img.get('image_id')

                # 计算匹配分数
                title = (img.get('title') or '').lower()
                filename = (img.get('filename') or '').lower()

                # 处理标签
                tags = img.get('tags', [])
                if tags and len(tags) > 0 and hasattr(tags[0], 'name'):
                    tag_names = [tag.name.lower() for tag in tags]
                else:
                    tag_names = [str(tag).lower() for tag in tags if tag]

                # 标题匹配（权重最高）
                title_matches = 0
                for keyword in keyword_list:
                    if keyword in title:
                        score += 3
                        title_matches += 1

                # 标签匹配（权重中等）
                tag_matches = 0
                for keyword in keyword_list:
                    for tag in tag_names:
                        if keyword in tag or tag in keyword:
                            score += 2
                            tag_matches += 1
                            break  # 每个关键词只匹配一次

                # 文件名匹配（权重较低）
                filename_matches = 0
                for keyword in keyword_list:
                    if keyword in filename:
                        score += 1
                        filename_matches += 1

                # 记录详细匹配信息
                if score > 0:
                    logger.debug(f"图片 {image_id} 匹配分数: {score} (标题:{title_matches}, 标签:{tag_matches}, 文件名:{filename_matches})")

                # 更新最佳匹配
                if score > best_score:
                    best_score = score
                    best_match = image_id
                    logger.debug(f"更新最佳匹配: {best_match}, 新分数: {best_score}")

            if best_match and best_score > 0:
                logger.info(f"找到最佳匹配图片: {best_match}, 分数: {best_score}")
                return best_match
            else:
                logger.info("未找到匹配的本地图片")
                return None

        except Exception as e:
            logger.error(f"本地图片搜索失败: {e}")
            return None



    def _truncate_search_query(self, query: str, max_length: int = 100) -> str:
        """截断搜索查询以符合API限制，保持单词完整性"""
        if not query or len(query) <= max_length:
            return query

        # 在最大长度内找到最后一个空格
        truncated = query[:max_length]
        last_space = truncated.rfind(' ')

        if last_space > 0:
            # 在最后一个空格处截断，保持单词完整
            return truncated[:last_space]
        else:
            # 如果没有空格，直接截断
            return truncated

    async def _ai_generate_search_query(self, slide_title: str, slide_content: str,
                                      project_topic: str, project_scenario: str,
                                      requirement: ImageRequirement = None,
                                      default_provider: Optional[str] = None) -> Optional[str]:
        """使用AI生成网络搜索关键词"""
        try:
            # 检测项目语言
            project_language = self._detect_project_language(project_topic, slide_title, slide_content)

            # 构建需求信息
            requirement_info = ""
            if requirement:
                requirement_info = f"""
图片需求信息：
- 用途：{requirement.purpose.value}
- 描述：{requirement.description}
- 优先级：{requirement.priority}
"""

            # 根据项目语言生成不同的提示词
            if project_language == "zh":
                language_instruction = "中文关键词"
                example_format = "商务 会议 演示 图表"
                search_instruction = "生成3-5个中文关键词，用空格分隔"
            else:
                language_instruction = "英文关键词"
                example_format = "business meeting presentation chart"
                search_instruction = "生成3-5个英文关键词，用空格分隔"

            prompt = f"""作为专业的图片搜索专家，请为以下PPT幻灯片生成最佳的{language_instruction}。

项目主题：{project_topic}
项目场景：{project_scenario}
幻灯片标题：{slide_title}
幻灯片内容：{slide_content}
{requirement_info}

要求：
1. {search_instruction}，总长度不超过80个字符
2. 关键词要准确描述所需图片的内容和用途
3. 考虑项目场景和图片用途，选择合适的图片风格
4. 避免过于抽象的词汇，优先选择具体的视觉元素
5. 确保关键词适合在网络图片库中搜索

示例格式：{example_format}
请只回复关键词，不要其他内容："""

            response = await self._text_completion(
                prompt=prompt,
                temperature=0.5
            )

            search_query = response.content.strip()

            # 根据不同提供商截断查询
            provider_name = self._normalize_network_search_provider(default_provider) or "unsplash"

            # Pixabay API的100字符限制，其他提供商使用更宽松的限制
            max_length = 100 if provider_name == 'pixabay' else 200
            truncated_query = self._truncate_search_query(search_query, max_length)

            if len(search_query) > max_length:
                logger.warning(f"搜索关键词过长，已截断: '{search_query}' -> '{truncated_query}'")

            # logger.info(f"AI生成搜索关键词: {truncated_query}")
            return truncated_query

        except Exception as e:
            logger.error(f"AI生成搜索关键词失败: {e}")
            return None

    def _detect_project_language(self, project_topic: str, slide_title: str, slide_content: str) -> str:
        """检测项目语言"""
        # 合并所有文本内容
        combined_text = f"{project_topic} {slide_title} {slide_content}"

        # 检查是否包含中文字符
        chinese_pattern = r'[\u4e00-\u9fff]'
        if re.search(chinese_pattern, combined_text):
            return "zh"
        else:
            return "en"

    def _normalize_resolution_value(self, value: Any) -> Optional[tuple]:
        """将尺寸值规范化为(width, height)元组"""
        if isinstance(value, str):
            match = re.match(r"(\d+)\s*[x×]\s*(\d+)", value.strip())
            if match:
                try:
                    return int(match.group(1)), int(match.group(2))
                except (TypeError, ValueError):
                    return None

        if isinstance(value, dict):
            width = value.get('width') or value.get('w')
            height = value.get('height') or value.get('h')
            try:
                if width and height:
                    return int(width), int(height)
            except (TypeError, ValueError):
                return None

        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                return int(value[0]), int(value[1])
            except (TypeError, ValueError):
                return None

        return None

    def _get_resolution_options(self, provider: str, image_config: Dict[str, Any]) -> List[tuple]:
        """获取指定提供商的可用分辨率列表（已去重、按配置优先顺序）"""
        provider_key = (provider or image_config.get('default_ai_image_provider') or 'dalle').lower()

        default_presets = {
            'dalle': ["1792x1024", "1024x1792", "1024x1024"],
            'openai_image': ["1536x1024", "1024x1536", "1024x1024"],
            'siliconflow': ["1024x1024", "1024x2048", "1536x1024", "2048x1152", "1152x2048"],
            'gemini': ["1024x1024", "1344x768", "768x1344"],
            'pollinations': ["1024x1024", "1344x768", "768x1344", "1536x1024", "1024x1536"],

            'default': ["1792x1024", "1024x1792", "1024x1024"]
        }

        presets = image_config.get('ai_image_resolution_presets')
        parsed_presets = {}
        if isinstance(presets, str) and presets.strip():
            try:
                parsed_presets = json.loads(presets)
            except Exception as e:
                logger.warning(f"Failed to parse ai_image_resolution_presets: {e}")
        elif isinstance(presets, dict):
            parsed_presets = presets

        options: List[tuple] = []
        provider_presets = parsed_presets.get(provider_key) if isinstance(parsed_presets, dict) else None
        if provider_presets:
            if not isinstance(provider_presets, list):
                provider_presets = [provider_presets]
            for value in provider_presets:
                normalized = self._normalize_resolution_value(value)
                if normalized:
                    options.append(normalized)
        
        # 如果没有自定义预设，使用默认预设
        if not options:
            fallback_presets = default_presets.get(provider_key) or default_presets['default']
            for value in fallback_presets:
                normalized = self._normalize_resolution_value(value)
                if normalized:
                    options.append(normalized)

        # 允许从单值配置中注入优先尺寸（如dalle_image_size），添加到列表开头
        provider_size_keys = {
            'dalle': 'dalle_image_size',
            'siliconflow': 'siliconflow_image_size',
        }
        size_key = provider_size_keys.get(provider_key)
        if size_key and image_config.get(size_key):
            normalized_size = self._normalize_resolution_value(image_config.get(size_key))
            if normalized_size and normalized_size not in options:
                options.insert(0, normalized_size)

        # 去重并保持顺序
        unique_options = []
        for opt in options:
            if opt not in unique_options:
                unique_options.append(opt)

        return unique_options

    async def _ai_decide_image_dimensions(self, slide_title: str, slide_content: str,
                                        project_topic: str, project_scenario: str,
                                        requirement: ImageRequirement = None,
                                        provider: Optional[str] = None,
                                        image_config: Optional[Dict[str, Any]] = None) -> tuple:
        """使用AI决定图片的最佳尺寸"""
        try:
            config = image_config or {}
            provider_key = (provider or config.get('default_ai_image_provider') or 'dalle').lower()

            available_dimensions = self._get_resolution_options(provider_key, config)
            if not available_dimensions:
                available_dimensions = [(1792, 1024), (1024, 1792), (1024, 1024)]

            # 限制选项数量，避免提示过长
            if len(available_dimensions) > 6:
                available_dimensions = available_dimensions[:6]

            if len(available_dimensions) == 1:
                selected_dimensions = available_dimensions[0]
                logger.info(f"仅有一个可用尺寸，直接使用: {selected_dimensions[0]}x{selected_dimensions[1]} (提供商: {provider_key})")
                return selected_dimensions

            # 构建需求信息
            requirement_info = ""
            if requirement:
                requirement_info = f"""
图片需求信息：
- 用途：{requirement.purpose.value}
- 描述：{requirement.description}
- 优先级：{requirement.priority}
"""

            option_lines = []
            for idx, (w, h) in enumerate(available_dimensions, start=1):
                aspect = w / h
                if aspect > 1.1:
                    orientation = "横向"
                    use_case = "横向展示、背景或宽屏内容"
                elif aspect < 0.9:
                    orientation = "竖向"
                    use_case = "人物肖像、竖版海报或移动端展示"
                else:
                    orientation = "正方形"
                    use_case = "产品展示、图标或社交媒体"
                option_lines.append(f"{idx}. {w}x{h} ({orientation}，适合{use_case})")

            prompt = f"""作为专业的PPT设计师，请根据以下信息为图片选择最佳的尺寸规格。

项目信息：
- 主题：{project_topic}
- 场景：{project_scenario}

幻灯片信息：
- 标题：{slide_title}
- 内容：{slide_content}

{requirement_info}

可选尺寸规格：
当前图片提供商：{provider_key}
{chr(10).join(option_lines)}

请根据内容特点、用途和展示效果选择最合适的尺寸。

要求：
1. 考虑内容的视觉特点（横向/竖向/方形更适合）
2. 考虑图片用途（背景/装饰/说明/图标等）
3. 考虑PPT演示的整体效果
4. 只回复对应的数字编号或尺寸值（如 1792x1024），不要其他内容"""

            response = await self._text_completion(
                prompt=prompt,
                temperature=0.3
            )

            choice_text = response.content.strip()

            # 先尝试解析显式的尺寸值
            selected_dimensions = available_dimensions[0]
            size_match = re.search(r"(\d+)\s*[x×]\s*(\d+)", choice_text)
            if size_match:
                candidate = (int(size_match.group(1)), int(size_match.group(2)))
                for dims in available_dimensions:
                    if dims == candidate:
                        selected_dimensions = dims
                        break

            # 如果未匹配到尺寸值，再尝试编号
            if selected_dimensions == available_dimensions[0]:
                index_match = re.search(r"(\d+)", choice_text)
                if index_match:
                    idx = int(index_match.group(1))
                    if 1 <= idx <= len(available_dimensions):
                        selected_dimensions = available_dimensions[idx - 1]

            logger.info(f"AI选择图片尺寸: {selected_dimensions[0]}x{selected_dimensions[1]} (响应: {choice_text}, 提供商: {provider_key})")

            return selected_dimensions

        except Exception as e:
            logger.error(f"AI决定图片尺寸失败: {e}")
            fallback = available_dimensions[0] if 'available_dimensions' in locals() and available_dimensions else (1792, 1024)
            return fallback  # 默认尺寸

    async def _ai_generate_image_prompt(self, slide_title: str, slide_content: str, project_topic: str,
                                      project_scenario: str, page_number: int, total_pages: int,
                                      template_html: str = "", requirement: ImageRequirement = None,
                                      image_index: int = 1) -> Optional[str]:
        """使用AI生成图片生成提示词"""
        try:
            # 构建包含模板HTML的提示词
            template_context = ""
            if template_html.strip():
                template_context = f"""
当前PPT模板HTML参考：
{template_html[:500]}...
"""

            # 构建需求信息
            requirement_info = ""
            if requirement:
                requirement_info = f"""
图片需求信息：
- 用途：{requirement.purpose.value}
- 描述：{requirement.description}
- 优先级：{requirement.priority}
- 当前是第{image_index}张图片
"""

            prompt = f"""作为专业的AI图片生成提示词专家，请为以下PPT幻灯片生成高质量的英文图片生成提示词。

项目信息：
- 主题：{project_topic}
- 场景：{project_scenario}
- 当前页：{page_number}/{total_pages}

幻灯片信息：
- 标题：{slide_title}
- 内容：{slide_content}

{requirement_info}
{template_context}

要求：
1. 生成详细的英文提示词，描述所需图片的视觉内容
2. 根据项目场景、图片用途和模板风格选择合适的风格
3. 包含具体的视觉元素描述，确保与模板风格协调
4. 确保图片适合PPT演示使用，符合指定用途
5. 考虑16:9或4:3的横向构图
6. 避免包含文字内容
7. 如果是多张图片中的一张，确保风格一致但内容有所区别

风格指导：
- business: professional, clean, modern office, corporate style
- technology: futuristic, digital, high-tech, innovation
- education: clear, informative, academic, learning environment
- general: clean, modern, professional presentation style

用途指导：
- decoration: 装饰性，美观、和谐、不抢夺主要内容焦点
- illustration: 说明性，直观、清晰、辅助理解内容
- background: 背景性，淡雅、不干扰前景内容
- icon: 图标性，简洁、符号化、易识别
- chart_support: 图表辅助，数据可视化、专业、清晰
- content_visual: 内容可视化，概念具象化、生动、准确

请生成一个完整的英文提示词（不超过120词），直接输出提示词，不要添加任何其他内容"""

            response = await self._text_completion(
                prompt=prompt,
                temperature=0.7
            )

            image_prompt = response.content.strip()
            logger.info(f"AI生成第{image_index}张图片提示词: {image_prompt}")
            return image_prompt

        except Exception as e:
            logger.error(f"AI生成图片提示词失败: {e}")
            return None

    async def _ai_should_add_image(self, slide_data: Dict[str, Any], project_topic: str,
                                 project_scenario: str, page_number: int, total_pages: int) -> bool:
        """使用AI判断该页是否需要或适合插入图片"""
        try:

            # 提取幻灯片内容信息
            slide_title = slide_data.get('title', '')
            slide_content = slide_data.get('content_points', [])
            slide_content_text = '\n'.join(slide_content) if isinstance(slide_content, list) else str(slide_content)
            content_length = len(slide_content_text.strip())
            content_points_count = len(slide_content) if isinstance(slide_content, list) else 0

            prompt = f"""作为专业的PPT设计师，请根据以下标准判断该幻灯片是否需要插入配图：

【项目信息】
- 主题：{project_topic}
- 场景：{project_scenario}
- 当前页：{page_number}/{total_pages}

【幻灯片内容】
- 标题：{slide_title}
- 内容要点数量：{content_points_count}个
- 内容字数：{content_length}字
- 具体内容：
{slide_content_text}

【判断标准】
请综合考虑以下因素：

1. 内容丰富程度：
   - 内容过少（<50字或<3个要点）：建议添加图片增强视觉效果
   - 内容适中（50-200字，3-6个要点）：根据内容性质判断
   - 内容丰富（>200字或>6个要点）：通常不需要额外图片

2. 理解难度：
   - 抽象概念、复杂流程、技术原理：需要图片辅助理解
   - 数据统计、对比分析：适合图表或图示
   - 简单陈述、常识内容：通常不需要图片

3. 内容类型：
   - 封面页、章节页：通常需要装饰性图片
   - 总结页、结论页：根据内容量判断
   - 纯文字列表：可能需要图片平衡版面
   - 已有充实内容的页面：通常不需要额外图片

4. 视觉平衡：
   - 页面显得空旷：需要图片填充
   - 文字密集：不建议添加图片
   - 版面协调：根据整体设计需要

请基于以上标准进行专业判断，只回复"是"或"否"："""

            response = await self._text_completion(
                prompt=prompt,
                temperature=0.7
            )
            # logger.info(f"AI判断是否需要图片的回复: {response.content}")
            decision = response.content.strip().lower()
            should_add = decision in ['是', 'yes', 'true', '需要', '适合']

            logger.info(f"AI判断第{page_number}页是否需要图片: {decision} -> {should_add}")
            return should_add

        except Exception as e:
            logger.error(f"AI判断是否添加图片失败: {e}")
            # 出错时默认不添加图片，避免不必要的处理
            return False

    async def _insert_images_into_slide(self, slide_html: str, images_collection: SlideImagesCollection, slide_title: str) -> str:
        """AI智能将生成的图片插入到幻灯片HTML中"""
        try:
            if not images_collection or not images_collection.images:
                logger.warning("没有图片需要插入")
                return slide_html


            # 准备图片信息
            images_info = []
            for i, image in enumerate(images_collection.images):
                image_info = {
                    "index": i + 1,
                    "url": image.absolute_url,
                    "description": image.content_description or f"配图{i+1}",
                    "alt_text": image.alt_text or f"配图{i+1}",
                    "title": image.title or f"AI生成配图{i+1}",
                    "source": image.source.value,
                    "width": image.width,
                    "height": image.height
                }
                images_info.append(image_info)

            # 构建AI提示词
            prompt = f"""作为专业的网页设计师，请分析以下幻灯片HTML结构，并智能地将提供的图片融入到页面内。

幻灯片标题：{slide_title}

当前HTML结构：
```html
{slide_html}
```

需要插入的图片信息：
{images_info}

要求：
- 请在HTML中合理使用这些图片资源
- 图片地址已经是绝对地址，可以直接使用
- 根据图片用途、内容描述和实际尺寸选择合适的位置和样式
- 充分利用图片的尺寸信息（宽度x高度）来优化布局设计
- 根据图片文件大小和格式选择合适的显示策略
- 确保图片与页面内容和设计风格协调
- 可以使用CSS对图片进行适当的样式调整（大小、位置、边框等）


**重要输出格式要求**：
- 必须使用markdown代码块格式返回HTML代码
- 格式：```html\\n[HTML代码]\\n```
- HTML代码必须以<!DOCTYPE html>开始，以</html>结束
- 不要在代码块前后添加任何解释文字
- **页眉页脚保持原样**
"""
            # 调用AI进行智能插入
            response = await self._text_completion(
                prompt=prompt,
                temperature=0.3
            )

            # 提取markdown代码块中的HTML内容
            updated_html = self._extract_html_from_markdown_response(response.content.strip())

            if not updated_html:
                logger.warning("无法从AI响应中提取HTML内容，使用默认插入逻辑")
                return await self._insert_images_with_default_logic(slide_html, images_collection, slide_title)

            # 验证返回的HTML是否有效
            if self._validate_html_structure(updated_html):
                logger.info(f"AI成功插入{len(images_collection.images)}张图片到幻灯片中")
                return updated_html
            else:
                logger.warning("AI返回的HTML结构无效，使用默认插入逻辑")
                return await self._insert_images_with_default_logic(slide_html, images_collection, slide_title)

        except Exception as e:
            logger.error(f"AI智能插入图片失败: {e}")
            logger.info("回退到默认插入逻辑")
            return await self._insert_images_with_default_logic(slide_html, images_collection, slide_title)

    def _extract_html_from_markdown_response(self, response_content: str) -> str:
        """从AI响应中提取markdown代码块中的HTML内容"""
        try:
            import re

            # 查找markdown代码块 ```html ... ```
            html_pattern = r'```html\s*\n(.*?)\n```'
            match = re.search(html_pattern, response_content, re.DOTALL | re.IGNORECASE)

            if match:
                html_content = match.group(1).strip()
                logger.debug(f"成功提取HTML内容，长度: {len(html_content)} 字符")
                return html_content

            # 如果没找到标准格式，尝试查找其他可能的格式
            # 查找 ```html ... ``` (不区分大小写)
            html_pattern2 = r'```(?:html|HTML)\s*\n?(.*?)\n?```'
            match2 = re.search(html_pattern2, response_content, re.DOTALL)

            if match2:
                html_content = match2.group(1).strip()
                logger.debug(f"使用备用模式提取HTML内容，长度: {len(html_content)} 字符")
                return html_content

            # 如果还是没找到，尝试查找任何代码块
            code_pattern = r'```\s*\n?(.*?)\n?```'
            match3 = re.search(code_pattern, response_content, re.DOTALL)

            if match3:
                potential_html = match3.group(1).strip()
                # 检查是否看起来像HTML
                if ('<!DOCTYPE html>' in potential_html or
                    '<html' in potential_html or
                    '<div' in potential_html or
                    '<body' in potential_html):
                    logger.debug(f"从通用代码块中提取HTML内容，长度: {len(potential_html)} 字符")
                    return potential_html

            # 最后尝试：如果响应内容本身就是HTML（没有代码块包装）
            if ('<!DOCTYPE html>' in response_content or
                '<html' in response_content or
                ('<div' in response_content and '</' in response_content)):
                logger.debug("响应内容本身就是HTML格式")
                return response_content.strip()

            logger.warning("无法从AI响应中提取HTML内容")
            logger.debug(f"AI响应内容预览: {response_content[:200]}...")
            return ""

        except Exception as e:
            logger.error(f"提取HTML内容失败: {e}")
            return ""

    def _validate_html_structure(self, html: str) -> bool:
        """验证HTML结构是否有效"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # 检查基本结构 - 至少要有一个容器元素
            container_elements = soup.find_all(['body', 'div', 'section', 'main', 'article'])
            if not container_elements:
                return False

            # 检查是否包含图片元素
            img_elements = soup.find_all('img')
            if not img_elements:
                return False

            # 检查HTML长度是否合理（不能太短或太长）
            if len(html.strip()) < 50 or len(html.strip()) > 50000:
                return False

            # 检查图片元素是否有有效的src属性
            valid_images = 0
            for img in img_elements:
                src = img.get('src', '').strip()
                if src and (src.startswith('http') or src.startswith('/') or src.startswith('data:')):
                    valid_images += 1

            if valid_images == 0:
                return False

            return True

        except Exception as e:
            logger.error(f"HTML验证失败: {e}")
            return False

    async def _insert_images_with_default_logic(self, slide_html: str, images_collection: SlideImagesCollection, slide_title: str) -> str:
        """使用默认逻辑插入图片（备用方案）"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(slide_html, 'html.parser')

            # 查找合适的插入位置
            # 1. 优先查找现有的图片容器
            img_containers = soup.find_all(['div', 'section'], class_=lambda x: x and any(
                keyword in x.lower() for keyword in ['image', 'img', 'picture', 'photo', 'visual']
            ))

            # 2. 查找内容区域
            content_areas = soup.find_all(['div', 'section'], class_=lambda x: x and any(
                keyword in x.lower() for keyword in ['content', 'main', 'body', 'text']
            ))

            # 3. 查找标题后的位置
            title_elements = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])

            inserted_count = 0
            for i, image in enumerate(images_collection.images):
                if inserted_count >= 3:  # 最多插入3张图片
                    break

                # 创建图片元素
                img_element = soup.new_tag('img')
                img_element['src'] = image.absolute_url
                img_element['alt'] = image.alt_text or f"配图{i+1}"
                img_element['title'] = image.title or f"AI生成配图{i+1}"
                img_element['style'] = "max-width: 100%; height: auto; border-radius: 8px; margin: 10px 0;"

                # 创建图片容器
                img_container = soup.new_tag('div')
                img_container['class'] = 'auto-generated-image-container'
                img_container['style'] = "text-align: center; margin: 20px 0; padding: 10px;"
                img_container.append(img_element)

                # 添加图片说明
                if image.content_description:
                    caption = soup.new_tag('p')
                    caption['style'] = "font-size: 0.9em; color: #666; margin-top: 8px; font-style: italic;"
                    caption.string = image.content_description
                    img_container.append(caption)

                # 选择插入位置
                inserted = False

                # 方法1: 插入到现有图片容器中
                if img_containers and not inserted:
                    target_container = img_containers[min(i, len(img_containers) - 1)]
                    target_container.clear()
                    target_container.append(img_container)
                    inserted = True
                    logger.info(f"图片{i+1}插入到现有图片容器中")

                # 方法2: 插入到内容区域
                elif content_areas and not inserted:
                    target_area = content_areas[0]
                    # 在内容区域的末尾插入
                    target_area.append(img_container)
                    inserted = True
                    logger.info(f"图片{i+1}插入到内容区域")

                # 方法3: 插入到标题后
                elif title_elements and not inserted:
                    title_element = title_elements[0]
                    title_element.insert_after(img_container)
                    inserted = True
                    logger.info(f"图片{i+1}插入到标题后")

                # 方法4: 插入到body末尾
                elif not inserted:
                    body = soup.find('body')
                    if body:
                        body.append(img_container)
                        inserted = True
                        logger.info(f"图片{i+1}插入到body末尾")

                if inserted:
                    inserted_count += 1

            logger.info(f"默认逻辑成功插入{inserted_count}张图片到幻灯片中")
            return str(soup)

        except Exception as e:
            logger.error(f"默认插入图片逻辑失败: {e}")
            return slide_html
