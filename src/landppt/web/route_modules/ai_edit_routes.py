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
from types import SimpleNamespace
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


class AISlideEditRequest(BaseModel):
    slideIndex: int
    slideTitle: str
    slideContent: str
    userRequest: str
    projectInfo: Dict[str, Any]
    slideOutline: Optional[Dict[str, Any]] = None
    chatHistory: Optional[List[Dict[str, str]]] = None
    images: Optional[List[Dict[str, Any]]] = None  # 新增：图片信息列表（url/id/name/size 等）
    visionEnabled: Optional[bool] = False  # 新增：视觉模式启用状态
    slideScreenshot: Optional[str] = None  # 新增：幻灯片截图数据（data URL / base64）


class AIElementEditRequest(BaseModel):
    slideIndex: int
    slideTitle: str
    slideContent: str
    elementHtml: str
    elementId: str
    userRequest: str
    projectInfo: Dict[str, Any]
    slideOutline: Optional[Dict[str, Any]] = None
    visionEnabled: Optional[bool] = False
    elementScreenshot: Optional[str] = None


class AISlideNativeDialogRequest(BaseModel):
    slideIndex: int
    slideTitle: str
    slideContent: str
    userRequest: str
    chatHistory: Optional[List[Dict[str, str]]] = None
    images: Optional[List[Dict[str, str]]] = None  # 粘贴/上传图片信息列表（url/id/name/size）


class AIBulletPointEnhanceRequest(BaseModel):
    slideIndex: int
    slideTitle: str
    slideContent: str
    userRequest: str
    projectInfo: Dict[str, Any]
    slideOutline: Optional[Dict[str, Any]] = None
    contextInfo: Optional[Dict[str, Any]] = None  # 包含原始要点、其他要点等上下文信息


class AIImageRegenerateRequest(BaseModel):
    slide_index: int
    image_info: Dict[str, Any]
    slide_content: Dict[str, Any]
    project_topic: str
    project_scenario: str
    regeneration_reason: Optional[str] = None


class AIAutoImageGenerateRequest(BaseModel):
    slide_index: int
    slide_content: Dict[str, Any]
    project_topic: str
    project_scenario: str


class AutoLayoutRepairRequest(BaseModel):
    html_content: str
    slide_data: Dict[str, Any]


class OutlineAIOptimizeRequest(BaseModel):
    outline_content: str  # JSON格式的大纲内容
    user_request: str  # 用户的优化需求
    project_info: Dict[str, Any]  # 项目信息
    optimization_type: str = "full"  # full=全大纲优化, single=单页优化
    slide_index: Optional[int] = None  # 当optimization_type=single时使用
    language: Optional[str] = None  # 目标语言（如 zh/en/ja...），优先级高于大纲metadata.language


@router.post("/api/projects/{project_id}/slides/{slide_index}/auto-repair-layout")
async def auto_repair_layout(
    project_id: str,
    slide_index: int,
    request: AutoLayoutRepairRequest,
    user: User = Depends(get_current_user_required)
):
    """Run multimodal layout inspection and repair workflow for a single slide."""
    try:
        if slide_index < 1:
            raise HTTPException(status_code=400, detail="Slide index must be >= 1")

        html_content = (request.html_content or "").strip()
        if not html_content:
            raise HTTPException(status_code=400, detail="HTML content is required")

        # 使用用户特定的PPT服务，以便从数据库读取用户配置
        user_ppt_service = get_ppt_service_for_user(user.id)

        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        slides_data = project.slides_data or []
        total_pages = len(slides_data)
        if total_pages == 0:
            total_pages = request.slide_data.get("total_pages") or request.slide_data.get("totalSlides") or slide_index

        slide_payload = dict(request.slide_data or {})
        slide_payload.setdefault("page_number", slide_index)
        slide_payload.setdefault("title", slide_payload.get("title", f"第{slide_index}页"))

        repaired_html = await user_ppt_service._apply_auto_layout_repair(
            html_content,
            slide_payload,
            slide_index,
            total_pages or slide_index
        )

        changed = repaired_html.strip() != html_content

        if project.slides_data is None:

            project.slides_data = []

        while len(project.slides_data) < slide_index:
            page_number = len(project.slides_data) + 1
            project.slides_data.append({
                "page_number": page_number,
                "title": f"第{page_number}页",
                "html_content": "",
                "slide_type": "content",
                "content_points": [],
                "is_user_edited": False
            })

        existing_slide = project.slides_data[slide_index - 1]
        updated_slide = {
            **existing_slide,
            "page_number": slide_index,
            "title": slide_payload.get("title", existing_slide.get("title", f"第{slide_index}页")),
            "html_content": repaired_html,
        }

        project.slides_data[slide_index - 1] = updated_slide

        if changed:
            outline_title = project.title
            if isinstance(project.outline, dict):
                outline_title = project.outline.get('title', project.title)
            elif hasattr(project.outline, 'title'):
                outline_title = project.outline.title

            project.slides_html = ppt_service._combine_slides_to_full_html(
                project.slides_data,
                outline_title
            )
            project.updated_at = time.time()

        try:
            from ...services.db_project_manager import DatabaseProjectManager
            db_manager = DatabaseProjectManager()
            await db_manager.save_single_slide(project_id, slide_index - 1, updated_slide)

            if changed:
                await db_manager.update_project_data(project_id, {
                    "slides_html": project.slides_html,
                    "updated_at": project.updated_at
                })

        except Exception as save_error:
            logger.error(f"Failed to persist auto layout repair result: {save_error}")

        return {
            "success": True,
            "repaired_html": repaired_html,
            "changed": changed
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auto layout repair failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/ai/slide-edit")
async def ai_slide_edit(
    request: AISlideEditRequest,
    user: User = Depends(get_current_user_required)
):
    """AI编辑幻灯片接口"""
    try:
        # Check credits before AI editing
        user_ppt_service = get_ppt_service_for_user(user.id)
        role = "vision_analysis" if request.visionEnabled else "editor"
        provider, settings = await user_ppt_service.get_role_provider_async(role)
        editor_provider_name = settings.get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_edit", 1, provider_name=editor_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "error": f"积分不足，AI编辑需要 {required} 积分，当前余额 {balance} 积分"
            }

        # 获取AI提供者（已在积分校验前获取）

        # 构建AI编辑上下文
        outline_info = ""
        if request.slideOutline:
            outline_info = f"""
当前幻灯片大纲信息：
- 幻灯片类型：{request.slideOutline.get('slide_type', '未知')}
- 描述：{request.slideOutline.get('description', '无')}
- 要点：{', '.join(request.slideOutline.get('content_points', [])) if request.slideOutline.get('content_points') else '无'}
"""

        context = f"""
你是一位专业的PPT设计师和编辑助手。用户想要对当前幻灯片进行编辑修改。

当前幻灯片信息：
- 页码：第{request.slideIndex}页
- 标题：{request.slideTitle}
- 项目主题：{request.projectInfo.get('title', '未知')}
- 项目场景：{request.projectInfo.get('scenario', '未知')}
{outline_info}
用户的编辑要求：
{request.userRequest}

当前幻灯片的HTML内容：
{request.slideContent}

请根据用户的要求和幻灯片大纲信息，提供以下内容：
1. 对用户要求的理解和分析
2. 具体的修改建议
3. 如果需要，提供修改后的完整HTML代码

注意事项：
- 确保修改后的内容符合PPT演示的专业标准和大纲要求
- 生成的HTML应该是完整的，包含必要的CSS样式
- 保持1280x720的PPT标准尺寸
- 参考大纲信息中的要点和描述来优化内容
"""

        # 构建AI消息，包含对话历史
        messages = [
            AIMessage(role=MessageRole.SYSTEM, content="你是一位专业的PPT设计师和编辑助手，擅长根据用户需求修改和优化PPT内容。")
        ]

        # 添加对话历史
        if request.chatHistory:
            logger.debug(f"AI编辑接收到对话历史，共 {len(request.chatHistory)} 条消息")
            for i, chat_msg in enumerate(request.chatHistory):
                role = MessageRole.USER if chat_msg.get('role') == 'user' else MessageRole.ASSISTANT
                content = chat_msg.get('content', '')
                logger.debug(f"对话历史 {i+1}: {role.value} - {content[:100]}...")
                messages.append(AIMessage(role=role, content=content))
        else:
            logger.debug("AI编辑未接收到对话历史")

        # 添加当前用户请求
        messages.append(AIMessage(role=MessageRole.USER, content=context))

        # 调用AI生成回复（自动应用用户配置的 temperature / top_p）
        response = await user_ppt_service._chat_completion_for_role(role, messages=messages)

        ai_response = response.content

        # 检查是否包含HTML代码
        new_html_content = None
        if "```html" in ai_response:
            import re
            html_match = re.search(r'```html\s*(.*?)\s*```', ai_response, re.DOTALL)
            if html_match:
                new_html_content = html_match.group(1).strip()

        await consume_credits_for_operation(
            user.id,
            "ai_edit",
            1,
            description=f"AI编辑: 第{request.slideIndex}页 {request.slideTitle}",
            reference_id=str(request.projectInfo.get("project_id") or request.projectInfo.get("id") or ""),
            provider_name=editor_provider_name,
        )

        return {
            "success": True,
            "response": ai_response,
            "newHtmlContent": new_html_content
        }

    except Exception as e:
        logger.error(f"AI编辑请求失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "response": "抱歉，AI编辑服务暂时不可用。请稍后重试。"
        }


