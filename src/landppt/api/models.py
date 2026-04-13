"""
Pydantic models for API requests and responses
"""

from typing import List, Optional, Dict, Any, Union, Literal
from pydantic import BaseModel, Field
import time
import uuid

# OpenAI Compatible Models

class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"] = Field(..., description="The role of the message author")
    content: str = Field(..., description="The content of the message")
    name: Optional[str] = Field(None, description="The name of the author of this message")

class ChatCompletionRequest(BaseModel):
    model: str = Field(..., description="ID of the model to use")
    messages: List[ChatMessage] = Field(..., description="A list of messages comprising the conversation so far")
    temperature: Optional[float] = Field(1.0, ge=0, le=2, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, gt=0, description="Maximum number of tokens to generate")
    top_p: Optional[float] = Field(1.0, ge=0, le=1, description="Nucleus sampling parameter")
    n: Optional[int] = Field(1, ge=1, le=128, description="Number of chat completion choices to generate")
    stream: Optional[bool] = Field(False, description="Whether to stream back partial progress")
    stop: Optional[Union[str, List[str]]] = Field(None, description="Up to 4 sequences where the API will stop generating")
    presence_penalty: Optional[float] = Field(0, ge=-2, le=2, description="Presence penalty parameter")
    frequency_penalty: Optional[float] = Field(0, ge=-2, le=2, description="Frequency penalty parameter")
    user: Optional[str] = Field(None, description="A unique identifier representing your end-user")

class CompletionRequest(BaseModel):
    model: str = Field(..., description="ID of the model to use")
    prompt: Union[str, List[str]] = Field(..., description="The prompt(s) to generate completions for")
    temperature: Optional[float] = Field(1.0, ge=0, le=2, description="Sampling temperature")
    max_tokens: Optional[int] = Field(16, gt=0, description="Maximum number of tokens to generate")
    top_p: Optional[float] = Field(1.0, ge=0, le=1, description="Nucleus sampling parameter")
    n: Optional[int] = Field(1, ge=1, le=128, description="Number of completions to generate")
    stream: Optional[bool] = Field(False, description="Whether to stream back partial progress")
    stop: Optional[Union[str, List[str]]] = Field(None, description="Up to 4 sequences where the API will stop generating")
    presence_penalty: Optional[float] = Field(0, ge=-2, le=2, description="Presence penalty parameter")
    frequency_penalty: Optional[float] = Field(0, ge=-2, le=2, description="Frequency penalty parameter")
    user: Optional[str] = Field(None, description="A unique identifier representing your end-user")

class Usage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None

class CompletionChoice(BaseModel):
    text: str
    index: int
    finish_reason: Optional[str] = None

class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:29]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[ChatCompletionChoice]
    usage: Usage

class CompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"cmpl-{uuid.uuid4().hex[:29]}")
    object: str = "text_completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: List[CompletionChoice]
    usage: Usage

# LandPPT Specific Models

class PPTScenario(BaseModel):
    id: str
    name: str
    description: str
    icon: str
    template_config: Dict[str, Any]


class PPTGenerationRequest(BaseModel):
    scenario: str = Field(..., description="PPT scenario type")
    topic: str = Field(..., description="PPT topic/theme")
    requirements: Optional[str] = Field(None, description="Additional requirements")
    network_mode: bool = Field(False, description="Whether to use network mode for enhanced generation")
    language: str = Field("zh", description="Language for the PPT content")
    uploaded_content: Optional[str] = Field(None, description="Content from uploaded files")
    # User ownership
    user_id: Optional[int] = Field(None, description="User ID for project ownership")
    # 目标受众和风格相关参数
    target_audience: Optional[str] = Field(None, description="Target audience for the PPT")
    ppt_style: str = Field("general", description="PPT style: 'general', 'conference', 'custom'")
    custom_style_prompt: Optional[str] = Field(None, description="Custom style prompt")
    description: Optional[str] = Field(None, description="Additional description or requirements")
    # 文件生成相关参数
    use_file_content: bool = Field(False, description="Whether to use uploaded file content for generation")
    file_processing_mode: str = Field("markitdown", description="File processing mode: 'markitdown' or 'magic_pdf'")
    content_analysis_depth: str = Field("standard", description="Content analysis depth: 'fast', 'standard', 'deep'")


