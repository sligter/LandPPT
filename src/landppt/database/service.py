"""
Database service layer for converting between database models and API models
"""

import time
import uuid
import logging
import copy
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

from .repositories import (
    ProjectRepository, TodoBoardRepository, TodoStageRepository,
    ProjectVersionRepository, SlideDataRepository, PPTTemplateRepository, GlobalMasterTemplateRepository
)
from .models import (
    Project as DBProject,
    TodoBoard as DBTodoBoard,
    TodoStage as DBTodoStage,
    SlideData as DBSlideData,
    PPTTemplate as DBPPTTemplate,
    GlobalMasterTemplate as DBGlobalMasterTemplate,
)
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

    @staticmethod
    def _clone_json(value: Any) -> Any:
        return copy.deepcopy(value) if value is not None else None

    @staticmethod
    def _get_slide_content_type(slide_data: Dict[str, Any]) -> str:
        return (
            slide_data.get("content_type")
            or slide_data.get("slide_type")
            or slide_data.get("type")
            or "content"
        )

    @classmethod
    def _get_slide_metadata(cls, slide_data: Dict[str, Any]) -> Dict[str, Any]:
        metadata = slide_data.get("metadata")
        if not isinstance(metadata, dict):
            metadata = slide_data.get("slide_metadata")
        metadata = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}

        for key in (
            "slide_type",
            "type",
            "description",
            "subtitle",
            "content",
            "content_points",
            "page_number",
            # Failure markers must round-trip: a slide saved by a failed run holds
            # an error div and has to be regenerated rather than skipped.
            "generation_failed",
            "generation_error",
            "composition_brief",
        ):
            if key in slide_data and slide_data.get(key) is not None:
                metadata[key] = copy.deepcopy(slide_data[key])

        # A slide that regenerated successfully must lose the stale failure marker.
        if slide_data.get("html_content") and not slide_data.get("generation_failed"):
            metadata.pop("generation_failed", None)
            metadata.pop("generation_error", None)

        return metadata

    @classmethod
    def _normalize_slide_json_entry(
        cls,
        slide_index: int,
        slide_data: Dict[str, Any],
        existing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        entry = dict(existing or {})
        incoming = dict(slide_data or {})
        for key, value in incoming.items():
            if value is not None:
                entry[key] = copy.deepcopy(value)

        entry["page_number"] = slide_index + 1
        entry["title"] = entry.get("title") or f"Slide {slide_index + 1}"
        content_type = cls._get_slide_content_type(entry)
        entry["content_type"] = content_type
        entry.setdefault("slide_type", content_type)
        entry["metadata"] = cls._get_slide_metadata(entry)
        return entry

    @classmethod
    def _slide_record_from_payload(
        cls,
        project_id: str,
        slide_index: int,
        slide_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        slide_data = dict(slide_data or {})
        return {
            "project_id": project_id,
            "slide_index": slide_index,
            "slide_id": slide_data.get("slide_id", f"slide_{slide_index}"),
            "title": slide_data.get("title", f"Slide {slide_index + 1}"),
            "content_type": cls._get_slide_content_type(slide_data),
            "html_content": slide_data.get("html_content", ""),
            "slide_metadata": cls._get_slide_metadata(slide_data),
            "is_user_edited": bool(slide_data.get("is_user_edited", False)),
        }
    
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
                for key in ("generation_failed", "generation_error", "composition_brief"):
                    if key in slide_dict["metadata"]:
                        slide_dict[key] = copy.deepcopy(slide_dict["metadata"][key])
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
            # getattr: this converter is also handed lightweight row stand-ins that
            # carry only the columns a caller cares about.
            user_id=getattr(db_project, "user_id", None),
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

    async def _sync_outline_to_existing_slides(
        self,
        project_id: str,
        outline: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> None:
        """Copy outline title/type metadata into existing slide storage."""
        if not isinstance(outline, dict):
            return

        outline_slides = outline.get("slides")
        if not isinstance(outline_slides, list):
            return

        project = await self.project_repo.get_by_id(project_id, user_id=user_id)
        if not project:
            return

        stored_slides_data = list(project.slides_data or [])
        update_project_json = bool(stored_slides_data)
        slide_rows = {
            slide.slide_index: slide
            for slide in await self.slide_repo.get_slides_by_project_id(project_id)
        }

        for index, outline_slide in enumerate(outline_slides):
            if not isinstance(outline_slide, dict):
                continue

            if index < len(stored_slides_data):
                stored_slides_data[index] = self._normalize_slide_json_entry(
                    index,
                    outline_slide,
                    existing=stored_slides_data[index],
                )

            slide_row = slide_rows.get(index)
            if slide_row:
                slide_row.title = outline_slide.get("title") or slide_row.title
                slide_row.content_type = self._get_slide_content_type(outline_slide)
                metadata = dict(slide_row.slide_metadata or {})
                metadata.update(self._get_slide_metadata(outline_slide))
                slide_row.slide_metadata = metadata
                slide_row.updated_at = time.time()

        if update_project_json:
            project.slides_data = stored_slides_data
            project.updated_at = time.time()

        if update_project_json or slide_rows:
            await self.session.commit()

    async def _sync_single_slide_to_project_json(
        self,
        project_id: str,
        slide_index: int,
        slide_data: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> None:
        project = await self.project_repo.get_by_id(project_id, user_id=user_id)
        if not project:
            return

        slides_data = list(project.slides_data or [])
        while len(slides_data) <= slide_index:
            placeholder_index = len(slides_data)
            slides_data.append(
                {
                    "page_number": placeholder_index + 1,
                    "title": f"Slide {placeholder_index + 1}",
                    "html_content": "",
                }
            )

        slides_data[slide_index] = self._normalize_slide_json_entry(
            slide_index,
            slide_data,
            existing=slides_data[slide_index],
        )
        project.slides_data = slides_data
        project.updated_at = time.time()
        await self.session.commit()
    
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

            result = await self.project_repo.update(project_id, update_data, user_id=effective_user_id)

            if result:
                logger.info(f"Successfully saved outline for project {project_id}")
                await self._sync_outline_to_existing_slides(
                    project_id,
                    outline,
                    user_id=effective_user_id,
                )

                # 验证保存是否成功
                saved_project = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
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
                slides_records.append(self._slide_record_from_payload(project_id, i, slide_data))

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

    async def set_slide_locked(self, project_id: str, slide_index: int, locked: bool) -> bool:
        """Persist a slide's regeneration lock in its metadata.

        Stored in ``slide_metadata`` rather than a dedicated column so the flag
        needs no schema migration.
        """
        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return False

        slide = await self.slide_repo.get_slide_by_index(project_id, slide_index)
        if slide is None:
            logger.warning(
                f"Cannot set lock: slide {slide_index} not found for project {project_id}"
            )
            return False

        metadata = dict(slide.slide_metadata or {})
        if locked:
            metadata["locked"] = True
        else:
            metadata.pop("locked", None)

        return await self.slide_repo.update_slide(slide.slide_id, {"slide_metadata": metadata})

    async def get_locked_slide_indices(self, project_id: str) -> set:
        """Indices of slides the user has locked against regeneration."""
        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return set()

        slides = await self.slide_repo.get_slides_by_project_id(project_id)
        return {
            slide.slide_index
            for slide in slides
            if isinstance(slide.slide_metadata, dict) and slide.slide_metadata.get("locked")
        }

    async def clear_project_outline(self, project_id: str) -> bool:
        """Drop the stored outline.

        ``save_project_outline`` deliberately refuses empty payloads so a failed
        generation cannot wipe a good outline; resetting a workflow stage is the
        one case where clearing is the intent, so it needs its own entry point.
        """
        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return False

        result = await self.project_repo.update(
            project_id,
            {"outline": None, "updated_at": time.time()},
            user_id=effective_user_id,
        )
        if result is None:
            logger.error(f"Failed to clear outline for project {project_id}")
            return False

        logger.info(f"Cleared outline for project {project_id}")
        return True

    async def clear_project_slides(self, project_id: str) -> bool:
        """Delete every slide row and the cached combined HTML for a project."""
        effective_user_id = current_user_id.get()
        if effective_user_id is not None:
            owned = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
            if not owned:
                return False

        await self.slide_repo.delete_slides_by_project_id(project_id)

        result = await self.project_repo.update(
            project_id,
            {"slides_html": None, "slides_data": None, "updated_at": time.time()},
            user_id=effective_user_id,
        )
        if result is None:
            logger.error(f"Failed to clear slides for project {project_id}")
            return False

        logger.info(f"Cleared all slides for project {project_id}")
        return True

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
                slide_records.append(self._slide_record_from_payload(project_id, i, slide_data))

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
                slide_record = self._slide_record_from_payload(project_id, slide_index, slide_data)

                logger.debug(f"📊 准备保存的幻灯片记录: 标题='{slide_record['title']}', 跳过用户编辑={skip_if_user_edited}")

                # Use upsert to insert or update the slide, passing skip_if_user_edited
                result_slide = await self.slide_repo.upsert_slide(project_id, slide_index, slide_record, skip_if_user_edited=skip_if_user_edited)

                if result_slide:
                    await self._sync_single_slide_to_project_json(
                        project_id,
                        slide_index,
                        slide_data,
                        user_id=effective_user_id,
                    )
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

    async def apply_slide_structure_operation(
        self,
        project_id: str,
        operation: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> bool:
        """Apply an outline structural operation to persisted slide order."""
        if not isinstance(operation, dict):
            return True

        op_type = str(operation.get("type") or operation.get("operation") or "").strip().lower()
        if op_type not in {"delete", "move", "insert"}:
            return True

        effective_user_id = user_id
        if effective_user_id == USER_SCOPE_ALL:
            effective_user_id = None
        if effective_user_id is None:
            effective_user_id = current_user_id.get()

        project = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
        if not project:
            return False

        if op_type == "insert":
            return True

        slide_rows = list(await self.slide_repo.get_slides_by_project_id(project_id))
        slides_json = list(project.slides_data or [])

        try:
            from_index = int(operation.get("from_index", operation.get("slide_index", -1)))
        except (TypeError, ValueError):
            return False

        changed = False

        if op_type == "delete":
            if 0 <= from_index < len(slide_rows):
                removed = slide_rows.pop(from_index)
                await self.session.delete(removed)
                changed = True

            if 0 <= from_index < len(slides_json):
                slides_json.pop(from_index)
                changed = True

        elif op_type == "move":
            try:
                to_index = int(operation.get("to_index"))
            except (TypeError, ValueError):
                return False

            if from_index == to_index:
                return True

            if 0 <= from_index < len(slide_rows):
                moved_row = slide_rows.pop(from_index)
                slide_rows.insert(max(0, min(to_index, len(slide_rows))), moved_row)
                changed = True

            if 0 <= from_index < len(slides_json):
                moved_json = slides_json.pop(from_index)
                slides_json.insert(max(0, min(to_index, len(slides_json))), moved_json)
                changed = True

        if not changed:
            return True

        for index, slide in enumerate(slide_rows):
            slide.slide_index = index
            slide.updated_at = time.time()

        for index, slide_data in enumerate(slides_json):
            if isinstance(slide_data, dict):
                slide_data["page_number"] = index + 1

        project.slides_data = slides_json
        project.updated_at = time.time()
        await self.session.commit()
        return True

    async def duplicate_project(
        self,
        project_id: str,
        user_id: Optional[int] = None,
        title_suffix: str = " (Copy)",
    ) -> Optional[PPTProject]:
        """Duplicate a project for the same owner."""
        effective_user_id = user_id
        if effective_user_id == USER_SCOPE_ALL:
            effective_user_id = None
        if effective_user_id is None:
            effective_user_id = current_user_id.get()

        source = await self.project_repo.get_by_id(project_id, user_id=effective_user_id)
        if not source:
            return None

        new_project_id = str(uuid.uuid4())
        now = time.time()

        try:
            duplicate = DBProject(
                project_id=new_project_id,
                user_id=source.user_id,
                title=f"{source.title}{title_suffix}",
                scenario=source.scenario,
                topic=source.topic,
                requirements=source.requirements,
                status=source.status,
                outline=self._clone_json(source.outline),
                slides_html=source.slides_html,
                slides_data=self._clone_json(source.slides_data),
                confirmed_requirements=self._clone_json(source.confirmed_requirements),
                project_metadata=self._clone_json(source.project_metadata),
                version=source.version,
                share_enabled=False,
                share_token=None,
                created_at=now,
                updated_at=now,
            )
            self.session.add(duplicate)
            await self.session.flush()

            template_id_map: Dict[int, int] = {}
            template_stmt = select(DBPPTTemplate).where(DBPPTTemplate.project_id == project_id)
            template_result = await self.session.execute(template_stmt)
            for template in template_result.scalars().all():
                copied_template = DBPPTTemplate(
                    project_id=new_project_id,
                    template_type=template.template_type,
                    template_name=template.template_name,
                    description=template.description,
                    html_template=template.html_template,
                    applicable_scenarios=self._clone_json(template.applicable_scenarios),
                    style_config=self._clone_json(template.style_config),
                    usage_count=template.usage_count,
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(copied_template)
                await self.session.flush()
                template_id_map[template.id] = copied_template.id

            if source.todo_board:
                copied_board = DBTodoBoard(
                    project_id=new_project_id,
                    current_stage_index=source.todo_board.current_stage_index,
                    overall_progress=source.todo_board.overall_progress,
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(copied_board)
                await self.session.flush()

                for stage in source.todo_board.stages:
                    self.session.add(
                        DBTodoStage(
                            todo_board_id=copied_board.id,
                            project_id=new_project_id,
                            stage_id=stage.stage_id,
                            stage_index=stage.stage_index,
                            title=stage.title,
                            description=stage.description,
                            status=stage.status,
                            progress=stage.progress,
                            result=self._clone_json(stage.result),
                            created_at=now,
                            updated_at=now,
                        )
                    )

            for slide in sorted(source.slides, key=lambda item: item.slide_index):
                # slide_id 列为 VARCHAR(100)。直接在原 id 后追加 "_copy_xxxxxxxx"
                # 会在多次复制后不断变长并越界，导致 PostgreSQL
                # StringDataRightTruncationError。改用基于编号的固定短 id，
                # 长度恒定，不随复制次数增长。
                new_slide_id = f"slide_{slide.slide_index}_{uuid.uuid4().hex[:8]}"
                self.session.add(
                    DBSlideData(
                        project_id=new_project_id,
                        slide_index=slide.slide_index,
                        slide_id=new_slide_id,
                        title=slide.title,
                        content_type=slide.content_type,
                        html_content=slide.html_content,
                        slide_metadata=self._clone_json(slide.slide_metadata),
                        template_id=template_id_map.get(slide.template_id),
                        is_user_edited=slide.is_user_edited,
                        created_at=now,
                        updated_at=now,
                    )
                )

            await self.session.commit()
            duplicated_project = await self.project_repo.get_by_id(
                new_project_id,
                user_id=source.user_id,
            )
            return self._convert_db_project_to_api(duplicated_project) if duplicated_project else None

        except Exception:
            await self.session.rollback()
            logger.exception("Failed to duplicate project %s", project_id)
            return None

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

    async def restore_project_version(
        self, project_id: str, version: int, user_id: Optional[int] = None
    ) -> bool:
        """Restore a project's outline and slides from a saved version.

        Previously only the unused in-memory manager implemented this, so the
        REST endpoint raised AttributeError and returned 500 on every call.
        """
        project = await self.project_repo.get_by_id(project_id, user_id=user_id)
        if not project:
            return False

        target = None
        for saved in (project.versions or []):
            saved_version = saved.get("version") if isinstance(saved, dict) else getattr(saved, "version", None)
            if saved_version == version:
                target = saved
                break

        if target is None:
            logger.warning(f"Version {version} not found for project {project_id}")
            return False

        version_data = target.get("data") if isinstance(target, dict) else getattr(target, "data", None)
        if not isinstance(version_data, dict):
            logger.error(f"Version {version} of project {project_id} has no usable data")
            return False

        update_data: Dict[str, Any] = {"updated_at": time.time()}
        if "outline" in version_data:
            update_data["outline"] = version_data["outline"]
        if "slides_html" in version_data:
            update_data["slides_html"] = version_data["slides_html"]
        if "slides_data" in version_data:
            update_data["slides_data"] = version_data["slides_data"]

        if len(update_data) == 1:
            logger.error(f"Version {version} of project {project_id} contains nothing restorable")
            return False

        result = await self.project_repo.update(project_id, update_data, user_id=user_id)
        if result is None:
            return False

        # Slide rows must follow the restored deck, or the project keeps serving the
        # newer slides alongside the older outline.
        slides_data = update_data.get("slides_data")
        if isinstance(slides_data, list):
            await self.slide_repo.delete_slides_by_project_id(project_id)
            records = [
                self._slide_record_from_payload(project_id, index, slide)
                for index, slide in enumerate(slides_data)
                if isinstance(slide, dict)
            ]
            if records:
                await self.slide_repo.create_slides(records)

        logger.info(f"Restored project {project_id} to version {version}")
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
