"""
SQLAlchemy database models for LandPPT
"""

import time
import hashlib
from typing import Dict, Any, List, Optional
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    Boolean,
    ForeignKey,
    JSON,
    DateTime,
    UniqueConstraint,
    case,
    event,
    func,
    select,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
from datetime import datetime

Base = declarative_base()


class User(Base):
    """User model for authentication"""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    avatar: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    credits_balance: Mapped[int] = mapped_column(Integer, default=0)  # User credits balance
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_login: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    register_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    registration_channel: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    invite_code_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    
    # OAuth fields
    github_id: Mapped[Optional[str]] = mapped_column(String(50), unique=True, index=True, nullable=True)
    linuxdo_id: Mapped[Optional[str]] = mapped_column(String(50), unique=True, index=True, nullable=True)
    oauth_provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'github', 'linuxdo' or null for local

    # Relationships
    projects: Mapped[List["Project"]] = relationship("Project", back_populates="owner")
    credit_transactions: Mapped[List["CreditTransaction"]] = relationship("CreditTransaction", back_populates="user")
    configs: Mapped[List["UserConfig"]] = relationship("UserConfig", back_populates="user")
    api_keys: Mapped[List["UserAPIKey"]] = relationship("UserAPIKey", back_populates="user")
    metrics: Mapped[Optional["UserMetrics"]] = relationship("UserMetrics", back_populates="user", uselist=False)

    def set_password(self, password: str):
        """Set password hash"""
        self.password_hash = hashlib.sha256(password.encode()).hexdigest()

    def check_password(self, password: str) -> bool:
        """Check if password is correct"""
        return self.password_hash == hashlib.sha256(password.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        payload = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "phone": self.phone,
            "avatar": self.avatar,
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "credits_balance": self.credits_balance,
            "created_at": self.created_at,
            "last_login": self.last_login,
            "register_ip": self.register_ip,
            "last_login_ip": self.last_login_ip,
            "registration_channel": self.registration_channel,
            "invite_code_id": self.invite_code_id,
            "github_id": self.github_id,
            "linuxdo_id": self.linuxdo_id,
            "oauth_provider": self.oauth_provider
        }
        metrics = self.__dict__.get("metrics")
        if metrics is not None:
            payload["metrics"] = metrics.to_dict()
        return payload


class UserMetrics(Base):
    """Aggregated user metrics for operations and activity."""
    __tablename__ = "user_metrics"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    last_active_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    projects_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits_consumed_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits_recharged_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_project_created_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_credit_consumed_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_credit_recharged_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="metrics")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "last_active_at": self.last_active_at,
            "projects_count": self.projects_count,
            "credits_consumed_total": self.credits_consumed_total,
            "credits_recharged_total": self.credits_recharged_total,
            "last_project_created_at": self.last_project_created_at,
            "last_credit_consumed_at": self.last_credit_consumed_at,
            "last_credit_recharged_at": self.last_credit_recharged_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class UserSession(Base):
    """User session model"""
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationship
    user: Mapped["User"] = relationship("User")

    def is_expired(self) -> bool:
        """Check if session is expired"""
        # If expires_at is set to year 2099 or later, consider it as never expires
        year_2099_timestamp = time.mktime(time.strptime("2099-01-01 00:00:00", "%Y-%m-%d %H:%M:%S"))
        if self.expires_at >= year_2099_timestamp:
            return False
        return time.time() > self.expires_at


class UserAPIKey(Base):
    """User-managed API key (hashed) for machine-to-machine access."""
    __tablename__ = "user_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_used_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expires_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="api_keys")