@router.post("/api/ai/element-edit")
async def ai_element_edit(
    request: AIElementEditRequest,
    user: User = Depends(get_current_user_required)
):
    """AI element-level editing endpoint (returns updated element HTML only)."""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        role = "polish"
        _, settings = await user_ppt_service.get_role_provider_async(role)
        polish_provider_name = settings.get("provider")

        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_edit", 1, provider_name=polish_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "error": f"积分不足，AI编辑需要 {required} 积分，当前余额 {balance} 积分"
            }

        outline_info = ""
        if request.slideOutline:
            outline_info = f"\nSlide outline info:\n{request.slideOutline}\n"

        vision_hint = ""
        if request.visionEnabled and request.elementScreenshot:
            vision_hint = "\nYou will also receive an image screenshot of the selected element for visual reference.\n"

        context = f"""
You are a professional PPT designer and HTML editor.
The user selected ONE element from a slide. You MUST only modify the selected element.
{vision_hint}

User request:
{request.userRequest}

Selected element HTML (must preserve data-quick-ai-id=\"{request.elementId}\"):
{request.elementHtml}

Full slide HTML (for style and layout reference only):
{request.slideContent}
{outline_info}
Return ONLY the updated element HTML, as a single root element.
Do NOT wrap in markdown/code fences. Do NOT include any explanation.
Constraints:
- No <script> tags.
- No inline event handlers (no attributes starting with \"on\").
- Keep original positioning/size unless explicitly requested.
""".strip()

        messages = [
            AIMessage(
                role=MessageRole.SYSTEM,
                content="You are a professional PPT designer and HTML editor. Follow the user's request precisely."
            ),
        ]

        if request.visionEnabled and request.elementScreenshot:
            from ...ai.base import TextContent, ImageContent
            user_content = [
                TextContent(text=context),
                ImageContent(image_url={"url": request.elementScreenshot}),
            ]
            messages.append(AIMessage(role=MessageRole.USER, content=user_content))
        else:
            messages.append(AIMessage(role=MessageRole.USER, content=context))

        response = await user_ppt_service._chat_completion_for_role(role, messages=messages)
        ai_response = (response.content or "").strip()

        def _extract_candidate_html(text: str) -> str:
            import re
            patterns = [
                r"```html\\s*(.*?)\\s*```",
                r"```HTML\\s*(.*?)\\s*```",
                r"```\\s*html\\s*(.*?)\\s*```",
            ]
            for pattern in patterns:
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    return (m.group(1) or "").strip()
            return text.strip()

        def _sanitize_single_root_element(html: str, element_id: str) -> str | None:
            from bs4 import BeautifulSoup

            candidate = _extract_candidate_html(html)
            if not candidate:
                return None

            soup = BeautifulSoup(candidate, "html.parser")

            root = None
            if soup.body:
                root = soup.body.find(True, recursive=False) or soup.body.find(True)
            if not root:
                root = soup.find(True)
            if not root:
                return None

            for script in root.find_all("script"):
                script.decompose()

            for node in [root, *root.find_all(True)]:
                for attr in list(getattr(node, "attrs", {}).keys()):
                    if (attr or "").lower().startswith("on"):
                        try:
                            del node.attrs[attr]
                        except Exception:
                            pass

            root.attrs["data-quick-ai-id"] = element_id
            return str(root).strip()

        updated_element_html = _sanitize_single_root_element(ai_response, request.elementId)
        if not updated_element_html:
            return {
                "success": False,
                "error": "AI 返回内容中未能提取到有效的元素 HTML",
                "full_response": ai_response,
            }

        await consume_credits_for_operation(
            user.id,
            "ai_edit",
            1,
            description=f"AI元素编辑: 第{request.slideIndex}页 {request.slideTitle}",
            reference_id=str(request.projectInfo.get("project_id") or request.projectInfo.get("id") or ""),
            provider_name=polish_provider_name,
        )

        return {
            "success": True,
            "updated_element_html": updated_element_html,
            "full_response": ai_response,
        }

    except Exception as e:
        logger.error(f"AI element edit failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/api/ai/slide-edit/stream")
