"""
Speech Script Generation Service
Provides AI-powered speech script generation for PPT presentations
"""

import logging
import time
import uuid
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from ..ai.base import AIMessage, MessageRole
from ..ai.providers import get_ai_provider, get_role_provider
from ..core.config import ai_config
from ..api.models import PPTProject
from .progress_tracker import progress_tracker

logger = logging.getLogger(__name__)


class SpeechTone(str, Enum):
    """Speech tone options"""
    FORMAL = "formal"
    CASUAL = "casual"
    PERSUASIVE = "persuasive"
    EDUCATIONAL = "educational"
    CONVERSATIONAL = "conversational"
    AUTHORITATIVE = "authoritative"
    STORYTELLING = "storytelling"


class TargetAudience(str, Enum):
    """Target audience options"""
    EXECUTIVES = "executives"
    STUDENTS = "students"
    GENERAL_PUBLIC = "general_public"
    TECHNICAL_EXPERTS = "technical_experts"
    COLLEAGUES = "colleagues"
    CLIENTS = "clients"
    INVESTORS = "investors"


class LanguageComplexity(str, Enum):
    """Language complexity levels"""
    SIMPLE = "simple"
    MODERATE = "moderate"
    ADVANCED = "advanced"


@dataclass
class SpeechScriptCustomization:
    """Speech script customization options"""
    language: str = "zh"
    tone: SpeechTone = SpeechTone.CONVERSATIONAL
    target_audience: TargetAudience = TargetAudience.GENERAL_PUBLIC
    language_complexity: LanguageComplexity = LanguageComplexity.MODERATE
    custom_style_prompt: Optional[str] = None
    include_transitions: bool = True
    include_timing_notes: bool = False
    speaking_pace: str = "normal"  # slow, normal, fast


@dataclass
class SlideScriptData:
    """Data for a single slide's speech script"""
    slide_index: int
    slide_title: str
    script_content: str
    estimated_duration: Optional[str] = None
    speaker_notes: Optional[str] = None