class PPTOutline(BaseModel):
    title: str
    slides: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class PPTGenerationResponse(BaseModel):

    task_id: str
    status: str
    outline: Optional[PPTOutline] = None
    slides_html: Optional[str] = None
    error: Optional[str] = None

# Enhanced Task Management Models
class TodoStage(BaseModel):
    id: str
    name: str
    description: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"] = "pending"
    progress: float = 0.0
    subtasks: List[str] = []
    result: Optional[Dict[str, Any]] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class TodoBoard(BaseModel):
    task_id: str
    title: str
    stages: List[TodoStage]
    current_stage_index: int = 0
    overall_progress: float = 0.0
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

# Project Management Models
class PPTProject(BaseModel):
    project_id: str
    title: str
    scenario: str
    topic: str
    requirements: Optional[str] = None
    status: Literal["draft", "in_progress", "completed", "archived"] = "draft"
    outline: Optional[Dict[str, Any]] = None  # Changed to Dict for flexibility
    slides_html: Optional[str] = None
    slides_data: Optional[List[Dict[str, Any]]] = None  # Individual slide data
    confirmed_requirements: Optional[Dict[str, Any]] = None  # Confirmed requirements from step 1
    project_metadata: Optional[Dict[str, Any]] = None  # 项目元数据，包括选择的模板ID等
    todo_board: Optional[TodoBoard] = None
    version: int = 1
    versions: List[Dict[str, Any]] = []
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class ProjectListResponse(BaseModel):
    projects: List[PPTProject]
    total: int
    page: int
    page_size: int

# Enhanced Slide Models
class SlideContent(BaseModel):
    type: Literal["title", "content", "image", "chart", "list", "thankyou", "agenda", "section", "conclusion"]
    title: str
    subtitle: Optional[str] = None
    content: Optional[str] = None
    bullet_points: Optional[List[str]] = None
    image_suggestions: Optional[List[str]] = None
    chart_data: Optional[Dict[str, Any]] = None
    layout: str = "default"
    locked: bool = False

class EnhancedPPTOutline(BaseModel):
    title: str
    slides: List[SlideContent]
    metadata: Dict[str, Any]
    theme_config: Dict[str, Any] = {}

# File Upload Models
class FileUploadResponse(BaseModel):
    filename: str
    size: int
    type: str
    processed_content: str
    extracted_topics: List[str] = []
    suggested_scenarios: List[str] = []
    message: str

class FileOutlineGenerationRequest(BaseModel):
    """从文件生成PPT大纲的请求模型"""
    file_path: str = Field(..., description="Uploaded file path")
    filename: str = Field(..., description="Original filename")
    topic: Optional[str] = Field(None, description="Custom topic override")
    scenario: str = Field("general", description="PPT scenario type")
    requirements: Optional[str] = Field(None, description="Specific requirements from user")
    target_audience: Optional[str] = Field(None, description="Target audience for the PPT")
    language: str = Field("zh", description="Language for the PPT content: 'zh' for Chinese, 'en' for English")
    page_count_mode: str = Field("ai_decide", description="Page count mode: 'ai_decide', 'custom_range', 'fixed'")
    min_pages: Optional[int] = Field(8, description="Minimum pages for custom_range mode")
    max_pages: Optional[int] = Field(15, description="Maximum pages for custom_range mode")
    fixed_pages: Optional[int] = Field(10, description="Fixed page count")
    ppt_style: str = Field("general", description="PPT style: 'general', 'conference', 'custom'")
    custom_style_prompt: Optional[str] = Field(None, description="Custom style prompt")
    file_processing_mode: str = Field("markitdown", description="File processing mode")
    content_analysis_depth: str = Field("standard", description="Content analysis depth")

