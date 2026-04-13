"""
LandPPT specific API endpoints
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Depends
from typing import List, Optional

from ..auth.middleware import get_current_user_required
from ..database.models import User
import uuid
import json
import logging
import re

from .models import (
    PPTScenario, PPTGenerationRequest, PPTGenerationResponse,
    PPTOutline, PPTProject, TodoBoard, ProjectListResponse,
    FileUploadResponse, SlideContent, FileOutlineGenerationRequest,
    FileOutlineGenerationResponse, TemplateSelectionRequest, TemplateSelectionResponse
)
from ..services.service_instances import ppt_service, get_ppt_service_for_user
from ..services.file_processor import FileProcessor
from ..services.deep_research_service import DEEPResearchService
from ..services.research_report_generator import ResearchReportGenerator
from ..core.config import ai_config, resolve_timeout_seconds


def filter_think_tags(content: str) -> str:
    """
    Filter out think tags from content - supports multiple formats
    """
    if not content:
        return content

    # Patterns for different think tag formats
    # Note: We add capturing groups to preserve surrounding whitespace
    patterns = [
        r'(\s*)<think[\s\S]*?></think>(\s*)',           # <think>...</think> with whitespace
        r'(\s*)<think[\s\S]*?/>(\s*)',                  # <think.../> with whitespace
        r'(\s*)<think>[\s\S]*?</think>(\s*)',            # <tool_call>...</think> with whitespace
    ]

    filtered_content = content
    # Keep applying patterns until no more matches (handles nested or multiple tags)
    max_iterations = 10
    for _ in range(max_iterations):
        new_content = filtered_content
        for pattern in patterns:
            new_content = re.sub(pattern, r'\1\2', new_content, flags=re.IGNORECASE)
        if new_content == filtered_content:
            break
        filtered_content = new_content

    # Clean up whitespace
    # Remove multiple consecutive empty lines (more than 2)
    filtered_content = re.sub(r'\n\s*\n\s*\n+', '\n\n', filtered_content)

    # Remove empty lines at the beginning and end
    filtered_content = filtered_content.strip()

    # Clean up extra spaces within lines (but preserve single spaces)
    filtered_content = re.sub(r' {2,}', ' ', filtered_content)

    return filtered_content


router = APIRouter()
logger = logging.getLogger(__name__)
file_processor = FileProcessor()

# Research services (lazy initialization)
_research_service = None
_report_generator = None
_enhanced_research_service = None
_enhanced_report_generator = None

def get_research_service():
    """Get research service instance (lazy initialization)"""
    global _research_service
    if _research_service is None:
        try:
            _research_service = DEEPResearchService()
            logger.info("Research service initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize research service: {e}")
    return _research_service

def reload_research_service():
    """Reload research service to pick up new configuration"""
    global _research_service
    logger.info("Reloading research service...")

    if _research_service is not None:
        try:
            _research_service.reload_config()
            logger.info("Research service configuration reloaded successfully")

            # Verify the service is still available after reload
            if not _research_service.is_available():
                logger.warning("Research service is not available after reload, will recreate on next access")
                _research_service = None

        except Exception as e:
            logger.warning(f"Failed to reload research service config: {e}")
            # If reload fails, recreate the service
            _research_service = None
    else:
        # If service doesn't exist, force recreation on next access
        logger.info("Research service will be recreated on next access with new configuration")

def get_report_generator():
    """Get report generator instance (lazy initialization)"""
    global _report_generator
    if _report_generator is None:
        try:
            _report_generator = ResearchReportGenerator()
            logger.info("Report generator initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize report generator: {e}")
    return _report_generator


def get_enhanced_research_service():
    """Get enhanced research service instance (lazy initialization)"""
    global _enhanced_research_service
    if _enhanced_research_service is None:
        try:
            from ..services.research.enhanced_research_service import EnhancedResearchService
            _enhanced_research_service = EnhancedResearchService()
            logger.info("Enhanced research service initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize enhanced research service: {e}")
    return _enhanced_research_service


def get_enhanced_report_generator():
    """Get enhanced report generator instance (lazy initialization)"""
    global _enhanced_report_generator
    if _enhanced_report_generator is None:
        try:
            from ..services.research.enhanced_report_generator import EnhancedReportGenerator
            _enhanced_report_generator = EnhancedReportGenerator()
            logger.info("Enhanced report generator initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize enhanced report generator: {e}")
    return _enhanced_report_generator

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "LandPPT API",
        "version": "0.1.0",
        "ai_provider": ai_config.default_ai_provider,
        "available_providers": ai_config.get_available_providers()
    }

@router.get("/ai/providers")
async def get_ai_providers():
    """Get available AI providers"""
    # Get all providers (built-in only)
    all_providers = ai_config.get_available_providers()

    return {
        "default_provider": ai_config.default_ai_provider,
        "available_providers": all_providers,
        "provider_status": {
            provider: ai_config.is_provider_available(provider)
            for provider in all_providers
        }
    }

@router.post("/ai/providers/{provider_name}/test")
async def test_ai_provider(provider_name: str, request: Request):
    """Test a specific AI provider - uses frontend provided config if available"""
    # Anthropic has its own dedicated proxy endpoint in routes.py
    if provider_name == "anthropic":
        raise HTTPException(
            status_code=400,
            detail="Anthropic testing is handled by a dedicated endpoint. Please use the frontend test function."
        )

    try:
        import aiohttp
        import json

        # Try to get configuration from request body (if provided by frontend)
        body = None
        try:
            body = await request.json()
        except:
            pass  # No JSON body, use backend config

        # Special handling for OpenAI provider with frontend config
        if provider_name == "openai" and body:
            base_url = body.get('base_url')
            api_key = body.get('api_key')
            model = body.get('model', 'gpt-4o')
            
            if base_url and api_key:
                # Use frontend provided config for OpenAI
                logger.info(f"Testing OpenAI with frontend config: {base_url}")
                
                # Ensure base URL ends with /v1
                if not base_url.endswith('/v1'):
                    base_url = base_url.rstrip('/') + '/v1'
                
                chat_url = f"{base_url}/chat/completions"
                timeout_seconds = resolve_timeout_seconds(
                    body.get("llm_timeout_seconds") if isinstance(body, dict) else None,
                    ai_config.llm_timeout_seconds,
                )
                
                async with aiohttp.ClientSession() as session:
                    headers = {
                        'Authorization': f'Bearer {api_key}',
                        'Content-Type': 'application/json'
                    }
                    
                    payload = {
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": "Say 'Hello, I am working!' in exactly 5 words."
                            }
                        ],
                        "temperature": 0
                    }
                    
                    async with session.post(
                        chat_url,
                        headers=headers,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            # Apply think tag filtering to the response
                            raw_content = data['choices'][0]['message']['content']
                            filtered_content = filter_think_tags(raw_content)
                            return {
                                "provider": provider_name,
                                "status": "success",
                                "model": model,
                                "response_preview": filtered_content,
                                "usage": data.get('usage', {})
                            }
                        else:
                            error_text = await response.text()
                            raise HTTPException(status_code=response.status, detail=f"API error: {error_text}")
        
        # Fallback to backend config for other providers or when no frontend config
        from ..ai import AIProviderFactory, AIMessage, MessageRole

        if not ai_config.is_provider_available(provider_name):
            raise HTTPException(status_code=400, detail=f"Provider {provider_name} is not available")

        # Create provider instance with backend config
        provider = AIProviderFactory.create_provider(provider_name)

        # Test with a simple message
        test_message = AIMessage(
            role=MessageRole.USER,
            content="Hello, please respond with a brief greeting."
        )

        response = await provider.chat_completion([test_message])

        # Apply think tag filtering to the response content
        filtered_content = filter_think_tags(response.content)

        return {
            "provider": provider_name,
            "status": "success",
            "model": response.model,
            "response_preview": filtered_content[:100] + "..." if len(filtered_content) > 100 else filtered_content,
            "usage": response.usage
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Provider test failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Provider test failed: {str(e)}")

@router.get("/scenarios", response_model=List[PPTScenario])
async def get_scenarios():
    """Get available PPT scenarios - Updated to match requires.md specifications"""
    return [
        PPTScenario(
            id="general",
            name="通用",
            description="适用于各种通用场景的PPT模板，提供专业的商务风格",
            icon="📋",
            template_config={"style": "professional", "color_scheme": "blue", "font_family": "Arial, sans-serif"}
        ),
        PPTScenario(
            id="tourism",
            name="旅游观光",
            description="旅游线路策划、景点介绍、行程规划等旅游相关内容",
            icon="🌍",
            template_config={"style": "vibrant", "color_scheme": "green", "font_family": "Georgia, serif"}
        ),
        PPTScenario(
            id="education",
            name="儿童科普",
            description="教育培训、科普知识、儿童友好的设计风格",
            icon="🎓",
            template_config={"style": "playful", "color_scheme": "rainbow", "font_family": "Comic Sans MS, cursive"}
        ),
        PPTScenario(
            id="analysis",
            name="深入分析",
            description="数据分析、研究报告、学术论文等专业分析内容",
            icon="📊",
            template_config={"style": "analytical", "color_scheme": "dark", "font_family": "Helvetica, sans-serif"}
        ),
        PPTScenario(
            id="history",
            name="历史文化",
            description="历史事件、文化传承、人文艺术等主题",
            icon="🏛️",
            template_config={"style": "classical", "color_scheme": "brown", "font_family": "Times New Roman, serif"}
        ),
        PPTScenario(
            id="technology",
            name="科技技术",
            description="技术介绍、产品发布、创新展示等科技内容",
            icon="💻",
            template_config={"style": "modern", "color_scheme": "purple", "font_family": "Roboto, sans-serif"}
        ),
        PPTScenario(
            id="business",
            name="方案汇报",
            description="商业计划、项目汇报、企业展示等商务场景",
            icon="💼",
            template_config={"style": "corporate", "color_scheme": "navy", "font_family": "Arial, sans-serif"}
        )
    ]

# Legacy PPT generation endpoint removed - now using project-based workflow
# Use POST /projects to create a new project instead

@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload document for PPT generation"""
    try:
        # Validate file type
        allowed_types = [".docx", ".pdf", ".txt", ".md"]
        file_extension = "." + file.filename.split(".")[-1].lower()
        
        if file_extension not in allowed_types:
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported file type. Allowed types: {', '.join(allowed_types)}"
            )
        
        # Read file content
        content = await file.read()
        
        # Process file based on type
        processed_content = await ppt_service.process_uploaded_file(
            filename=file.filename,
            content=content,
            file_type=file_extension
        )
        
        return {
            "filename": file.filename,
            "size": len(content),
            "type": file_extension,
            "processed_content": processed_content,
            "message": "File uploaded and processed successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

# Legacy task management endpoints removed - now using project-based workflow
# Use /projects endpoints for project management instead

@router.post("/outline/generate")
async def generate_outline(request: PPTGenerationRequest):
    """Generate PPT outline only"""
    try:
        outline = await ppt_service.generate_outline(request)
        return {"outline": outline, "status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating outline: {str(e)}")

# New Project Management Endpoints

@router.post("/projects", response_model=PPTProject)
async def create_project(
    request: PPTGenerationRequest,
    user: User = Depends(get_current_user_required)
):
    """Create a new PPT project with TODO workflow"""
    try:
        # Ensure user_id is set from authenticated user
        request.user_id = user.id
        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.create_project_with_workflow(request)
        return project

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating project: {str(e)}")

@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    page: int = 1,
    page_size: int = 10,
    status: Optional[str] = None,
    user: User = Depends(get_current_user_required)
):
    """List projects with pagination - only returns projects owned by current user"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        return await user_ppt_service.project_manager.list_projects(
            page=page, page_size=page_size, status=status, user_id=user.id
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing projects: {str(e)}")

@router.get("/projects/{project_id}", response_model=PPTProject)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user_required)
):
    """Get project details - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting project: {str(e)}")

