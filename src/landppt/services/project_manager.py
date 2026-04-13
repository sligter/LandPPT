"""
Project and TODO Board Management Service
Implements the comprehensive project lifecycle management as specified in requires.md
"""

import uuid
import time
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from ..api.models import (
    PPTProject, TodoBoard, TodoStage, ProjectListResponse,
    PPTGenerationRequest, PPTOutline, EnhancedPPTOutline
)

# Configure logger for this module
logger = logging.getLogger(__name__)


class ProjectManager:
    """Manages PPT projects with TODO board workflow"""
    
    def __init__(self):
        self.projects: Dict[str, PPTProject] = {}
        self.todo_boards: Dict[str, TodoBoard] = {}

    @staticmethod
    def _normalize_progress(progress: Any) -> float:
        try:
            value = float(progress)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(100.0, value))

    @classmethod
    def calculate_overall_progress(cls, stages: List[TodoStage]) -> float:
        if not stages:
            return 0.0
        return sum(cls._normalize_progress(stage.progress) for stage in stages) / len(stages)
    
    async def create_project(self, request: PPTGenerationRequest) -> PPTProject:
        """Create a new PPT project with TODO board"""
        project_id = str(uuid.uuid4())
        
        # Create TODO board with 5 stages as per requirements
        todo_board = self._create_todo_board(project_id, request)
        
        project = PPTProject(
            project_id=project_id,
            title=f"{request.topic} - {request.scenario}",
            scenario=request.scenario,
            topic=request.topic,
            requirements=request.requirements,
            status="draft",
            todo_board=todo_board
        )
        
        self.projects[project_id] = project
        self.todo_boards[project_id] = todo_board
        
        return project
    
    def _create_todo_board(self, project_id: str, request: PPTGenerationRequest) -> TodoBoard:
        """Create initial TODO board with placeholder stages (will be updated after requirements confirmation)"""
        stages = [
            TodoStage(
                id="requirements_confirmation",
                name="需求确认",
                description="AI根据用户设定的场景和上传的文件内容提供补充信息用来确认用户的任务需求",
                subtasks=[
                    "生成需求确认表单，包含Topic/Type/Content focus/Tech highlights/Target audience等字段"
                ]
            )
        ]

        return TodoBoard(
            task_id=project_id,
            title={request.topic},
            stages=stages
        )

    def update_todo_board_with_confirmed_requirements(self, project_id: str, confirmed_requirements: Dict[str, Any]) -> bool:
        """Update TODO board with full workflow after requirements confirmation"""
        try:
            todo_board = self.todo_boards.get(project_id)
            if not todo_board:
                return False

            # Create simplified workflow stages - 只有3个阶段
            stages = [
                TodoStage(
                    id="requirements_confirmation",
                    name="需求确认",
                    description="确认PPT主题、内容重点、技术亮点和目标受众",
                    status="completed",  # This stage is completed when requirements are confirmed
                    progress=100.0,
                    subtasks=["需求确认完成"]  # Simplified - only title
                ),
                TodoStage(
                    id="outline_generation",
                    name="大纲生成",
                    description="基于确认的需求生成PPT大纲结构",
                    status="pending",  # Start as pending
                    progress=0.0,
                    subtasks=["生成PPT大纲"]  # Simplified - only title
                ),
                TodoStage(
                    id="ppt_creation",
                    name="PPT生成",
                    description="根据大纲生成完整的PPT页面",
                    status="pending",  # Start as pending
                    progress=0.0,
                    subtasks=["PPT生成"]  # Simplified - only title
                )
            ]

            todo_board.stages = stages
            todo_board.updated_at = time.time()

            # Recalculate overall progress correctly
            todo_board.overall_progress = self.calculate_overall_progress(stages)

            # Set current stage index to the first non-completed stage
            todo_board.current_stage_index = 0
            for i, stage in enumerate(stages):
                if stage.status != "completed":
                    todo_board.current_stage_index = i
                    break

            return True

        except Exception as e:
            print(f"Error updating TODO board: {e}")
            return False
    
    async def get_project(self, project_id: str) -> Optional[PPTProject]:
        """Get project by ID from memory only"""
        return self.projects.get(project_id)
    
    async def list_projects(self, page: int = 1, page_size: int = 10, 
                          status: Optional[str] = None) -> ProjectListResponse:
        """List projects with pagination"""
        projects = list(self.projects.values())
        
        # Filter by status if provided
        if status:
            projects = [p for p in projects if p.status == status]
        
        # Sort by updated_at descending
        projects.sort(key=lambda x: x.updated_at, reverse=True)
        
        # Pagination
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_projects = projects[start_idx:end_idx]
        
        return ProjectListResponse(
            projects=paginated_projects,
            total=len(projects),
            page=page,
            page_size=page_size
        )
    
    async def update_project_status(self, project_id: str, status: str) -> bool:
        """Update project status"""
        if project_id in self.projects:
            self.projects[project_id].status = status
            self.projects[project_id].updated_at = time.time()
            return True
        return False
    
    async def get_todo_board(self, project_id: str) -> Optional[TodoBoard]:
        """Get TODO board for project"""
        return self.todo_boards.get(project_id)
    
    async def update_stage_status(self, project_id: str, stage_id: str, 
                                status: str, progress: float = None,
                                result: Dict[str, Any] = None) -> bool:
        """Update stage status in TODO board"""
        todo_board = self.todo_boards.get(project_id)
        if not todo_board:
            return False
        
        # Find and update stage
        for i, stage in enumerate(todo_board.stages):
            if stage.id == stage_id:
                stage.status = status
                stage.updated_at = time.time()
                
                if progress is not None:
                    stage.progress = self._normalize_progress(progress)
                elif status == "completed":
                    stage.progress = 100.0
                
                if result is not None:
                    stage.result = result
                
                # Update current stage index if this stage is completed
                if status == "completed" and i == todo_board.current_stage_index:
                    todo_board.current_stage_index = min(i + 1, len(todo_board.stages) - 1)

                # Update overall progress
                todo_board.overall_progress = self.calculate_overall_progress(todo_board.stages)
                todo_board.updated_at = time.time()

                # Also update the project's TODO board reference
                if project_id in self.projects:
                    self.projects[project_id].todo_board = todo_board
                    self.projects[project_id].updated_at = time.time()

                logger.info(f"Updated stage {stage_id} to {status}, overall progress: {todo_board.overall_progress}%")
                
                return True
        
        return False
    
    async def add_subtask(self, project_id: str, stage_id: str, subtask: str) -> bool:
        """Add subtask to a stage"""
        todo_board = self.todo_boards.get(project_id)
        if not todo_board:
            return False
        
        for stage in todo_board.stages:
            if stage.id == stage_id:
                stage.subtasks.append(subtask)
                stage.updated_at = time.time()
                return True
        
        return False
    
    async def save_project_version(self, project_id: str, version_data: Dict[str, Any]) -> bool:
        """Save a version of the project"""
        project = self.projects.get(project_id)
        if not project:
            return False
        
        version_info = {
            "version": project.version,
            "timestamp": time.time(),
            "data": version_data,
            "description": f"Version {project.version} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
        
        project.versions.append(version_info)
        project.version += 1
        project.updated_at = time.time()
        
        return True
    
    async def get_project_versions(self, project_id: str) -> List[Dict[str, Any]]:
        """Get all versions of a project"""
        project = self.projects.get(project_id)
        if not project:
            return []
        
        return project.versions
    
    async def restore_project_version(self, project_id: str, version: int) -> bool:
        """Restore project to a specific version"""
        project = self.projects.get(project_id)
        if not project:
            return False
        
        # Find the version
        target_version = None
        for v in project.versions:
            if v["version"] == version:
                target_version = v
                break
        
        if not target_version:
            return False
        
        # Restore the data
        version_data = target_version["data"]
        if "outline" in version_data:
            project.outline = PPTOutline(**version_data["outline"])
        if "slides_html" in version_data:
            project.slides_html = version_data["slides_html"]
        
        project.updated_at = time.time()
        return True
    
    async def delete_project(self, project_id: str) -> bool:
        """Delete a project"""
        if project_id in self.projects:
            del self.projects[project_id]
            if project_id in self.todo_boards:
                del self.todo_boards[project_id]
            return True
        return False
    
    async def archive_project(self, project_id: str) -> bool:
        """Archive a project"""
        return await self.update_project_status(project_id, "archived")