class FileOutlineGenerationResponse(BaseModel):
    """从文件生成PPT大纲的响应模型"""
    success: bool
    outline: Optional[Dict[str, Any]] = None
    file_info: Optional[Dict[str, Any]] = None
    processing_stats: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: str

# TaskStatus model removed - now using project-based workflow with TodoBoard

# Global Master Template Models
class GlobalMasterTemplateCreate(BaseModel):
    """Request model for creating a global master template"""
    template_name: str = Field(..., description="Template name (must be unique)")
    description: Optional[str] = Field("", description="Template description")
    html_template: str = Field(..., description="HTML template content")
    tags: Optional[List[str]] = Field([], description="Template tags for categorization")
    is_default: Optional[bool] = Field(False, description="Whether this is the default template")
    created_by: Optional[str] = Field("user", description="Creator identifier")


class GlobalMasterTemplateUpdate(BaseModel):
    """Request model for updating a global master template"""
    template_name: Optional[str] = Field(None, description="Template name (must be unique)")
    description: Optional[str] = Field(None, description="Template description")
    html_template: Optional[str] = Field(None, description="HTML template content")
    tags: Optional[List[str]] = Field(None, description="Template tags for categorization")
    is_default: Optional[bool] = Field(None, description="Whether this is the default template")
    is_active: Optional[bool] = Field(None, description="Whether the template is active")


class GlobalMasterTemplateResponse(BaseModel):
    """Response model for global master template"""
    id: int
    user_id: Optional[int] = None
    template_name: str
    description: str
    preview_image: Optional[str] = None
    tags: List[str]
    is_default: bool
    is_active: bool
    usage_count: int
    created_by: str
    created_at: float
    updated_at: float


class GlobalMasterTemplateDetailResponse(GlobalMasterTemplateResponse):
    """Detailed response model for global master template"""
    html_template: str
    style_config: Optional[Dict[str, Any]] = None


class ReferenceImageData(BaseModel):
    """Reference image data for AI generation"""
    filename: str = Field(..., description="Image filename")
    data: str = Field(..., description="Base64 encoded image data")
    size: int = Field(..., description="File size in bytes")
    type: str = Field(..., description="MIME type")


class ReferencePptxData(BaseModel):
    """Reference PPTX data for template extraction"""
    filename: str = Field(..., description="PPTX filename")
    data: str = Field(..., description="Base64 encoded PPTX data (raw base64 or data URL)")
    size: int = Field(..., description="File size in bytes")
    type: str = Field("application/vnd.openxmlformats-officedocument.presentationml.presentation", description="MIME type")


class GlobalMasterTemplateGenerateRequest(BaseModel):
    """Request model for AI-generated global master template"""
    prompt: str = Field(..., description="AI generation prompt")
    template_name: str = Field(..., description="Template name (must be unique)")
    description: Optional[str] = Field("", description="Template description")
    tags: Optional[List[str]] = Field([], description="Template tags")
    generation_mode: str = Field("text_only", description="Generation mode: text_only, reference_style, exact_replica, pptx_extract")
    reference_image: Optional[ReferenceImageData] = Field(None, description="Reference image for multimodal generation")
    reference_pptx: Optional[ReferencePptxData] = Field(None, description="Reference PPTX for template extraction")


class TemplateSelectionRequest(BaseModel):
    """Request model for template selection during PPT generation"""
    project_id: str = Field(..., description="Project ID")
    selected_template_id: Optional[int] = Field(None, description="Selected template ID (None for default)")
    template_mode: Optional[Literal["global", "default", "free"]] = Field(
        None,
        description="Template mode: global (selected template), default (system default), free (AI decides)"
    )


class TemplateSelectionResponse(BaseModel):
    """Response model for template selection"""
    success: bool
    message: str
    selected_template: Optional[GlobalMasterTemplateResponse] = None
