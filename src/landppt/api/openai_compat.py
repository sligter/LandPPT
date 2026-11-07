"""
OpenAI-compatible API endpoints
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
import json
import re
import time
import uuid
from typing import AsyncGenerator

from .models import (
    ChatCompletionRequest, ChatCompletionResponse, ChatCompletionChoice,
    CompletionRequest, CompletionResponse, CompletionChoice,
    ChatMessage, Usage
)
from ..services.ai_service import AIService
from ..core.config import ai_config

router = APIRouter()
ai_service = AIService()

@router.post("/chat/completions", response_model=None)
async def create_chat_completion(request: ChatCompletionRequest):
    """
    Create a chat completion (OpenAI compatible)
    """
    try:
        # Check if this is a PPT-related request
        last_message = request.messages[-1].content if request.messages else ""
        
        if ai_service.is_ppt_request(last_message):
            # Handle PPT generation request
            response_content = await ai_service.handle_ppt_chat_request(request)
        else:
            # Handle general chat request
            response_content = await ai_service.handle_general_chat_request(request)
        
        if request.stream:
            return StreamingResponse(
                _chat_completion_chunks(request.model, response_content),
                media_type="text/event-stream",
            )
        
        # Calculate token usage (simplified)
        prompt_tokens = sum(len(msg.content.split()) for msg in request.messages)
        completion_tokens = len(response_content.split())
        
        choice = ChatCompletionChoice(
            index=0,
            message=ChatMessage(role="assistant", content=response_content),
            finish_reason="stop"
        )
        
        return ChatCompletionResponse(
            model=request.model,
            choices=[choice],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            )
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating completion: {str(e)}")

@router.post("/completions", response_model=CompletionResponse)
async def create_completion(request: CompletionRequest):
    """
    Create a text completion (OpenAI compatible)
    """
    try:
        prompt = request.prompt if isinstance(request.prompt, str) else request.prompt[0]
        
        if ai_service.is_ppt_request(prompt):
            # Handle PPT generation request
            response_text = await ai_service.handle_ppt_completion_request(request)
        else:
            # Handle general completion request
            response_text = await ai_service.handle_general_completion_request(request)
        
        # Calculate token usage (simplified)
        prompt_tokens = len(prompt.split())
        completion_tokens = len(response_text.split())
        
        choice = CompletionChoice(
            text=response_text,
            index=0,
            finish_reason="stop"
        )
        
        return CompletionResponse(
            model=request.model,
            choices=[choice],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            )
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating completion: {str(e)}")

@router.get("/models")
async def list_models():
    """
    List available models (OpenAI compatible)
    """
    return {
        "object": "list",
        "data": [
            {
                "id": "landppt-v1",
                "object": "model",
                "created": 1677610602,
                "owned_by": "landppt",
                "permission": [],
                "root": "landppt-v1",
                "parent": None
            },
            {
                "id": "landppt-ppt-generator",
                "object": "model", 
                "created": 1677610602,
                "owned_by": "landppt",
                "permission": [],
                "root": "landppt-ppt-generator",
                "parent": None
            }
        ]
    }

async def _chat_completion_chunks(model: str, response_content: str) -> AsyncGenerator[str, None]:
    """
    Yield OpenAI-style SSE chunks for an already generated response
    """
    chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    def chunk(delta: dict, finish_reason=None) -> str:
        data = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(data)}\n\n"

    yield chunk({"role": "assistant"})
    # Split on word boundaries but keep the original whitespace (newlines matter)
    for piece in re.findall(r"\S+\s*|\s+", response_content):
        yield chunk({"content": piece})
    yield chunk({}, "stop")
    yield "data: [DONE]\n\n"


async def stream_chat_completion(request: ChatCompletionRequest) -> AsyncGenerator[str, None]:
    """
    Stream chat completion responses
    """
    try:
        last_message = request.messages[-1].content if request.messages else ""
        
        if ai_service.is_ppt_request(last_message):
            response_content = await ai_service.handle_ppt_chat_request(request)
        else:
            response_content = await ai_service.handle_general_chat_request(request)
        
        async for line in _chat_completion_chunks(request.model, response_content):
            yield line
        
    except Exception as e:
        error_chunk = {
            "error": {
                "message": str(e),
                "type": "server_error"
            }
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