class Project(Base):
    """Project model for storing PPT projects"""
    __tablename__ = "projects"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # Project owner
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    scenario: Mapped[str] = mapped_column(String(100), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    requirements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    outline: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    slides_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slides_data: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    confirmed_requirements: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    project_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # 项目元数据，包括选择的模板ID等
    version: Mapped[int] = mapped_column(Integer, default=1)
    share_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True, nullable=True)  # 分享token，用于公开访问
    share_enabled: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否启用分享
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)
    
    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="projects")
    todo_board: Mapped[Optional["TodoBoard"]] = relationship("TodoBoard", back_populates="project", uselist=False)
    versions: Mapped[List["ProjectVersion"]] = relationship("ProjectVersion", back_populates="project")
    slides: Mapped[List["SlideData"]] = relationship("SlideData", back_populates="project")
    speech_scripts: Mapped[List["SpeechScript"]] = relationship("SpeechScript", back_populates="project")
    narration_audios: Mapped[List["NarrationAudio"]] = relationship("NarrationAudio", back_populates="project")


class TodoBoard(Base):
    """TODO Board model for project workflow management"""
    __tablename__ = "todo_boards"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id"), unique=True)
    current_stage_index: Mapped[int] = mapped_column(Integer, default=0)
    overall_progress: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)
    
    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="todo_board")
    stages: Mapped[List["TodoStage"]] = relationship("TodoStage", back_populates="todo_board", order_by="TodoStage.stage_index")


class TodoStage(Base):
    """TODO Stage model for individual workflow stages"""
    __tablename__ = "todo_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    todo_board_id: Mapped[int] = mapped_column(Integer, ForeignKey("todo_boards.id"))
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id"), index=True)  # Added for direct project reference
    stage_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # Added index for better performance
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)  # Added index for status queries
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)

    # Relationships
    todo_board: Mapped["TodoBoard"] = relationship("TodoBoard", back_populates="stages")
    project: Mapped["Project"] = relationship("Project", foreign_keys=[project_id])  # Direct project relationship


class ProjectVersion(Base):
    """Project version model for version control"""
    __tablename__ = "project_versions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, default=time.time)
    data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    
    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="versions")


class SlideData(Base):
    """Slide data model for individual PPT slides"""
    __tablename__ = "slide_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id"))
    slide_index: Mapped[int] = mapped_column(Integer, nullable=False)
    slide_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    html_content: Mapped[str] = mapped_column(Text, nullable=False)
    slide_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    template_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("ppt_templates.id"), nullable=True)
    is_user_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="slides")
    template: Mapped[Optional["PPTTemplate"]] = relationship("PPTTemplate", back_populates="slides")


class PPTTemplate(Base):
    """PPT Template model for storing master templates"""
    __tablename__ = "ppt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id"))
    template_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # title, content, chart, image, summary
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    html_template: Mapped[str] = mapped_column(Text, nullable=False)
    applicable_scenarios: Mapped[List[str]] = mapped_column(JSON, nullable=True)  # 适用场景
    style_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # 样式配置
    usage_count: Mapped[int] = mapped_column(Integer, default=0)  # 使用次数统计
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)

    # Relationships
    project: Mapped["Project"] = relationship("Project", foreign_keys=[project_id])
    slides: Mapped[List["SlideData"]] = relationship("SlideData", back_populates="template")


class GlobalMasterTemplate(Base):
    """Global Master Template model for storing reusable master templates"""
    __tablename__ = "global_master_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    template_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    html_template: Mapped[str] = mapped_column(Text, nullable=False)
    preview_image: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Base64 encoded preview image
    style_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)  # 样式配置
    tags: Mapped[List[str]] = mapped_column(JSON, nullable=True)  # 标签分类
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否为默认模板
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # 是否启用
    usage_count: Mapped[int] = mapped_column(Integer, default=0)  # 使用次数统计
    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 创建者
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)


class SpeechScript(Base):
    """演讲稿存储表"""
    __tablename__ = "speech_scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id"), nullable=False, index=True)
    slide_index: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="zh", nullable=False, index=True)
    slide_title: Mapped[str] = mapped_column(String(255), nullable=False)
    script_content: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_duration: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    speaker_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 生成参数
    generation_type: Mapped[str] = mapped_column(String(20), nullable=False)  # single, multi, full
    tone: Mapped[str] = mapped_column(String(50), nullable=False)
    target_audience: Mapped[str] = mapped_column(String(100), nullable=False)
    custom_audience: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 自定义受众描述
    language_complexity: Mapped[str] = mapped_column(String(20), nullable=False)
    speaking_pace: Mapped[str] = mapped_column(String(20), nullable=False)
    custom_style_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    include_transitions: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    include_timing_notes: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 时间戳
    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time, nullable=False)

    # 关联关系
    project: Mapped["Project"] = relationship("Project", back_populates="speech_scripts")

    def __repr__(self):
        return (
            f"<SpeechScript(id={self.id}, project_id='{self.project_id}', "
            f"slide_index={self.slide_index}, language='{self.language}')>"
        )