@router.get("/projects/{project_id}/todo", response_model=TodoBoard)
async def get_project_todo_board(
    project_id: str,
    user: User = Depends(get_current_user_required)
):
    """Get TODO board for a project - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        todo_board = await user_ppt_service.get_project_todo_board(project_id, user_id=user.id)
        if not todo_board:
            raise HTTPException(status_code=404, detail="TODO board not found")
        return todo_board

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting TODO board: {str(e)}")

@router.put("/projects/{project_id}/stages/{stage_id}")
async def update_project_stage(
    project_id: str,
    stage_id: str,
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Update project stage status - enforces user ownership"""
    try:
        # Parse JSON body
        body = await request.json()
        status = body.get("status")
        progress = body.get("progress")

        if not status:
            raise HTTPException(status_code=422, detail="Status is required")

        user_ppt_service = get_ppt_service_for_user(user.id)
        success = await user_ppt_service.update_project_stage(
            project_id, stage_id, status, progress, user_id=user.id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Project or stage not found")
        return {"status": "success", "message": "Stage updated successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating stage: {str(e)}")

@router.post("/projects/{project_id}/continue-from-stage")
async def continue_from_stage(
    project_id: str,
    request: Request,
    user: User = Depends(get_current_user_required)
):
    """Continue project workflow from a specific stage - enforces user ownership"""
    try:
        # Parse JSON body
        body = await request.json()
        stage_id = body.get("stage_id")

        if not stage_id:
            raise HTTPException(status_code=422, detail="Stage ID is required")

        # Get project with user ownership check
        user_ppt_service = get_ppt_service_for_user(user.id)
        project = await user_ppt_service.project_manager.get_project(project_id, user_id=user.id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Reset stages from the specified stage onwards
        success = await user_ppt_service.reset_stages_from(project_id, stage_id, user_id=user.id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to reset stages")

        # Start workflow from the specified stage
        await user_ppt_service.start_workflow_from_stage(project_id, stage_id, user_id=user.id)

        return {
            "status": "success",
            "message": f"Workflow restarted from stage: {stage_id}",
            "project_id": project_id,
            "stage_id": stage_id
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error continuing from stage: {str(e)}")



@router.post("/projects/{project_id}/slides/{slide_index}/lock")
async def lock_slide(
    project_id: str,
    slide_index: int,
    user: User = Depends(get_current_user_required)
):
    """Lock a slide to prevent regeneration - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        success = await user_ppt_service.lock_slide(project_id, slide_index, user_id=user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Slide not found")
        return {"status": "success", "message": "Slide locked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error locking slide: {str(e)}")

@router.post("/projects/{project_id}/slides/{slide_index}/unlock")
async def unlock_slide(
    project_id: str,
    slide_index: int,
    user: User = Depends(get_current_user_required)
):
    """Unlock a slide to allow regeneration - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        success = await user_ppt_service.unlock_slide(project_id, slide_index, user_id=user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Slide not found")
        return {"status": "success", "message": "Slide unlocked successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error unlocking slide: {str(e)}")

@router.get("/projects/{project_id}/versions")
async def get_project_versions(
    project_id: str,
    user: User = Depends(get_current_user_required)
):
    """Get all versions of a project - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        versions = await user_ppt_service.project_manager.get_project_versions(project_id, user_id=user.id)
        return {"versions": versions, "status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting project versions: {str(e)}")

@router.post("/projects/{project_id}/versions/{version}/restore")
async def restore_project_version(
    project_id: str,
    version: int,
    user: User = Depends(get_current_user_required)
):
    """Restore project to a specific version - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        success = await user_ppt_service.project_manager.restore_project_version(
            project_id, version, user_id=user.id
        )
        if not success:
            raise HTTPException(status_code=404, detail="Project or version not found")
        return {"status": "success", "message": "Project restored successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error restoring project version: {str(e)}")

@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user_required)
):
    """Delete a project - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        success = await user_ppt_service.project_manager.delete_project(project_id, user_id=user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"status": "success", "message": "Project deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting project: {str(e)}")

@router.post("/projects/{project_id}/archive")
async def archive_project(
    project_id: str,
    user: User = Depends(get_current_user_required)
):
    """Archive a project - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        success = await user_ppt_service.project_manager.archive_project(project_id, user_id=user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"status": "success", "message": "Project archived successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error archiving project: {str(e)}")

# File Upload Endpoints

@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(file: UploadFile = File(...)):
    """Upload and process document file"""
    try:
        # Validate file
        is_valid, message = file_processor.validate_file(file.filename, file.size)
        if not is_valid:
            raise HTTPException(status_code=400, detail=message)

        # Save uploaded file temporarily
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # Process the file
            result = await file_processor.process_file(temp_file_path, file.filename)
            return result

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

@router.get("/upload/formats")
async def get_supported_formats():
    """Get supported file formats"""
    try:
        formats = file_processor.get_supported_formats()
        return {
            "supported_formats": formats,
            "max_size_mb": 100,
            "description": "支持的文件格式和上传限制"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting formats: {str(e)}")

@router.post("/upload/create-project", response_model=PPTProject)
async def create_project_from_upload(
    file: UploadFile = File(...),
    topic: Optional[str] = Form(None),
    scenario: Optional[str] = Form(None),
    requirements: Optional[str] = Form(None),
    language: str = Form("zh"),
    user: User = Depends(get_current_user_required)
):
    """Upload file and create project directly - associates with current user"""
    try:
        # Validate and process file
        is_valid, message = file_processor.validate_file(file.filename, file.size)
        if not is_valid:
            raise HTTPException(status_code=400, detail=message)

        # Save and process file
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # Process file
            file_result = await file_processor.process_file(temp_file_path, file.filename)

            # Create PPT request from content
            ppt_data = await file_processor.create_ppt_from_content(
                file_result.processed_content,
                topic
            )

            # Override with user inputs if provided
            if topic:
                ppt_data['topic'] = topic
            if scenario:
                ppt_data['scenario'] = scenario
            if requirements:
                ppt_data['requirements'] = requirements

            # Create project request with user_id
            project_request = PPTGenerationRequest(**ppt_data)
            project_request.user_id = user.id

            # Create project with workflow
            user_ppt_service = get_ppt_service_for_user(user.id)
            project = await user_ppt_service.create_project_with_workflow(project_request)

            return project

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating project from upload: {str(e)}")

@router.post("/upload/analyze")
async def analyze_uploaded_content(file: UploadFile = File(...)):
    """Analyze uploaded file and suggest PPT structure"""
    try:
        # Validate file
        is_valid, message = file_processor.validate_file(file.filename, file.size)
        if not is_valid:
            raise HTTPException(status_code=400, detail=message)

        # Save and process file
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name

        try:
            # Process file
            file_result = await file_processor.process_file(temp_file_path, file.filename)

            # Create suggested PPT structure
            ppt_suggestion = await file_processor.create_ppt_from_content(file_result.processed_content)

            return {
                "file_info": file_result,
                "ppt_suggestion": ppt_suggestion,
                "status": "success"
            }

        finally:
            # Clean up temporary file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing file: {str(e)}")

@router.post("/slides/generate")
async def generate_slides(outline: PPTOutline, scenario: str = "general"):
    """Generate slides from outline"""
    try:
        slides_html = await ppt_service.generate_slides_from_outline(outline, scenario)
        return {"slides_html": slides_html, "status": "success"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating slides: {str(e)}")

@router.post("/files/generate-outline", response_model=FileOutlineGenerationResponse)
async def generate_outline_from_file(request: FileOutlineGenerationRequest):
    """使用summeryanyfile从文件生成PPT大纲"""
    try:
        # 调用增强的PPT服务来生成大纲
        result = await ppt_service.generate_outline_from_file(request)
        return result

    except Exception as e:
        logger.error(f"Error generating outline from file: {e}")
        return FileOutlineGenerationResponse(
            success=False,
            error=str(e),
            message=f"从文件生成大纲失败: {str(e)}"
        )

@router.post("/files/upload-and-generate-outline")
async def upload_file_and_generate_outline(
    files: List[UploadFile] = File(...),
    topic: Optional[str] = Form(None),
    scenario: str = Form("general"),
    page_count_mode: str = Form("ai_decide"),
    min_pages: int = Form(8),
    max_pages: int = Form(15),
    fixed_pages: int = Form(10),
    ppt_style: str = Form("general"),
    custom_style_prompt: Optional[str] = Form(None),
    file_processing_mode: str = Form("markitdown"),
    content_analysis_depth: str = Form("standard"),
    focus_content: Optional[str] = Form(None),
    tech_highlights: Optional[str] = Form(None),
    target_audience: Optional[str] = Form(None),
    network_mode: bool = Form(False),  # 是否启用联网搜索（与项目创建保持一致）
    language: str = Form("zh")  # 语言参数
):
    """上传多个文件并直接生成PPT大纲，支持联网搜索集成"""
    try:
        # 验证所有文件
        for file in files:
            is_valid, message = file_processor.validate_file(file.filename, file.size)
            if not is_valid:
                raise HTTPException(status_code=400, detail=f"{file.filename}: {message}")

        # 保存所有临时文件并处理
        import tempfile
        import os

        temp_file_paths = []
        all_processed_content = []

        try:
            # 保存并处理每个文件
            for file in files:
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
                    content = await file.read()
                    temp_file.write(content)
                    temp_file_path = temp_file.name
                    temp_file_paths.append(temp_file_path)

                # 处理单个文件
                file_result = await file_processor.process_file(
                    temp_file_path,
                    file.filename,
                    file_processing_mode=file_processing_mode,
                )
                all_processed_content.append({
                    "filename": file.filename,
                    "content": file_result.processed_content
                })

            # 如果启用联网搜索，先进行搜索并整合
            merged_file_path = None
            if network_mode and topic:
                logger.info(f"启用联网搜索模式，主题: {topic}")

                # 构建上下文信息
                context = {
                    'scenario': scenario,
                    'target_audience': target_audience or '普通大众',
                    'requirements': '',
                    'ppt_style': ppt_style,
                    'description': f'文件数量: {len(files)}',
                    'file_processing_mode': file_processing_mode,
                }

                # 获取所有文件路径
                file_paths_for_merge = [path for path in temp_file_paths if not path.endswith('.md')]

                # 进行联网搜索并与文件整合
                merged_file_path = await ppt_service.conduct_research_and_merge_with_files(
                    topic=topic,
                    language=language,
                    file_paths=file_paths_for_merge,
                    context=context
                )

                temp_file_paths.append(merged_file_path)
                logger.info(f"✅ 联网搜索和文件整合完成: {merged_file_path}")

                # 使用整合后的文件作为最终文件
                final_filename = f"merged_with_search_{len(files)}_files.md"
            else:
                # 不使用联网搜索，仅合并所有文件内容
                merged_content = file_processor.merge_multiple_files_to_markdown(all_processed_content)

                # 创建临时合并文件
                with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md', encoding='utf-8') as merged_file:
                    merged_file.write(merged_content)
                    merged_file_path = merged_file.name
                    temp_file_paths.append(merged_file_path)

                final_filename = f"merged_content_{len(files)}_files.md"

            # 解析多选字段
            focus_content_list = focus_content.split(',') if focus_content else []
            tech_highlights_list = tech_highlights.split(',') if tech_highlights else []

            # 创建请求对象，使用合并后的文件
            outline_request = FileOutlineGenerationRequest(
                file_path=merged_file_path,
                filename=final_filename,
                topic=topic,
                scenario=scenario,
                requirements="",  # API调用暂时没有requirements参数
                page_count_mode=page_count_mode,
                min_pages=min_pages,
                max_pages=max_pages,
                fixed_pages=fixed_pages,
                ppt_style=ppt_style,
                custom_style_prompt=custom_style_prompt,
                file_processing_mode=file_processing_mode,
                content_analysis_depth=content_analysis_depth,
                target_audience=target_audience,
                language=language
            )

            # 生成大纲
            result = await ppt_service.generate_outline_from_file(outline_request)

            # 在结果中添加文件列表信息
            if result.success and result.metadata:
                result.metadata["source_files"] = [f.filename for f in files]
                result.metadata["files_count"] = len(files)
                result.metadata["network_mode"] = network_mode
                if network_mode:
                    result.metadata["search_topic"] = topic

            return result

        finally:
            # 清理所有临时文件
            for temp_path in temp_file_paths:
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete temp file {temp_path}: {e}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading files and generating outline: {e}")
        return FileOutlineGenerationResponse(
            success=False,
            error=str(e),
            message=f"文件上传和大纲生成失败: {str(e)}"
        )


@router.post("/projects/{project_id}/select-template", response_model=TemplateSelectionResponse)
async def select_global_template_for_project(
    project_id: str,
    request: TemplateSelectionRequest,
    user: User = Depends(get_current_user_required)
):
    """为项目选择全局母版模板 - enforces user ownership"""
    try:
        # 验证项目ID匹配
        if request.project_id != project_id:
            raise HTTPException(status_code=400, detail="Project ID mismatch")

        # 选择模板 with user ownership check
        user_ppt_service = get_ppt_service_for_user(user.id)

        if request.template_mode == "free":
            result = await user_ppt_service.select_free_template_for_project(project_id, user_id=user.id)
        else:
            # "default" 和未指定都等价于 selected_template_id=None（由后端选择默认模板）
            template_id = None if request.template_mode == "default" else request.selected_template_id
            result = await user_ppt_service.select_global_template_for_project(project_id, template_id, user_id=user.id)

        if not result['success']:
            raise HTTPException(status_code=400, detail=result['message'])

        return TemplateSelectionResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to select template: {str(e)}")


@router.get("/projects/{project_id}/selected-template")
async def get_selected_global_template(
    project_id: str,
    user: User = Depends(get_current_user_required)
):
    """获取项目选择的全局母版模板 - enforces user ownership"""
    try:
        user_ppt_service = get_ppt_service_for_user(user.id)
        template = await user_ppt_service.get_selected_global_template(project_id, user_id=user.id)

        if not template:
            return {"selected_template": None, "message": "No template selected"}

        return {"selected_template": template}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get selected template: {str(e)}")


# 文件缓存管理端点
@router.get("/cache/stats")
async def get_file_cache_stats():
    """获取文件缓存统计信息"""
    try:
        stats = ppt_service.get_cache_stats()
        return {"success": True, "stats": stats}
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cache/cleanup")
async def cleanup_file_cache():
    """清理过期的文件缓存条目"""
    try:
        ppt_service.cleanup_cache()
        return {"success": True, "message": "文件缓存清理完成"}
    except Exception as e:
        logger.error(f"Error cleaning up cache: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# DEEP Research Endpoints

@router.get("/research/status")
async def get_research_status():
    """Get research service status"""
    try:
        research_service = get_research_service()
        if not research_service:
            return {
                "available": False,
                "message": "Research service not initialized",
                "tavily_configured": bool(ai_config.tavily_api_key)
            }

        status = research_service.get_status()
        return {
            "available": research_service.is_available(),
            "status": status,
            "tavily_configured": bool(ai_config.tavily_api_key)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting research status: {str(e)}")

@router.post("/research/conduct")
async def conduct_research(topic: str, language: str = "zh"):
    """Conduct DEEP research on a topic"""
    try:
        research_service = get_research_service()
        if not research_service or not research_service.is_available():
            raise HTTPException(
                status_code=503,
                detail="Research service not available. Please check Tavily API configuration."
            )

        # Conduct research
        research_report = await research_service.conduct_deep_research(topic, language)

        # Save report if generator is available
        report_path = None
        report_generator = get_report_generator()
        if report_generator:
            try:
                report_path = report_generator.save_report_to_file(research_report)
            except Exception as save_error:
                logger.warning(f"Failed to save research report: {save_error}")

        return {
            "success": True,
            "report": {
                "topic": research_report.topic,
                "language": research_report.language,
                "executive_summary": research_report.executive_summary,
                "key_findings": research_report.key_findings,
                "recommendations": research_report.recommendations,
                "total_duration": research_report.total_duration,
                "sources_count": len(research_report.sources),
                "steps_count": len(research_report.steps)
            },
            "report_path": report_path,
            "message": "Research completed successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error conducting research: {e}")
        raise HTTPException(status_code=500, detail=f"Research failed: {str(e)}")

@router.get("/research/reports")
async def list_research_reports():
    """List all saved research reports"""
    try:
        report_generator = get_report_generator()
        if not report_generator:
            raise HTTPException(
                status_code=503,
                detail="Report generator not available"
            )

        reports = report_generator.list_saved_reports()
        return {
            "success": True,
            "reports": reports,
            "total_count": len(reports),
            "reports_directory": report_generator.get_reports_directory()
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing reports: {str(e)}")

@router.delete("/research/reports/{filename}")
async def delete_research_report(filename: str):
    """Delete a research report"""
    try:
        report_generator = get_report_generator()
        if not report_generator:
            raise HTTPException(
                status_code=503,
                detail="Report generator not available"
            )

        success = report_generator.delete_report(filename)
        if not success:
            raise HTTPException(status_code=404, detail="Report not found")

        return {
            "success": True,
            "message": f"Report {filename} deleted successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting report: {str(e)}")

@router.get("/research/reports/directory")
async def get_reports_directory():
    """Get the reports directory path"""
    try:
        report_generator = get_report_generator()
        if not report_generator:
            raise HTTPException(
                status_code=503,
                detail="Report generator not available"
            )

        directory = report_generator.get_reports_directory()
        return {
            "success": True,
            "directory": directory,
            "message": "Reports are saved in this directory"
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting directory: {str(e)}")


# Enhanced Research API Endpoints

@router.post("/research/enhanced/conduct")
async def conduct_enhanced_research(topic: str, language: str = "zh"):
    """Conduct enhanced research using multiple providers and deep content analysis"""
    try:
        enhanced_service = get_enhanced_research_service()
        if not enhanced_service or not enhanced_service.is_available():
            raise HTTPException(
                status_code=503,
                detail="Enhanced research service not available. Please check provider configurations."
            )

        # Conduct enhanced research
        enhanced_report = await enhanced_service.conduct_enhanced_research(topic, language)

        # Save enhanced report
        report_path = None
        enhanced_generator = get_enhanced_report_generator()
        if enhanced_generator:
            try:
                report_path = enhanced_generator.save_report_to_file(enhanced_report)
            except Exception as save_error:
                logger.warning(f"Failed to save enhanced research report: {save_error}")

        return {
            "success": True,
            "message": "Enhanced research completed successfully",
            "report": {
                "topic": enhanced_report.topic,
                "language": enhanced_report.language,
                "executive_summary": enhanced_report.executive_summary,
                "key_findings": enhanced_report.key_findings,
                "recommendations": enhanced_report.recommendations,
                "sources": enhanced_report.sources,
                "created_at": enhanced_report.created_at.isoformat(),
                "total_duration": enhanced_report.total_duration,
                "steps_count": len(enhanced_report.steps),
                "provider_stats": enhanced_report.provider_stats,
                "content_analysis": enhanced_report.content_analysis
            },
            "report_path": report_path
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Enhanced research failed: {e}")
        raise HTTPException(status_code=500, detail=f"Enhanced research failed: {str(e)}")


@router.get("/research/enhanced/status")
async def get_enhanced_research_status():
    """Get enhanced research service status and configuration"""
    try:
        enhanced_service = get_enhanced_research_service()
        if not enhanced_service:
            return {
                "available": False,
                "message": "Enhanced research service not initialized"
            }

        status = enhanced_service.get_status()
        return {
            "success": True,
            "status": status
        }

    except Exception as e:
        logger.error(f"Error getting enhanced research status: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting enhanced research status: {str(e)}")


@router.get("/research/enhanced/providers")
async def get_available_research_providers():
    """Get list of available research providers"""
    try:
        enhanced_service = get_enhanced_research_service()
        providers = {
            "tavily": False,
            "searxng": False,
            "content_extraction": False
        }

        if enhanced_service:
            available_providers = enhanced_service.get_available_providers()
            for provider in available_providers:
                if provider in providers:
                    providers[provider] = True

            # Check content extraction
            from ...core.config import ai_config
            providers["content_extraction"] = ai_config.research_enable_content_extraction

        return {
            "success": True,
            "providers": providers,
            "enhanced_service_available": enhanced_service is not None and enhanced_service.is_available()
        }

    except Exception as e:
        logger.error(f"Error getting research providers: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting research providers: {str(e)}")
