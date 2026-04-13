"""
Enhanced AI Service for handling OpenAI-compatible requests and PPT generation
"""

import re
import json
import logging
from typing import Dict, Any, List, Optional
from ..api.models import ChatCompletionRequest, CompletionRequest, PPTGenerationRequest
from ..ai import get_ai_provider, AIMessage, MessageRole
from ..core.config import ai_config

logger = logging.getLogger(__name__)

class AIService:
    """Enhanced AI service for processing requests and generating responses"""

    def __init__(self, provider_name: Optional[str] = None):
        self.provider_name = provider_name

        self.ppt_keywords = [
            "ppt", "presentation", "slides", "幻灯片", "演示", "汇报",
            "展示", "发表", "讲解", "课件", "slide", "powerpoint"
        ]

        self.scenario_templates = {
            "general": {
                "style": "professional",
                "tone": "formal",
                "structure": ["introduction", "main_content", "conclusion"]
            },
            "tourism": {
                "style": "vibrant",
                "tone": "engaging",
                "structure": ["destination_overview", "attractions", "itinerary", "practical_info"]
            },
            "education": {
                "style": "playful",
                "tone": "friendly",
                "structure": ["learning_objectives", "key_concepts", "examples", "activities", "summary"]
            },
            "analysis": {
                "style": "analytical",
                "tone": "objective",
                "structure": ["problem_statement", "methodology", "findings", "analysis", "recommendations"]
            },
            "history": {
                "style": "classic",
                "tone": "narrative",
                "structure": ["background", "timeline", "key_events", "significance", "legacy"]
            },
            "technology": {
                "style": "modern",
                "tone": "innovative",
                "structure": ["overview", "features", "benefits", "implementation", "future"]
            },
            "business": {
                "style": "corporate",
                "tone": "persuasive",
                "structure": ["executive_summary", "problem", "solution", "market_analysis", "financial_projections"]
            }
        }

    @property
    def ai_provider(self):
        """Dynamically get AI provider to ensure latest config"""
        provider_name = self.provider_name or ai_config.default_ai_provider
        return get_ai_provider(provider_name)

    def is_ppt_request(self, text: str) -> bool:
        """Check if the request is related to PPT generation"""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.ppt_keywords)
    
    async def handle_ppt_chat_request(self, request: ChatCompletionRequest) -> str:
        """Handle PPT-related chat completion request using real AI"""
        try:
            # Convert to AI messages
            ai_messages = []
            for msg in request.messages:
                ai_messages.append(AIMessage(
                    role=MessageRole(msg.role),
                    content=msg.content
                ))

            # Add system prompt for PPT generation
            system_prompt = self._get_ppt_system_prompt()
            ai_messages.insert(0, AIMessage(
                role=MessageRole.SYSTEM,
                content=system_prompt
            ))

            # Generate response using AI provider
            request_kwargs: Dict[str, Any] = {
                "messages": ai_messages,
                "temperature": request.temperature or ai_config.temperature,
                "top_p": request.top_p or ai_config.top_p,
            }
            if request.max_tokens is not None:
                request_kwargs["max_output_tokens"] = request.max_tokens
            response = await self.ai_provider.chat_completion(**request_kwargs)

            return response.content

        except Exception as e:
            logger.error(f"Error in PPT chat request: {e}")
            # Fallback to basic response
            return await self._generate_fallback_ppt_response(request.messages[-1].content)
    
    async def handle_ppt_completion_request(self, request: CompletionRequest) -> str:
        """Handle PPT-related completion request using real AI"""
        try:
            prompt = request.prompt if isinstance(request.prompt, str) else request.prompt[0]

            # Create enhanced prompt for PPT generation
            enhanced_prompt = self._create_ppt_prompt(prompt)

            # Generate response using AI provider
            request_kwargs: Dict[str, Any] = {
                "prompt": enhanced_prompt,
                "temperature": request.temperature or ai_config.temperature,
                "top_p": request.top_p or ai_config.top_p,
            }
            if request.max_tokens is not None:
                request_kwargs["max_output_tokens"] = request.max_tokens
            response = await self.ai_provider.text_completion(**request_kwargs)

            return response.content

        except Exception as e:
            logger.error(f"Error in PPT completion request: {e}")
            # Fallback to basic response
            return await self._generate_fallback_ppt_response(prompt)
    
    async def handle_general_chat_request(self, request: ChatCompletionRequest) -> str:
        """Handle general (non-PPT) chat completion request using real AI"""
        try:
            # Convert to AI messages
            ai_messages = []
            for msg in request.messages:
                ai_messages.append(AIMessage(
                    role=MessageRole(msg.role),
                    content=msg.content
                ))

            # Add system prompt for general assistance
            system_prompt = self._get_general_system_prompt()
            ai_messages.insert(0, AIMessage(
                role=MessageRole.SYSTEM,
                content=system_prompt
            ))

            # Generate response using AI provider
            request_kwargs: Dict[str, Any] = {
                "messages": ai_messages,
                "temperature": request.temperature or ai_config.temperature,
                "top_p": request.top_p or ai_config.top_p,
            }
            if request.max_tokens is not None:
                request_kwargs["max_output_tokens"] = request.max_tokens
            response = await self.ai_provider.chat_completion(**request_kwargs)

            return response.content

        except Exception as e:
            logger.error(f"Error in general chat request: {e}")
            # Fallback to simple response
            return self._generate_fallback_general_response(request.messages[-1].content)
    
    async def handle_general_completion_request(self, request: CompletionRequest) -> str:
        """Handle general (non-PPT) completion request using real AI"""
        try:
            prompt = request.prompt if isinstance(request.prompt, str) else request.prompt[0]

            # Create enhanced prompt for general assistance
            enhanced_prompt = self._create_general_prompt(prompt)

            # Generate response using AI provider
            request_kwargs: Dict[str, Any] = {
                "prompt": enhanced_prompt,
                "temperature": request.temperature or ai_config.temperature,
                "top_p": request.top_p or ai_config.top_p,
            }
            if request.max_tokens is not None:
                request_kwargs["max_output_tokens"] = request.max_tokens
            response = await self.ai_provider.text_completion(**request_kwargs)

            return response.content

        except Exception as e:
            logger.error(f"Error in general completion request: {e}")
            # Fallback to simple response
            return f"Based on your prompt: {prompt}\n\nI'm LandPPT AI, specialized in presentation generation. If you'd like to create a presentation about this topic, I'd be happy to help!"

    def _get_ppt_system_prompt(self) -> str:
        """Get system prompt for PPT generation"""
        return """You are LandPPT AI, an expert presentation generation assistant. Your role is to help users create professional, engaging PowerPoint presentations.

Key capabilities:
1. Generate structured PPT outlines with clear sections
2. Create content for different scenarios: general, tourism, education, analysis, history, technology, business
3. Adapt tone and style based on target audience
4. Provide actionable, well-organized content
5. Support both Chinese and English languages

When helping with PPT creation:
- Always ask clarifying questions if the request is vague
- Suggest appropriate scenarios based on the topic
- Provide structured, logical content organization
- Include practical tips for presentation delivery
- Offer to generate specific slide content when requested

Be helpful, professional, and focused on creating high-quality presentations."""

    def _get_general_system_prompt(self) -> str:
        """Get system prompt for general assistance"""
        return """You are LandPPT AI, a helpful assistant specialized in presentation generation. While you can provide general assistance, your primary expertise is in creating professional PowerPoint presentations.

When users ask non-PPT questions:
- Provide helpful, accurate information
- Always offer to help turn their topic into a presentation
- Suggest how the topic could be structured as slides
- Maintain a friendly, professional tone
- Keep responses concise but informative

Your goal is to be helpful while gently guiding users toward your presentation generation capabilities."""

    def _create_ppt_prompt(self, user_prompt: str) -> str:
        """Create enhanced prompt for PPT generation"""
        return f"""As LandPPT AI, help the user create a professional presentation based on this request:

"{user_prompt}"

Please provide:
1. A suggested PPT structure/outline
2. Recommended scenario (general, tourism, education, analysis, history, technology, or business)
3. Key points for each section
4. Target audience considerations
5. Presentation tips

Make your response practical and actionable for creating an effective presentation."""

    def _create_general_prompt(self, user_prompt: str) -> str:
        """Create enhanced prompt for general assistance"""
        return f"""As LandPPT AI, respond to this user query:

"{user_prompt}"

Provide a helpful response, and if relevant, suggest how this topic could be turned into an effective presentation. Keep your response informative but concise."""

    async def _generate_fallback_ppt_response(self, prompt: str) -> str:
        """Generate fallback PPT response when AI fails"""
        ppt_info = self._extract_ppt_info(prompt)
        return await self._generate_guidance_response(ppt_info)

    def _generate_fallback_general_response(self, prompt: str) -> str:
        """Generate fallback general response when AI fails"""
        if "hello" in prompt.lower() or "hi" in prompt.lower():
            return "Hello! I'm LandPPT AI, your presentation generation assistant. How can I help you create an amazing presentation today?"
        elif "help" in prompt.lower():
            return """I can help you create professional presentations! Here's what I can do:

1. **Generate PPT outlines** - Just tell me your topic and I'll create a structured outline
2. **Create full presentations** - I'll generate complete slides with content
3. **Multiple scenarios** - Choose from general, tourism, education, analysis, history, technology, or business templates
4. **Smart content generation** - I'll adapt the content to your specific needs

Try saying something like: "Create a PPT about artificial intelligence for beginners" or "Generate a business presentation outline for a new product launch"."""
        else:
            return f"I understand you're asking about: {prompt}\n\nWhile I'm primarily designed for PPT generation, I can provide some general assistance. However, my specialty is creating presentations. Would you like me to help you turn this topic into a presentation?"

    def _extract_ppt_info(self, text: str) -> Dict[str, Any]:
        """Extract PPT-related information from text"""
        info = {
            "topic": "",
            "scenario": "general",
            "requirements": "",
            "language": "zh" if self._contains_chinese(text) else "en"
        }
        
        # Extract topic (simple heuristic)
        topic_patterns = [
            r"about\s+(.+?)(?:\s+for|\s+ppt|\s+presentation|$)",
            r"关于\s*(.+?)(?:\s*的|\s*PPT|\s*演示|$)",
            r"主题\s*[:：]\s*(.+?)(?:\s|$)",
            r"topic\s*[:：]\s*(.+?)(?:\s|$)"
        ]
        
        for pattern in topic_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                info["topic"] = match.group(1).strip()
                break
        
        if not info["topic"]:
            # Fallback: use the whole text as topic
            info["topic"] = text.strip()
        
        # Detect scenario
        scenario_keywords = {
            "tourism": ["travel", "tourism", "旅游", "景点", "旅行"],
            "education": ["education", "children", "kids", "教育", "儿童", "科普"],
            "analysis": ["analysis", "data", "research", "分析", "研究", "数据"],
            "history": ["history", "historical", "culture", "历史", "文化"],
            "technology": ["technology", "tech", "software", "技术", "科技", "软件"],
            "business": ["business", "company", "corporate", "商业", "企业", "公司"]
        }
        
        text_lower = text.lower()
        for scenario, keywords in scenario_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                info["scenario"] = scenario
                break
        
        return info
    
    def _contains_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters"""
        return bool(re.search(r'[\u4e00-\u9fff]', text))
    
    async def _generate_outline_response(self, ppt_info: Dict[str, Any]) -> str:
        """Generate PPT outline response"""
        topic = ppt_info["topic"]
        scenario = ppt_info["scenario"]
        language = ppt_info["language"]
        
        template = self.scenario_templates.get(scenario, self.scenario_templates["general"])
        
        if language == "zh":
            response = f"""# {topic} - PPT大纲