class NarrationAudio(Base):
    """Narration audio cache for slide-level TTS output."""

    __tablename__ = "narration_audios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.project_id"), nullable=False, index=True)
    slide_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), default="zh", nullable=False, index=True)

    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="edge_tts", index=True)
    voice: Mapped[str] = mapped_column(String(100), nullable=False)
    rate: Mapped[str] = mapped_column(String(20), nullable=False, default="+0%")
    audio_format: Mapped[str] = mapped_column(String(10), nullable=False, default="mp3")

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cues_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "slide_index",
            "language",
            "provider",
            "voice",
            "rate",
            "content_hash",
            name="uq_narration_audio_cache",
        ),
    )

    project: Mapped["Project"] = relationship("Project", back_populates="narration_audios")

    def __repr__(self):
        return (
            f"<NarrationAudio(id={self.id}, project_id='{self.project_id}', "
            f"slide_index={self.slide_index}, language='{self.language}', provider='{self.provider}')>"
        )


class CreditTransaction(Base):
    """Credit transaction history for audit trail"""
    __tablename__ = "credit_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # positive=credit, negative=debit
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # recharge, consume, refund, admin_adjust, redemption
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    reference_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # project_id, order_id, redemption_code, etc.
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="credit_transactions")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "amount": self.amount,
            "balance_after": self.balance_after,
            "transaction_type": self.transaction_type,
            "description": self.description,
            "reference_id": self.reference_id,
            "created_at": self.created_at
        }


class RedemptionCode(Base):
    """Redemption codes for credit recharge"""
    __tablename__ = "redemption_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    credits_amount: Mapped[int] = mapped_column(Integer, nullable=False)  # Credits granted when redeemed
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    used_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    used_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expires_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Optional expiration
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # Admin notes

    def is_valid(self) -> bool:
        """Check if code is valid (not used and not expired)"""
        if self.is_used:
            return False
        if self.expires_at and time.time() > self.expires_at:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "code": self.code,
            "credits_amount": self.credits_amount,
            "is_used": self.is_used,
            "used_by": self.used_by,
            "used_at": self.used_at,
            "expires_at": self.expires_at,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "description": self.description
        }


class InviteCode(Base):
    """Registration invite codes bound to a specific or universal channel."""
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # github, linuxdo, mail, universal
    credits_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    expires_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    def is_valid_for(self, channel: str) -> bool:
        normalized = str(channel or "").strip().lower()
        record_channel = (self.channel or "").strip().lower()
        if not self.is_active:
            return False
        if record_channel != "universal" and normalized != record_channel:
            return False
        if self.expires_at and time.time() > self.expires_at:
            return False
        return self.used_count < max(1, int(self.max_uses or 1))

    def remaining_uses(self) -> int:
        return max(0, max(1, int(self.max_uses or 1)) - max(0, int(self.used_count or 0)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "channel": self.channel,
            "credits_amount": self.credits_amount,
            "max_uses": self.max_uses,
            "used_count": self.used_count,
            "remaining_uses": self.remaining_uses(),
            "is_active": self.is_active,
            "expires_at": self.expires_at,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "description": self.description,
        }


class InviteCodeUsage(Base):
    """Audit log for invite code usage during registration."""
    __tablename__ = "invite_code_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    invite_code_id: Mapped[int] = mapped_column(Integer, ForeignKey("invite_codes.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    credits_granted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "invite_code_id": self.invite_code_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "credits_granted": self.credits_granted,
            "created_at": self.created_at,
        }


