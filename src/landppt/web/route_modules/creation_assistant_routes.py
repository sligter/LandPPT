"""Conversational requirement intake for the creation composer."""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ...auth.middleware import get_current_user_required
from ...database.models import User
from ...services.creation_assistant import build_messages, extract_urls, parse_reply
from .project_lifecycle_routes import SCENARIOS
from .support import check_credits_for_operation, consume_credits_for_operation, get_ppt_service_for_user, logger

router = APIRouter()


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class CreationAssistantRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    messages: List[ChatTurn] = Field(min_length=1, max_length=40)
    fields: Dict[str, Any] = Field(default_factory=dict)
    attachments: List[str] = Field(default_factory=list, max_length=50)
    links: List[str] = Field(default_factory=list, max_length=50)
    conversation_id: str | None = Field(default=None, max_length=80)


@router.post("/api/ai/creation-assistant")
async def creation_assistant(
    body: CreationAssistantRequest,
    user: User = Depends(get_current_user_required),
):
    """One turn of the requirement conversation: a reply plus the form values it implies."""
    if body.messages[-1].role != "user":
        return {"success": False, "error": "请先输入你的需求"}
    try:
        from ...services.runtime.ai_execution import new_ai_conversation_id

        service = get_ppt_service_for_user(user.id)
        _, settings = await service.get_role_provider_async("outline")
        provider_name = settings.get("provider")
        has_credits, required, balance = await check_credits_for_operation(
            user.id, "ai_other", 1, provider_name=provider_name
        )
        if not has_credits:
            return {"success": False, "error": f"积分不足，需要 {required} 积分，当前余额 {balance} 积分"}

        history = [turn.model_dump() for turn in body.messages[-20:]]
        fields = {key: value for key, value in body.fields.items() if isinstance(value, (str, int, float, bool))}
        messages = build_messages(
            history,
            fields,
            [str(name)[:200] for name in body.attachments],
            [str(url)[:2000] for url in body.links],
            SCENARIOS,
        )
        response = await service._chat_completion_for_role(
            "outline",
            messages=messages,
            conversation_id=body.conversation_id or new_ai_conversation_id("creation-assistant"),
        )
        user_urls = extract_urls(turn.content for turn in body.messages if turn.role == "user")
        result = parse_reply(
            response.content or "",
            user_urls,
            [item["id"] for item in SCENARIOS],
            str(fields.get("topic") or ""),
        )
        await consume_credits_for_operation(
            user.id, "ai_other", 1, description="对话式需求确认", reference_id="", provider_name=provider_name
        )
        return {"success": True, **result}
    except Exception as exc:  # noqa: BLE001
        logger.error("Creation assistant failed: %s", exc)
        return {"success": False, "error": str(exc) or "需求助手暂时不可用，请稍后再试"}
