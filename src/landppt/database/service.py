"""
Database service layer for converting between database models and API models
"""

import time
import uuid
import logging
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from .repositories import (
    ProjectRepository, TodoBoardRepository, TodoStageRepository,
    ProjectVersionRepository, SlideDataRepository, PPTTemplateRepository, GlobalMasterTemplateRepository
)
from .models import Project as DBProject, TodoBoard as DBTodoBoard, TodoStage as DBTodoStage, PPTTemplate as DBPPTTemplate, GlobalMasterTemplate as DBGlobalMasterTemplate
from ..api.models import (
    PPTProject, TodoBoard, TodoStage, ProjectListResponse,
    PPTGenerationRequest
)
from ..auth.request_context import current_user_id, USER_SCOPE_ALL


class DatabaseService:
    """Service for database operations with model conversion"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.project_repo = ProjectRepository(session)
        self.todo_board_repo = TodoBoardRepository(session)
        self.todo_stage_repo = TodoStageRepository(session)
        self.version_repo = ProjectVersionRepository(session)
        self.slide_repo = SlideDataRepository(session)

    @staticmethod
    def _normalize_progress(progress: Any) -> float:
        try:
            value = float(progress)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(100.0, value))

    @classmethod
    def _calculate_overall_progress(cls, stages: List[Any]) -> float:
        if not stages:
            return 0.0
        return sum(cls._normalize_progress(getattr(stage, "progress", 0.0)) for stage in stages) / len(stages)

    @staticmethod
    def _extract_expected_slide_count(outline: Any) -> int:
        if not isinstance(outline, dict):
            return 0
        slides = outline.get("slides")
        return len(slides) if isinstance(slides, list) else 0
    
    def _convert_db_project_to_api(self, db_project: DBProject) -> PPTProject:
        """Convert database project to API model"""
        # Convert todo board if exists
        todo_board = None
        if db_project.todo_board:
            stages = [
                TodoStage(
                    id=stage.stage_id,  # Map stage_id to id
                    name=stage.title,   # Map title to name
                    description=stage.description,
                    status=stage.status,
                    progress=stage.progress,
                    subtasks=[],  # API model expects subtasks list
                    result=stage.result or {},
                    created_at=stage.created_at,
                    updated_at=stage.updated_at
                )
                for stage in db_project.todo_board.stages
            ]

            todo_board = TodoBoard(
                task_id=db_project.project_id,  # Map project_id to task_id
                title=db_project.title,
                stages=stages,
                current_stage_index=db_project.todo_board.current_stage_index,
                overall_progress=db_project.todo_board.overall_progress,
                created_at=db_project.todo_board.created_at,
                updated_at=db_project.todo_board.updated_at
            )
        
        # Convert versions (avoid lazy loading issues)
        versions = []

        slides_data = []
        if db_project.slides:
            # 从slide_data表中加载实际的幻灯片数据
            slides_data = []
            for slide in sorted(db_project.slides, key=lambda x: x.slide_index):
                slide_dict = {
                    "slide_id": slide.slide_id,
                    "title": slide.title,
                    "content_type": slide.content_type,
                    "html_content": slide.html_content,
                    "metadata": slide.slide_metadata or {},
                    "is_user_edited": slide.is_user_edited,
                    "created_at": slide.created_at,
                    "updated_at": slide.updated_at,
                    "page_number": slide.slide_index + 1  # 添加page_number字段，从slide_index转换而来
                }
                slides_data.append(slide_dict)
            logger.debug(f"Loaded {len(slides_data)} slides from slide_data table for project {db_project.project_id}")
        elif db_project.slides_data:
            # 如果slide_data表中没有数据，回退到使用projects表中的slides_data字段
            slides_data = db_project.slides_data
            logger.debug(f"Using slides_data from projects table for project {db_project.project_id}: {len(slides_data)} slides")

        expected_slide_count = self._extract_expected_slide_count(db_project.outline)
        actual_slide_count = len(slides_data)
        has_confirmed_requirements = bool(db_project.confirmed_requirements)
        has_outline = expected_slide_count > 0
        has_any_ppt_output = actual_slide_count > 0 or bool(str(db_project.slides_html or "").strip())
        has_complete_ppt = actual_slide_count > 0 and (
            expected_slide_count == 0 or actual_slide_count >= expected_slide_count
        )

        if db_project.todo_board:
            reconciled_stages = []
            for stage in db_project.todo_board.stages:
                status = stage.status
                progress = self._normalize_progress(stage.progress)

                if stage.stage_id == "requirements_confirmation":
                    if has_confirmed_requirements:
                        status = "completed"
                        progress = 100.0
                    elif status == "completed":
                        status = "pending"
                        progress = 0.0
                elif stage.stage_id == "outline_generation":
                    if has_outline:
                        status = "completed"
                        progress = 100.0
                    elif status == "completed":
                        status = "pending"
                        progress = 0.0
                elif stage.stage_id == "ppt_creation":
                    if has_complete_ppt:
                        status = "completed"
                        progress = 100.0
                    elif status == "completed":
                        if expected_slide_count > 0 and actual_slide_count > 0:
                            status = "running"
                            progress = min(99.0, (actual_slide_count / expected_slide_count) * 100)
                        elif has_any_ppt_output:
                            status = "running"
                            progress = max(progress, 1.0)
                        else:
                            status = "pending"
                            progress = 0.0
                    elif (
                        expected_slide_count > 0
                        and actual_slide_count > 0
                        and status in {"pending", "running"}
                    ):
                        status = "running"
                        progress = max(progress, min(99.0, (actual_slide_count / expected_slide_count) * 100))

                if status == "completed":
                    progress = 100.0

                reconciled_stages.append(
                    TodoStage(
                        id=stage.stage_id,
                        name=stage.title,
                        description=stage.description,
                        status=status,
                        progress=progress,
                        subtasks=[],
                        result=stage.result or {},
                        created_at=stage.created_at,
                        updated_at=stage.updated_at
                    )
                )

            current_stage_index = len(reconciled_stages) - 1 if reconciled_stages else 0
            for i, stage in enumerate(reconciled_stages):
                if stage.status != "completed":
                    current_stage_index = i
                    break

            todo_board = TodoBoard(
                task_id=db_project.project_id,
                title=db_project.title,
                stages=reconciled_stages,
                current_stage_index=current_stage_index,
                overall_progress=self._calculate_overall_progress(reconciled_stages),
                created_at=db_project.todo_board.created_at,
                updated_at=db_project.todo_board.updated_at
            )

        project_status = db_project.status
        if project_status != "archived":
            if has_complete_ppt:
                project_status = "completed"
            elif has_confirmed_requirements or has_outline or has_any_ppt_output:
                project_status = "in_progress"
            else:
                project_status = "draft"

        return PPTProject(
            project_id=db_project.project_id,
            title=db_project.title,
            scenario=db_project.scenario,
            topic=db_project.topic,
            requirements=db_project.requirements,
            status=project_status,
            outline=db_project.outline,
            slides_html=db_project.slides_html,
            slides_data=slides_data,
            confirmed_requirements=db_project.confirmed_requirements,
            project_metadata=db_project.project_metadata,
            todo_board=todo_board,
            version=db_project.version,
            versions=versions,
            created_at=db_project.created_at,
            updated_at=db_project.updated_at
        )
    
    async def create_project(self, request: PPTGenerationRequest, user_id: Optional[int] = None) -> PPTProject:
        """Create a new project with todo board.

        Note: user_id must come from authenticated context; do not trust request.user_id from clients.
        """
        project_id = str(uuid.uuid4())
        # Prefer authenticated request context over client-supplied values.
        owner_id = user_id if user_id is not None else (current_user_id.get() or request.user_id)
        if owner_id is None:
            raise ValueError("user_id is required to create a project")
        
        # Create project
        project_data = {
            "project_id": project_id,
            "user_id": owner_id,
            "title": f"{request.topic} - {request.scenario}",
            "scenario": request.scenario,
            "topic": request.topic,
            "requirements": request.requirements,
            "status": "draft",
            "project_metadata": {
                "network_mode": request.network_mode,
                "language": request.language,
                "created_with_network_mode": request.network_mode
            }
        }
        
        db_project = await self.project_repo.create(project_data)

        
        # Create todo board
        board_data = {
            "project_id": project_id,
            "current_stage_index": 0,
            "overall_progress": 0.0
        }
        
        db_board = await self.todo_board_repo.create(board_data)
        
        # Create default stages - 只有3个阶段
        stages_data = [
            {
                "todo_board_id": db_board.id,
                "project_id": project_id,  # Add project_id for direct reference
                "stage_id": "requirements_confirmation",
                "stage_index": 0,
                "title": "需求确认",
                "description": "确认PPT主题、内容重点、技术亮点和目标受众",
                "status": "pending"
            },
            {
                "todo_board_id": db_board.id,
                "project_id": project_id,  # Add project_id for direct reference
                "stage_id": "outline_generation",
                "stage_index": 1,
                "title": "大纲生成",
                "description": "基于确认的需求生成PPT大纲结构",
                "status": "pending"
            },
            {
                "todo_board_id": db_board.id,
                "project_id": project_id,  # Add project_id for direct reference
                "stage_id": "ppt_creation",
                "stage_index": 2,
                "title": "PPT生成",
                "description": "根据大纲生成完整的PPT页面",
                "status": "pending"
            }
        ]
        
        await self.todo_stage_repo.create_stages(stages_data)
        
        # Get the complete project with relationships
        complete_project = await self.project_repo.get_by_id(project_id, user_id=owner_id)
        return self._convert_db_project_to_api(complete_project)
    
    async def get_project(self, project_id: str, user_id: Optional[int] = None) -> Optional[PPTProject]:
        """Get project by ID. If user_id is provided, enforces ownership."""
        db_project = await self.project_repo.get_by_id(project_id, user_id=user_id)
        if not db_project:
            return None
        return self._convert_db_project_to_api(db_project)
    
    async def list_projects(self, page: int = 1, page_size: int = 10, 
                          status: Optional[str] = None,
                          user_id: Optional[int] = None) -> ProjectListResponse:
        """List projects with pagination. If user_id is provided, filters by owner."""
        if status:
            total_candidates = await self.project_repo.count_projects(user_id=user_id)
            if total_candidates == 0:
                return ProjectListResponse(
                    projects=[],
                    total=0,
                    page=page,
                    page_size=page_size
                )

            db_projects = await self.project_repo.list_projects(
                user_id=user_id,
                page=1,
                page_size=total_candidates,
                status=None,
            )
            all_projects = [self._convert_db_project_to_api(db_project) for db_project in db_projects]
            filtered_projects = [project for project in all_projects if project.status == status]

            total = len(filtered_projects)
            offset = max(page - 1, 0) * page_size
            projects = filtered_projects[offset:offset + page_size]
        else:
            db_projects = await self.project_repo.list_projects(
                user_id=user_id,
                page=page,
                page_size=page_size,
                status=None,
            )
            total = await self.project_repo.count_projects(user_id=user_id, status=None)
            projects = [self._convert_db_project_to_api(db_project) for db_project in db_projects]
        
        return ProjectListResponse(
            projects=projects,
            total=total,
            page=page,
            page_size=page_size
        )
    
    async def update_project_status(self, project_id: str, status: str, user_id: Optional[int] = None) -> bool:
        """Update project status. If user_id is provided, enforces ownership."""
        result = await self.project_repo.update(project_id, {"status": status}, user_id=user_id)
        return result is not None
    
    async def update_stage_status(self, project_id: str, stage_id: str,
                                status: str, progress: float = None,
                                result: Dict[str, Any] = None,
                                user_id: Optional[int] = None) -> bool:
        """Update stage status. If user_id is provided, enforces project ownership."""
        effective_user_id = user_id
        if effective_user_id == USER_SCOPE_ALL:
            effective_user_id = None
        if effective_user_id is None:
            effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            project = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not project:
                return False
        update_data = {"status": status}
        if progress is not None:
            update_data["progress"] = self._normalize_progress(progress)
        elif status == "completed":
            update_data["progress"] = 100.0
        if result is not None:
            update_data["result"] = result

        # Use the more efficient method with project_id
        success = await self.todo_stage_repo.update_stage_by_project_and_stage(project_id, stage_id, update_data)
        
        if success:
            # Update overall progress - 重新获取最新的todo_board数据
            todo_board = await self.todo_board_repo.get_by_project_id(project_id)
            if todo_board:
                # 确保stages数据是最新的
                await self.session.refresh(todo_board)

                total_stages = len(todo_board.stages)
                overall_progress = self._calculate_overall_progress(todo_board.stages)

                # Update current stage index - 找到第一个未完成的阶段
                current_stage_index = total_stages - 1  # 默认为最后一个阶段
                for i, stage in enumerate(todo_board.stages):
                    if stage.status != "completed":
                        current_stage_index = i
                        break

                # 立即更新数据库
                update_result = await self.todo_board_repo.update(project_id, {
                    "overall_progress": overall_progress,
                    "current_stage_index": current_stage_index
                })

                if update_result:
                    logger.info(f"Updated TODO board progress: {overall_progress}%, current stage: {current_stage_index}")
                else:
                    logger.error(f"Failed to update TODO board progress for project {project_id}")
        
        return success
    
    async def save_project_outline(self, project_id: str, outline: Dict[str, Any]) -> bool:
        """Save project outline"""
        try:
            effective_user_id = current_user_id.get()
            if effective_user_id is not None:
                owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
                if not owned:
                    return False

            logger.info(f"Saving outline for project {project_id}")
            logger.debug(f"Outline data: {outline}")

            # 确保outline数据有效
            if not outline:
                logger.error("Outline data is empty or None")
                return False

            # 更新项目的outline字段
            update_data = {
                "outline": outline,
                "updated_at": time.time()
            }

            result = await self.project_repo.update(project_id, update_data)

            if result:
                logger.info(f"Successfully saved outline for project {project_id}")

                # 验证保存是否成功
                saved_project = await self.project_repo.get_by_id(project_id)
                if saved_project and saved_project.outline:
                    logger.info(f"Verified outline saved: {len(saved_project.outline.get('slides', []))} slides")
                    return True
                else:
                    logger.error(f"Outline verification failed for project {project_id}")
                    return False
            else:
                logger.error(f"Failed to update project {project_id} with outline")
                return False

        except Exception as e:
            logger.error(f"Error saving project outline: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def save_project_slides(self, project_id: str, slides_html: str,
                                slides_data: List[Dict[str, Any]] = None) -> bool:
        """Save project slides - 优化的批量更新方式"""
        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return False

        update_data = {"slides_html": slides_html}
        if slides_data:
            update_data["slides_data"] = slides_data

            # 获取现有幻灯片数量，确保不会意外删除幻灯片
            existing_slides = await self.slide_repo.get_slides_by_project_id(project_id)
            existing_count = len(existing_slides)
            new_count = len(slides_data)

            logger.info(f"🔄 开始批量更新幻灯片: 现有{existing_count}页, 新数据{new_count}页")

            # 准备幻灯片数据
            slides_records = []
            for i, slide_data in enumerate(slides_data):
                slide_record = {
                    "project_id": project_id,
                    "slide_index": i,
                    "slide_id": slide_data.get("slide_id", f"slide_{i}"),
                    "title": slide_data.get("title", f"Slide {i+1}"),
                    "content_type": slide_data.get("content_type", "content"),
                    "html_content": slide_data.get("html_content", ""),
                    "slide_metadata": slide_data.get("metadata", {}),
                    "is_user_edited": slide_data.get("is_user_edited", False)
                }
                slides_records.append(slide_record)

            # 使用批量upsert方式更新幻灯片
            try:
                batch_success = await self.slide_repo.batch_upsert_slides(project_id, slides_records)
                if batch_success:
                    logger.info(f"✅ 批量更新幻灯片成功: {new_count}页")
                else:
                    logger.error(f"❌ 批量更新幻灯片失败")
                    return False
            except Exception as e:
                logger.error(f"❌ 批量更新幻灯片异常: {e}")
                return False

        result = await self.project_repo.update(project_id, update_data)
        return result is not None

    async def cleanup_excess_slides(
        self,
        project_id: str,
        current_slide_count: int,
        user_id: Optional[int] = None,
    ) -> int:
        """清理多余的幻灯片 - 删除索引 >= current_slide_count 的幻灯片"""
        logger.info(f"🧹 开始清理项目 {project_id} 的多余幻灯片，保留前 {current_slide_count} 张")
        effective_user_id = user_id
        if effective_user_id == USER_SCOPE_ALL:
            effective_user_id = None
        if effective_user_id is None:
            effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return 0

        deleted_count = await self.slide_repo.delete_slides_after_index(project_id, current_slide_count)
        logger.info(f"✅ 清理完成，删除了 {deleted_count} 张多余的幻灯片")
        return deleted_count

    async def replace_all_project_slides(self, project_id: str, slides_html: str,
                                       slides_data: List[Dict[str, Any]] = None) -> bool:
        """完全替换项目的所有幻灯片 - 用于重新生成PPT等场景"""
        update_data = {"slides_html": slides_html}
        if slides_data:
            update_data["slides_data"] = slides_data

            # 删除所有现有幻灯片，然后重新创建
            logger.info(f"🔄 完全替换项目 {project_id} 的所有幻灯片")
            effective_user_id = current_user_id.get()
            if effective_user_id is not None:
                owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
                if not owned:
                    return False

            await self.slide_repo.delete_slides_by_project_id(project_id)

            slide_records = []
            for i, slide_data in enumerate(slides_data):
                slide_records.append({
                    "project_id": project_id,
                    "slide_index": i,
                    "slide_id": slide_data.get("slide_id", f"slide_{i}"),
                    "title": slide_data.get("title", f"Slide {i+1}"),
                    "content_type": slide_data.get("content_type", "content"),
                    "html_content": slide_data.get("html_content", ""),
                    "slide_metadata": slide_data.get("metadata", {}),
                    "is_user_edited": slide_data.get("is_user_edited", False)
                })

            if slide_records:
                await self.slide_repo.create_slides(slide_records)

        result = await self.project_repo.update(project_id, update_data)
        return result is not None

    async def save_single_slide(self, project_id: str, slide_index: int, slide_data: Dict[str, Any], skip_if_user_edited: bool = False) -> bool:
        """Save a single slide to database immediately with retry logic for SQLite locks
        
        Args:
            skip_if_user_edited: If True, skip updating slides that have is_user_edited=True.
                                 Generator should pass True, editor should pass False.
        """
        import asyncio

        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return False
        
        max_retries = 5
        base_delay = 0.1  # 100ms
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"🔄 数据库服务开始保存幻灯片: 项目ID={project_id}, 索引={slide_index}, 尝试={attempt + 1}")

                # 验证输入参数
                if not project_id:
                    raise ValueError("项目ID不能为空")
                if slide_index < 0:
                    raise ValueError(f"幻灯片索引不能为负数: {slide_index}")
                if not slide_data:
                    raise ValueError("幻灯片数据不能为空")

                # Prepare slide record for database
                slide_record = {
                    "project_id": project_id,
                    "slide_index": slide_index,
                    "slide_id": slide_data.get("slide_id", f"slide_{slide_index}"),
                    "title": slide_data.get("title", f"Slide {slide_index + 1}"),
                    "content_type": slide_data.get("content_type", "content"),
                    "html_content": slide_data.get("html_content", ""),
                    "slide_metadata": slide_data.get("metadata", {}),
                    "is_user_edited": slide_data.get("is_user_edited", False)
                }

                logger.debug(f"📊 准备保存的幻灯片记录: 标题='{slide_record['title']}', 跳过用户编辑={skip_if_user_edited}")

                # Use upsert to insert or update the slide, passing skip_if_user_edited
                result_slide = await self.slide_repo.upsert_slide(project_id, slide_index, slide_record, skip_if_user_edited=skip_if_user_edited)

                if result_slide:
                    logger.debug(f"✅ 幻灯片保存成功: 项目ID={project_id}, 索引={slide_index}, 数据库ID={result_slide.id}")
                    return True
                else:
                    logger.error(f"❌ 幻灯片保存失败: upsert_slide返回None")
                    return False
                    
            except Exception as e:
                error_str = str(e).lower()
                # Check if it's a database locked error - retry with backoff
                if "database is locked" in error_str or "locked" in error_str:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"⏳ 数据库锁定，{delay:.2f}秒后重试... (尝试 {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                        continue
                
                logger.error(f"❌ 保存单个幻灯片失败: 项目ID={project_id}, 索引={slide_index}, 错误={str(e)}")
                import traceback
                logger.error(f"❌ 错误堆栈: {traceback.format_exc()}")
                return False
        
        logger.error(f"❌ 保存单个幻灯片失败: 重试次数用尽, 项目ID={project_id}, 索引={slide_index}")
        return False

    async def update_project(self, project_id: str, update_data: Dict[str, Any], user_id: Optional[int] = None) -> bool:
        """Update project data. If user_id is provided, enforces ownership."""
        try:
            result = await self.project_repo.update(project_id, update_data, user_id=user_id)
            return result is not None
        except Exception as e:
            logger.error(f"Failed to update project {project_id}: {e}")
            return False

    async def update_slide_user_edited_status(self, project_id: str, slide_index: int, is_user_edited: bool = True) -> bool:
        """Update the user edited status for a specific slide"""
        try:
            effective_user_id = current_user_id.get()
            if effective_user_id is not None:
                owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
                if not owned:
                    return False

            # Update the slide in slide_data table
            await self.slide_repo.update_slide_user_edited_status(project_id, slide_index, is_user_edited)

            # Also update the slides_data in the project
            project = await self.project_repo.get_by_id(project_id)
            if project and project.slides_data and slide_index < len(project.slides_data):
                project.slides_data[slide_index]["is_user_edited"] = is_user_edited
                await self.project_repo.update(project_id, {"slides_data": project.slides_data})

            return True
        except Exception as e:
            logger.error(f"Failed to update slide user edited status: {e}")
            return False

    async def save_project_version(self, project_id: str, version_data: Dict[str, Any], user_id: Optional[int] = None) -> bool:
        """Save a project version. If user_id is provided, enforces ownership."""
        project = await self.project_repo.get_by_id(project_id, user_id=user_id)
        if not project:
            return False
        
        version_info = {
            "project_id": project_id,
            "version": project.version,
            "timestamp": time.time(),
            "data": version_data,
            "description": f"Version {project.version} - {time.strftime('%Y-%m-%d %H:%M:%S')}"
        }
        
        await self.version_repo.create(version_info)
        await self.project_repo.update(project_id, {"version": project.version + 1}, user_id=user_id)
        
        return True

    # PPT Template methods
    async def create_template(self, template_data: Dict[str, Any]) -> DBPPTTemplate:
        """Create a new PPT template"""
        template_repo = PPTTemplateRepository(self.session)
        return await template_repo.create_template(template_data)

    async def get_template_by_id(self, template_id: int) -> Optional[DBPPTTemplate]:
        """Get template by ID"""
        template_repo = PPTTemplateRepository(self.session)
        return await template_repo.get_template_by_id(template_id)

    async def get_templates_by_project_id(self, project_id: str) -> List[DBPPTTemplate]:
        """Get all templates for a project"""
        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return []
        template_repo = PPTTemplateRepository(self.session)
        return await template_repo.get_templates_by_project_id(project_id)

    async def get_templates_by_type(self, project_id: str, template_type: str) -> List[DBPPTTemplate]:
        """Get templates by type for a project"""
        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return []
        template_repo = PPTTemplateRepository(self.session)
        return await template_repo.get_templates_by_type(project_id, template_type)

    async def update_template(self, template_id: int, update_data: Dict[str, Any]) -> bool:
        """Update a template"""
        template_repo = PPTTemplateRepository(self.session)
        return await template_repo.update_template(template_id, update_data)

    async def increment_template_usage(self, template_id: int) -> bool:
        """Increment template usage count"""
        template_repo = PPTTemplateRepository(self.session)
        return await template_repo.increment_usage_count(template_id)

    async def delete_template(self, template_id: int) -> bool:
        """Delete a template"""
        template_repo = PPTTemplateRepository(self.session)
        return await template_repo.delete_template(template_id)

    async def delete_templates_by_project_id(self, project_id: str) -> bool:
        """Delete all templates for a project"""
        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return False
        template_repo = PPTTemplateRepository(self.session)
        return await template_repo.delete_templates_by_project_id(project_id)

    # Global Master Template methods
    async def create_global_master_template(
        self,
        template_data: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> DBGlobalMasterTemplate:
        """Create a new global master template"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.create_template(template_data, user_id=user_id)

    async def get_global_master_template_by_id(
        self,
        template_id: int,
        user_id: Optional[int] = None,
    ) -> Optional[DBGlobalMasterTemplate]:
        """Get global master template by ID"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.get_template_by_id(template_id, user_id=user_id)

    async def get_global_master_template_by_name(
        self,
        template_name: str,
        user_id: Optional[int] = None,
    ) -> Optional[DBGlobalMasterTemplate]:
        """Get global master template by name"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.get_template_by_name(template_name, user_id=user_id)

    async def get_all_global_master_templates(
        self,
        active_only: bool = True,
        user_id: Optional[int] = None,
    ) -> List[DBGlobalMasterTemplate]:
        """Get all global master templates"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.get_all_templates(active_only, user_id=user_id)

    async def get_global_master_templates_by_tags(
        self,
        tags: List[str],
        active_only: bool = True,
        user_id: Optional[int] = None,
    ) -> List[DBGlobalMasterTemplate]:
        """Get global master templates by tags"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.get_templates_by_tags(tags, active_only, user_id=user_id)

    async def get_global_master_templates_paginated(
        self,
        active_only: bool = True,
        offset: int = 0,
        limit: int = 6,
        search: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Tuple[List[DBGlobalMasterTemplate], int]:
        """Get global master templates with pagination"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.get_templates_paginated(
            active_only,
            offset,
            limit,
            search,
            user_id=user_id,
        )

    async def get_global_master_templates_by_tags_paginated(
        self,
        tags: List[str],
        active_only: bool = True,
        offset: int = 0,
        limit: int = 6,
        search: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Tuple[List[DBGlobalMasterTemplate], int]:
        """Get global master templates by tags with pagination"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.get_templates_by_tags_paginated(
            tags,
            active_only,
            offset,
            limit,
            search,
            user_id=user_id,
        )

    async def update_global_master_template(
        self,
        template_id: int,
        update_data: Dict[str, Any],
        user_id: Optional[int] = None,
        allow_system_write: bool = False,
    ) -> bool:
        """Update a global master template"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.update_template(
            template_id,
            update_data,
            user_id=user_id,
            allow_system_write=allow_system_write,
        )

    async def delete_global_master_template(
        self,
        template_id: int,
        user_id: Optional[int] = None,
        allow_system_write: bool = False,
    ) -> bool:
        """Delete a global master template"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.delete_template(
            template_id,
            user_id=user_id,
            allow_system_write=allow_system_write,
        )

    async def increment_global_master_template_usage(self, template_id: int, user_id: Optional[int] = None) -> bool:
        """Increment global master template usage count"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.increment_usage_count(template_id, user_id=user_id)

    async def set_default_global_master_template(
        self,
        template_id: int,
        user_id: Optional[int] = None,
        allow_system_write: bool = False,
    ) -> bool:
        """Set a global master template as default"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.set_default_template(
            template_id,
            user_id=user_id,
            allow_system_write=allow_system_write,
        )

    async def get_default_global_master_template(self, user_id: Optional[int] = None) -> Optional[DBGlobalMasterTemplate]:
        """Get the default global master template"""
        template_repo = GlobalMasterTemplateRepository(self.session)
        return await template_repo.get_default_template(user_id=user_id)
