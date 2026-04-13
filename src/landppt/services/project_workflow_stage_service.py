import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..api.models import (
    PPTGenerationRequest,
    PPTOutline,
    EnhancedPPTOutline,
    SlideContent,
    PPTProject,
    TodoBoard,
    FileOutlineGenerationResponse,
)
from ..ai import get_ai_provider, get_role_provider, AIMessage, MessageRole
from ..ai.base import TextContent, ImageContent
from ..core.config import ai_config, app_config
from .runtime.ai_execution import ExecutionContext
from .prompts import prompts_manager
from .research.enhanced_research_service import EnhancedResearchService
from .research.enhanced_report_generator import EnhancedReportGenerator
from .pyppeteer_pdf_converter import get_pdf_converter
from .image.image_service import ImageService
from .image.adapters.ppt_prompt_adapter import PPTSlideContext
from ..utils.thread_pool import run_blocking_io, to_thread


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .outline.project_outline_workflow_service import ProjectOutlineWorkflowService


class ProjectWorkflowStageService:
    """Workflow/todo orchestration extracted from ProjectOutlineWorkflowService."""

    def __init__(self, service: "ProjectOutlineWorkflowService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    async def create_project_with_workflow(self, request: PPTGenerationRequest) -> PPTProject:
            """Create a new project with complete TODO workflow"""
            try:
                # Create project with TODO board
                project = await self.project_manager.create_project(request)

                # Start the workflow
                await self._execute_project_workflow(project.project_id, request)

                return project

            except Exception as e:
                logger.error(f"Error creating project with workflow: {str(e)}")
                raise

    async def _execute_project_workflow(self, project_id: str, request: PPTGenerationRequest, user_id: Optional[int] = None):
            """Execute the complete project workflow with sequential subtask processing.
            
            Args:
                project_id: The project ID
                request: The PPT generation request (request.user_id is used if user_id not provided)
                user_id: Optional explicit user_id for async context preservation
            """
            ctx_token = None
            try:
                # Use explicit user_id or fall back to request.user_id
                effective_user_id = user_id or request.user_id

                # Background tasks run outside the request middleware, so ContextVar current_user_id may be unset.
                # Set it here so DB-backed per-user configs (e.g. MinerU keys) can be resolved reliably.
                try:
                    from ..auth.request_context import current_user_id

                    if effective_user_id is not None:
                        current = current_user_id.get()
                        if current != effective_user_id:
                            ctx_token = current_user_id.set(effective_user_id)
                except Exception:
                    ctx_token = None
                 
                # Get project to check if requirements are confirmed
                project = await self.project_manager.get_project(project_id, user_id=effective_user_id)
                if not project:
                    raise ValueError("Project not found")

                # Only execute if requirements are confirmed
                if not project.confirmed_requirements:
                    logger.info(f"Project {project_id} workflow waiting for requirements confirmation")
                    return

                # Get TODO board to access stages and subtasks
                todo_board = await self.project_manager.get_todo_board(project_id)
                if not todo_board:
                    raise ValueError("TODO board not found for project")

                # Process each stage sequentially (skip requirements confirmation stage)
                for stage_index, stage in enumerate(todo_board.stages):
                    # Skip requirements confirmation stage as it's already done
                    if stage.id == "requirements_confirmation":
                        continue

                    logger.info(f"Starting stage {stage_index + 1}: {stage.name}")

                    # Mark stage as running
                    await self.project_manager.update_stage_status(
                        project_id, stage.id, "running", 0.0
                    )

                    # Execute the complete stage as a single task
                    try:
                        stage_result = await self._execute_complete_stage(project_id, stage.id, request)
                    except Exception as e:
                        logger.error(f"Error executing stage '{stage.name}': {str(e)}")
                        # Mark stage as failed but continue with next stage
                        await self.project_manager.update_stage_status(
                            project_id, stage.id, "failed", 0.0, {"error": str(e)}
                        )
                        continue
                    # Wrap string result in dictionary for proper serialization
                    result_dict = {"message": stage_result} if isinstance(stage_result, str) else stage_result
                    await self.project_manager.update_stage_status(
                        project_id, stage.id, "completed", 100.0, result_dict
                    )

                    logger.info(f"Completed stage: {stage.name}")

                # Mark project as completed
                await self.project_manager.update_project_status(project_id, "completed")
                logger.info(f"Project workflow completed: {project_id}")

            except Exception as e:
                logger.error(f"Error in project workflow: {str(e)}")
                # Mark current stage as failed
                todo_board = await self.project_manager.get_todo_board(project_id)
                if todo_board and todo_board.current_stage_index < len(todo_board.stages):
                    current_stage = todo_board.stages[todo_board.current_stage_index]
                    await self.project_manager.update_stage_status(
                        project_id, current_stage.id, "failed", 0.0,
                        {"error": str(e)}
                    )
            finally:
                if ctx_token is not None:
                    try:
                        from ..auth.request_context import current_user_id

                        current_user_id.reset(ctx_token)
                    except Exception:
                        pass

    async def _execute_complete_stage(self, project_id: str, stage_id: str, request: PPTGenerationRequest):
            """Execute a complete stage as a single task"""
            try:
                logger.info(f"Executing complete stage: {stage_id}")

                # Get project and confirmed requirements
                project = await self.project_manager.get_project(project_id)
                if not project or not project.confirmed_requirements:
                    raise ValueError("Project or confirmed requirements not found")

                confirmed_requirements = project.confirmed_requirements

                # Execute based on stage type
                if stage_id == "outline_generation":
                    return await self._execute_outline_generation(project_id, confirmed_requirements, self._load_prompts_md_system_prompt())
                elif stage_id == "ppt_creation":
                    return await self._execute_ppt_creation(project_id, confirmed_requirements, self._load_prompts_md_system_prompt())
                else:
                    # Fallback for other stages
                    return await self._execute_general_stage(project_id, stage_id, confirmed_requirements)

            except Exception as e:
                logger.error(f"Error executing complete stage '{stage_id}': {str(e)}")
                raise

    async def _execute_general_stage(self, project_id: str, stage_id: str, confirmed_requirements: Dict[str, Any]):
            """Execute a general stage task"""
            try:
                system_prompt = self._load_prompts_md_system_prompt()

                context = f"""
    项目信息：
    - 主题：{confirmed_requirements['topic']}
    - 类型：{confirmed_requirements['type']}
    - 其他说明：{confirmed_requirements.get('description', '无')}

    当前阶段：{stage_id}

    请根据以上信息完成当前阶段的任务。
    """

                response = await self._text_completion_for_role("default",
                    prompt=context,
                    system_prompt=system_prompt,
                    temperature=ai_config.temperature
                )

                return {"message": response.content}

            except Exception as e:
                logger.error(f"Error executing general stage '{stage_id}': {str(e)}")
                raise

    async def _complete_stage(self, project_id: str, stage_id: str,
                                request: PPTGenerationRequest) -> Dict[str, Any]:
            """Complete a stage and return its result"""
            try:
                if stage_id == "outline_generation":
                    outline = await self.generate_outline(request)
                    return {"outline": outline.dict()}

                elif stage_id == "theme_design":
                    theme_config = await self._design_theme(request.scenario, request.language)
                    return {"theme_config": theme_config}

                elif stage_id == "content_generation":
                    # Get outline from previous stage
                    project = await self.project_manager.get_project(project_id)
                    if project and project.outline:
                        enhanced_slides = await self._generate_enhanced_content(project.outline, request)
                        return {"enhanced_slides": [slide.dict() for slide in enhanced_slides]}
                    else:
                        # Fallback: generate basic outline first
                        outline = await self.generate_outline(request)
                        enhanced_slides = await self._generate_enhanced_content(outline, request)
                        return {"enhanced_slides": [slide.dict() for slide in enhanced_slides]}

                elif stage_id == "layout_verification":
                    # Get slides from previous stage
                    todo_board = await self.project_manager.get_todo_board(project_id)
                    if todo_board:
                        for stage in todo_board.stages:
                            if stage.id == "content_generation" and stage.result:
                                slides_data = stage.result.get("enhanced_slides", [])
                                slides = [SlideContent(**slide_data) for slide_data in slides_data]
                                theme_config = {}
                                for s in todo_board.stages:
                                    if s.id == "theme_design" and s.result:
                                        theme_config = s.result.get("theme_config", {})
                                        break
                                verified_slides = await self._verify_layout(slides, theme_config)
                                return {"verified_slides": [slide.dict() for slide in verified_slides]}
                    return {"verified_slides": []}

                elif stage_id == "export_output":
                    # Get verified slides and generate HTML
                    todo_board = await self.project_manager.get_todo_board(project_id)
                    if todo_board:
                        slides_data = []
                        theme_config = {}

                        for stage in todo_board.stages:
                            if stage.id == "layout_verification" and stage.result:
                                slides_data = stage.result.get("verified_slides", [])
                            elif stage.id == "theme_design" and stage.result:
                                theme_config = stage.result.get("theme_config", {})

                        if slides_data:
                            slides = [SlideContent(**slide_data) for slide_data in slides_data]
                            html_content = await self._generate_html_output(slides, theme_config)

                            # Update project with final results
                            project = await self.project_manager.get_project(project_id)
                            if project:
                                project.slides_html = html_content

                                # Save version
                                await self.project_manager.save_project_version(
                                    project_id,
                                    {
                                        "slides_html": html_content,
                                        "theme_config": theme_config
                                    }
                                )

                            return {"html_content": html_content}

                    return {"html_content": ""}

                else:
                    return {"message": f"Stage {stage_id} completed"}

            except Exception as e:
                logger.error(f"Error completing stage '{stage_id}': {str(e)}")
                return {"error": str(e)}

    async def update_project_outline(self, project_id: str, outline_content: str) -> bool:
            """更新项目大纲内容，统一走标准化解析入口。"""
            try:
                project = await self.project_manager.get_project(project_id)
                if not project:
                    return False

                import json

                # 统一通过解析器处理，兼容 fenced JSON、轻微脏 JSON 和字段别名。
                structured_outline = self._parse_outline_content(outline_content, project)
                formatted_json = json.dumps(structured_outline, ensure_ascii=False, indent=2)

                # Update outline in the correct field
                if not project.outline:
                    project.outline = {}
                project.outline["content"] = formatted_json  # Store formatted JSON
                project.outline["title"] = structured_outline.get("title", project.topic)
                project.outline["slides"] = structured_outline.get("slides", [])
                project.outline["updated_at"] = time.time()

                # 保存更新的大纲到数据库
                try:
                    from .db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()
                    save_success = await db_manager.save_project_outline(project_id, project.outline)

                    if save_success:
                        logger.info(f"✅ Successfully saved updated outline to database for project {project_id}")
                    else:
                        logger.error(f"❌ Failed to save updated outline to database for project {project_id}")

                except Exception as save_error:
                    logger.error(f"❌ Exception while saving updated outline to database: {str(save_error)}")

                # Update TODO board stage result
                if project.todo_board:
                    for stage in project.todo_board.stages:
                        if stage.id == "outline_generation":
                            if not stage.result:
                                stage.result = {}
                            stage.result["outline_content"] = formatted_json
                            break

                return True

            except Exception as e:
                logger.error(f"Error updating project outline: {str(e)}")
                return False

    async def confirm_project_outline(self, project_id: str) -> bool:
            """Confirm project outline and enable PPT generation"""
            try:
                project = await self.project_manager.get_project(project_id)
                if not project:
                    return False

                # 确保大纲数据存在
                if not project.outline:
                    logger.error(f"No outline found for project {project_id}")
                    return False

                # 检查大纲是否包含slides数据
                if not project.outline.get('slides'):
                    logger.error(f"No slides found in outline for project {project_id}")

                    # 首先尝试从confirmed_requirements中的file_generated_outline恢复
                    if (project.confirmed_requirements and
                        project.confirmed_requirements.get('file_generated_outline') and
                        isinstance(project.confirmed_requirements['file_generated_outline'], dict)):

                        file_outline = project.confirmed_requirements['file_generated_outline']
                        if file_outline.get('slides'):
                            logger.info(f"Restoring outline from file_generated_outline with {len(file_outline['slides'])} slides")
                            # 恢复完整的大纲数据，保留确认状态
                            project.outline = file_outline.copy()
                            project.outline["confirmed"] = True
                            project.outline["confirmed_at"] = time.time()
                        else:
                            logger.error(f"file_generated_outline does not contain slides data")
                            return False
                    else:
                        # 尝试从数据库重新加载大纲
                        try:
                            from .db_project_manager import DatabaseProjectManager
                            db_manager = DatabaseProjectManager()
                            db_project = await db_manager.get_project(project_id)
                            if db_project and db_project.outline and db_project.outline.get('slides'):
                                project.outline = db_project.outline
                                logger.info(f"Reloaded outline from database for project {project_id}")
                            else:
                                logger.error(f"No valid outline found in database for project {project_id}")
                                return False
                        except Exception as reload_error:
                            logger.error(f"Failed to reload outline from database: {reload_error}")
                            return False

                # 保留原有的大纲数据，只添加确认状态
                project.outline["confirmed"] = True
                project.outline["confirmed_at"] = time.time()

                # 保存确认状态到数据库
                try:
                    from .db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()
                    save_success = await db_manager.save_project_outline(project_id, project.outline)

                    if save_success:
                        logger.info(f"✅ Successfully saved outline confirmation to database for project {project_id}")
                    else:
                        logger.error(f"❌ Failed to save outline confirmation to database for project {project_id}")

                except Exception as save_error:
                    logger.error(f"❌ Exception while saving outline confirmation to database: {save_error}")

                # Update TODO board - mark outline as confirmed and enable PPT creation
                if project.todo_board:
                    for stage in project.todo_board.stages:
                        if stage.id == "outline_generation":
                            stage.status = "completed"
                            if not stage.result:
                                stage.result = {}
                            stage.result["confirmed"] = True
                        elif stage.id == "ppt_creation":
                            stage.status = "pending"  # Enable PPT creation
                            break

                # Update project manager
                await self.project_manager.update_stage_status(
                    project_id, "outline_generation", "completed",
                    progress=100.0, result={"confirmed": True}
                )

                return True

            except Exception as e:
                logger.error(f"Error confirming project outline: {e}")
                return False

    def _get_default_suggestions(self, project: PPTProject) -> Dict[str, Any]:
            """Get default suggestions when AI generation fails"""
            # Generate basic suggestions based on project scenario
            scenario_types = {
                "general": ["通用展示", "综合介绍", "概述报告", "基础展示"],
                "tourism": ["旅游推介", "景点介绍", "文化展示", "旅行规划"],
                "education": ["教学课件", "学术报告", "知识分享", "培训材料"],
                "analysis": ["数据分析", "研究报告", "分析总结", "调研展示"],
                "history": ["历史回顾", "文化传承", "时代变迁", "历史教育"],
                "technology": ["技术分享", "产品介绍", "创新展示", "技术方案"],
                "business": ["商业计划", "项目汇报", "业务介绍", "企业展示"]
            }

            # Get type options based on scenario
            type_options = scenario_types.get(project.scenario, scenario_types["general"])

            # Generate suggested topic based on original topic
            suggested_topic = f"{project.topic} - 专业展示"

            return {
                "suggested_topic": suggested_topic,
                "type_options": type_options
            }

    def _get_default_todo_structure(self, confirmed_requirements: Dict[str, Any]) -> Dict[str, Any]:
            """Get default TODO structure based on confirmed requirements"""
            return {
                "stages": [
                    {
                        "id": "outline_generation",
                        "name": "生成PPT大纲",
                        "description": "设计PPT整体结构与框架，规划各章节内容与关键点，确定核心优势和创新点的展示方式",
                        "subtasks": ["生成PPT大纲"]  # Single task, description is explanatory
                    },
                    {
                        "id": "ppt_creation",
                        "name": "制作PPT",
                        "description": "设计PPT封面与导航页，根据大纲制作各章节内容页面，添加视觉元素和图表美化PPT",
                        "subtasks": ["制作PPT"]  # Single task, description is explanatory
                    }
                ]
            }

    async def _update_project_todo_board(self, project_id: str, todo_data: Dict[str, Any],
                                           confirmed_requirements: Dict[str, Any]):
            """Update project TODO board with custom stages (including requirements confirmation)"""
            try:
                from ..api.models import TodoStage, TodoBoard
                import time

                # Create complete stages including requirements confirmation
                stages = [
                    TodoStage(
                        id="requirements_confirmation",
                        name="需求确认",
                        description="AI根据用户设定的场景和上传的文件内容提供补充信息用来确认用户的任务需求",
                        status="completed",  # This stage is completed when requirements are confirmed
                        progress=100.0,
                        subtasks=["需求确认完成"]
                    )
                ]

                # Add custom stages from AI generation
                for stage_data in todo_data.get("stages", []):
                    stage = TodoStage(
                        id=stage_data["id"],
                        name=stage_data["name"],
                        description=stage_data["description"],
                        subtasks=stage_data["subtasks"],
                        status="pending",  # Start as pending
                        progress=0.0
                    )
                    stages.append(stage)

                # Create custom TODO board
                todo_board = TodoBoard(
                    task_id=project_id,
                    title=confirmed_requirements['topic'],
                    stages=stages
                )

                # Calculate correct overall progress
                todo_board.overall_progress = self.project_manager.calculate_overall_progress(stages)

                # Set current stage index to the first non-completed stage
                todo_board.current_stage_index = 0
                for i, stage in enumerate(stages):
                    if stage.status != "completed":
                        todo_board.current_stage_index = i
                        break

                # Update project manager
                self.project_manager.todo_boards[project_id] = todo_board

                # Update project with confirmed requirements
                project = await self.project_manager.get_project(project_id)
                if project:
                    project.topic = confirmed_requirements['topic']
                    project.requirements = f"""
    类型：{confirmed_requirements['type']}
    其他说明：{confirmed_requirements.get('description', '无')}
    """
                    project.updated_at = time.time()

            except Exception as e:
                logger.error(f"Error updating project TODO board: {e}")
                raise

    async def confirm_requirements_and_update_workflow(self, project_id: str, confirmed_requirements: Dict[str, Any]) -> bool:
            """Confirm requirements and update the TODO board with complete workflow"""
            try:
                project = await self.project_manager.get_project(project_id)
                if not project:
                    return False

                # Store confirmed requirements
                project.confirmed_requirements = confirmed_requirements
                project.status = "in_progress"
                project.updated_at = time.time()

                # 如果有文件生成的大纲，直接设置到项目的outline字段中
                file_generated_outline = confirmed_requirements.get('file_generated_outline')
                if file_generated_outline and isinstance(file_generated_outline, dict):
                    logger.info(f"Setting file-generated outline to project {project_id}")
                    project.outline = file_generated_outline
                    project.updated_at = time.time()

                # Save confirmed requirements to database
                try:
                    from .db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()

                    # Update project status
                    await db_manager.update_project_status(project_id, "in_progress")
                    logger.info(f"Successfully updated project status in database for project {project_id}")

                    # Save confirmed requirements to database
                    await db_manager.save_confirmed_requirements(project_id, confirmed_requirements)
                    logger.info(f"Successfully saved confirmed requirements to database for project {project_id}")

                    # 如果有文件生成的大纲，也保存到数据库
                    if file_generated_outline:
                        save_success = await db_manager.save_project_outline(project_id, file_generated_outline)
                        if save_success:
                            logger.info(f"✅ Successfully saved file-generated outline to database for project {project_id}")
                        else:
                            logger.error(f"❌ Failed to save file-generated outline to database for project {project_id}")

                    # Update requirements confirmation stage to completed
                    await db_manager.update_stage_status(
                        project_id,
                        "requirements_confirmation",
                        "completed",
                        100.0,
                        {"confirmed_at": time.time(), "requirements": confirmed_requirements}
                    )
                    logger.info(f"Successfully updated requirements confirmation stage to completed for project {project_id}")

                except Exception as save_error:
                    logger.error(f"Failed to update project status or save requirements in database: {save_error}")
                    import traceback
                    traceback.print_exc()

                # Update TODO board with default workflow (无需AI生成) - 修复：添加await
                success = await self.project_manager.update_todo_board_with_confirmed_requirements(
                    project_id, confirmed_requirements
                )

                # 不再启动后台工作流，让前端直接控制大纲生成
                return success

            except Exception as e:
                logger.error(f"Error confirming requirements: {e}")
                return False

    async def get_project_todo_board(self, project_id: str, user_id: Optional[int] = None) -> Optional[TodoBoard]:
            """Get TODO board for a project. If user_id is provided, enforces ownership."""
            return await self.project_manager.get_todo_board(project_id, user_id=user_id)

    async def update_project_stage(self, project_id: str, stage_id: str, status: str,
                                     progress: float = None, result: Dict[str, Any] = None,
                                     user_id: Optional[int] = None) -> bool:
            """Update project stage status. If user_id is provided, enforces ownership."""
            return await self.project_manager.update_stage_status(
                project_id, stage_id, status, progress, result, user_id=user_id
            )

    async def reset_stages_from(self, project_id: str, stage_id: str, user_id: Optional[int] = None) -> bool:
            """Reset all stages from the specified stage onwards. If user_id is provided, enforces ownership."""
            try:
                project = await self.project_manager.get_project(project_id, user_id=user_id)
                if not project or not project.todo_board:
                    return False

                # Find the stage index
                stage_index = -1
                for i, stage in enumerate(project.todo_board.stages):
                    if stage.id == stage_id:
                        stage_index = i
                        break

                if stage_index == -1:
                    logger.error(f"Stage {stage_id} not found in project {project_id}")
                    return False

                # Reset all stages from the specified stage onwards
                for i in range(stage_index, len(project.todo_board.stages)):
                    stage = project.todo_board.stages[i]
                    stage.status = "pending"
                    stage.progress = 0.0
                    stage.result = None
                    stage.updated_at = time.time()

                # Update current stage index
                project.todo_board.current_stage_index = stage_index

                # Recalculate overall progress
                project.todo_board.overall_progress = self.project_manager.calculate_overall_progress(project.todo_board.stages)
                project.todo_board.updated_at = time.time()

                # Clear related project data based on the stage being reset
                if stage_id == "outline_generation":
                    # Reset outline and all subsequent data
                    project.outline = None
                    project.slides_html = None
                    project.slides_data = None
                elif stage_id == "ppt_creation":
                    # Reset only PPT data, keep outline
                    project.slides_html = None
                    project.slides_data = None

                project.updated_at = time.time()

                # 保存重置后的项目状态到数据库
                try:
                    from .db_project_manager import DatabaseProjectManager
                    db_manager = DatabaseProjectManager()

                    # 更新项目状态
                    await db_manager.update_project_status(project_id, "in_progress")

                    # 重置相关阶段状态到数据库
                    for i in range(stage_index, len(project.todo_board.stages)):
                        stage = project.todo_board.stages[i]
                        await db_manager.update_stage_status(
                            project_id,
                            stage.id,
                            "pending",
                            0.0,
                            None
                        )

                    # 如果重置了大纲生成阶段，清除数据库中的大纲和幻灯片数据
                    if stage_id == "outline_generation":
                        # 清除大纲数据
                        await db_manager.save_project_outline(project_id, None)
                        # 清除幻灯片数据
                        await db_manager.save_project_slides(project_id, "", [])
                    elif stage_id == "ppt_creation":
                        # 只清除幻灯片数据，保留大纲
                        await db_manager.save_project_slides(project_id, "", [])

                    logger.info(f"Successfully saved reset stages to database for project {project_id}")

                except Exception as save_error:
                    logger.error(f"Failed to save reset stages to database: {save_error}")
                    # 继续执行，因为内存中的数据已经重置

                logger.info(f"Reset stages from {stage_id} onwards for project {project_id}")
                return True

            except Exception as e:
                logger.error(f"Error resetting stages from {stage_id}: {e}")
                return False

    async def start_workflow_from_stage(self, project_id: str, stage_id: str, user_id: Optional[int] = None) -> bool:
            """Start workflow execution from a specific stage. If user_id is provided, enforces ownership."""
            try:
                project = await self.project_manager.get_project(project_id, user_id=user_id)
                if not project:
                    return False

                # Check if requirements are confirmed (needed for all stages except requirements_confirmation)
                if stage_id != "requirements_confirmation" and not project.confirmed_requirements:
                    logger.error(f"Cannot start from stage {stage_id}: requirements not confirmed")
                    return False

                # Start the workflow from the specified stage
                # This will be handled by the existing workflow execution logic
                # For now, just mark the stage as ready to start
                await self.project_manager.update_stage_status(
                    project_id, stage_id, "pending", 0.0
                )

                logger.info(f"Workflow ready to start from stage {stage_id} for project {project_id}")
                return True

            except Exception as e:
                logger.error(f"Error starting workflow from stage {stage_id}: {e}")
                return False