@dataclass
class SpeechScriptResult:
    """Result of speech script generation"""
    success: bool
    scripts: List[SlideScriptData]
    total_estimated_duration: Optional[str] = None
    generation_metadata: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class SpeechScriptService:
    """Service for generating AI-powered speech scripts for presentations"""
    
    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id
        self.ai_provider = None
        self.provider_settings: Optional[Dict[str, Optional[str]]] = None
        # Note: _initialize_ai_provider is sync, if user_id is provided,
        # we need to call initialize_async() after construction
        if user_id is None:
            self._initialize_ai_provider()

    async def initialize_async(self):
        """Async initialization for user-specific AI provider from database"""
        if self.user_id is not None:
            await self._initialize_ai_provider_async()
        else:
            self._initialize_ai_provider()

    async def _initialize_ai_provider_async(self):
        """Initialize AI provider from user's database configuration"""
        from .db_config_service import (
            get_db_config_service,
            get_user_ai_provider,
            get_user_ai_provider_config,
            get_user_role_provider,
        )

        # 1) Prefer per-user, per-role configuration (speech_script_model_provider / speech_script_model_name)
        try:
            provider, role_settings = await get_user_role_provider(self.user_id, "speech_script")
            self.ai_provider = provider
            self.provider_settings = role_settings
            logger.info(
                "Initialized speech script AI provider from DB role config: "
                f"user_id={self.user_id}, provider={role_settings.get('provider')}, model={role_settings.get('model')}"
            )
            return
        except Exception as e:
            logger.warning(
                f"Failed to initialize speech script AI provider from DB role config for user {self.user_id}: {e}"
            )

        # 2) If the configured provider cannot be created (e.g. missing system LandPPT key),
        # fall back to any working provider from the user's DB settings.
        try:
            config_service = get_db_config_service()
            user_config = await config_service.get_all_config(user_id=self.user_id)
            system_config = await config_service.get_all_config(user_id=None)

            def _norm_provider(value: Optional[str]) -> Optional[str]:
                if not value:
                    return None
                value = str(value).strip().lower()
                if value == "gemini":
                    return "google"
                return value or None

            requested_role_provider = _norm_provider(user_config.get("speech_script_model_provider"))
            requested_default_provider = _norm_provider(user_config.get("default_ai_provider"))
            role_model = (user_config.get("speech_script_model_name") or "").strip() or None
            enable_local_models = bool(user_config.get("enable_local_models"))

            candidates: List[str] = []
            for value in (requested_role_provider, requested_default_provider):
                if value and value not in candidates:
                    candidates.append(value)

            # Add other likely configured providers (in priority order).
            if user_config.get("openai_api_key") and "openai" not in candidates:
                candidates.append("openai")
            if user_config.get("anthropic_api_key") and "anthropic" not in candidates:
                candidates.append("anthropic")
            if user_config.get("google_api_key") and "google" not in candidates:
                candidates.append("google")
            # Ollama doesn't require an API key; only try it when local models are enabled.
            if enable_local_models and "ollama" not in candidates:
                candidates.append("ollama")
            # LandPPT requires system credentials; only try if configured.
            if system_config.get("landppt_api_key") and "landppt" not in candidates:
                candidates.append("landppt")

            for provider_name in candidates:
                try:
                    provider_config = await get_user_ai_provider_config(self.user_id, provider_name=provider_name)
                    needs_api_key = provider_name not in {"ollama"}
                    has_api_key = bool(provider_config.get("api_key"))
                    if needs_api_key and not has_api_key:
                        logger.info(
                            f"Skipping provider '{provider_name}' for user {self.user_id}: missing api_key in DB config"
                        )
                        continue

                    provider = await get_user_ai_provider(self.user_id, provider_name=provider_name)
                    model = role_model or provider_config.get("model")
                    self.ai_provider = provider
                    self.provider_settings = {
                        "role": "speech_script",
                        "provider": provider_name,
                        "model": model,
                    }
                    logger.info(
                        "Initialized speech script AI provider from DB fallback: "
                        f"user_id={self.user_id}, provider={provider_name}, model={model}"
                    )
                    return
                except Exception as provider_error:
                    logger.warning(
                        f"Failed to initialize provider '{provider_name}' for user {self.user_id}: {provider_error}"
                    )
        except Exception as e:
            logger.warning(f"Failed to select fallback AI provider from DB for user {self.user_id}: {e}")

        # 3) Final fallback to global config (env/.env)
        self._initialize_ai_provider()



    def _initialize_ai_provider(self):
        """Initialize AI provider from global config (fallback)"""
        try:
            provider, settings = get_role_provider("speech_script")
            self.ai_provider = provider
            self.provider_settings = settings
        except Exception as e:
            logger.warning(f"Failed to load provider for speech script role, fallback to default provider: {e}")
            try:
                self.ai_provider = get_ai_provider()
                self.provider_settings = {
                    "provider": ai_config.default_ai_provider,
                    "model": ai_config.get_provider_config().get("model")
                }
            except Exception as fallback_error:
                logger.error(f"Failed to initialize AI provider: {fallback_error}")
                self.ai_provider = None
                self.provider_settings = None

    
    async def generate_single_slide_script(
        self,
        project: PPTProject,
        slide_index: int,
        customization: SpeechScriptCustomization
    ) -> SpeechScriptResult:
        """Generate speech script for a single slide"""
        try:
            if not self.ai_provider:
                return SpeechScriptResult(
                    success=False,
                    scripts=[],
                    error_message="AI provider not available"
                )
            
            if not project.slides_data or slide_index >= len(project.slides_data):
                return SpeechScriptResult(
                    success=False,
                    scripts=[],
                    error_message="Invalid slide index"
                )
            
            slide = project.slides_data[slide_index]
            
            # Get context from previous slide if available
            previous_slide_context = ""
            if slide_index > 0:
                prev_slide = project.slides_data[slide_index - 1]
                previous_slide_context = self._extract_slide_context(prev_slide)
            
            # Generate script
            script_content = await self._generate_script_for_slide(
                slide, slide_index, len(project.slides_data),
                project, previous_slide_context, customization
            )
            
            # Estimate duration
            estimated_duration = self._estimate_speaking_duration(script_content)
            
            slide_script = SlideScriptData(
                slide_index=slide_index,
                slide_title=slide.get('title', f'第{slide_index + 1}页'),
                script_content=script_content,
                estimated_duration=estimated_duration
            )
            
            return SpeechScriptResult(
                success=True,
                scripts=[slide_script],
                total_estimated_duration=estimated_duration,
                generation_metadata={
                    "generation_time": time.time(),
                    "customization": customization.__dict__
                }
            )
            
        except Exception as e:
            logger.error(f"Error generating single slide script: {e}")
            return SpeechScriptResult(
                success=False,
                scripts=[],
                error_message=str(e)
            )
    
    async def generate_multi_slide_scripts(
        self,
        project: PPTProject,
        slide_indices: List[int],
        customization: SpeechScriptCustomization
    ) -> SpeechScriptResult:
        """Generate speech scripts for multiple slides"""
        try:
            if not self.ai_provider:
                return SpeechScriptResult(
                    success=False,
                    scripts=[],
                    error_message="AI provider not available"
                )
            
            if not project.slides_data:
                return SpeechScriptResult(
                    success=False,
                    scripts=[],
                    error_message="No slides data available"
                )
            
            scripts = []
            total_duration_seconds = 0
            
            for i, slide_index in enumerate(slide_indices):
                if slide_index >= len(project.slides_data):
                    continue
                
                slide = project.slides_data[slide_index]
                
                # Get context from previous slide in the sequence
                previous_slide_context = ""
                if i > 0:
                    prev_index = slide_indices[i - 1]
                    if prev_index < len(project.slides_data):
                        prev_slide = project.slides_data[prev_index]
                        previous_slide_context = self._extract_slide_context(prev_slide)
                elif slide_index > 0:
                    # Use actual previous slide if this is the first in selection
                    prev_slide = project.slides_data[slide_index - 1]
                    previous_slide_context = self._extract_slide_context(prev_slide)
                
                # Generate script
                script_content = await self._generate_script_for_slide(
                    slide, slide_index, len(project.slides_data),
                    project, previous_slide_context, customization
                )
                
                # Estimate duration
                estimated_duration = self._estimate_speaking_duration(script_content)
                duration_seconds = self._parse_duration_to_seconds(estimated_duration)
                total_duration_seconds += duration_seconds
                
                slide_script = SlideScriptData(
                    slide_index=slide_index,
                    slide_title=slide.get('title', f'第{slide_index + 1}页'),
                    script_content=script_content,
                    estimated_duration=estimated_duration
                )
                
                scripts.append(slide_script)
            
            total_duration = self._format_duration_from_seconds(total_duration_seconds)
            
            return SpeechScriptResult(
                success=True,
                scripts=scripts,
                total_estimated_duration=total_duration,
                generation_metadata={
                    "generation_time": time.time(),
                    "customization": customization.__dict__,
                    "slide_count": len(scripts)
                }
            )
            
        except Exception as e:
            logger.error(f"Error generating multi-slide scripts: {e}")
            return SpeechScriptResult(
                success=False,
                scripts=[],
                error_message=str(e)
            )
    
    async def generate_full_presentation_scripts(
        self,
        project: PPTProject,
        customization: SpeechScriptCustomization,
        progress_callback=None,
        task_id: str = None
    ) -> SpeechScriptResult:
        """Generate speech scripts for the entire presentation with retry mechanism"""
        try:
            if not project.slides_data:
                return SpeechScriptResult(
                    success=False,
                    scripts=[],
                    error_message="No slides data available"
                )

            # Generate scripts for all slides with retry mechanism
            slide_indices = list(range(len(project.slides_data)))
            result = await self.generate_multi_slide_scripts_with_retry(
                project, slide_indices, customization, progress_callback, task_id=task_id
            )

            # 不再自动添加开场白和结束语，完全按照选择的页面生成演讲稿
            # Opening and closing remarks are no longer automatically added

            return result

        except Exception as e:
            logger.error(f"Error generating full presentation scripts: {e}")
            return SpeechScriptResult(
                success=False,
                scripts=[],
                error_message=str(e)
            )

    async def generate_multi_slide_scripts_with_retry(
        self,
        project: PPTProject,
        slide_indices: List[int],
        customization: SpeechScriptCustomization,
        progress_callback=None,
        max_retries: int = 5,
        task_id: str = None
    ) -> SpeechScriptResult:
        """Generate speech scripts for multiple slides with retry mechanism"""
        try:
            if not project.slides_data:
                return SpeechScriptResult(
                    success=False,
                    scripts=[],
                    error_message="No slides data available"
                )

            total_slides = len(slide_indices)
            successful_scripts = []
            failed_slides = []
            skipped_slides = []

            # Create progress tracking task
            if not task_id:
                task_id = str(uuid.uuid4())

            progress_info = await progress_tracker.create_task_async(
                task_id=task_id,
                project_id=project.project_id,
                total_slides=total_slides,
                overwrite=False,
            )

            # Track progress
            completed_count = 0

            for i, slide_index in enumerate(slide_indices):
                if slide_index >= len(project.slides_data):
                    fallback_title = f'第{slide_index + 1}页'
                    failed_slides.append({
                        'slide_index': slide_index,
                        'slide_title': fallback_title,
                        'error': '页码超出范围'
                    })
                    await progress_tracker.add_slide_failed_async(
                        task_id,
                        slide_index,
                        fallback_title,
                        '页码超出范围'
                    )
                    if progress_callback:
                        progress_callback({
                            'type': 'slide_failed',
                            'slide_index': slide_index,
                            'slide_title': fallback_title,
                            'error': '页码超出范围'
                        })
                    continue

                slide = project.slides_data[slide_index]
                slide_title = slide.get('title', f'第{slide_index + 1}页')

                # Update progress
                await progress_tracker.update_progress_async(
                    task_id,
                    current_slide=slide_index,
                    current_slide_title=slide_title,
                    message=f'正在生成第{slide_index + 1}页演讲稿...'
                )

                if progress_callback:
                    progress_callback({
                        'type': 'progress',
                        'current_slide': slide_index + 1,
                        'total_slides': total_slides,
                        'completed': completed_count,
                        'failed': len(failed_slides),
                        'skipped': len(skipped_slides),
                        'message': f'正在生成第{slide_index + 1}页演讲稿...'
                    })

                # Try to generate script with retries
                script_generated = False
                last_error = None

                for retry_count in range(max_retries):
                    try:
                        # Get previous slide context for better coherence
                        previous_slide_context = ""
                        if slide_index > 0 and successful_scripts:
                            # Find the most recent successful script before this slide
                            for prev_script in reversed(successful_scripts):
                                if prev_script.slide_index < slide_index:
                                    prev_content = prev_script.script_content
                                    if len(prev_content) > 200:
                                        previous_slide_context = prev_content[-200:]
                                    else:
                                        previous_slide_context = prev_content
                                    break

                        # Generate script
                        script_content = await self._generate_script_for_slide(
                            slide, slide_index, len(project.slides_data),
                            project, previous_slide_context, customization
                        )

                        # Estimate duration
                        estimated_duration = self._estimate_speaking_duration(script_content)

                        slide_script = SlideScriptData(
                            slide_index=slide_index,
                            slide_title=slide_title,
                            script_content=script_content,
                            estimated_duration=estimated_duration
                        )

                        successful_scripts.append(slide_script)
                        script_generated = True
                        completed_count += 1

                        # Update progress tracker
                        await progress_tracker.add_slide_completed_async(task_id, slide_index, slide_title)

                        # Update progress callback
                        if progress_callback:
                            progress_callback({
                                'type': 'slide_completed',
                                'slide_index': slide_index,
                                'slide_title': slide_title,
                                'completed': completed_count,
                                'total_slides': total_slides
                            })

                        break  # Success, exit retry loop

                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"Retry {retry_count + 1}/{max_retries} failed for slide {slide_index + 1}: {e}")

                        # Update progress with retry info
                        if progress_callback:
                            progress_callback({
                                'type': 'retry',
                                'slide_index': slide_index,
                                'retry_count': retry_count + 1,
                                'max_retries': max_retries,
                                'error': str(e)
                            })

                        # Wait a bit before retrying
                        import asyncio
                        await asyncio.sleep(1)

                # If all retries failed, mark as failed or skipped
                if not script_generated:
                    if max_retries > 0:
                        failed_slides.append({
                            'slide_index': slide_index,
                            'slide_title': slide_title,
                            'error': last_error or 'Unknown error'
                        })

                        # Update progress tracker
                        await progress_tracker.add_slide_failed_async(task_id, slide_index, slide_title, last_error or 'Unknown error')

                        # Update progress callback
                        if progress_callback:
                            progress_callback({
                                'type': 'slide_failed',
                                'slide_index': slide_index,
                                'slide_title': slide_title,
                                'error': last_error
                            })
                    else:
                        skipped_slides.append({
                            'slide_index': slide_index,
                            'slide_title': slide_title,
                            'reason': 'Max retries exceeded'
                        })

                        # Update progress tracker
                        await progress_tracker.add_slide_skipped_async(task_id, slide_index, slide_title, 'Max retries exceeded')

            # Calculate total duration
            total_duration = self._calculate_total_duration([s.estimated_duration for s in successful_scripts])

            # Determine overall success
            success = len(successful_scripts) > 0
            error_message = None

            if len(failed_slides) > 0 or len(skipped_slides) > 0:
                error_parts = []
                if failed_slides:
                    error_parts.append(f"{len(failed_slides)}页生成失败")
                if skipped_slides:
                    error_parts.append(f"{len(skipped_slides)}页被跳过")
                error_message = "部分页面生成失败: " + ", ".join(error_parts)

            # Final progress update - DO NOT mark as completed here
            # The task will be marked as completed in routes.py after database save
            if not success:
                await progress_tracker.fail_task_async(task_id, error_message or "生成失败")

            if progress_callback:
                progress_callback({
                    'type': 'completed',
                    'successful': len(successful_scripts),
                    'failed': len(failed_slides),
                    'skipped': len(skipped_slides),
                    'total': total_slides
                })

            return SpeechScriptResult(
                success=success,
                scripts=successful_scripts,
                total_estimated_duration=total_duration,
                error_message=error_message,
                generation_metadata={
                    "generation_time": time.time(),
                    "customization": customization.__dict__,
                    "successful_slides": len(successful_scripts),
                    "failed_slides": len(failed_slides),
                    "skipped_slides": len(skipped_slides),
                    "failed_details": failed_slides,
                    "skipped_details": skipped_slides
                }
            )

        except Exception as e:
            logger.error(f"Error in generate_multi_slide_scripts_with_retry: {e}")
            return SpeechScriptResult(
                success=False,
                scripts=[],
                error_message=str(e)
            )

    async def _generate_script_for_slide(
        self,
        slide: Dict[str, Any],
        slide_index: int,
        total_slides: int,
        project: PPTProject,
        previous_slide_context: str,
        customization: SpeechScriptCustomization
    ) -> str:
        """Generate speech script for a single slide using AI"""
        
        # Check if AI provider is available
        if not self.ai_provider:
            raise RuntimeError("AI provider not initialized. Please check AI configuration and API keys.")
        
        # Create the prompt for speech script generation
        prompt = self._create_speech_script_prompt(
            slide, slide_index, total_slides, project,
            previous_slide_context, customization
        )
        
        # Generate using AI
        response = await self.ai_provider.text_completion(
            prompt=prompt,
            **self._build_request_kwargs(
                temperature=0.7
            )
        )
        
        return response.content.strip()

    async def humanize_script(
        self,
        original_script: str,
        customization: SpeechScriptCustomization
    ) -> str:
        """将已有演讲稿改写为更自然的口播表达。"""

        if not self.ai_provider:
            raise RuntimeError("AI provider not initialized. Please check AI configuration and API keys.")

        cleaned_script = (original_script or "").strip()
        if not cleaned_script:
            raise ValueError("Original speech script cannot be empty")

        prompt = self._create_humanized_script_prompt(cleaned_script, customization)
        response = await self.ai_provider.text_completion(
            prompt=prompt,
            **self._build_request_kwargs(
                temperature=0.55
            )
        )
        return (response.content or "").strip()
    
    def _create_speech_script_prompt(
        self,
        slide: Dict[str, Any],
        slide_index: int,
        total_slides: int,
        project: PPTProject,
        previous_slide_context: str,
        customization: SpeechScriptCustomization
    ) -> str:
        """Create AI prompt for speech script generation"""

        from .prompts.speech_script_prompts import SpeechScriptPrompts

        project_info = {
            'topic': project.topic,
            'scenario': project.scenario
        }

        customization_dict = {
            'language': getattr(customization, "language", "zh"),
            'tone': customization.tone.value,
            'target_audience': customization.target_audience.value,
            'language_complexity': customization.language_complexity.value,
            'custom_style_prompt': customization.custom_style_prompt,
            'include_transitions': customization.include_transitions,
            'speaking_pace': customization.speaking_pace
        }

        return SpeechScriptPrompts.get_single_slide_script_prompt(
            slide, slide_index, total_slides, project_info,
            previous_slide_context, customization_dict
        )

    def _create_humanized_script_prompt(
        self,
        original_script: str,
        customization: SpeechScriptCustomization
    ) -> str:
        """创建演讲稿人话化提示词。"""

        from .prompts.speech_script_prompts import SpeechScriptPrompts

        customization_dict = {
            'language': getattr(customization, "language", "zh"),
            'tone': customization.tone.value,
            'target_audience': customization.target_audience.value,
            'language_complexity': customization.language_complexity.value,
            'custom_style_prompt': customization.custom_style_prompt,
            'include_transitions': customization.include_transitions,
            'speaking_pace': customization.speaking_pace
        }

        return SpeechScriptPrompts.get_humanized_script_prompt(
            original_script,
            customization_dict
        )

    def _get_tone_description(self, tone: SpeechTone) -> str:
        """Get description for speech tone"""
        descriptions = {
            SpeechTone.FORMAL: "正式、严谨、专业的商务语调",
            SpeechTone.CASUAL: "轻松、自然、亲切的日常语调",
            SpeechTone.PERSUASIVE: "有说服力、激励性的语调",
            SpeechTone.EDUCATIONAL: "教学式、解释性的语调",
            SpeechTone.CONVERSATIONAL: "对话式、互动性的语调",
            SpeechTone.AUTHORITATIVE: "权威、自信、专家式的语调",
            SpeechTone.STORYTELLING: "叙事性、生动有趣的语调"
        }
        return descriptions.get(tone, "自然流畅的语调")

    def _get_audience_description(self, audience: TargetAudience) -> str:
        """Get description for target audience"""
        descriptions = {
            TargetAudience.EXECUTIVES: "企业高管和决策者，注重效率和结果",
            TargetAudience.STUDENTS: "学生群体，需要清晰的解释和引导",
            TargetAudience.GENERAL_PUBLIC: "普通大众，使用通俗易懂的语言",
            TargetAudience.TECHNICAL_EXPERTS: "技术专家，可以使用专业术语",
            TargetAudience.COLLEAGUES: "同事和合作伙伴，平等交流的语调",
            TargetAudience.CLIENTS: "客户群体，注重价值和利益",
            TargetAudience.INVESTORS: "投资者，关注商业价值和回报"
        }
        return descriptions.get(audience, "一般听众")

    def _get_complexity_description(self, complexity: LanguageComplexity) -> str:
        """Get description for language complexity"""
        descriptions = {
            LanguageComplexity.SIMPLE: "简单易懂，避免复杂词汇和长句",
            LanguageComplexity.MODERATE: "适中复杂度，平衡专业性和可理解性",
            LanguageComplexity.ADVANCED: "较高复杂度，可以使用专业术语和复杂概念"
        }
        return descriptions.get(complexity, "适中复杂度")

    def _extract_slide_context(self, slide: Dict[str, Any]) -> str:
        """Extract context summary from a slide"""
        title = slide.get('title', '')
        content = slide.get('html_content', '')

        # Extract text content from HTML
        import re
        text_content = re.sub(r'<[^>]+>', '', content)
        text_content = re.sub(r'\s+', ' ', text_content).strip()

        # Create a brief summary
        if len(text_content) > 200:
            text_content = text_content[:200] + "..."

        return f"{title}: {text_content}"

    def _estimate_speaking_duration(self, script_content: str) -> str:
        """Estimate speaking duration based on script length"""
        # Average speaking rate: 150-160 words per minute in Chinese
        # For Chinese text, we estimate by character count
        char_count = len(script_content)

        # Rough estimation: 300-400 characters per minute for Chinese
        minutes = char_count / 350

        if minutes < 1:
            seconds = int(minutes * 60)
            return f"{seconds}秒"
        else:
            return f"{minutes:.1f}分钟"

    def _calculate_total_duration(self, durations: List[str]) -> str:
        """Calculate total duration from a list of duration strings"""
        total_seconds = 0

        for duration in durations:
            if duration:
                total_seconds += self._parse_duration_to_seconds(duration)

        # Convert back to readable format
        if total_seconds < 60:
            return f"{total_seconds}秒"
        else:
            minutes = total_seconds / 60
            return f"{minutes:.1f}分钟"

    def _parse_duration_to_seconds(self, duration_str: str) -> int:
        """Parse duration string to seconds"""
        import re

        # Extract numbers and units
        minutes_match = re.search(r'(\d+(?:\.\d+)?)分钟', duration_str)
        seconds_match = re.search(r'(\d+)秒', duration_str)

        total_seconds = 0

        if minutes_match:
            minutes = float(minutes_match.group(1))
            total_seconds += int(minutes * 60)

        if seconds_match:
            seconds = int(seconds_match.group(1))
            total_seconds += seconds

        return total_seconds

    def _format_duration_from_seconds(self, total_seconds: int) -> str:
        """Format duration from seconds to readable string"""
        if total_seconds < 60:
            return f"{total_seconds}秒"
        else:
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            if seconds > 0:
                return f"{minutes}分钟{seconds}秒"
            else:
                return f"{minutes}分钟"

    async def _add_presentation_bookends(
        self,
        scripts: List[SlideScriptData],
        project: PPTProject,
        customization: SpeechScriptCustomization
    ) -> List[SlideScriptData]:
        """Add opening and closing remarks for full presentation"""
        try:
            # Generate opening remarks
            opening_script = await self._generate_opening_remarks(project, customization)
            opening_slide = SlideScriptData(
                slide_index=-1,  # Special index for opening
                slide_title="开场白",
                script_content=opening_script,
                estimated_duration=self._estimate_speaking_duration(opening_script)
            )

            # Generate closing remarks
            closing_script = await self._generate_closing_remarks(project, customization)
            closing_slide = SlideScriptData(
                slide_index=len(scripts),  # Special index for closing
                slide_title="结束语",
                script_content=closing_script,
                estimated_duration=self._estimate_speaking_duration(closing_script)
            )

            # Insert opening at the beginning and closing at the end
            return [opening_slide] + scripts + [closing_slide]

        except Exception as e:
            logger.error(f"Error adding presentation bookends: {e}")
            return scripts

    async def _generate_opening_remarks(
        self,
        project: PPTProject,
        customization: SpeechScriptCustomization
    ) -> str:
        """Generate opening remarks for the presentation"""

        from .prompts.speech_script_prompts import SpeechScriptPrompts

        project_info = {
            'topic': project.topic,
            'scenario': project.scenario
        }

        customization_dict = {
            'language': getattr(customization, "language", "zh"),
            'tone': customization.tone.value,
            'target_audience': customization.target_audience.value,
            'language_complexity': customization.language_complexity.value
        }

        prompt = SpeechScriptPrompts.get_opening_remarks_prompt(
            project_info, customization_dict
        )

        response = await self.ai_provider.text_completion(
            prompt=prompt,
            **self._build_request_kwargs(
                temperature=0.7
            )
        )

        return response.content.strip()

    async def _generate_closing_remarks(
        self,
        project: PPTProject,
        customization: SpeechScriptCustomization
    ) -> str:
        """Generate closing remarks for the presentation"""

        from .prompts.speech_script_prompts import SpeechScriptPrompts

        project_info = {
            'topic': project.topic,
            'scenario': project.scenario
        }

        customization_dict = {
            'language': getattr(customization, "language", "zh"),
            'tone': customization.tone.value,
            'target_audience': customization.target_audience.value,
            'language_complexity': customization.language_complexity.value
        }

        prompt = SpeechScriptPrompts.get_closing_remarks_prompt(
            project_info, customization_dict
        )

        response = await self.ai_provider.text_completion(
            prompt=prompt,
            **self._build_request_kwargs(
                temperature=0.7
            )
        )

        return response.content.strip()

    def _build_request_kwargs(self, **kwargs) -> Dict[str, Any]:
        """Merge base kwargs with role-specific model override if configured."""
        if self.provider_settings and self.provider_settings.get("model"):
            kwargs.setdefault("model", self.provider_settings["model"])
        return kwargs
