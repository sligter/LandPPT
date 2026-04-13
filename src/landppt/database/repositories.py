"""
Repository classes for database operations
"""

import time
import logging
import secrets
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, func, or_, inspect, text
from sqlalchemy.orm import selectinload

from .models import Project, TodoBoard, TodoStage, ProjectVersion, SlideData, PPTTemplate, GlobalMasterTemplate, CreditTransaction, RedemptionCode, User, UserConfig, UserMetrics
from ..api.models import PPTProject, TodoBoard as TodoBoardModel, TodoStage as TodoStageModel

logger = logging.getLogger(__name__)

from ..auth.request_context import current_user_id, USER_SCOPE_ALL


def _effective_user_id(user_id: Optional[int]) -> Optional[int]:
    """
    Resolve an optional user_id for per-request scoping.

    - If user_id == USER_SCOPE_ALL: disable scoping (admin/system usage).
    - If user_id is None: use current request-scoped user_id (if any).
    - Else: use the provided user_id.
    """
    if user_id == USER_SCOPE_ALL:
        return None
    if user_id is None:
        return current_user_id.get()
    return user_id


class ProjectRepository:
    """Repository for Project operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _delete_legacy_slide_revisions(self, project_id: str) -> None:
        """
        删除未纳入当前 ORM 映射、但线上数据库已存在的 slide_revisions 记录。

        背景：
        历史数据库中可能已经存在 slide_revisions.project_id -> projects.project_id
        的外键约束，而当前代码仓库尚未维护对应模型。若不在删除项目时先清理，
        会被数据库外键拦截，导致项目无法删除。
        """
        connection = await self.session.connection()
        has_slide_revisions_table = await connection.run_sync(
            lambda sync_conn: inspect(sync_conn).has_table("slide_revisions")
        )
        if not has_slide_revisions_table:
            return

        await self.session.execute(
            text("DELETE FROM slide_revisions WHERE project_id = :project_id"),
            {"project_id": project_id},
        )
    
    async def create(self, project_data: Dict[str, Any]) -> Project:
        """Create a new project"""
        project = Project(**project_data)
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project
    
    async def get_by_id(self, project_id: str, user_id: Optional[int] = None) -> Optional[Project]:
        """Get project by ID with all relationships. If user_id is provided, also checks ownership."""
        user_id = _effective_user_id(user_id)
        stmt = select(Project).where(Project.project_id == project_id).options(
            selectinload(Project.todo_board).selectinload(TodoBoard.stages),
            selectinload(Project.versions),
            selectinload(Project.slides)
        )
        if user_id is not None:
            stmt = stmt.where(Project.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def list_projects(self, user_id: Optional[int] = None, page: int = 1, page_size: int = 10, status: Optional[str] = None) -> List[Project]:
        """List projects with pagination. If user_id is provided, filters by owner."""
        user_id = _effective_user_id(user_id)
        stmt = select(Project).options(
            selectinload(Project.todo_board).selectinload(TodoBoard.stages),
            selectinload(Project.versions),
            selectinload(Project.slides)
        )
        
        if user_id is not None:
            stmt = stmt.where(Project.user_id == user_id)
        if status:
            stmt = stmt.where(Project.status == status)
        
        stmt = stmt.order_by(Project.updated_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def count_projects(self, user_id: Optional[int] = None, status: Optional[str] = None) -> int:
        """Count total projects. If user_id is provided, counts only that user's projects."""
        user_id = _effective_user_id(user_id)
        stmt = select(func.count(Project.id))
        if user_id is not None:
            stmt = stmt.where(Project.user_id == user_id)
        if status:
            stmt = stmt.where(Project.status == status)

        result = await self.session.execute(stmt)
        return result.scalar() or 0
    
    async def update(
        self,
        project_id: str,
        update_data: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> Optional[Project]:
        """Update project. If user_id is provided, enforces ownership."""
        user_id = _effective_user_id(user_id)
        try:
            # 首先获取项目（如果提供 user_id 则校验归属）
            project = await self.get_by_id(project_id, user_id=user_id)
            if not project:
                logger.warning(f"No project found with ID {project_id} for update")
                return None

            # 更新项目属性
            for key, value in update_data.items():
                if hasattr(project, key):
                    setattr(project, key, value)

            # 设置更新时间
            project.updated_at = time.time()

            # 提交更改
            await self.session.commit()
            await self.session.refresh(project)

            logger.info(f"Successfully updated project {project_id}")
            return project

        except Exception as e:
            logger.error(f"Error updating project {project_id}: {e}")
            await self.session.rollback()
            raise
    
    async def delete(self, project_id: str, user_id: Optional[int] = None) -> bool:
        """Delete project and all related records. If user_id is provided, enforces ownership."""
        from .models import (
            TodoStage,
            TodoBoard,
            SlideData,
            ProjectVersion,
            PPTTemplate,
            SpeechScript,
            NarrationAudio,
        )
        
        user_id = _effective_user_id(user_id)
        
        # First, verify the project exists and user has permission
        stmt = select(Project).where(Project.project_id == project_id)
        if user_id is not None:
            stmt = stmt.where(Project.user_id == user_id)
        result = await self.session.execute(stmt)
        project = result.scalar_one_or_none()
        
        if not project:
            return False
        
        try:
            # Delete related records in order (child tables first)
            # 1. Delete todo_stages (references todo_boards and projects)
            await self.session.execute(
                delete(TodoStage).where(TodoStage.project_id == project_id)
            )
            
            # 2. Delete todo_boards (references projects)
            await self.session.execute(
                delete(TodoBoard).where(TodoBoard.project_id == project_id)
            )

            # 3. 删除遗留的 slide_revisions，避免真实数据库中的外键阻塞项目删除
            await self._delete_legacy_slide_revisions(project_id)

            # 4. Delete slides (references projects)
            await self.session.execute(
                delete(SlideData).where(SlideData.project_id == project_id)
            )
            
            # 5. Delete project versions (references projects)
            await self.session.execute(
                delete(ProjectVersion).where(ProjectVersion.project_id == project_id)
            )
            
            # 6. Delete templates (references projects)
            await self.session.execute(
                delete(PPTTemplate).where(PPTTemplate.project_id == project_id)
            )
            
            # 7. Delete speech scripts (references projects)
            await self.session.execute(
                delete(SpeechScript).where(SpeechScript.project_id == project_id)
            )
            
            # 8. Delete narration audio cache records (references projects)
            await self.session.execute(
                delete(NarrationAudio).where(NarrationAudio.project_id == project_id)
            )

            # 9. Finally delete the project itself
            await self.session.execute(
                delete(Project).where(Project.project_id == project_id)
            )
            
            await self.session.commit()
            logger.info(f"Successfully deleted project {project_id} and all related records")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting project {project_id}: {e}")
            await self.session.rollback()
            raise


class TodoBoardRepository:
    """Repository for TodoBoard operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, board_data: Dict[str, Any]) -> TodoBoard:
        """Create a new todo board"""
        board = TodoBoard(**board_data)
        self.session.add(board)
        await self.session.commit()
        await self.session.refresh(board)
        return board
    
    async def get_by_project_id(self, project_id: str) -> Optional[TodoBoard]:
        """Get todo board by project ID"""
        stmt = select(TodoBoard).where(TodoBoard.project_id == project_id).options(
            selectinload(TodoBoard.stages)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def update(self, project_id: str, update_data: Dict[str, Any]) -> Optional[TodoBoard]:
        """Update todo board"""
        update_data['updated_at'] = time.time()
        stmt = update(TodoBoard).where(TodoBoard.project_id == project_id).values(**update_data)
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_by_project_id(project_id)


class TodoStageRepository:
    """Repository for TodoStage operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create_stages(self, stages_data: List[Dict[str, Any]]) -> List[TodoStage]:
        """Create multiple stages"""
        stages = [TodoStage(**stage_data) for stage_data in stages_data]
        self.session.add_all(stages)
        await self.session.commit()
        for stage in stages:
            await self.session.refresh(stage)
        return stages
    
    async def update_stage(self, stage_id: str, update_data: Dict[str, Any]) -> bool:
        """Update a specific stage"""
        update_data['updated_at'] = time.time()
        stmt = update(TodoStage).where(TodoStage.stage_id == stage_id).values(**update_data)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def update_stage_by_project_and_stage(self, project_id: str, stage_id: str, update_data: Dict[str, Any]) -> bool:
        """Update a specific stage by project_id and stage_id for better performance"""
        update_data['updated_at'] = time.time()
        stmt = update(TodoStage).where(
            TodoStage.project_id == project_id,
            TodoStage.stage_id == stage_id
        ).values(**update_data)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def get_stage_by_project_and_stage(self, project_id: str, stage_id: str) -> Optional[TodoStage]:
        """Get a specific stage by project_id and stage_id"""
        stmt = select(TodoStage).where(
            TodoStage.project_id == project_id,
            TodoStage.stage_id == stage_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_stages_by_board_id(self, board_id: int) -> List[TodoStage]:
        """Get all stages for a todo board"""
        stmt = select(TodoStage).where(TodoStage.todo_board_id == board_id).order_by(TodoStage.stage_index)
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ProjectVersionRepository:
    """Repository for ProjectVersion operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, version_data: Dict[str, Any]) -> ProjectVersion:
        """Create a new project version"""
        version = ProjectVersion(**version_data)
        self.session.add(version)
        await self.session.commit()
        await self.session.refresh(version)
        return version
    
    async def get_versions_by_project_id(self, project_id: str) -> List[ProjectVersion]:
        """Get all versions for a project"""
        stmt = select(ProjectVersion).where(ProjectVersion.project_id == project_id).order_by(ProjectVersion.version.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()


class SlideDataRepository:
    """Repository for SlideData operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create_slides(self, slides_data: List[Dict[str, Any]]) -> List[SlideData]:
        """Create multiple slides"""
        slides = [SlideData(**slide_data) for slide_data in slides_data]
        self.session.add_all(slides)
        await self.session.commit()
        for slide in slides:
            await self.session.refresh(slide)
        return slides

    async def create_single_slide(self, slide_data: Dict[str, Any]) -> SlideData:
        """Create a single slide"""
        slide = SlideData(**slide_data)
        self.session.add(slide)
        await self.session.commit()
        await self.session.refresh(slide)
        return slide

    async def upsert_slide(self, project_id: str, slide_index: int, slide_data: Dict[str, Any], skip_if_user_edited: bool = False) -> SlideData:
        """Insert or update a single slide
        
        Args:
            project_id: Project ID
            slide_index: Slide index (0-based)
            slide_data: Slide data dictionary
            skip_if_user_edited: If True, skip updating slides that have is_user_edited=True.
                                 This allows generator to not overwrite user edits.
        """
        import logging
        logger = logging.getLogger(__name__)

        logger.info(f"🔄 数据库仓库开始upsert幻灯片: 项目ID={project_id}, 索引={slide_index}, 跳过用户编辑={skip_if_user_edited}")

        # Check if slide already exists
        stmt = select(SlideData).where(
            SlideData.project_id == project_id,
            SlideData.slide_index == slide_index
        )
        result = await self.session.execute(stmt)
        existing_slide = result.scalar_one_or_none()

        if existing_slide:
            # 如果skip_if_user_edited=True且现有幻灯片已被用户编辑，跳过更新
            if skip_if_user_edited and existing_slide.is_user_edited:
                logger.info(f"⏭️ 跳过更新用户编辑的幻灯片: 项目ID={project_id}, 索引={slide_index}")
                return existing_slide
            
            # Update existing slide
            logger.info(f"📝 更新现有幻灯片: 数据库ID={existing_slide.id}, 项目ID={project_id}, 索引={slide_index}")
            slide_data['updated_at'] = time.time()

            updated_fields = []
            for key, value in slide_data.items():
                if hasattr(existing_slide, key):
                    old_value = getattr(existing_slide, key)
                    if old_value != value:
                        setattr(existing_slide, key, value)
                        updated_fields.append(key)

            logger.info(f"📊 更新的字段: {updated_fields}")
            await self.session.commit()
            await self.session.refresh(existing_slide)
            logger.info(f"✅ 幻灯片更新成功: 数据库ID={existing_slide.id}")
            return existing_slide
        else:
            # Create new slide
            logger.info(f"➕ 创建新幻灯片: 项目ID={project_id}, 索引={slide_index}")
            slide_data['created_at'] = time.time()
            slide_data['updated_at'] = time.time()
            new_slide = await self.create_single_slide(slide_data)
            logger.info(f"✅ 新幻灯片创建成功: 数据库ID={new_slide.id}")
            return new_slide
    
    async def get_slides_by_project_id(self, project_id: str) -> List[SlideData]:
        """Get all slides for a project"""
        stmt = select(SlideData).where(SlideData.project_id == project_id).order_by(SlideData.slide_index)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_slide_by_index(self, project_id: str, slide_index: int) -> Optional[SlideData]:
        """Get a single slide by project_id and slide_index"""
        stmt = select(SlideData).where(
            SlideData.project_id == project_id,
            SlideData.slide_index == slide_index
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def update_slide(self, slide_id: str, update_data: Dict[str, Any]) -> bool:
        """Update a specific slide"""
        update_data['updated_at'] = time.time()
        stmt = update(SlideData).where(SlideData.slide_id == slide_id).values(**update_data)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0
    
    async def delete_slides_by_project_id(self, project_id: str) -> bool:
        """Delete all slides for a project"""
        stmt = delete(SlideData).where(SlideData.project_id == project_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def delete_slides_after_index(self, project_id: str, start_index: int) -> int:
        """Delete slides with index >= start_index for a project"""
        logger.debug(f"🗑️ 删除项目 {project_id} 中索引 >= {start_index} 的幻灯片")
        stmt = delete(SlideData).where(
            and_(
                SlideData.project_id == project_id,
                SlideData.slide_index >= start_index
            )
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        deleted_count = result.rowcount
        logger.debug(f"✅ 成功删除 {deleted_count} 张多余的幻灯片")
        return deleted_count

    async def batch_upsert_slides(self, project_id: str, slides_data: List[Dict[str, Any]]) -> bool:
        """批量插入或更新幻灯片 - 优化版本"""
        logger.debug(f"🔄 开始批量upsert幻灯片: 项目ID={project_id}, 数量={len(slides_data)}")

        try:
            # 获取现有幻灯片
            existing_slides_stmt = select(SlideData).where(SlideData.project_id == project_id)
            result = await self.session.execute(existing_slides_stmt)
            existing_slides = {slide.slide_index: slide for slide in result.scalars().all()}

            updated_count = 0
            created_count = 0
            current_time = time.time()

            # 批量处理幻灯片
            for i, slide_data in enumerate(slides_data):
                slide_index = i

                if slide_index in existing_slides:
                    # 更新现有幻灯片
                    existing_slide = existing_slides[slide_index]
                    slide_data['updated_at'] = current_time

                    # 只更新有变化的字段
                    has_changes = False
                    for key, value in slide_data.items():
                        if hasattr(existing_slide, key) and getattr(existing_slide, key) != value:
                            setattr(existing_slide, key, value)
                            has_changes = True

                    if has_changes:
                        updated_count += 1
                else:
                    # 创建新幻灯片
                    slide_data.update({
                        'project_id': project_id,
                        'slide_index': slide_index,
                        'created_at': current_time,
                        'updated_at': current_time
                    })
                    new_slide = SlideData(**slide_data)
                    self.session.add(new_slide)
                    created_count += 1

            # 一次性提交所有更改
            await self.session.commit()

            logger.debug(f"✅ 批量upsert完成: 更新={updated_count}, 创建={created_count}")
            return True

        except Exception as e:
            logger.error(f"❌ 批量upsert失败: {e}")
            await self.session.rollback()
            return False

    async def update_slide_user_edited_status(self, project_id: str, slide_index: int, is_user_edited: bool = True) -> bool:
        """Update the user edited status for a specific slide"""
        stmt = update(SlideData).where(
            SlideData.project_id == project_id,
            SlideData.slide_index == slide_index
        ).values(
            is_user_edited=is_user_edited,
            updated_at=time.time()
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0


class PPTTemplateRepository:
    """Repository for PPT template operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_template(self, template_data: Dict[str, Any]) -> PPTTemplate:
        """Create a new PPT template"""
        template_data['created_at'] = time.time()
        template_data['updated_at'] = time.time()
        template = PPTTemplate(**template_data)
        self.session.add(template)
        await self.session.commit()
        await self.session.refresh(template)
        return template

    async def get_template_by_id(self, template_id: int) -> Optional[PPTTemplate]:
        """Get template by ID"""
        stmt = select(PPTTemplate).where(PPTTemplate.id == template_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_templates_by_project_id(self, project_id: str) -> List[PPTTemplate]:
        """Get all templates for a project"""
        stmt = select(PPTTemplate).where(PPTTemplate.project_id == project_id).order_by(PPTTemplate.created_at)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_templates_by_type(self, project_id: str, template_type: str) -> List[PPTTemplate]:
        """Get templates by type for a project"""
        stmt = select(PPTTemplate).where(
            PPTTemplate.project_id == project_id,
            PPTTemplate.template_type == template_type
        ).order_by(PPTTemplate.created_at)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_template(self, template_id: int, update_data: Dict[str, Any]) -> bool:
        """Update a template"""
        update_data['updated_at'] = time.time()
        stmt = update(PPTTemplate).where(PPTTemplate.id == template_id).values(**update_data)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def increment_usage_count(self, template_id: int) -> bool:
        """Increment template usage count"""
        stmt = update(PPTTemplate).where(PPTTemplate.id == template_id).values(
            usage_count=PPTTemplate.usage_count + 1,
            updated_at=time.time()
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def delete_template(self, template_id: int) -> bool:
        """Delete a template"""
        stmt = delete(PPTTemplate).where(PPTTemplate.id == template_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0


class GlobalMasterTemplateRepository:
    """Repository for Global Master Template operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _apply_visibility_scope(self, stmt, user_id: Optional[int], include_system: bool = True):
        """Apply per-user visibility scope to global templates query."""
        effective_user_id = _effective_user_id(user_id)
        if effective_user_id is None:
            return stmt
        if include_system:
            return stmt.where(
                or_(
                    GlobalMasterTemplate.user_id == effective_user_id,
                    GlobalMasterTemplate.user_id.is_(None),
                )
            )
        return stmt.where(GlobalMasterTemplate.user_id == effective_user_id)

    async def create_template(self, template_data: Dict[str, Any], user_id: Optional[int] = None) -> GlobalMasterTemplate:
        """Create a new global master template"""
        effective_user_id = _effective_user_id(user_id)
        if effective_user_id is not None and template_data.get("user_id") is None:
            template_data["user_id"] = effective_user_id

        template_data['created_at'] = time.time()
        template_data['updated_at'] = time.time()
        template = GlobalMasterTemplate(**template_data)
        self.session.add(template)
        await self.session.commit()
        await self.session.refresh(template)
        return template

    async def get_template_by_id(self, template_id: int, user_id: Optional[int] = None) -> Optional[GlobalMasterTemplate]:
        """Get template by ID"""
        stmt = select(GlobalMasterTemplate).where(GlobalMasterTemplate.id == template_id)
        stmt = self._apply_visibility_scope(stmt, user_id, include_system=True)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_template_by_name(self, template_name: str, user_id: Optional[int] = None) -> Optional[GlobalMasterTemplate]:
        """Get template by name"""
        stmt = select(GlobalMasterTemplate).where(GlobalMasterTemplate.template_name == template_name)
        stmt = self._apply_visibility_scope(stmt, user_id, include_system=True)
        stmt = stmt.order_by(GlobalMasterTemplate.updated_at.desc()).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_all_templates(self, active_only: bool = True, user_id: Optional[int] = None) -> List[GlobalMasterTemplate]:
        """Get all global master templates"""
        stmt = select(GlobalMasterTemplate)
        stmt = self._apply_visibility_scope(stmt, user_id, include_system=True)
        if active_only:
            stmt = stmt.where(GlobalMasterTemplate.is_active == True)
        stmt = stmt.order_by(GlobalMasterTemplate.is_default.desc(), GlobalMasterTemplate.usage_count.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_templates_by_tags(
        self,
        tags: List[str],
        active_only: bool = True,
        user_id: Optional[int] = None,
    ) -> List[GlobalMasterTemplate]:
        """Get templates by tags"""
        stmt = select(GlobalMasterTemplate)
        stmt = self._apply_visibility_scope(stmt, user_id, include_system=True)
        if active_only:
            stmt = stmt.where(GlobalMasterTemplate.is_active == True)

        # Filter by tags (any tag matches)
        for tag in tags:
            stmt = stmt.where(GlobalMasterTemplate.tags.contains([tag]))

        stmt = stmt.order_by(GlobalMasterTemplate.usage_count.desc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_templates_paginated(
        self,
        active_only: bool = True,
        offset: int = 0,
        limit: int = 6,
        search: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Tuple[List[GlobalMasterTemplate], int]:
        """Get templates with pagination"""
        # Base query
        stmt = select(GlobalMasterTemplate)
        count_stmt = select(func.count(GlobalMasterTemplate.id))
        stmt = self._apply_visibility_scope(stmt, user_id, include_system=True)
        count_stmt = self._apply_visibility_scope(count_stmt, user_id, include_system=True)

        if active_only:
            stmt = stmt.where(GlobalMasterTemplate.is_active == True)
            count_stmt = count_stmt.where(GlobalMasterTemplate.is_active == True)

        # Add search filter
        if search and search.strip():
            search_filter = or_(
                GlobalMasterTemplate.template_name.ilike(f"%{search}%"),
                GlobalMasterTemplate.description.ilike(f"%{search}%")
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        # Order and paginate
        stmt = stmt.order_by(
            GlobalMasterTemplate.is_default.desc(),
            GlobalMasterTemplate.usage_count.desc()
        ).offset(offset).limit(limit)

        # Execute queries
        result = await self.session.execute(stmt)
        count_result = await self.session.execute(count_stmt)

        templates = result.scalars().all()
        total_count = count_result.scalar()

        return templates, total_count

    async def get_templates_by_tags_paginated(
        self,
        tags: List[str],
        active_only: bool = True,
        offset: int = 0,
        limit: int = 6,
        search: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Tuple[List[GlobalMasterTemplate], int]:
        """Get templates by tags with pagination"""
        # Base query
        stmt = select(GlobalMasterTemplate)
        count_stmt = select(func.count(GlobalMasterTemplate.id))
        stmt = self._apply_visibility_scope(stmt, user_id, include_system=True)
        count_stmt = self._apply_visibility_scope(count_stmt, user_id, include_system=True)

        if active_only:
            stmt = stmt.where(GlobalMasterTemplate.is_active == True)
            count_stmt = count_stmt.where(GlobalMasterTemplate.is_active == True)

        # Filter by tags (any tag matches)
        for tag in tags:
            tag_filter = GlobalMasterTemplate.tags.contains([tag])
            stmt = stmt.where(tag_filter)
            count_stmt = count_stmt.where(tag_filter)

        # Add search filter
        if search and search.strip():
            search_filter = or_(
                GlobalMasterTemplate.template_name.ilike(f"%{search}%"),
                GlobalMasterTemplate.description.ilike(f"%{search}%")
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        # Order and paginate
        stmt = stmt.order_by(GlobalMasterTemplate.usage_count.desc()).offset(offset).limit(limit)

        # Execute queries
        result = await self.session.execute(stmt)
        count_result = await self.session.execute(count_stmt)

        templates = result.scalars().all()
        total_count = count_result.scalar()

        return templates, total_count

    async def update_template(
        self,
        template_id: int,
        update_data: Dict[str, Any],
        user_id: Optional[int] = None,
        allow_system_write: bool = False,
    ) -> bool:
        """Update a global master template"""
        effective_user_id = _effective_user_id(user_id)
        update_data['updated_at'] = time.time()
        stmt = update(GlobalMasterTemplate).where(GlobalMasterTemplate.id == template_id)
        if effective_user_id is not None:
            if allow_system_write:
                # Admin scoped write: allow own templates + system templates.
                stmt = stmt.where(
                    or_(
                        GlobalMasterTemplate.user_id == effective_user_id,
                        GlobalMasterTemplate.user_id.is_(None),
                    )
                )
            else:
                # Scoped users can only modify their own templates.
                stmt = stmt.where(GlobalMasterTemplate.user_id == effective_user_id)
        stmt = stmt.values(**update_data)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def delete_template(
        self,
        template_id: int,
        user_id: Optional[int] = None,
        allow_system_write: bool = False,
    ) -> bool:
        """Delete a global master template"""
        try:
            effective_user_id = _effective_user_id(user_id)
            stmt = delete(GlobalMasterTemplate).where(GlobalMasterTemplate.id == template_id)
            if effective_user_id is not None:
                if allow_system_write:
                    # Admin scoped write: allow own templates + system templates.
                    stmt = stmt.where(
                        or_(
                            GlobalMasterTemplate.user_id == effective_user_id,
                            GlobalMasterTemplate.user_id.is_(None),
                        )
                    )
                else:
                    # Scoped users can only delete their own templates.
                    stmt = stmt.where(GlobalMasterTemplate.user_id == effective_user_id)
            result = await self.session.execute(stmt)
            await self.session.commit()

            rows_affected = result.rowcount
            logger.info(f"Delete operation for template {template_id}: {rows_affected} rows affected")

            return rows_affected > 0
        except Exception as e:
            logger.error(f"Error deleting template {template_id}: {e}")
            await self.session.rollback()
            raise

    async def increment_usage_count(self, template_id: int, user_id: Optional[int] = None) -> bool:
        """Increment template usage count"""
        effective_user_id = _effective_user_id(user_id)
        stmt = update(GlobalMasterTemplate).where(GlobalMasterTemplate.id == template_id)
        if effective_user_id is not None:
            # Usage can be tracked for both user-owned and system templates.
            stmt = stmt.where(
                or_(
                    GlobalMasterTemplate.user_id == effective_user_id,
                    GlobalMasterTemplate.user_id.is_(None),
                )
            )
        stmt = stmt.values(
            usage_count=GlobalMasterTemplate.usage_count + 1,
            updated_at=time.time()
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def set_default_template(
        self,
        template_id: int,
        user_id: Optional[int] = None,
        allow_system_write: bool = False,
    ) -> bool:
        """Set a template as default (and unset others)"""
        effective_user_id = _effective_user_id(user_id)
        now = time.time()

        if effective_user_id is None:
            # Unscoped/system operation: preserve historical behavior.
            stmt = update(GlobalMasterTemplate).values(is_default=False, updated_at=now)
            await self.session.execute(stmt)

            stmt = update(GlobalMasterTemplate).where(GlobalMasterTemplate.id == template_id).values(
                is_default=True,
                updated_at=now
            )
            result = await self.session.execute(stmt)
            await self.session.commit()
            return result.rowcount > 0

        if allow_system_write:
            target_stmt = (
                select(GlobalMasterTemplate.id, GlobalMasterTemplate.user_id)
                .where(
                    GlobalMasterTemplate.id == template_id,
                    or_(
                        GlobalMasterTemplate.user_id == effective_user_id,
                        GlobalMasterTemplate.user_id.is_(None),
                    )
                )
                .limit(1)
            )
            target_result = await self.session.execute(target_stmt)
            target = target_result.first()
            if target is None:
                await self.session.rollback()
                return False

            target_user_id = target.user_id

            if target_user_id is None:
                # Admin/system scoped write: update only shared system templates.
                stmt = (
                    update(GlobalMasterTemplate)
                    .where(GlobalMasterTemplate.user_id.is_(None))
                    .values(is_default=False, updated_at=now)
                )
                await self.session.execute(stmt)

                stmt = (
                    update(GlobalMasterTemplate)
                    .where(
                        GlobalMasterTemplate.id == template_id,
                        GlobalMasterTemplate.user_id.is_(None),
                    )
                    .values(is_default=True, updated_at=now)
                )
                result = await self.session.execute(stmt)
                await self.session.commit()
                return result.rowcount > 0

        # Scoped user operation: only affect this user's templates.
        stmt = (
            update(GlobalMasterTemplate)
            .where(GlobalMasterTemplate.user_id == effective_user_id)
            .values(is_default=False, updated_at=now)
        )
        await self.session.execute(stmt)

        stmt = (
            update(GlobalMasterTemplate)
            .where(
                GlobalMasterTemplate.id == template_id,
                GlobalMasterTemplate.user_id == effective_user_id,
            )
            .values(is_default=True, updated_at=now)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def get_default_template(self, user_id: Optional[int] = None) -> Optional[GlobalMasterTemplate]:
        """Get the default template"""
        effective_user_id = _effective_user_id(user_id)

        if effective_user_id is not None:
            # Prefer user's own default template.
            user_default_stmt = (
                select(GlobalMasterTemplate)
                .where(
                    GlobalMasterTemplate.user_id == effective_user_id,
                    GlobalMasterTemplate.is_default == True,
                    GlobalMasterTemplate.is_active == True,
                )
                .order_by(GlobalMasterTemplate.updated_at.desc())
                .limit(1)
            )
            user_default_result = await self.session.execute(user_default_stmt)
            user_default = user_default_result.scalars().first()
            if user_default is not None:
                return user_default

            # Fall back to shared system default template.
            system_default_stmt = (
                select(GlobalMasterTemplate)
                .where(
                    GlobalMasterTemplate.user_id.is_(None),
                    GlobalMasterTemplate.is_default == True,
                    GlobalMasterTemplate.is_active == True,
                )
                .order_by(GlobalMasterTemplate.updated_at.desc())
                .limit(1)
            )
            system_default_result = await self.session.execute(system_default_stmt)
            return system_default_result.scalars().first()

        stmt = (
            select(GlobalMasterTemplate)
            .where(
                GlobalMasterTemplate.is_default == True,
                GlobalMasterTemplate.is_active == True,
            )
            .order_by(GlobalMasterTemplate.updated_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()



    async def delete_templates_by_project_id(self, project_id: str) -> bool:
        """Delete all templates for a project"""
        stmt = delete(PPTTemplate).where(PPTTemplate.project_id == project_id)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0


class CreditTransactionRepository:
    """Repository for CreditTransaction operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, transaction_data: Dict[str, Any]) -> CreditTransaction:
        """Create a new credit transaction"""
        transaction = CreditTransaction(**transaction_data)
        self.session.add(transaction)
        await self.session.commit()
        await self.session.refresh(transaction)
        return transaction
    
    async def get_user_transactions(
        self, 
        user_id: int, 
        page: int = 1, 
        page_size: int = 20,
        transaction_type: Optional[str] = None
    ) -> Tuple[List[CreditTransaction], int]:
        """Get transactions for a user with pagination"""
        stmt = select(CreditTransaction).where(CreditTransaction.user_id == user_id)
        count_stmt = select(func.count(CreditTransaction.id)).where(CreditTransaction.user_id == user_id)
        
        if transaction_type:
            stmt = stmt.where(CreditTransaction.transaction_type == transaction_type)
            count_stmt = count_stmt.where(CreditTransaction.transaction_type == transaction_type)
        
        stmt = stmt.order_by(CreditTransaction.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        
        result = await self.session.execute(stmt)
        count_result = await self.session.execute(count_stmt)
        
        return result.scalars().all(), count_result.scalar() or 0
    
    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Get credit statistics for a user"""
        # Total consumed
        consumed_stmt = select(func.sum(CreditTransaction.amount)).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.amount < 0
        )
        consumed_result = await self.session.execute(consumed_stmt)
        total_consumed = abs(consumed_result.scalar() or 0)
        
        # Total recharged
        recharged_stmt = select(func.sum(CreditTransaction.amount)).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.amount > 0
        )
        recharged_result = await self.session.execute(recharged_stmt)
        total_recharged = recharged_result.scalar() or 0
        
        # Transaction count
        count_stmt = select(func.count(CreditTransaction.id)).where(
            CreditTransaction.user_id == user_id
        )
        count_result = await self.session.execute(count_stmt)
        transaction_count = count_result.scalar() or 0
        
        return {
            "total_consumed": total_consumed,
            "total_recharged": total_recharged,
            "transaction_count": transaction_count
        }


class RedemptionCodeRepository:
    """Repository for RedemptionCode operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, code_data: Dict[str, Any]) -> RedemptionCode:
        """Create a new redemption code"""
        # Generate unique code if not provided
        if 'code' not in code_data:
            code_data['code'] = secrets.token_urlsafe(8).upper()
        
        code = RedemptionCode(**code_data)
        self.session.add(code)
        await self.session.commit()
        await self.session.refresh(code)
        return code
    
    async def create_batch(self, count: int, credits_amount: int, created_by: int, expires_at: Optional[float] = None, description: Optional[str] = None) -> List[RedemptionCode]:
        """Create multiple redemption codes at once"""
        codes = []
        for _ in range(count):
            code_data = {
                'code': secrets.token_urlsafe(8).upper(),
                'credits_amount': credits_amount,
                'created_by': created_by,
                'expires_at': expires_at,
                'description': description
            }
            code = RedemptionCode(**code_data)
            self.session.add(code)
            codes.append(code)
        
        await self.session.commit()
        for code in codes:
            await self.session.refresh(code)
        return codes
    
    async def get_by_code(self, code: str) -> Optional[RedemptionCode]:
        """Get redemption code by code string"""
        stmt = select(RedemptionCode).where(RedemptionCode.code == code.upper())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def use_code(self, code: str, user_id: int) -> Optional[RedemptionCode]:
        """Mark a code as used by a user"""
        redemption_code = await self.get_by_code(code)
        if not redemption_code or not redemption_code.is_valid():
            return None
        
        redemption_code.is_used = True
        redemption_code.used_by = user_id
        redemption_code.used_at = time.time()
        
        await self.session.commit()
        await self.session.refresh(redemption_code)
        return redemption_code
    
    async def list_codes(
        self, 
        page: int = 1, 
        page_size: int = 20,
        is_used: Optional[bool] = None,
        created_by: Optional[int] = None,
        search: Optional[str] = None
    ) -> Tuple[List[RedemptionCode], int]:
        """List redemption codes with pagination"""
        stmt = select(RedemptionCode)
        count_stmt = select(func.count(RedemptionCode.id))
        
        if is_used is not None:
            stmt = stmt.where(RedemptionCode.is_used == is_used)
            count_stmt = count_stmt.where(RedemptionCode.is_used == is_used)
        
        if created_by is not None:
            stmt = stmt.where(RedemptionCode.created_by == created_by)
            count_stmt = count_stmt.where(RedemptionCode.created_by == created_by)

        if search:
            from sqlalchemy import or_
            search_filter = or_(
                RedemptionCode.code.ilike(f"%{search}%"),
                RedemptionCode.description.ilike(f"%{search}%")
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)
        
        stmt = stmt.order_by(RedemptionCode.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        
        result = await self.session.execute(stmt)
        count_result = await self.session.execute(count_stmt)
        
        return result.scalars().all(), count_result.scalar() or 0
    
    async def delete_code(self, code_id: int) -> bool:
        """Delete a redemption code (only if unused)"""
        stmt = delete(RedemptionCode).where(
            RedemptionCode.id == code_id,
            RedemptionCode.is_used == False
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0


class UserRepository:
    """Repository for User operations (async version)"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        stmt = select(User).where(User.id == user_id).options(selectinload(User.metrics))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def update_credits_balance(self, user_id: int, new_balance: int) -> bool:
        """Update user's credits balance"""
        stmt = update(User).where(User.id == user_id).values(credits_balance=new_balance)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0
    
    async def add_credits(self, user_id: int, amount: int) -> Optional[int]:
        """Add credits to user balance and return new balance"""
        user = await self.get_by_id(user_id)
        if not user:
            return None
        
        new_balance = user.credits_balance + amount
        if new_balance < 0:
            return None  # Cannot go negative
        
        await self.update_credits_balance(user_id, new_balance)
        return new_balance
    
    async def list_users(
        self, 
        page: int = 1, 
        page_size: int = 20,
        is_active: Optional[bool] = None,
        is_admin: Optional[bool] = None,
        search: Optional[str] = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> Tuple[List[User], int]:
        """List users with pagination"""
        from sqlalchemy import or_
        
        stmt = select(User).options(selectinload(User.metrics))
        count_stmt = select(func.count(User.id))
        
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)
            count_stmt = count_stmt.where(User.is_active == is_active)

        if is_admin is not None:
            stmt = stmt.where(User.is_admin == is_admin)
            count_stmt = count_stmt.where(User.is_admin == is_admin)
        
        if search:
            search_filter = or_(
                User.username.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
            stmt = stmt.where(search_filter)
            count_stmt = count_stmt.where(search_filter)

        metric_sorts = {
            "projects_count": func.coalesce(UserMetrics.projects_count, 0),
            "credits_consumed_total": func.coalesce(UserMetrics.credits_consumed_total, 0),
            "last_active_at": UserMetrics.last_active_at,
        }
        sort_key = (sort_by or "").strip()
        if sort_key in metric_sorts:
            stmt = stmt.outerjoin(UserMetrics, UserMetrics.user_id == User.id)

        allowed_sorts = {
            "id": User.id,
            "username": User.username,
            "email": User.email,
            "is_active": User.is_active,
            "is_admin": User.is_admin,
            "credits_balance": User.credits_balance,
            "created_at": User.created_at,
            "last_login": User.last_login,
            **metric_sorts,
        }

        sort_col = allowed_sorts.get(sort_key, User.created_at)
        direction = (sort_dir or "desc").strip().lower()
        direction = "asc" if direction == "asc" else "desc"
        order_expr = sort_col.asc() if direction == "asc" else sort_col.desc()
        if sort_key in {"email", "last_login", "last_active_at"}:
            order_expr = order_expr.nulls_last()

        stmt = stmt.order_by(order_expr, User.id.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        
        result = await self.session.execute(stmt)
        count_result = await self.session.execute(count_stmt)
        
        return result.scalars().all(), count_result.scalar() or 0


class UserConfigRepository:
    """Repository for user-specific configuration operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_config(self, user_id: Optional[int], key: str) -> Optional[str]:
        """
        Get config value for user, falling back to system default.
        
        Args:
            user_id: User ID (None = system default only)
            key: Configuration key
            
        Returns:
            Config value or None
        """
        # First try user-specific config if user_id provided
        if user_id is not None:
            stmt = select(UserConfig).where(
                UserConfig.user_id == user_id,
                UserConfig.config_key == key
            )
            result = await self.session.execute(stmt)
            config = result.scalar_one_or_none()
            if config and config.config_value is not None:
                return config.config_value
        
        # Fall back to system default (user_id = NULL)
        stmt = select(UserConfig).where(
            UserConfig.user_id.is_(None),
            UserConfig.config_key == key
        )
        result = await self.session.execute(stmt)
        config = result.scalar_one_or_none()
        return config.config_value if config else None
    
    async def get_all_configs(self, user_id: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
        """
        Get all configs for user, merged with system defaults.
        
        Returns dict of {key: {value, type, category}}
        """
        configs = {}
        
        # First get all system defaults
        stmt = select(UserConfig).where(UserConfig.user_id.is_(None))
        result = await self.session.execute(stmt)
        system_configs = result.scalars().all()
        
        for config in system_configs:
            configs[config.config_key] = {
                "value": config.config_value,
                "type": config.config_type,
                "category": config.category,
                "is_user_override": False
            }
        
        # Then overlay with user-specific configs
        if user_id is not None:
            stmt = select(UserConfig).where(UserConfig.user_id == user_id)
            result = await self.session.execute(stmt)
            user_configs = result.scalars().all()
            
            for config in user_configs:
                configs[config.config_key] = {
                    "value": config.config_value,
                    "type": config.config_type,
                    "category": config.category,
                    "is_user_override": True
                }
        
        return configs
    
    async def get_configs_by_category(self, user_id: Optional[int], category: str) -> Dict[str, str]:
        """Get configs for a specific category, with user overrides"""
        all_configs = await self.get_all_configs(user_id)
        return {
            key: info["value"]
            for key, info in all_configs.items()
            if info["category"] == category
        }
    
    async def set_config(self, user_id: Optional[int], key: str, value: str,
                        config_type: str = "text", category: str = "general") -> bool:
        """
        Set config value for user (upsert).
        
        Args:
            user_id: User ID (None = system default)
            key: Configuration key
            value: Configuration value
            config_type: Type of config (text, password, number, boolean, json)
            category: Category of config
        """
        try:
            # Check if config exists
            if user_id is not None:
                stmt = select(UserConfig).where(
                    UserConfig.user_id == user_id,
                    UserConfig.config_key == key
                )
            else:
                stmt = select(UserConfig).where(
                    UserConfig.user_id.is_(None),
                    UserConfig.config_key == key
                )
            
            result = await self.session.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing
                existing.config_value = value
                existing.config_type = config_type
                existing.category = category
                existing.updated_at = time.time()
            else:
                # Create new
                new_config = UserConfig(
                    user_id=user_id,
                    config_key=key,
                    config_value=value,
                    config_type=config_type,
                    category=category
                )
                self.session.add(new_config)
            
            await self.session.flush()
            return True
            
        except Exception as e:
            logger.error(f"Error setting config {key} for user {user_id}: {e}")
            return False
    
    async def delete_config(self, user_id: int, key: str) -> bool:
        """
        Delete user-specific config (reverts to system default).
        
        Only deletes user overrides, not system defaults.
        """
        if user_id is None:
            logger.warning("Cannot delete system config via delete_config")
            return False
        
        try:
            stmt = delete(UserConfig).where(
                UserConfig.user_id == user_id,
                UserConfig.config_key == key
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting config {key} for user {user_id}: {e}")
            return False
    
    async def reset_user_configs(self, user_id: int, category: Optional[str] = None) -> int:
        """
        Reset all user configs (or a category) to system defaults.
        
        Returns number of deleted configs.
        """
        if user_id is None:
            return 0
        
        try:
            stmt = delete(UserConfig).where(UserConfig.user_id == user_id)
            if category:
                stmt = stmt.where(UserConfig.category == category)
            
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount
        except Exception as e:
            logger.error(f"Error resetting configs for user {user_id}: {e}")
            return 0
    
    async def copy_system_defaults_to_user(self, user_id: int) -> int:
        """
        Copy all system default configs to user as overrides.
        
        Useful for initializing new user configs.
        """
        if user_id is None:
            return 0
        
        try:
            # Get all system defaults
            stmt = select(UserConfig).where(UserConfig.user_id.is_(None))
            result = await self.session.execute(stmt)
            system_configs = result.scalars().all()
            
            count = 0
            for config in system_configs:
                # Check if user already has this config
                check_stmt = select(UserConfig).where(
                    UserConfig.user_id == user_id,
                    UserConfig.config_key == config.config_key
                )
                check_result = await self.session.execute(check_stmt)
                if check_result.scalar_one_or_none() is None:
                    new_config = UserConfig(
                        user_id=user_id,
                        config_key=config.config_key,
                        config_value=config.config_value,
                        config_type=config.config_type,
                        category=config.category
                    )
                    self.session.add(new_config)
                    count += 1
            
            await self.session.flush()
            return count
        except Exception as e:
            logger.error(f"Error copying configs for user {user_id}: {e}")
            return 0