class DailyCheckIn(Base):
    """Daily user sign-in records."""
    __tablename__ = "daily_checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    checkin_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    reward_points: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("user_id", "checkin_date", name="uq_daily_checkins_user_date"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "checkin_date": self.checkin_date,
            "reward_points": self.reward_points,
            "created_at": self.created_at,
        }


class SponsorProfile(Base):
    """Custom sponsor profile shown on the public thank-you page."""
    __tablename__ = "sponsor_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    nickname: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    link_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    amount: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "nickname": self.nickname,
            "avatar_url": self.avatar_url,
            "bio": self.bio,
            "link_url": self.link_url,
            "amount": self.amount,
            "note": self.note,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class VerificationCode(Base):
    """Email verification codes for registration and password reset"""
    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    code_type: Mapped[str] = mapped_column(String(20), nullable=False)  # register, reset
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)

    def is_valid(self) -> bool:
        """Check if code is valid (not used and not expired)"""
        if self.is_used:
            return False
        if time.time() > self.expires_at:
            return False
        return True


class UserConfig(Base):
    """User-specific configuration storage for per-user isolated settings"""
    __tablename__ = "user_configs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    config_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    config_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_type: Mapped[str] = mapped_column(String(20), default="text")  # text, password, number, boolean, json
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time, onupdate=time.time)
    
    # Unique constraint: one key per user (NULL user_id = system default)
    __table_args__ = (
        UniqueConstraint('user_id', 'config_key', name='uq_user_config_key'),
    )
    
    # Relationship
    user: Mapped[Optional["User"]] = relationship("User", back_populates="configs")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "config_key": self.config_key,
            "config_value": self.config_value,
            "config_type": self.config_type,
            "category": self.category,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


def _user_metrics_table_exists(connection) -> bool:
    try:
        return sa_inspect(connection).has_table(UserMetrics.__tablename__)
    except Exception:
        return False


def _load_user_metrics_row(connection, user_id: int) -> Optional[Dict[str, Any]]:
    row = connection.execute(
        select(UserMetrics.__table__).where(UserMetrics.user_id == user_id)
    ).mappings().first()
    return dict(row) if row else None


def _upsert_user_metrics_row(connection, user_id: int, values: Dict[str, Any]) -> None:
    if not user_id or not _user_metrics_table_exists(connection):
        return

    now = float(values.get("updated_at") or time.time())
    existing = _load_user_metrics_row(connection, user_id)

    if existing is None:
        insert_values = {
            "user_id": user_id,
            "last_active_at": None,
            "projects_count": 0,
            "credits_consumed_total": 0,
            "credits_recharged_total": 0,
            "last_project_created_at": None,
            "last_credit_consumed_at": None,
            "last_credit_recharged_at": None,
            "created_at": now,
            "updated_at": now,
        }
        for key, value in values.items():
            if value is not None:
                insert_values[key] = value
        connection.execute(UserMetrics.__table__.insert().values(**insert_values))
        return

    update_values = dict(values)
    update_values["updated_at"] = now

    for field in (
        "last_active_at",
        "last_project_created_at",
        "last_credit_consumed_at",
        "last_credit_recharged_at",
    ):
        incoming = update_values.get(field)
        current = existing.get(field)
        if incoming is None:
            continue
        if current is None or float(incoming) >= float(current):
            update_values[field] = incoming
        else:
            update_values.pop(field, None)

    connection.execute(
        UserMetrics.__table__.update()
        .where(UserMetrics.user_id == user_id)
        .values(**update_values)
    )


def _touch_user_metrics(connection, user_id: int, activity_ts: Optional[float] = None) -> None:
    _upsert_user_metrics_row(
        connection,
        user_id,
        {
            "last_active_at": float(activity_ts or time.time()),
            "updated_at": float(activity_ts or time.time()),
        },
    )


def _recalculate_project_metrics(connection, user_id: int, activity_ts: Optional[float] = None) -> None:
    if not user_id or not _user_metrics_table_exists(connection):
        return

    project_count = connection.execute(
        select(func.count(Project.id)).where(Project.user_id == user_id)
    ).scalar() or 0
    last_project_created_at = connection.execute(
        select(func.max(Project.created_at)).where(Project.user_id == user_id)
    ).scalar()

    values: Dict[str, Any] = {
        "projects_count": int(project_count),
        "last_project_created_at": last_project_created_at,
        "updated_at": float(activity_ts or time.time()),
    }
    if activity_ts is not None:
        values["last_active_at"] = float(activity_ts)

    _upsert_user_metrics_row(connection, user_id, values)