async def ai_slide_edit_stream(
    request: AISlideEditRequest,
    user: User = Depends(get_current_user_required)
):
    """AI编辑幻灯片流式接口"""
    try:
        # 获取AI提供者
        user_ppt_service = get_ppt_service_for_user(user.id)
        role = "vision_analysis" if request.visionEnabled else "editor"
        provider, settings = await user_ppt_service.get_role_provider_async(role)
        editor_provider_name = settings.get("provider")
        user_gen_config = {}
        try:
            user_gen_config = await user_ppt_service._get_user_generation_config()
        except Exception:
            user_gen_config = {}

        temperature = user_gen_config.get("temperature", ai_config.temperature)
        top_p = user_gen_config.get("top_p", getattr(ai_config, "top_p", 1.0))

        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_edit", 1, provider_name=editor_provider_name
        )
        if not has_credits:
            return StreamingResponse(
                iter([f"data: {json.dumps({'type': 'error', 'content': '', 'error': f'积分不足，AI编辑需要 {required} 积分，当前余额 {balance} 积分'})}\n\n"]),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control",
                },
            )

        # 构建AI编辑上下文
        outline_info = ""
        if request.slideOutline:
            outline_info = f"""
当前幻灯片大纲信息：
{request.slideOutline}
"""

        # 构建图片信息
        images_info = ""
        if request.images and len(request.images) > 0:
            images_info = f"""

用户上传的图片信息：
"""
            for i, image in enumerate(request.images, 1):
                url = image.get("url", "") if isinstance(image, dict) else ""
                # 避免把 data URL/base64 整段塞进文本上下文（图片会以多模态内容附带）
                if isinstance(url, str) and url.startswith("data:image"):
                    url_display = "（data URL 已随消息附带）"
                else:
                    url_display = url

                images_info += f"""
- 图片{i}：{image.get('name', '未知')}
  - URL：{url_display}
  - 大小：{image.get('size', '未知')}
  - 说明：请分析这张图片的内容，理解用户的意图，并根据编辑要求进行相应的处理
"""

        # 构建视觉上下文信息
        vision_context = ""
        if request.visionEnabled and request.slideScreenshot:
            vision_context = f"""

🔍 视觉上下文：
- 当前幻灯片的视觉截图已提供
- 请结合截图中的视觉内容来理解用户的编辑需求
- 注意截图中的布局、颜色、字体、图片位置等视觉元素
- 在提供编辑建议时，请考虑当前的视觉呈现效果
"""

        context = f"""
你是一位专业的PPT设计师和编辑助手。用户想要对当前幻灯片进行编辑修改。

当前幻灯片信息：
- 页码：第{request.slideIndex}页
- 标题：{request.slideTitle}
- 项目主题：{request.projectInfo.get('title', '未知')}
- 项目场景：{request.projectInfo.get('scenario', '未知')}
{outline_info}{images_info}{vision_context}
用户的编辑要求：
{request.userRequest}

当前幻灯片的HTML内容：
{request.slideContent}

请根据用户的要求和幻灯片大纲信息，提供以下内容：
1. 对用户要求的理解和分析
2. 具体的修改建议
3. 默认提供修改后的完整HTML代码

注意事项：
- 保持原有的设计风格和布局结构
- 确保修改后的内容符合PPT演示的专业标准和大纲要求
- 如果用户要求不明确，请提供多个可选方案
- 生成的HTML应该是完整的，包含必要的CSS样式
- 保持1280x720的PPT标准尺寸
- 参考大纲信息中的要点和描述来优化内容
"""

        # 构建AI消息，包含对话历史
        messages = [
            AIMessage(role=MessageRole.SYSTEM, content="你是一位专业的PPT设计师和编辑助手，擅长根据用户需求修改和优化PPT内容。")
        ]

        # 添加对话历史
        if request.chatHistory:
            logger.info(f"AI流式编辑接收到对话历史，共 {len(request.chatHistory)} 条消息")
            for i, chat_msg in enumerate(request.chatHistory):
                role = MessageRole.USER if chat_msg.get('role') == 'user' else MessageRole.ASSISTANT
                content = chat_msg.get('content', '')
                logger.info(f"对话历史 {i+1}: {role.value} - {content[:100]}...")
                messages.append(AIMessage(role=role, content=content))
        else:
            logger.info("AI流式编辑未接收到对话历史")

        # 添加当前用户请求（视觉模式：支持截图 + 上传图片的多模态内容）
        if request.visionEnabled:
            from ...ai.base import TextContent, ImageContent

            user_content = [TextContent(text=context)]

            if request.slideScreenshot:
                user_content.append(ImageContent(image_url={"url": request.slideScreenshot}))

            if request.images:
                for img in request.images:
                    url = (img or {}).get("url")
                    if url:
                        user_content.append(ImageContent(image_url={"url": url}))

            messages.append(AIMessage(role=MessageRole.USER, content=user_content))
        else:
            messages.append(AIMessage(role=MessageRole.USER, content=context))

        async def generate_ai_stream():
            try:
                # 发送开始信号
                yield f"data: {json.dumps({'type': 'start', 'content': ''})}\n\n"

                # 流式生成AI回复
                full_response = ""
                if hasattr(provider, 'stream_chat_completion'):
                    async for chunk in provider.stream_chat_completion(
                        messages=messages,
                        temperature=temperature,
                        top_p=top_p,
                        model=settings.get('model')
                    ):
                        if chunk:
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                else:
                    response = await provider.chat_completion(
                        messages=messages,
                        temperature=temperature,
                        top_p=top_p,
                        model=settings.get('model')
                    )
                    if response.content:
                        full_response = response.content
                        yield f"data: {json.dumps({'type': 'content', 'content': response.content})}\n\n"

                # 检查是否包含HTML代码 - 改进版本，支持多种格式
                new_html_content = None
                import re
                
                # 尝试多种HTML代码块格式
                html_patterns = [
                    r'```html\s*(.*?)\s*```',  # 标准格式
                    r'```HTML\s*(.*?)\s*```',  # 大写
                    r'```\s*html\s*(.*?)\s*```',  # 带空格
                    r'<html[^>]*>.*?</html>',  # 完整HTML文档
                    r'<div[^>]*style[^>]*>.*?</div>',  # PPT幻灯片div
                ]
                
                for pattern in html_patterns:
                    html_match = re.search(pattern, full_response, re.DOTALL | re.IGNORECASE)
                    if html_match:
                        new_html_content = html_match.group(1).strip() if html_match.groups() else html_match.group(0).strip()
                        logger.info(f"HTML内容提取成功，使用模式: {pattern}，内容长度: {len(new_html_content)}")
                        break
                
                if not new_html_content:
                    logger.warning(f"未能从AI响应中提取HTML内容。响应长度: {len(full_response)}")
                    logger.debug(f"AI完整响应: {full_response[:500]}...")

                # 发送完成信号
                yield f"data: {json.dumps({'type': 'complete', 'content': '', 'newHtmlContent': new_html_content, 'fullResponse': full_response})}\n\n"

                await consume_credits_for_operation(
                    user.id,
                    "ai_edit",
                    1,
                    description=f"AI编辑(流式): 第{request.slideIndex}页 {request.slideTitle}",
                    reference_id=str(request.projectInfo.get("project_id") or request.projectInfo.get("id") or ""),
                    provider_name=editor_provider_name,
                )

            except Exception as e:
                logger.error(f"AI流式编辑请求失败: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': '', 'error': str(e)})}\n\n"

        return StreamingResponse(
            generate_ai_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control"
            }
        )

    except Exception as e:
        logger.error(f"AI流式编辑请求失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "response": "抱歉，AI编辑服务暂时不可用。请稍后重试。"
        }


@router.post("/api/ai/slide-native-dialog/stream")
async def ai_slide_native_dialog_stream(
    request: AISlideNativeDialogRequest,
    user: User = Depends(get_current_user_required)
):
    """AI自由对话流式接口（不设系统提示词，仅当前页）"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        provider, settings = await user_ppt_service.get_role_provider_async("editor")
        dialog_provider_name = settings.get("provider")
        user_gen_config = {}
        try:
            user_gen_config = await user_ppt_service._get_user_generation_config()
        except Exception:
            user_gen_config = {}

        temperature = user_gen_config.get("temperature", ai_config.temperature)
        top_p = user_gen_config.get("top_p", getattr(ai_config, "top_p", 1.0))

        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_other", 1, provider_name=dialog_provider_name
        )
        if not has_credits:
            return StreamingResponse(
                iter([f"data: {json.dumps({'type': 'error', 'content': '', 'error': f'积分不足，需要 {required} 积分，当前余额 {balance} 积分'})}\n\n"]),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Headers": "Cache-Control",
                },
            )

        images_info = ""
        if request.images:
            images_info = f"\n用户上传/粘贴的图片数量：{len(request.images)}（图片内容在消息中以多模态形式附带）\n"

        context = f"""
当前页面信息（仅此页）：
- 页码：第{request.slideIndex}页
- 标题：{request.slideTitle}

当前页面HTML内容：
{request.slideContent}

用户问题：
{request.userRequest}
{images_info}
"""

        messages: List[AIMessage] = []

        # 添加对话历史（忽略 system 角色，避免“系统提示词”进入模型）
        if request.chatHistory:
            for chat_msg in request.chatHistory:
                role_str = (chat_msg.get("role") or "").lower()
                if role_str == "system":
                    continue

                if role_str == "assistant":
                    role = MessageRole.ASSISTANT
                else:
                    role = MessageRole.USER

                messages.append(AIMessage(role=role, content=chat_msg.get("content", "")))

        # 添加当前用户请求（支持粘贴/上传图片的多模态内容）
        if request.images and len(request.images) > 0:
            from ...ai.base import TextContent, ImageContent

            user_content = [TextContent(text=context)]
            for img in request.images:
                url = img.get("url")
                if url:
                    user_content.append(ImageContent(image_url={"url": url}))

            messages.append(AIMessage(role=MessageRole.USER, content=user_content))
        else:
            messages.append(AIMessage(role=MessageRole.USER, content=context))

        async def generate_ai_stream():
            try:
                yield f"data: {json.dumps({'type': 'start', 'content': ''})}\n\n"

                full_response = ""
                if hasattr(provider, "stream_chat_completion"):
                    async for chunk in provider.stream_chat_completion(
                        messages=messages,
                        temperature=temperature,
                        top_p=top_p,
                        model=settings.get("model"),
                    ):
                        if chunk:
                            full_response += chunk
                            yield f"data: {json.dumps({'type': 'content', 'content': chunk})}\n\n"
                else:
                    response = await provider.chat_completion(
                        messages=messages,
                        temperature=temperature,
                        top_p=top_p,
                        model=settings.get("model"),
                    )
                    if response.content:
                        full_response = response.content
                        yield f"data: {json.dumps({'type': 'content', 'content': response.content})}\n\n"

                yield f"data: {json.dumps({'type': 'complete', 'content': '', 'fullResponse': full_response})}\n\n"

                await consume_credits_for_operation(
                    user.id,
                    "ai_other",
                    1,
                    description=f"AI自由对话(流式): 第{request.slideIndex}页 {request.slideTitle}",
                    reference_id="",
                    provider_name=dialog_provider_name,
                )

            except Exception as e:
                logger.error(f"AI自由对话流式请求失败: {e}")
                yield f"data: {json.dumps({'type': 'error', 'content': '', 'error': str(e)})}\n\n"

        return StreamingResponse(
            generate_ai_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control",
            },
        )

    except Exception as e:
        logger.error(f"AI自由对话请求失败: {e}")
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'content': '', 'error': str(e)})}\n\n"]),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control",
            },
        )


@router.post("/api/ai/optimize-outline")
async def ai_optimize_outline(
    request: OutlineAIOptimizeRequest,
    user: User = Depends(get_current_user_required)
):
    """AI优化大纲接口 - 支持全大纲优化和单页优化"""
    try:
        # 获取AI提供者
        user_ppt_service = get_ppt_service_for_user(user.id)
        provider, settings = await user_ppt_service.get_role_provider_async("editor")
        optimize_provider_name = settings.get("provider")

        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_other", 1, provider_name=optimize_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "error": f"积分不足，需要 {required} 积分，当前余额 {balance} 积分"
            }
        
        # 统一使用服务层解析器，避免 fenced JSON 或轻微脏 JSON 被误判失败。
        try:
            project_topic = (
                request.project_info.get("topic")
                or request.project_info.get("title")
                or "PPT大纲"
            )
            outline_data = user_ppt_service.project_outline_workflow._parse_outline_content(
                request.outline_content,
                SimpleNamespace(topic=project_topic),
            )
        except Exception as e:
            return {
                "success": False,
                "error": f"大纲解析失败: {str(e)}"
            }

        def _normalize_language_code(value: Any) -> Optional[str]:
            if not isinstance(value, str):
                return None
            code = value.strip().lower()
            if not code:
                return None
            # Normalize common variants (zh-cn -> zh, en-us -> en, etc.)
            if code.startswith("zh"):
                return "zh"
            if code.startswith("en"):
                return "en"
            if code.startswith("ja"):
                return "ja"
            if code.startswith("ko"):
                return "ko"
            if code.startswith("fr"):
                return "fr"
            if code.startswith("de"):
                return "de"
            if code.startswith("es"):
                return "es"
            return code

        outline_language = None
        if isinstance(outline_data, dict):
            metadata = outline_data.get("metadata")
            if isinstance(metadata, dict):
                outline_language = metadata.get("language") or outline_data.get("language")
            else:
                outline_language = outline_data.get("language")

        target_language = (
            _normalize_language_code(request.language)
            or _normalize_language_code(outline_language)
            or "zh"
        )
        
        # 根据优化类型构建不同的提示词
        if request.optimization_type == "single" and request.slide_index is not None:
            # 单页优化
            if request.slide_index < 0 or request.slide_index >= len(outline_data.get('slides', [])):
                return {
                    "success": False,
                    "error": "无效的幻灯片索引"
                }
            
            slide = outline_data['slides'][request.slide_index]
            
            context = f"""Output language: {target_language}
