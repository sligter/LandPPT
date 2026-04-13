import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from ...core.config import app_config


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from ..enhanced_ppt_service import EnhancedPPTService


class SlideGenerationService:
    """Own the long-running slide generation orchestration workflow."""

    def __init__(self, service: "EnhancedPPTService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def _generate_slides_streaming_impl(self, project_id: str):
            """Internal implementation of slide generation streaming"""
            try:
                import json
                import time
                db_manager_status = None
                cache = None

                project = await self.project_manager.get_project(project_id)
                if not project:
                    error_data = {'error': '项目未找到'}
                    yield f"data: {json.dumps(error_data)}\n\n"
                    return

                # 检查并确保大纲数据正确
                outline = None
                slides = []

                # 首先尝试从项目中获取大纲
                if project.outline and isinstance(project.outline, dict):
                    outline = project.outline
                    slides = outline.get('slides', [])
                    logger.info(f"Found outline in project with {len(slides)} slides")

                # 如果没有slides或slides为空，尝试从数据库重新加载
                if not slides:
                    logger.info(f"No slides found in project outline, attempting to reload from database")
                    logger.error(f"DEBUG: Full outline structure for project {project_id}:")
                    logger.error(f"Outline type: {type(project.outline)}")
                    if project.outline:
                        logger.error(f"Outline keys: {list(project.outline.keys()) if isinstance(project.outline, dict) else 'Not a dict'}")
                        if isinstance(project.outline, dict) and 'slides' in project.outline:
                            logger.error(f"Slides type: {type(project.outline['slides'])}, content: {project.outline['slides']}")

                    try:
                        from ..db_project_manager import DatabaseProjectManager
                        db_manager = DatabaseProjectManager()

                        # 重新从数据库获取项目数据
                        fresh_project = await db_manager.get_project(project_id)
                        if fresh_project and fresh_project.outline:
                            outline = fresh_project.outline
                            slides = outline.get('slides', [])
                            logger.info(f"Reloaded outline from database with {len(slides)} slides")

                            # 更新内存中的项目数据
                            project.outline = outline
                        else:
                            logger.error(f"Failed to reload project from database or outline is None")
                            if fresh_project:
                                logger.error(f"Fresh project outline type: {type(fresh_project.outline)}")

                    except Exception as db_error:
                        logger.error(f"Failed to reload outline from database: {db_error}")
                        import traceback
                        logger.error(f"Database reload traceback: {traceback.format_exc()}")

                # 如果仍然没有slides，检查是否有大纲内容需要解析
                if not slides and outline and 'content' in outline:
                    logger.info(f"Found outline content, attempting to parse slides")
                    try:
                        # 尝试解析大纲内容
                        parsed_outline = self._parse_outline_content(outline['content'], project)
                        slides = parsed_outline.get('slides', [])
                        logger.info(f"Parsed {len(slides)} slides from outline content")

                        # 更新大纲数据
                        outline['slides'] = slides
                        project.outline = outline

                    except Exception as parse_error:
                        logger.error(f"Failed to parse outline content: {parse_error}")

                # 特殊处理：如果outline直接包含slides数组但为空，尝试从content字段解析
                if not slides and outline and isinstance(outline, dict):
                    # 检查是否有content字段包含JSON格式的大纲
                    content_field = outline.get('content', '')
                    if content_field and isinstance(content_field, str):
                        logger.info(f"Attempting to parse slides from content field")
                        try:
                            import json
                            # 尝试解析content字段中的JSON
                            content_data = json.loads(content_field)
                            if isinstance(content_data, dict) and 'slides' in content_data:
                                slides = content_data['slides']
                                logger.info(f"Successfully parsed {len(slides)} slides from content JSON")

                                # 更新outline中的slides
                                outline['slides'] = slides
                                project.outline = outline
                        except json.JSONDecodeError as json_error:
                            logger.error(f"Failed to parse content as JSON: {json_error}")
                        except Exception as content_error:
                            logger.error(f"Failed to extract slides from content: {content_error}")

                # 最后尝试：如果outline本身就是完整的大纲数据（包含title和slides）
                if not slides and outline and isinstance(outline, dict):
                    # 检查outline是否直接包含slides数组
                    direct_slides = outline.get('slides', [])
                    if direct_slides and isinstance(direct_slides, list):
                        slides = direct_slides
                        logger.info(f"Found {len(slides)} slides directly in outline")
                    # 或者检查是否有嵌套的大纲结构
                    elif 'outline' in outline and isinstance(outline['outline'], dict):
                        nested_slides = outline['outline'].get('slides', [])
                        if nested_slides and isinstance(nested_slides, list):
                            slides = nested_slides
                            logger.info(f"Found {len(slides)} slides in nested outline structure")

                # 额外调试：打印outline结构以便诊断
                if not slides:
                    logger.error(f"DEBUG: Full outline structure for project {project_id}:")
                    logger.error(f"Outline type: {type(outline)}")
                    if outline:
                        logger.error(f"Outline keys: {list(outline.keys()) if isinstance(outline, dict) else 'Not a dict'}")
                        if isinstance(outline, dict):
                            for key, value in outline.items():
                                logger.error(f"  {key}: {type(value)} - {len(value) if isinstance(value, (list, dict, str)) else value}")
                                if key == 'slides' and isinstance(value, list):
                                    logger.error(f"    Slides count: {len(value)}")
                                    if value:
                                        logger.error(f"    First slide: {value[0] if len(value) > 0 else 'None'}")
                                elif key == 'content' and isinstance(value, str):
                                    logger.error(f"    Content preview: {value[:200]}...")

                    # 尝试直接从outline中提取slides，不管结构如何
                    if isinstance(outline, dict):
                        # 递归搜索slides字段
                        def find_slides_recursive(obj, path=""):
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    current_path = f"{path}.{k}" if path else k
                                    if k == 'slides' and isinstance(v, list) and v:
                                        logger.info(f"Found slides at path: {current_path} with {len(v)} items")
                                        return v
                                    elif isinstance(v, (dict, list)):
                                        result = find_slides_recursive(v, current_path)
                                        if result:
                                            return result
                            elif isinstance(obj, list):
                                for i, item in enumerate(obj):
                                    current_path = f"{path}[{i}]" if path else f"[{i}]"
                                    if isinstance(item, (dict, list)):
                                        result = find_slides_recursive(item, current_path)
                                        if result:
                                            return result
                            return None

                        found_slides = find_slides_recursive(outline)
                        if found_slides:
                            slides = found_slides
                            logger.info(f"Successfully found {len(slides)} slides through recursive search")

                # 最后的fallback：如果仍然没有slides，返回错误而不是生成默认大纲
                if not slides:
                    error_message = "❌ 错误：未找到PPT大纲数据，请先完成大纲生成步骤"
                    logger.error(f"No slides found for project {project_id}")
                    logger.error(f"Project outline structure: {type(project.outline)}")
                    if project.outline:
                        logger.error(f"Outline keys: {list(project.outline.keys()) if isinstance(project.outline, dict) else 'Not a dict'}")
                        if isinstance(project.outline, dict) and 'slides' in project.outline:
                            logger.error(f"Slides type: {type(project.outline['slides'])}, length: {len(project.outline['slides']) if isinstance(project.outline['slides'], list) else 'Not a list'}")
                    error_data = {'error': error_message}
                    yield f"data: {json.dumps(error_data)}\n\n"
                    return

                # 如果没有确认需求，使用默认需求配置
                if not project.confirmed_requirements:
                    logger.info(f"Project {project_id} has no confirmed requirements, using default configuration")
                    confirmed_requirements = {
                        "topic": project.topic,
                        "target_audience": "普通大众",
                        "focus_content": ["核心概念", "主要特点"],
                        "tech_highlights": ["技术要点", "实践应用"],
                        "page_count_settings": {"mode": "ai_decide"},
                        "ppt_style": "general",
                        "description": f"基于主题 '{project.topic}' 的PPT演示"
                    }
                else:
                    confirmed_requirements = project.confirmed_requirements

                # 确保我们有有效的大纲和slides数据
                if not outline:
                    outline = project.outline

                if not slides:
                    slides = outline.get('slides', []) if outline else []

                # 最终检查：如果仍然没有slides，返回错误
                if not slides:
                    error_message = "❌ 错误：大纲中没有幻灯片信息，请检查大纲生成是否完成"
                    logger.error(f"No slides found after all attempts for project {project_id}")
                    error_data = {'error': error_message}
                    yield f"data: {json.dumps(error_data)}\n\n"
                    return

                logger.info(f"Starting PPT generation for project {project_id} with {len(slides)} slides")

                # Mark PPT creation stage as running (important for reconnect/follow-mode streaming)
                db_manager_status = None
                generated_slide_indices: set[int] = set()
                processed_slide_indices: set[int] = set()
                ppt_creation_started_at = time.time()
                credits_provider_name: str | None = None
                credits_reference_id: str | None = None
                credits_expected_new_slides = 0
                credits_should_bill = False
                try:
                    from ..db_project_manager import DatabaseProjectManager
                    db_manager_status = DatabaseProjectManager()
                    await db_manager_status.update_stage_status(
                        project_id,
                        "ppt_creation",
                        "running",
                        0.0,
                        {"started_at": ppt_creation_started_at}
                    )
                except Exception as status_error:
                    logger.warning(f"Failed to update PPT creation stage to running: {status_error}")

                async def sync_ppt_creation_progress(extra_result: Optional[Dict[str, Any]] = None) -> None:
                    if db_manager_status is None:
                        return

                    total_slides = len(slides)
                    progress_value = 0.0
                    if total_slides > 0:
                        progress_value = min((len(processed_slide_indices) / total_slides) * 100, 99.0)

                    result_payload = {
                        "started_at": ppt_creation_started_at,
                        "slides_count": total_slides,
                        "processed_slides": len(processed_slide_indices),
                    }
                    if extra_result:
                        result_payload.update(extra_result)

                    try:
                        await db_manager_status.update_stage_status(
                            project_id,
                            "ppt_creation",
                            "running",
                            progress_value,
                            result_payload,
                        )
                    except Exception as progress_error:
                        logger.warning(f"Failed to sync PPT creation progress: {progress_error}")

                # Credits check before generating any new slides (only for LandPPT official provider).
                if app_config.enable_credits_system and self.user_id is not None:
                    try:
                        _, slide_settings = await self.get_role_provider_async("slide_generation")
                        credits_provider_name = slide_settings.get("provider")
                        credits_should_bill = (credits_provider_name or "").strip().lower() == "landppt"
                    except Exception as provider_error:
                        logger.warning(f"Failed to resolve slide_generation provider for credits: {provider_error}")
                        credits_should_bill = False

                if credits_should_bill:
                    try:
                        from ..db_project_manager import DatabaseProjectManager
                        db_manager = DatabaseProjectManager()
                        existing_slides = await db_manager.list_slides(project_id)
                        existing_with_html = {
                            int(s.get("page_number", 0)) - 1
                            for s in (existing_slides or [])
                            if s and s.get("html_content") and int(s.get("page_number", 0)) > 0
                        }
                        credits_expected_new_slides = sum(
                            1 for idx in range(len(slides)) if idx not in existing_with_html
                        )
                    except Exception as scan_error:
                        logger.warning(f"Failed to pre-scan existing slides for credits: {scan_error}")
                        credits_expected_new_slides = len(slides)

                    if credits_expected_new_slides > 0:
                        credits_reference_id = f"{project_id}:ppt_creation:{int(ppt_creation_started_at * 1000)}"
                        try:
                            from ..credits_service import CreditsService
                            from ...database.database import AsyncSessionLocal

                            async with AsyncSessionLocal() as session:
                                credits_service = CreditsService(session)
                                required = credits_service.get_operation_cost(
                                    "slide_generation", credits_expected_new_slides
                                )
                                balance = await credits_service.get_balance(self.user_id)
                                if balance < required:
                                    message = f"积分不足，PPT生成需要{required}积分，当前余额{balance}积分"
                                    try:
                                        if db_manager_status is None:
                                            from ..db_project_manager import DatabaseProjectManager
                                            db_manager_status = DatabaseProjectManager()
                                        await db_manager_status.update_stage_status(
                                            project_id,
                                            "ppt_creation",
                                            "failed",
                                            None,
                                            {
                                                "message": message,
                                                "failed_at": time.time(),
                                                "required": required,
                                                "balance": balance,
                                                "provider": credits_provider_name,
                                            },
                                        )
                                    except Exception:
                                        pass
                                    yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
                                    return
                        except Exception as credits_error:
                            message = f"积分检查失败: {credits_error}"
                            try:
                                if db_manager_status is None:
                                    from ..db_project_manager import DatabaseProjectManager
                                    db_manager_status = DatabaseProjectManager()
                                await db_manager_status.update_stage_status(
                                    project_id,
                                    "ppt_creation",
                                    "failed",
                                    None,
                                    {"message": message, "failed_at": time.time()},
                                )
                            except Exception:
                                pass
                            yield f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"
                            return

                # Cache service (used for cooperative cancellation)
                try:
                    from ..cache_service import get_cache_service
                    cache = await get_cache_service()
                except Exception:
                    cache = None

                # Load system prompt
                system_prompt = self._load_prompts_md_system_prompt()

                # Initialize slides data if not exists
                if not project.slides_data:
                    project.slides_data = []

                # 检查是否启用并行生成 - 从用户配置读取
                user_gen_config = await self._get_user_generation_config()
                parallel_enabled = user_gen_config["enable_parallel_generation"]
                parallel_count = user_gen_config["parallel_slides_count"] if parallel_enabled else 1
                design_context_prepared = False

                if parallel_enabled:
                    logger.info(f"🚀 并行生成已启用，每批生成 {parallel_count} 页")
                else:
                    logger.info(f"📝 使用顺序生成模式")

                logger.info("创意指导模式：统一使用全局规则与页面类型指导")

                # 批量生成幻灯片（支持并行和顺序两种模式）
                i = 0
                while i < len(slides):
                    # Cooperative cancellation (stop/pause button or API request)
                    try:
                        if await self._is_slides_generation_cancelled(project_id, cache=cache):
                            cancel_message = "已收到停止请求，已停止生成。"
                            try:
                                if db_manager_status is None:
                                    from ..db_project_manager import DatabaseProjectManager
                                    db_manager_status = DatabaseProjectManager()
                                await db_manager_status.update_stage_status(
                                    project_id,
                                    "ppt_creation",
                                    "cancelled",
                                    None,
                                    {"message": cancel_message, "cancelled_at": time.time()}
                                )
                            except Exception:
                                pass
                            yield f"data: {json.dumps({'type': 'error', 'message': cancel_message})}\n\n"
                            return
                    except Exception:
                        pass
                    # 确定本批次要生成的幻灯片
                    batch_end = min(i + parallel_count, len(slides))
                    batch_slides = slides[i:batch_end]

                    # 收集本批次需要生成的幻灯片
                    slides_to_generate = []
                    slides_to_skip = []

                    for idx in range(i, batch_end):
                        slide = slides[idx]
                        page_number = idx + 1  # page_number 从1开始

                        # 检查是否已存在 - 首先从数据库查询，确保获取最新状态
                        # 这修复了并发请求时内存数据不一致的问题
                        existing_slide = None

                        # 优先从数据库获取单个幻灯片的最新状态
                        try:
                            from ..db_project_manager import DatabaseProjectManager
                            db_manager = DatabaseProjectManager()
                            db_slide = await db_manager.get_single_slide(project_id, idx)
                            if db_slide and db_slide.get('html_content'):
                                existing_slide = db_slide
                                logger.debug(f"从数据库获取到第{page_number}页的幻灯片数据")
                        except Exception as db_error:
                            logger.warning(f"从数据库获取幻灯片失败，回退到内存数据: {db_error}")

                        # 如果数据库中没有，检查内存中的project.slides_data
                        if not existing_slide and project.slides_data:
                            for s in project.slides_data:
                                if s and s.get('page_number') == page_number:
                                    existing_slide = s
                                    break

                        if existing_slide and existing_slide.get('html_content'):
                            # 幻灯片已存在，跳过
                            if existing_slide.get('is_user_edited', False):
                                skip_message = f'第{idx+1}页已被用户编辑，跳过重新生成'
                            else:
                                skip_message = f'第{idx+1}页已存在，跳过生成'

                            # 同步更新内存中的slides_data
                            while len(project.slides_data) <= idx:
                                project.slides_data.append(None)
                            project.slides_data[idx] = existing_slide

                            skip_data = {
                                'type': 'slide_skipped',
                                'current': idx + 1,
                                'total': len(slides),
                                'message': skip_message,
                                'slide_data': existing_slide
                            }
                            yield f"data: {json.dumps(skip_data)}\n\n"
                            slides_to_skip.append(idx)
                            processed_slide_indices.add(idx)
                        else:
                            # 需要生成
                            slides_to_generate.append((idx, slide))

                    # 如果有需要生成的幻灯片
                    if slides_to_skip:
                        await sync_ppt_creation_progress()

                    if slides_to_generate:
                        if not design_context_prepared:
                            # logger.info(
                            #     "仅预热共享创意缓存后立即开始PPT生成，剩余单页创意指导转后台异步预热"
                            # )
                            await self._prepare_project_creative_guidance(
                                project_id=project_id,
                                slide_data=slides[0],
                                confirmed_requirements=confirmed_requirements,
                                all_slides=slides,
                                total_pages=len(slides),
                                prewarm_slide_guides=0,
                                async_prewarm_remaining_slide_guides=True,
                            )
                            design_context_prepared = True

                        if parallel_enabled and len(slides_to_generate) > 1:
                            # 流式并行生成
                            logger.info(f"📦 流式并行生成 {len(slides_to_generate)} 页")

                            # 发送初始进度消息
                            for idx, slide in slides_to_generate:
                                progress_data = {
                                    'type': 'progress',
                                    'current': idx + 1,
                                    'total': len(slides),
                                    'message': f'正在生成第{idx+1}页：{slide.get("title", "")}...'
                                }
                                yield f"data: {json.dumps(progress_data)}\n\n"

                            # 创建包装协程，返回结果和元数据
                            async def generate_with_metadata(idx, slide):
                                try:
                                    html_content = await self._generate_single_slide_html_with_prompts(
                                        slide, confirmed_requirements, system_prompt,
                                        idx + 1, len(slides), slides, project.slides_data, project_id
                                    )
                                    return idx, slide, html_content, None
                                except Exception as e:
                                    return idx, slide, None, e

                            # 创建所有并行任务
                            tasks = [generate_with_metadata(idx, slide) for idx, slide in slides_to_generate]

                            # 流式处理完成的任务 - 一旦某页生成完成，立即展示和添加
                            for coro in asyncio.as_completed(tasks):
                                idx, slide, html_content, error = await coro
                                try:
                                    if error:
                                        raise error
                                    logger.info(f"✅ 流式生成第{idx+1}页成功")
                                except Exception as e:
                                    logger.error(f"❌ 流式生成第{idx+1}页失败: {e}")
                                    html_content = f"<div style='padding: 50px; text-align: center; color: red;'>生成失败：{str(e)}</div>"

                                # 创建幻灯片数据
                                slide_data = {
                                    "page_number": idx + 1,
                                    "title": slide.get('title', f'第{idx+1}页'),
                                    "html_content": html_content,
                                    "is_user_edited": False
                                }

                                # 更新项目数据
                                while len(project.slides_data) <= idx:
                                    project.slides_data.append(None)
                                project.slides_data[idx] = slide_data

                                # 保存到数据库
                                try:
                                    from ..db_project_manager import DatabaseProjectManager
                                    db_manager = DatabaseProjectManager()
                                    project.updated_at = time.time()
                                    generated_slide_indices.add(idx)
                                    await db_manager.save_single_slide(project_id, idx, slide_data, skip_if_user_edited=True)
                                    logger.info(f"💾 第{idx+1}页已保存到数据库")
                                except Exception as save_error:
                                    logger.error(f"保存第{idx+1}页失败: {save_error}")

                                # 立即发送幻灯片数据到前端
                                slide_response = {'type': 'slide', 'slide_data': slide_data}
                                yield f"data: {json.dumps(slide_response)}\n\n"
                                processed_slide_indices.add(idx)
                                await sync_ppt_creation_progress()
                        else:
                            # 顺序生成（未启用并行或只有一页）
                            for idx, slide in slides_to_generate:
                                try:
                                    # 发送进度更新
                                    slide_title = slide.get('title', '')
                                    progress_data = {
                                        'type': 'progress',
                                        'current': idx + 1,
                                        'total': len(slides),
                                        'message': f'正在生成第{idx+1}页：{slide_title}...'
                                    }
                                    yield f"data: {json.dumps(progress_data)}\n\n"
                                    logger.info(f"Generating slide {idx+1}/{len(slides)}: {slide_title}")

                                    # 生成HTML
                                    html_content = await self._generate_single_slide_html_with_prompts(
                                        slide, confirmed_requirements, system_prompt,
                                        idx + 1, len(slides), slides, project.slides_data, project_id
                                    )

                                    # 创建幻灯片数据
                                    slide_data = {
                                        "page_number": idx + 1,
                                        "title": slide.get('title', f'第{idx+1}页'),
                                        "html_content": html_content,
                                        "is_user_edited": False
                                    }

                                    # 更新项目数据
                                    while len(project.slides_data) <= idx:
                                        project.slides_data.append(None)
                                    project.slides_data[idx] = slide_data

                                    # 保存到数据库
                                    try:
                                        from ..db_project_manager import DatabaseProjectManager
                                        db_manager = DatabaseProjectManager()
                                        project.updated_at = time.time()
                                        generated_slide_indices.add(idx)
                                        await db_manager.save_single_slide(project_id, idx, slide_data, skip_if_user_edited=True)
                                        logger.info(f"Successfully saved slide {idx+1} to database for project {project_id}")
                                    except Exception as save_error:
                                        logger.error(f"Failed to save slide {idx+1} to database: {save_error}")

                                    # 发送幻灯片数据
                                    slide_response = {'type': 'slide', 'slide_data': slide_data}
                                    yield f"data: {json.dumps(slide_response)}\n\n"
                                    processed_slide_indices.add(idx)
                                    await sync_ppt_creation_progress()

                                except Exception as e:
                                    logger.error(f"Error generating slide {idx+1}: {e}")
                                    # 发送错误幻灯片
                                    error_slide = {
                                        "page_number": idx + 1,
                                        "title": slide.get('title', f'第{idx+1}页'),
                                        "html_content": f"<div style='padding: 50px; text-align: center; color: red;'>生成失败：{str(e)}</div>"
                                    }

                                    while len(project.slides_data) <= idx:
                                        project.slides_data.append(None)
                                    project.slides_data[idx] = error_slide

                                    # Persist error slide to DB as well (so reconnect/follow-mode can render it)
                                    try:
                                        from ..db_project_manager import DatabaseProjectManager
                                        db_manager = DatabaseProjectManager()
                                        project.updated_at = time.time()
                                        generated_slide_indices.add(idx)
                                        await db_manager.save_single_slide(project_id, idx, error_slide, skip_if_user_edited=True)
                                    except Exception as save_error:
                                        logger.error(f"Failed to save error slide {idx+1} to database: {save_error}")

                                    error_response = {'type': 'slide', 'slide_data': error_slide}
                                    yield f"data: {json.dumps(error_response)}\n\n"
                                    processed_slide_indices.add(idx)
                                    await sync_ppt_creation_progress({"last_error": str(e)})

                    # 移动到下一批
                    i = batch_end

                # Generate combined HTML
                project.slides_html = self._combine_slides_to_full_html(
                    project.slides_data, outline.get('title', project.title)
                )
                project.status = "completed"
                project.updated_at = time.time()

                # Update project status and stage completion (slides already saved individually)
                try:
                    from ..db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()

                    # Update project with final slides_html and slides_data (without recreating individual slides)
                    await db_manager.update_project_data(project_id, {
                        "slides_html": project.slides_html,
                        "slides_data": project.slides_data,
                        "status": "completed",
                        "updated_at": time.time()
                    })
                    logger.info(f"Successfully updated project data for project {project_id}")

                    # Update PPT creation stage status to completed
                    await db_manager.update_stage_status(
                        project_id,
                        "ppt_creation",
                        "completed",
                        100.0,
                        {"slides_count": len(slides), "completed_at": time.time()}
                    )
                    logger.info(f"Successfully updated PPT creation stage to completed for project {project_id}")

                except Exception as save_error:
                    logger.error(f"Failed to update project status in database: {save_error}")
                    # Continue anyway, as the data is still in memory

                # Bill credits once per PPT creation run (best-effort; only for billable providers).
                if (
                    app_config.enable_credits_system
                    and credits_should_bill
                    and credits_reference_id
                    and self.user_id is not None
                    and generated_slide_indices
                ):
                    try:
                        from sqlalchemy import select, func
                        from ...database.models import CreditTransaction
                        from ...database.database import AsyncSessionLocal
                        from ..credits_service import CreditsService

                        async with AsyncSessionLocal() as session:
                            billed_stmt = select(func.count(CreditTransaction.id)).where(
                                CreditTransaction.user_id == self.user_id,
                                CreditTransaction.transaction_type == "consume",
                                CreditTransaction.reference_id == credits_reference_id,
                                CreditTransaction.amount < 0,
                            )
                            already_billed = (await session.execute(billed_stmt)).scalar() or 0
                            if not already_billed:
                                credits_service = CreditsService(session)
                                billed_ok, billed_msg = await credits_service.consume_credits(
                                    user_id=self.user_id,
                                    operation_type="slide_generation",
                                    quantity=len(generated_slide_indices),
                                    description=f"PPT generation: {getattr(project, 'topic', '')}",
                                    reference_id=credits_reference_id,
                                )
                                if billed_ok:
                                    logger.info(
                                        "Billed %s slides for project %s (%s): %s",
                                        len(generated_slide_indices),
                                        project_id,
                                        credits_reference_id,
                                        billed_msg,
                                    )
                                else:
                                    logger.warning(
                                        "Slide credits billing skipped/failed for project %s: %s",
                                        project_id,
                                        billed_msg,
                                    )
                    except Exception as billing_error:
                        logger.error(
                            "Credits consumption error for ppt_creation (project=%s): %s",
                            project_id,
                            billing_error,
                            exc_info=True,
                        )

                # Send completion message
                complete_message = f'✅ PPT制作完成！成功生成 {len(slides)} 页幻灯片'
                complete_response = {'type': 'complete', 'message': complete_message}
                yield f"data: {json.dumps(complete_response)}\n\n"

            except Exception as e:
                logger.error(f"Error in streaming PPT generation: {e}")
                # Persist failure state so reconnect/follow-mode can stop promptly
                try:
                    if db_manager_status is None:
                        from ..db_project_manager import DatabaseProjectManager
                        db_manager_status = DatabaseProjectManager()
                    await db_manager_status.update_stage_status(
                        project_id,
                        "ppt_creation",
                        "failed",
                        None,
                        {"message": str(e), "failed_at": time.time()}
                    )
                except Exception:
                    pass
                error_message = f'生成过程中出现错误：{str(e)}'
                error_response = {'type': 'error', 'message': error_message}
                yield f"data: {json.dumps(error_response)}\n\n"