def _recalculate_credit_metrics(connection, user_id: int, activity_ts: Optional[float] = None) -> None:
    if not user_id or not _user_metrics_table_exists(connection):
        return

    consumed_total = connection.execute(
        select(
            func.coalesce(
                func.sum(
                    case((CreditTransaction.amount < 0, -CreditTransaction.amount), else_=0)
                ),
                0,
            )
        ).where(CreditTransaction.user_id == user_id)
    ).scalar() or 0

    recharged_total = connection.execute(
        select(
            func.coalesce(
                func.sum(
                    case((CreditTransaction.amount > 0, CreditTransaction.amount), else_=0)
                ),
                0,
            )
        ).where(CreditTransaction.user_id == user_id)
    ).scalar() or 0

    last_credit_consumed_at = connection.execute(
        select(func.max(CreditTransaction.created_at)).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.amount < 0,
        )
    ).scalar()

    last_credit_recharged_at = connection.execute(
        select(func.max(CreditTransaction.created_at)).where(
            CreditTransaction.user_id == user_id,
            CreditTransaction.amount > 0,
        )
    ).scalar()

    values: Dict[str, Any] = {
        "credits_consumed_total": int(consumed_total),
        "credits_recharged_total": int(recharged_total),
        "last_credit_consumed_at": last_credit_consumed_at,
        "last_credit_recharged_at": last_credit_recharged_at,
        "updated_at": float(activity_ts or time.time()),
    }
    if activity_ts is not None:
        values["last_active_at"] = float(activity_ts)

    _upsert_user_metrics_row(connection, user_id, values)


@event.listens_for(User, "after_insert")
def _user_metrics_after_user_insert(mapper, connection, target) -> None:
    created_at = float(getattr(target, "created_at", None) or time.time())
    _upsert_user_metrics_row(
        connection,
        int(target.id),
        {
            "last_active_at": created_at,
            "updated_at": created_at,
            "created_at": created_at,
        },
    )


@event.listens_for(User, "after_update")
def _user_metrics_after_user_update(mapper, connection, target) -> None:
    state = sa_inspect(target)
    if state.attrs.last_login.history.has_changes() and target.last_login is not None:
        _touch_user_metrics(connection, int(target.id), float(target.last_login))


@event.listens_for(UserAPIKey, "after_update")
def _user_metrics_after_api_key_update(mapper, connection, target) -> None:
    state = sa_inspect(target)
    if state.attrs.last_used_at.history.has_changes() and target.last_used_at is not None:
        _touch_user_metrics(connection, int(target.user_id), float(target.last_used_at))


@event.listens_for(Project, "after_insert")
def _user_metrics_after_project_insert(mapper, connection, target) -> None:
    created_at = float(getattr(target, "created_at", None) or time.time())
    _recalculate_project_metrics(connection, int(target.user_id), created_at)


@event.listens_for(Project, "after_update")
def _user_metrics_after_project_update(mapper, connection, target) -> None:
    updated_at = float(getattr(target, "updated_at", None) or time.time())
    _touch_user_metrics(connection, int(target.user_id), updated_at)


@event.listens_for(Project, "after_delete")
def _user_metrics_after_project_delete(mapper, connection, target) -> None:
    _recalculate_project_metrics(connection, int(target.user_id), float(time.time()))


@event.listens_for(CreditTransaction, "after_insert")
def _user_metrics_after_credit_transaction_insert(mapper, connection, target) -> None:
    activity_types = {"consume", "redemption", "daily_checkin", "invite_reward"}
    activity_ts = None
    if str(getattr(target, "transaction_type", "") or "").strip().lower() in activity_types:
        activity_ts = float(getattr(target, "created_at", None) or time.time())
    _recalculate_credit_metrics(connection, int(target.user_id), activity_ts)