## 基本信息
- **主题**: {topic}
- **场景**: {scenario}
- **风格**: {template['style']}

## 幻灯片结构

### 第1页：封面页
- 标题：{topic}
- 副标题：专业演示
- 日期和演讲者信息

### 第2页：目录
- 演示内容概览
- 主要章节导航

"""
            
            # Generate content based on scenario structure
            for i, section in enumerate(template["structure"], 3):
                section_names = {
                    "introduction": "引言",
                    "main_content": "主要内容", 
                    "conclusion": "总结",
                    "destination_overview": "目的地概览",
                    "attractions": "主要景点",
                    "itinerary": "行程安排",
                    "practical_info": "实用信息",
                    "learning_objectives": "学习目标",
                    "key_concepts": "核心概念",
                    "examples": "实例说明",
                    "activities": "互动活动",
                    "summary": "总结回顾",
                    "problem_statement": "问题陈述",
                    "methodology": "研究方法",
                    "findings": "研究发现",
                    "analysis": "深入分析",
                    "recommendations": "建议方案",
                    "background": "历史背景",
                    "timeline": "时间线",
                    "key_events": "关键事件",
                    "significance": "重要意义",
                    "legacy": "历史影响",
                    "overview": "技术概览",
                    "features": "核心功能",
                    "benefits": "优势特点",
                    "implementation": "实施方案",
                    "future": "未来展望",
                    "executive_summary": "执行摘要",
                    "problem": "问题分析",
                    "solution": "解决方案",
                    "market_analysis": "市场分析",
                    "financial_projections": "财务预测"
                }
                
                section_name = section_names.get(section, section)
                response += f"### 第{i}页：{section_name}\n- 相关内容要点\n- 支撑数据或案例\n\n"
            
            response += f"### 第{len(template['structure']) + 3}页：谢谢\n- 感谢聆听\n- 联系方式\n- Q&A环节"
            
        else:
            response = f"""# {topic} - PPT Outline

## Basic Information
- **Topic**: {topic}
- **Scenario**: {scenario}
- **Style**: {template['style']}

## Slide Structure

### Slide 1: Title Page
- Title: {topic}
- Subtitle: Professional Presentation
- Date and Presenter Information

### Slide 2: Agenda
- Presentation Overview
- Main Section Navigation

"""
            
            for i, section in enumerate(template["structure"], 3):
                response += f"### Slide {i}: {section.replace('_', ' ').title()}\n- Key content points\n- Supporting data or examples\n\n"
            
            response += f"### Slide {len(template['structure']) + 3}: Thank You\n- Thank you for your attention\n- Contact Information\n- Q&A Session"
        
        return response
    