你是一位专业的PPT大纲设计专家。用户想要优化PPT大纲中的第{request.slide_index + 1}页内容。

项目信息：
- 主题：{request.project_info.get('topic', '未知')}
- 场景：{request.project_info.get('scenario', '通用')}
- 目标受众：{request.project_info.get('target_audience', '普通大众')}

当前页面信息：
- 页码：第{slide.get('page_number', request.slide_index + 1)}页
- 标题：{slide.get('title', '未命名')}
- 类型：{slide.get('slide_type', 'content')}
- 内容要点：{json.dumps(slide.get('content_points', []), ensure_ascii=False, indent=2)}

用户的优化需求：
{request.user_request}

请根据用户需求优化这一页的内容。

【重要】直接返回优化后的JSON数据，不要包含任何解释性文字或markdown标记（如```json）。

返回格式示例：
{{
  "page_number": {slide.get('page_number', request.slide_index + 1)},
  "title": "优化后的标题",
  "subtitle": "副标题（可选）",
  "content_points": ["要点1", "要点2", "要点3"],
  "slide_type": "content",
  "description": "页面描述（可选）"
}}

优化要求：
1. 保持与整体大纲的连贯性和逻辑性
2. 确保内容要点清晰、具体、有价值
3. 标题要简洁有力，能够准确概括页面内容
4. content_points数组中的字符串可以包含代码示例（用```标记），这是合法的JSON字符串内容
5. 【关键】只返回纯JSON对象，不要用```json包裹整个JSON，不要添加任何其他解释文字
"""
        else:
            # 全大纲优化
            context = f"""Output language: {target_language}
你是一位专业的PPT大纲设计专家。用户想要优化整个PPT大纲。

项目信息：
- 主题：{request.project_info.get('topic', '未知')}
- 场景：{request.project_info.get('scenario', '通用')}
- 目标受众：{request.project_info.get('target_audience', '普通大众')}
- 当前页数：{len(outline_data.get('slides', []))}页

当前大纲：
{json.dumps(outline_data, ensure_ascii=False, indent=2)}

用户的优化需求：
{request.user_request}

请根据用户需求优化整个大纲。

【重要】直接返回完整的优化后的JSON数据，不要包含任何解释性文字、markdown标记或注释。

返回格式示例：
{{
  "title": "优化后的PPT标题",
  "slides": [
    {{
      "page_number": 1,
      "title": "页面标题",
      "subtitle": "副标题（可选）",
      "content_points": ["要点1", "要点2"],
      "slide_type": "title",
      "description": "页面描述（可选）"
    }}
  ],
  "metadata": {{
    "scenario": "{request.project_info.get('scenario', '通用')}",
    "language": "{target_language}",
    "target_audience": "{request.project_info.get('target_audience', '普通大众')}",
    "optimized": true
  }}
}}

优化要求：
1. 保持大纲的整体逻辑性和连贯性
2. 确保每页内容要点清晰、具体、有价值
3. 可以调整页面顺序、合并或拆分页面，但要保持总体结构合理
4. 标题要简洁有力
5. 【关键】只返回纯JSON格式，不要添加任何解释、注释或markdown标记
"""
        
        # 构建AI消息
        messages = [
            AIMessage(role=MessageRole.SYSTEM, content="你是一位专业的PPT大纲设计专家，擅长优化和改进PPT大纲结构和内容。你的回复必须是纯JSON格式，不要包含任何解释性文字、markdown标记或注释。"),
            AIMessage(role=MessageRole.SYSTEM, content=f"Output language: {target_language}. Return pure JSON only."),
            AIMessage(role=MessageRole.USER, content=context)
        ]
        
        # 调用AI生成回复（自动应用用户配置的 temperature / top_p）
        response = await user_ppt_service._chat_completion_for_role("editor", messages=messages)
        
        ai_response = response.content
        
        # 智能提取JSON内容
        import re
        
        def extract_json_from_response(text: str) -> str:
            """从AI响应中提取JSON内容，支持多种格式"""
            
            # 优先方法: 查找第一个{到最后一个}之间的内容
            # 这样可以避免错误提取content_points字段内的代码块
            first_brace = text.find('{')
            last_brace = text.rfind('}')
            if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
                potential_json = text[first_brace:last_brace + 1]
                # 尝试解析，如果成功则返回
                try:
                    json.loads(potential_json)
                    return potential_json.strip()
                except json.JSONDecodeError:
                    # 如果解析失败，尝试清理注释后再试
                    cleaned_json = re.sub(r'//[^\n]*', '', potential_json)  # 单行注释
                    cleaned_json = re.sub(r'/\*.*?\*/', '', cleaned_json, flags=re.DOTALL)  # 多行注释
                    try:
                        json.loads(cleaned_json)
                        return cleaned_json.strip()
                    except json.JSONDecodeError:
                        pass  # 继续尝试其他方法
            
            # 备用方法: 提取markdown代码块中的JSON（仅当标记为json时）
            # 使用更严格的匹配，确保是JSON代码块而不是其他代码块
            json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
            if json_match:
                extracted = json_match.group(1).strip()
                # 验证提取的内容是否是有效JSON
                try:
                    json.loads(extracted)
                    return extracted
                except json.JSONDecodeError:
                    pass  # 继续尝试其他方法
            
            # 最后尝试: 直接返回清理后的文本
            cleaned = text.strip()
            if cleaned.startswith('{'):
                return cleaned
            
            # 尝试找到JSON开始的位置
            for line in cleaned.split('\n'):
                line = line.strip()
                if line.startswith('{'):
                    start_idx = cleaned.find(line)
                    return cleaned[start_idx:].strip()
            
            return cleaned
        
        optimized_json = extract_json_from_response(ai_response)
        
        # 验证JSON格式
        try:
            optimized_data = json.loads(optimized_json)
        except json.JSONDecodeError as e:
            # 提供更详细的错误信息，帮助调试
            return {
                "success": False,
                "error": f"AI返回的内容不是有效的JSON格式: {str(e)}",
                "raw_response": ai_response,
                "extracted_json": optimized_json[:500] if len(optimized_json) > 500 else optimized_json
            }

        await consume_credits_for_operation(
            user.id,
            "ai_other",
            1,
            description="AI优化大纲",
            reference_id="",
            provider_name=optimize_provider_name,
        )

        return {
            "success": True,
            "optimized_content": json.dumps(optimized_data, ensure_ascii=False, indent=2),
            "optimization_type": request.optimization_type,
            "raw_response": ai_response
        }
        
    except Exception as e:
        logger.error(f"AI优化大纲请求失败: {e}")
        return {
            "success": False,
            "error": str(e)
        }


@router.post("/api/ai/regenerate-image")
async def ai_regenerate_image(
    request: AIImageRegenerateRequest,
    user: User = Depends(get_current_user_required)
):
    """AI重新生成图像接口 - 完全遵循enhanced_ppt_service.py的标准流程"""
    try:
        # 获取图像服务和AI提供者
        from ...services.image.image_service import get_image_service

        image_service = get_image_service()
        if not image_service:
            return {
                "success": False,
                "message": "图像服务不可用"
            }

        user_ppt_service = get_ppt_service_for_user(user.id)
        provider, settings = await user_ppt_service.get_role_provider_async("editor")
        # Ensure we have a general AI provider instance as well (some image processors expect ai_provider)
        # Use user-configured provider instead of default
        from ...services.db_config_service import get_user_ai_provider
        from ...services.db_config_service import get_user_ai_provider_config

        ai_provider_config = await get_user_ai_provider_config(user.id)
        billing_provider_name = ai_provider_config.get("provider_name")
        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_other", 1, provider_name=billing_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "message": f"积分不足，需要 {required} 积分，当前余额 {balance} 积分"
            }
        ai_provider = await get_user_ai_provider(user.id)
        if not ai_provider:
            return {
                "success": False,
                "message": "AI提供者不可用"
            }

        # 获取图像配置 - 从用户数据库配置读取（非环境变量）
        from ...services.db_config_service import get_db_config_service
        db_config_service = get_db_config_service()
        image_config = await db_config_service.get_config_by_category('image_service', user_id=user.id)

        # 检查是否启用图片生成服务
        enable_image_service = image_config.get('enable_image_service', False)
        if not enable_image_service:
            return {
                "success": False,
                "message": "图片生成服务未启用，请在配置中启用"
            }

        # 第一步：检查启用的图片来源（完全遵循PPTImageProcessor的逻辑）
        from ...services.models.slide_image_info import ImageSource

        enabled_sources = []
        if image_config.get('enable_local_images', True):
            enabled_sources.append(ImageSource.LOCAL)
        if image_config.get('enable_network_search', False):
            enabled_sources.append(ImageSource.NETWORK)
        if image_config.get('enable_ai_generation', False):
            enabled_sources.append(ImageSource.AI_GENERATED)

        if not enabled_sources:
            return {
                "success": False,
                "message": "没有启用任何图片来源，请在配置中启用至少一种图片来源"
            }

        # 初始化PPT图像处理器
        from ...services.ppt_image_processor import PPTImageProcessor

        image_processor = PPTImageProcessor(
            image_service=image_service,
            ai_provider=ai_provider,
            user_id=user.id
        )

        # 提取图像信息和幻灯片内容
        image_info = request.image_info
        slide_content = request.slide_content

        # 构建幻灯片数据结构（遵循PPTImageProcessor期望的格式）
        slide_data = {
            'title': slide_content.get('title', ''),
            'content_points': [slide_content.get('title', '')],  # 简化的内容点
        }

        # 构建确认需求结构
        confirmed_requirements = {
            'project_topic': request.project_topic,
            'project_scenario': request.project_scenario
        }

        # 第二步：直接创建图像重新生成需求（跳过AI配图适用性判断）
        logger.info(f"开始图片重新生成，启用的来源: {[source.value for source in enabled_sources]}")

        # 分析原图像的用途和上下文
        image_context = await analyze_image_context(
            image_info, slide_content, request.project_topic, request.project_scenario
        )

        # 根据启用的来源和配置，智能选择最佳的图片来源
        selected_source = select_best_image_source(enabled_sources, image_config, image_context)

        # 创建图像需求对象（直接生成，不需要AI判断是否适合配图）
        from ...services.models.slide_image_info import ImageRequirement, ImagePurpose

        # 将字符串用途转换为ImagePurpose枚举
        purpose_str = image_context.get('image_purpose', 'illustration')
        purpose_mapping = {
            'background': ImagePurpose.BACKGROUND,
            'icon': ImagePurpose.ICON,
            'chart_support': ImagePurpose.CHART_SUPPORT,
            'decoration': ImagePurpose.DECORATION,
            'illustration': ImagePurpose.ILLUSTRATION
        }
        purpose = purpose_mapping.get(purpose_str, ImagePurpose.ILLUSTRATION)

        requirement = ImageRequirement(
            source=selected_source,
            count=1,
            purpose=purpose,
            description=f"重新生成图像: {image_info.get('alt', '')} - {request.project_topic}",
            priority=5  # 高优先级，因为是用户明确请求的重新生成
        )

        logger.info(f"选择图片来源: {selected_source.value}, 用途: {purpose.value}")

        # 第三步：直接处理图片生成（单个需求）
        from ...services.models.slide_image_info import SlideImagesCollection

        images_collection = SlideImagesCollection(page_number=request.slide_index + 1, images=[])

        # 根据选择的来源处理图片生成
        if requirement.source == ImageSource.LOCAL and ImageSource.LOCAL in enabled_sources:
            local_images = await image_processor._process_local_images(
                requirement, request.project_topic, request.project_scenario,
                slide_content.get('title', ''), slide_content.get('title', '')
            )
            images_collection.images.extend(local_images)

        elif requirement.source == ImageSource.NETWORK and ImageSource.NETWORK in enabled_sources:
            network_images = await image_processor._process_network_images(
                requirement, request.project_topic, request.project_scenario,
                slide_content.get('title', ''), slide_content.get('title', ''), image_config
            )
            images_collection.images.extend(network_images)

        elif requirement.source == ImageSource.AI_GENERATED and ImageSource.AI_GENERATED in enabled_sources:
            ai_images = await image_processor._process_ai_generated_images(
                requirement=requirement,
                project_topic=request.project_topic,
                project_scenario=request.project_scenario,
                slide_title=slide_content.get('title', ''),
                slide_content=slide_content.get('title', ''),
                image_config=image_config,
                page_number=request.slide_index + 1,
                total_pages=1,
                template_html=slide_content.get('html_content', '')
            )
            images_collection.images.extend(ai_images)

        # 重新计算统计信息
        images_collection.__post_init__()

        if images_collection.total_count == 0:
            return {
                "success": False,
                "message": "未能生成任何图片，请检查配置和网络连接"
            }

        # 获取第一张生成的图像（用于替换）
        new_image = images_collection.images[0]
        new_image_url = new_image.absolute_url

        # 替换HTML中的图像
        updated_html = replace_image_in_html(
            slide_content.get('html_content', ''),
            image_info,
            new_image_url
        )

        logger.info(f"图片重新生成成功: {new_image.source.value}来源, URL: {new_image_url}")

        await consume_credits_for_operation(
            user.id,
            "ai_other",
            1,
            description="AI重新生成图片",
            reference_id="",
            provider_name=billing_provider_name,
        )

        return {
            "success": True,
            "message": f"图像重新生成成功（来源：{new_image.source.value}）",
            "new_image_url": new_image_url,
            "new_image_id": new_image.image_id,
            "updated_html_content": updated_html,
            "generation_prompt": getattr(new_image, 'generation_prompt', ''),
            "image_source": new_image.source.value,
            "ai_analysis": {
                "total_images_analyzed": 1,
                "reasoning": f"用户请求重新生成{image_context.get('image_purpose', '图像')}，选择{selected_source.value}来源",
                "enabled_sources": [source.value for source in enabled_sources],
                "selected_source": selected_source.value
            },
            "image_info": {
                "width": new_image.width,
                "height": new_image.height,
                "format": getattr(new_image, 'format', 'unknown'),
                "alt_text": new_image.alt_text,
                "title": new_image.title,
                "source": new_image.source.value,
                "purpose": new_image.purpose.value
            }
        }

    except Exception as e:
        logger.error(f"AI图像重新生成失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "message": f"图像重新生成失败: {str(e)}"
        }


@router.post("/api/ai/auto-generate-slide-images")
async def ai_auto_generate_slide_images(
    request: AIAutoImageGenerateRequest,
    user: User = Depends(get_current_user_required)
):
    """AI一键配图接口 - 自动分析幻灯片内容并生成相关配图"""
    try:
        # 获取图像服务和AI提供者
        from ...services.image.image_service import get_image_service

        image_service = get_image_service()
        if not image_service:
            return {
                "success": False,
                "message": "图像服务不可用"
            }

        # Use user-configured provider instead of default
        from ...services.db_config_service import get_user_ai_provider, get_user_ai_provider_config

        ai_provider_config = await get_user_ai_provider_config(user.id)
        billing_provider_name = ai_provider_config.get("provider_name")
        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_other", 1, provider_name=billing_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "message": f"积分不足，需要 {required} 积分，当前余额 {balance} 积分"
            }
        ai_provider = await get_user_ai_provider(user.id)
        if not ai_provider:
            return {
                "success": False,
                "message": "AI提供者不可用"
            }

        # 获取图像处理器
        from ...services.ppt_image_processor import PPTImageProcessor
        image_processor = PPTImageProcessor(image_service, ai_provider, user.id)

        slide_content = request.slide_content
        slide_title = slide_content.get('title', f'第{request.slide_index + 1}页')
        slide_html = slide_content.get('html_content', '')

        logger.info(f"开始为第{request.slide_index + 1}页进行一键配图")

        # 第一步：AI分析幻灯片内容，确定是否需要配图以及配图需求
        analysis_prompt = f"""作为专业的PPT设计师，请分析以下幻灯片内容，判断是否需要配图以及配图需求。

项目主题：{request.project_topic}
项目场景：{request.project_scenario}
幻灯片标题：{slide_title}
幻灯片HTML内容：{slide_html[:1000]}...

请分析：
1. 这个幻灯片是否需要配图？
2. 如果需要，应该配几张图？
3. 每张图的用途和描述是什么？
4. 图片应该插入到什么位置？

请以JSON格式回复：
{{
    "needs_images": true/false,
    "image_count": 数量,
    "images": [
        {{
            "purpose": "图片用途（如：主要插图、装饰图、背景图等）",
            "description": "图片内容描述",
            "keywords": "搜索关键词",
            "position": "插入位置（如：标题下方、内容中间、页面右侧等）"
        }}
    ],
    "reasoning": "分析理由"
}}"""

        analysis_response = await ai_provider.text_completion(
            prompt=analysis_prompt,
            temperature=0.3
        )

        # 解析AI分析结果
        import json
        try:
            analysis_result = json.loads(analysis_response.content.strip())
        except json.JSONDecodeError:
            # 如果JSON解析失败，使用默认配置
            analysis_result = {
                "needs_images": True,
                "image_count": 1,
                "images": [{
                    "purpose": "主要插图",
                    "description": f"与{slide_title}相关的配图",
                    "keywords": f"{request.project_topic} {slide_title}",
                    "position": "内容中间"
                }],
                "reasoning": "默认为幻灯片添加一张主要配图"
            }

        if not analysis_result.get("needs_images", False):
            await consume_credits_for_operation(
                user.id,
                "ai_other",
                1,
                description=f"AI一键配图(仅分析): 第{request.slide_index + 1}页 {slide_title}",
                reference_id="",
                provider_name=billing_provider_name,
            )
            return {
                "success": True,
                "message": "AI分析认为此幻灯片不需要配图",
                "updated_html_content": slide_html,
                "generated_images_count": 0,
                "ai_analysis": analysis_result
            }

        # 第二步：根据分析结果生成图片需求
        from ...services.models.slide_image_info import ImageRequirement, ImagePurpose, ImageSource, SlideImagesCollection

        images_collection = SlideImagesCollection(page_number=request.slide_index + 1, images=[])

        # 获取图像配置 - 从用户数据库配置读取（非环境变量）
        from ...services.db_config_service import get_db_config_service
        db_config_service = get_db_config_service()
        image_config = await db_config_service.get_config_by_category('image_service', user_id=user.id)

        # 检查是否启用图片生成服务
        enable_image_service = image_config.get('enable_image_service', False)
        if not enable_image_service:
            return {
                "success": False,
                "message": "图片生成服务未启用，请在配置中启用"
            }

        # 获取启用的图像来源（使用与重新生成图片相同的逻辑）
        from ...services.models.slide_image_info import ImageSource

        enabled_sources = []
        if image_config.get('enable_local_images', True):
            enabled_sources.append(ImageSource.LOCAL)
        if image_config.get('enable_network_search', False):
            enabled_sources.append(ImageSource.NETWORK)
        if image_config.get('enable_ai_generation', False):
            enabled_sources.append(ImageSource.AI_GENERATED)

        if not enabled_sources:
            return {
                "success": False,
                "message": "没有启用的图像来源，请在设置中配置图像获取方式"
            }

        # 使用与重新生成图片完全相同的图片来源选择逻辑
        image_context = {
            'image_purpose': 'illustration',  # 一键配图默认为说明性图片
            'slide_title': slide_title,
            'slide_content': slide_html
        }

        selected_source = select_best_image_source(enabled_sources, image_config, image_context)

        # 为每个图片需求生成图片
        for i, image_info in enumerate(analysis_result.get("images", [])[:3]):  # 最多3张图
            # 创建图片需求
            requirement = ImageRequirement(
                purpose=ImagePurpose.ILLUSTRATION,
                description=image_info.get("description", "相关配图"),
                priority=1,
                source=selected_source,
                count=1
            )

            # 根据选择的来源处理图片生成
            if requirement.source == ImageSource.AI_GENERATED and ImageSource.AI_GENERATED in enabled_sources:
                ai_images = await image_processor._process_ai_generated_images(
                    requirement=requirement,
                    project_topic=request.project_topic,
                    project_scenario=request.project_scenario,
                    slide_title=slide_title,
                    slide_content=slide_title,
                    image_config=image_config,
                    page_number=request.slide_index + 1,
                    total_pages=1,
                    template_html=slide_html
                )
                images_collection.images.extend(ai_images)

            elif requirement.source == ImageSource.NETWORK and ImageSource.NETWORK in enabled_sources:
                network_images = await image_processor._process_network_images(
                    requirement=requirement,
                    project_topic=request.project_topic,
                    project_scenario=request.project_scenario,
                    slide_title=slide_title,
                    slide_content=slide_title,
                    image_config=image_config
                )
                images_collection.images.extend(network_images)

            elif requirement.source == ImageSource.LOCAL and ImageSource.LOCAL in enabled_sources:
                local_images = await image_processor._process_local_images(
                    requirement=requirement,
                    project_topic=request.project_topic,
                    project_scenario=request.project_scenario,
                    slide_title=slide_title,
                    slide_content=slide_title
                )
                images_collection.images.extend(local_images)

        if not images_collection.images:
            return {
                "success": False,
                "message": "未能生成任何配图，请检查图像服务配置"
            }

        # 第三步：将生成的图片插入到幻灯片中
        updated_html = await image_processor._insert_images_into_slide(
            slide_html, images_collection, slide_title
        )

        logger.info(f"一键配图完成: 生成{len(images_collection.images)}张图片")

        await consume_credits_for_operation(
            user.id,
            "ai_other",
            1,
            description=f"AI一键配图: 第{request.slide_index + 1}页 {slide_title}",
            reference_id="",
            provider_name=billing_provider_name,
        )

        return {
            "success": True,
            "message": f"一键配图完成，已生成{len(images_collection.images)}张图片",
            "updated_html_content": updated_html,
            "generated_images_count": len(images_collection.images),
            "generated_images": [
                {
                    "image_id": img.image_id,
                    "url": img.absolute_url,
                    "description": img.content_description,
                    "source": img.source.value
                } for img in images_collection.images
            ],
            "ai_analysis": analysis_result
        }

    except Exception as e:
        logger.error(f"AI一键配图失败: {e}")
        return {
            "success": False,
            "message": f"一键配图失败: {str(e)}"
        }


@router.post("/api/ai/enhance-bullet-point")
async def ai_enhance_bullet_point(
    request: AIBulletPointEnhanceRequest,
    user: User = Depends(get_current_user_required)
):
    """AI增强要点接口"""
    try:
        # 获取AI提供者
        user_ppt_service = get_ppt_service_for_user(user.id)
        provider, settings = await user_ppt_service.get_role_provider_async("outline")
        enhance_provider_name = settings.get("provider")

        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_edit", 1, provider_name=enhance_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "error": f"积分不足，需要 {required} 积分，当前余额 {balance} 积分"
            }

        # 构建上下文信息
        context_info = ""
        if request.contextInfo:
            original_point = request.contextInfo.get('originalBulletPoint', '')
            other_points = request.contextInfo.get('otherBulletPoints', [])
            point_index = request.contextInfo.get('pointIndex', 0)

            context_info = f"""
当前要点上下文信息：
- 要点位置：第{point_index + 1}个要点
- 原始要点内容：{original_point}
- 同页面其他要点：{', '.join(other_points) if other_points else '无'}
"""

        # 构建大纲信息
        outline_info = ""
        if request.slideOutline:
            outline_info = f"""
当前幻灯片大纲信息：
- 幻灯片类型：{request.slideOutline.get('slide_type', '未知')}
- 描述：{request.slideOutline.get('description', '无')}
- 所有要点：{', '.join(request.slideOutline.get('content_points', [])) if request.slideOutline.get('content_points') else '无'}
"""

        # 构建AI增强提示词
        context = f"""
你是一位专业的PPT内容编辑专家。用户需要你增强和优化一个PPT要点的内容。

项目信息：
- 项目标题：{request.projectInfo.get('title', '未知')}
- 项目主题：{request.projectInfo.get('topic', '未知')}
- 应用场景：{request.projectInfo.get('scenario', '未知')}

幻灯片信息：
- 幻灯片标题：{request.slideTitle}
- 幻灯片位置：第{request.slideIndex}页

{outline_info}

{context_info}

用户请求：{request.userRequest}

请根据以上信息，对要点进行增强和优化。要求：

1. **保持核心意思不变**：不要改变要点的基本含义和方向
2. **增加具体细节**：添加更多具体的描述、数据、例子或说明
3. **提升表达质量**：使用更专业、更有吸引力的表达方式
4. **保持简洁性**：虽然要增强内容，但仍要保持要点的简洁特性，不要过于冗长
5. **与其他要点协调**：确保增强后的要点与同页面其他要点在风格和层次上保持一致
6. **符合场景需求**：根据应用场景调整语言风格和专业程度

请直接返回增强后的要点内容，不需要额外的解释或格式化。
"""

        # 调用AI生成增强内容（自动应用用户配置的 temperature / top_p）
        response = await user_ppt_service._text_completion_for_role("outline", prompt=context)

        enhanced_text = response.content.strip()

        # 简单的内容验证
        if not enhanced_text or len(enhanced_text) < 5:
            raise ValueError("AI生成的增强内容过短或为空")

        await consume_credits_for_operation(
            user.id,
            "ai_edit",
            1,
            description=f"AI要点增强: 第{request.slideIndex}页 {request.slideTitle}",
            reference_id=str(request.projectInfo.get("project_id") or request.projectInfo.get("id") or ""),
            provider_name=enhance_provider_name,
        )

        return {
            "success": True,
            "enhancedText": enhanced_text,
            "originalText": request.contextInfo.get('originalBulletPoint', '') if request.contextInfo else ""
        }

    except Exception as e:
        logger.error(f"AI要点增强请求失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "抱歉，AI要点增强服务暂时不可用。请稍后重试。"
        }


@router.post("/api/ai/enhance-all-bullet-points")
async def ai_enhance_all_bullet_points(
    request: AIBulletPointEnhanceRequest,
    user: User = Depends(get_current_user_required)
):
    """AI增强所有要点接口"""
    try:
        # 获取AI提供者
        user_ppt_service = get_ppt_service_for_user(user.id)
        provider, settings = await user_ppt_service.get_role_provider_async("outline")
        enhance_all_provider_name = settings.get("provider")

        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_edit", 1, provider_name=enhance_all_provider_name
        )
        if not has_credits:
            return {
                "success": False,
                "error": f"积分不足，需要 {required} 积分，当前余额 {balance} 积分"
            }

        # 构建上下文信息
        context_info = ""
        all_points = []
        if request.contextInfo:
            all_points = request.contextInfo.get('allBulletPoints', [])
            total_points = request.contextInfo.get('totalPoints', 0)

            context_info = f"""
当前要点上下文信息：
- 要点总数：{total_points}个
- 所有要点内容：
"""
            for i, point in enumerate(all_points, 1):
                context_info += f"  {i}. {point}\n"

        # 构建大纲信息
        outline_info = ""
        if request.slideOutline:
            outline_info = f"""
当前幻灯片大纲信息：
- 幻灯片类型：{request.slideOutline.get('slide_type', '未知')}
- 描述：{request.slideOutline.get('description', '无')}
"""

        # 构建AI增强提示词
        context = f"""
请对以下PPT要点进行增强和优化。

项目背景：
- 项目：{request.projectInfo.get('title', '未知')}
- 主题：{request.projectInfo.get('topic', '未知')}
- 场景：{request.projectInfo.get('scenario', '未知')}
- 幻灯片：{request.slideTitle}（第{request.slideIndex}页）

{outline_info}

{context_info}

增强要求：
1. 保持每个要点的核心意思不变
2. 添加具体细节、数据或例子
3. 使用更专业、准确的表达
4. 保持简洁，避免冗长
5. 确保要点间逻辑连贯、风格统一
6. 符合{request.projectInfo.get('scenario', '商务')}场景的专业要求

重要：请直接返回增强后的要点列表，每行一个要点，不要包含任何解释、开场白或格式说明。不要添加编号、符号或其他标记。

示例格式：
第一个增强后的要点内容
第二个增强后的要点内容
第三个增强后的要点内容
"""

        # 调用AI生成增强内容（自动应用用户配置的 temperature / top_p）
        response = await user_ppt_service._text_completion_for_role("outline", prompt=context)

        enhanced_content = response.content.strip()

        # 解析增强后的要点 - 改进的过滤逻辑
        enhanced_points = []
        if enhanced_content:
            # 按行分割，过滤空行
            lines = [line.strip() for line in enhanced_content.split('\n') if line.strip()]

            # 过滤掉常见的无关内容
            filtered_lines = []
            skip_patterns = [
                '好的', '作为', '我将', '我会', '以下是', '根据', '请注意', '需要说明',
                '增强后的要点', '优化后的', '改进后的', '以上', '总结', '希望',
                '如有', '如果', '建议', '推荐', '注意', '提醒', '说明',
                '要点1', '要点2', '要点3', '要点4', '要点5',
                '第一', '第二', '第三', '第四', '第五', '第六', '第七', '第八', '第九', '第十',
                '1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.', '10.',
                '•', '·', '-', '*', '→', '▪', '▫'
            ]

            for line in lines:
                # 跳过过短的行（可能是格式标记）
                if len(line) < 5:
                    continue

                # 跳过包含常见开场白模式的行
                should_skip = False
                for pattern in skip_patterns:
                    if line.startswith(pattern) or (pattern in ['好的', '作为', '我将', '我会'] and pattern in line[:10]):
                        should_skip = True
                        break

                # 跳过纯数字或符号开头的行（可能是编号）
                if line[0].isdigit() or line[0] in ['•', '·', '-', '*', '→', '▪', '▫']:
                    # 但保留去掉编号后的内容
                    cleaned_line = line
                    # 移除开头的编号和符号
                    import re
                    cleaned_line = re.sub(r'^[\d\s\.\-\*\•\·\→\▪\▫]+', '', cleaned_line).strip()
                    if len(cleaned_line) >= 5:
                        filtered_lines.append(cleaned_line)
                    continue

                if not should_skip:
                    filtered_lines.append(line)

            enhanced_points = filtered_lines

        # 简单的内容验证
        if not enhanced_points or len(enhanced_points) == 0:
            raise ValueError("AI生成的增强内容为空或被过滤")

        await consume_credits_for_operation(
            user.id,
            "ai_edit",
            1,
            description=f"AI要点增强(全量): 第{request.slideIndex}页 {request.slideTitle}",
            reference_id=str(request.projectInfo.get("project_id") or request.projectInfo.get("id") or ""),
            provider_name=enhance_all_provider_name,
        )

        return {
            "success": True,
            "enhancedPoints": enhanced_points,
            "originalPoints": all_points,
            "totalEnhanced": len(enhanced_points)
        }

    except Exception as e:
        logger.error(f"AI增强所有要点请求失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "抱歉，AI要点增强服务暂时不可用。请稍后重试。"
        }


async def analyze_image_context(image_info: Dict[str, Any], slide_content: Dict[str, Any],
                               project_topic: str, project_scenario: str) -> Dict[str, Any]:
    """分析图像在幻灯片中的上下文"""
    return {
        "slide_title": slide_content.get("title", ""),
        "slide_content": slide_content.get("html_content", ""),
        "image_alt": image_info.get("alt", ""),
        "image_title": image_info.get("title", ""),
        "image_size": f"{image_info.get('width', 0)}x{image_info.get('height', 0)}",
        "image_position": image_info.get("position", {}),
        "project_topic": project_topic,
        "project_scenario": project_scenario,
        "image_purpose": determine_image_purpose(image_info, slide_content)
    }


def determine_image_purpose(image_info: Dict[str, Any], slide_content: Dict[str, Any]) -> str:
    """确定图像在幻灯片中的用途"""
    # 简单的启发式规则来确定图像用途
    width = image_info.get('width', 0)
    height = image_info.get('height', 0)
    alt_text = image_info.get('alt', '').lower()

    if width > 800 or height > 600:
        return "background"  # 大图像可能是背景
    elif 'icon' in alt_text or 'logo' in alt_text:
        return "icon"
    elif 'chart' in alt_text or 'graph' in alt_text:
        return "chart_support"
    elif width < 200 and height < 200:
        return "decoration"
    else:
        return "illustration"


def select_best_image_source(enabled_sources: List, image_config: Dict[str, Any], image_context: Dict[str, Any]):
    """智能选择最佳的图片来源"""
    from ...services.models.slide_image_info import ImageSource

    # 如果只有一个启用的来源，直接使用
    if len(enabled_sources) == 1:
        return enabled_sources[0]

    # 根据图像用途和配置智能选择
    image_purpose = image_context.get('image_purpose', 'illustration')

    # 优先级规则
    if image_purpose == 'background':
        # 背景图优先使用AI生成，其次网络搜索
        if ImageSource.AI_GENERATED in enabled_sources:
            return ImageSource.AI_GENERATED
        elif ImageSource.NETWORK in enabled_sources:
            return ImageSource.NETWORK
        elif ImageSource.LOCAL in enabled_sources:
            return ImageSource.LOCAL

    elif image_purpose == 'icon':
        # 图标优先使用本地，其次AI生成
        if ImageSource.LOCAL in enabled_sources:
            return ImageSource.LOCAL
        elif ImageSource.AI_GENERATED in enabled_sources:
            return ImageSource.AI_GENERATED
        elif ImageSource.NETWORK in enabled_sources:
            return ImageSource.NETWORK

    elif image_purpose in ['illustration', 'chart_support', 'decoration']:
        # 说明性图片优先使用网络搜索，其次AI生成
        if ImageSource.NETWORK in enabled_sources:
            return ImageSource.NETWORK
        elif ImageSource.AI_GENERATED in enabled_sources:
            return ImageSource.AI_GENERATED
        elif ImageSource.LOCAL in enabled_sources:
            return ImageSource.LOCAL

    # 默认优先级：AI生成 > 网络搜索 > 本地
    for source in [ImageSource.AI_GENERATED, ImageSource.NETWORK, ImageSource.LOCAL]:
        if source in enabled_sources:
            return source

    # 如果都没有，返回第一个可用的
    return enabled_sources[0] if enabled_sources else ImageSource.AI_GENERATED


def replace_image_in_html(html_content: str, image_info: Dict[str, Any], new_image_url: str) -> str:
    """在HTML内容中替换指定的图像，支持img标签、背景图像和SVG，保持布局和样式"""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, 'html.parser')

        old_src = image_info.get('src', '')
        image_type = image_info.get('type', 'img')

        if not old_src:
            logger.warning("图像信息中没有src属性，无法替换")
            return html_content

        replacement_success = False

        if image_type == 'img':
            # 处理 <img> 标签
            replacement_success = replace_img_tag(soup, image_info, new_image_url, old_src)

        elif image_type == 'background':
            # 处理背景图像
            replacement_success = replace_background_image(soup, image_info, new_image_url, old_src)

        elif image_type == 'svg':
            # 处理SVG图像
            replacement_success = replace_svg_image(soup, image_info, new_image_url, old_src)

        if replacement_success:
            logger.info(f"成功替换{image_type}图像: {old_src} -> {new_image_url}")
            return str(soup)
        else:
            logger.warning(f"未找到匹配的{image_type}图像进行替换")
            return fallback_string_replacement(html_content, old_src, new_image_url)

    except Exception as e:
        logger.error(f"替换HTML中的图像失败: {e}")
        return fallback_string_replacement(html_content, image_info.get('src', ''), new_image_url)


def replace_img_tag(soup, image_info: Dict[str, Any], new_image_url: str, old_src: str) -> bool:
    """替换img标签"""
    img_elements = soup.find_all('img')

    for img in img_elements:
        img_src = img.get('src', '')

        # 比较图像源URL（处理相对路径和绝对路径）
        if (img_src == old_src or
            img_src.endswith(old_src.split('/')[-1]) or
            old_src.endswith(img_src.split('/')[-1])):

            # 替换图像URL
            img['src'] = new_image_url

            # 保持原有的重要属性
            preserved_attributes = ['class', 'style', 'width', 'height', 'id']
            for attr in preserved_attributes:
                if attr in image_info and image_info[attr]:
                    img[attr] = image_info[attr]

            # 更新或保持alt和title
            if image_info.get('alt'):
                img['alt'] = image_info['alt']
            if image_info.get('title'):
                img['title'] = image_info['title']

            # 确保图像加载错误时有后备处理
            if not img.get('onerror'):
                img['onerror'] = "this.style.display='none'"

            return True

    return False


def replace_background_image(soup, image_info: Dict[str, Any], new_image_url: str, old_src: str) -> bool:
    """替换CSS背景图像"""
    # 查找所有元素
    all_elements = soup.find_all()

    for element in all_elements:
        # 检查内联样式中的背景图像
        style = element.get('style', '')
        if 'background-image' in style and old_src in style:
            # 替换内联样式中的背景图像URL
            new_style = style.replace(old_src, new_image_url)
            element['style'] = new_style
            return True

        # 检查class属性，可能对应CSS规则中的背景图像
        class_names = element.get('class', [])
        if class_names and image_info.get('className'):
            # 如果class匹配，我们假设这是目标元素
            if any(cls in image_info.get('className', '') for cls in class_names):
                # 为元素添加内联背景图像样式
                current_style = element.get('style', '')
                if current_style and not current_style.endswith(';'):
                    current_style += ';'
                new_style = f"{current_style}background-image: url('{new_image_url}');"
                element['style'] = new_style
                return True

    return False


def replace_svg_image(soup, image_info: Dict[str, Any], new_image_url: str, old_src: str) -> bool:
    """替换SVG图像"""
    # 查找SVG元素
    svg_elements = soup.find_all('svg')

    for svg in svg_elements:
        # 如果SVG有src属性（虽然不常见）
        if svg.get('src') == old_src:
            svg['src'] = new_image_url
            return True

        # 检查SVG的内容或其他标识
        if image_info.get('outerHTML') and svg.get_text() in image_info.get('outerHTML', ''):
            # 对于内联SVG，我们可能需要替换整个元素
            # 这里简化处理，添加一个data属性来标记已替换
            svg['data-replaced-image'] = new_image_url
            return True

    return False


def fallback_string_replacement(html_content: str, old_src: str, new_image_url: str) -> str:
    """后备的字符串替换方案"""
    try:
        import re

        if old_src and old_src in html_content:
            # 尝试多种替换模式
            patterns = [
                # img标签的src属性
                (rf'(<img[^>]*src=")[^"]*({re.escape(old_src)}[^"]*")([^>]*>)', rf'\1{new_image_url}\3'),
                # CSS背景图像
                (rf'(background-image:\s*url\([\'"]?)[^\'")]*({re.escape(old_src)}[^\'")]*)', rf'\1{new_image_url}'),
                # 直接字符串替换
                (re.escape(old_src), new_image_url)
            ]

            for pattern, replacement in patterns:
                updated_html = re.sub(pattern, replacement, html_content, flags=re.IGNORECASE)
                if updated_html != html_content:
                    logger.info(f"使用后备方案成功替换图像: {old_src} -> {new_image_url}")
                    return updated_html

        return html_content

    except Exception as e:
        logger.error(f"后备替换方案也失败: {e}")
        return html_content
