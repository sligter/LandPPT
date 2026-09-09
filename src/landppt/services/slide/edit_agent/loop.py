"""统一的 slide edit agent 循环。

只有一套控制流：

    for iteration in 1..max:
        turn = await protocol.next_turn()
        if turn.tool_calls: 执行 -> 写回观察 -> 继续
        else:               收尾

协议（native tool_calls / JSON 文本）只决定消息怎么编解码，不参与控制流；
中止、计费、事件、草稿版本都挂在这一层。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import events
from .draft import SlideDraft
from .events import AgentEventEmitter, EventCallback
from .html_safety import compute_slide_html_hash, validate_slide_html
from .prompt import build_messages
from .protocol import (
    AgentTurn,
    NativeToolProtocolAdapter,
    ProtocolAdapter,
    TextToolProtocolAdapter,
    ToolCall,
    ToolProtocol,
    ToolProtocolRegistry,
    is_tool_parameter_rejection,
    tool_protocol_registry,
)
from .runs import AgentRunHandle
from .schema import (
    SlideEditAgentContext,
    SlideEditAgentRequest,
    SlideEditProposal,
    SlideEditRunResult,
    coerce_agent_max_iterations,
    new_proposal_id,
    now,
)
from .tools import SlideEditToolbox

logger = logging.getLogger(__name__)

#: 单条 draft_updated 事件里内联 HTML 的上限，超了就只报版本号。
_DRAFT_HTML_STREAM_LIMIT = 400_000

_MALFORMED_TEXT_TURN_HINT = (
    "上一轮回复不是合法的 JSON action。请只输出一个 JSON 对象，"
    '包含 "thought"、"action"、"action_input" 三个字段。'
)


class _ProtocolDowngrade(Exception):
    """provider 实际不支持原生工具调用，需要改用文本协议重跑。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class SlideEditAgentRun:
    """一次针对单页的 agent run。"""

    def __init__(
        self,
        context: SlideEditAgentContext,
        user_ppt_service: Any,
        *,
        event_callback: Optional[EventCallback] = None,
        handle: Optional[AgentRunHandle] = None,
    ):
        self.context = context
        self.user_ppt_service = user_ppt_service
        self.handle = handle
        self.emitter = AgentEventEmitter(context.run_id, event_callback)
        self.max_iterations = coerce_agent_max_iterations(context.request.maxIterations)
        self.role = _provider_role(context.request)
        self.draft = SlideDraft(context.base_html)
        self.toolbox = SlideEditToolbox(context, self.draft)
        self._iterations_used = 0

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    async def execute(self) -> SlideEditRunResult:
        protocol_key = await self._protocol_key()
        protocol = tool_protocol_registry.preferred(protocol_key)

        await self.emitter.emit(
            events.RUN_STARTED,
            projectId=self.context.project_id,
            slideIndex=self.context.slide_index,
            mode=self.context.mode,
            protocol=protocol.value,
            maxIterations=self.max_iterations,
            baseHash=self.draft.base_hash,
            tools=SlideEditToolbox.tool_names(),
        )

        try:
            return await self._drive(protocol)
        except _ProtocolDowngrade as downgrade:
            tool_protocol_registry.mark_text_only(protocol_key, downgrade.reason)
            await self.emitter.emit(
                events.PROTOCOL_CHANGED,
                protocol=ToolProtocol.TEXT.value,
                reason=downgrade.reason,
            )
            # 降级只发生在任何工具执行之前，但仍然重建草稿，确保干净起点。
            self._reset_draft()
            return await self._drive(ToolProtocol.TEXT)
        except Exception as exc:  # noqa: BLE001
            if not getattr(exc, "_slide_edit_error_emitted", False):
                await self.emitter.emit_error(exc, phase="model")
            raise

    def _reset_draft(self) -> None:
        self.draft = SlideDraft(self.context.base_html)
        self.toolbox = SlideEditToolbox(self.context, self.draft)
        self._iterations_used = 0

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------
    async def _drive(self, protocol: ToolProtocol) -> SlideEditRunResult:
        adapter = self._build_adapter(protocol)
        executed_tool = False

        for iteration in range(1, self.max_iterations + 1):
            if self._cancelled():
                return await self._finish("cancelled", iteration - 1)

            self._iterations_used = iteration
            await self.emitter.emit(events.TURN_STARTED, iteration=iteration)

            turn = await self._next_turn(adapter, iteration, executed_tool)

            if turn.malformed:
                if executed_tool or iteration >= self.max_iterations:
                    return await self._finish("completed", iteration, summary=turn.text)
                adapter.record_turn(turn)
                adapter.record_correction(_MALFORMED_TEXT_TURN_HINT)
                continue

            if turn.text:
                await self.emitter.emit(events.THINKING, iteration=iteration, text=turn.text)

            adapter.record_turn(turn)

            if not turn.tool_calls:
                return await self._finish("completed", iteration, summary=turn.text)

            for call in turn.tool_calls:
                observation = await self._run_tool(adapter, call, iteration)
                executed_tool = True
                adapter.record_tool_result(call, observation)
                if self._cancelled():
                    return await self._finish("cancelled", iteration)

        return await self._finish("max_iterations", self.max_iterations)

    async def _protocol_key(self) -> str:
        """协议能力表的键：provider + model。取不到就当未知，走默认 NATIVE。"""
        getter = getattr(self.user_ppt_service, "get_role_provider_async", None)
        provider_name: Optional[str] = None
        model: Optional[str] = None
        if getter is not None:
            try:
                _, settings = await getter(self.role)
                if isinstance(settings, dict):
                    provider_name = settings.get("provider")
                    model = settings.get("model")
            except Exception:  # noqa: BLE001
                logger.debug("Slide edit agent could not resolve provider settings", exc_info=True)
        return ToolProtocolRegistry.key_for(provider_name, model)

    def _build_adapter(self, protocol: ToolProtocol) -> ProtocolAdapter:
        messages = build_messages(
            self.context,
            self.draft,
            protocol=protocol,
            max_iterations=self.max_iterations,
        )
        chat = self._chat_fn()
        if protocol is ToolProtocol.NATIVE:
            return NativeToolProtocolAdapter(chat, messages, SlideEditToolbox.native_schemas())
        return TextToolProtocolAdapter(chat, messages)

    def _chat_fn(self):
        async def chat(**kwargs: Any):
            return await self.user_ppt_service._chat_completion_for_role(self.role, **kwargs)

        return chat

    async def _next_turn(
        self, adapter: ProtocolAdapter, iteration: int, executed_tool: bool
    ) -> AgentTurn:
        try:
            turn = await adapter.next_turn()
        except Exception as exc:  # noqa: BLE001
            downgradable = (
                adapter.protocol is ToolProtocol.NATIVE
                and not executed_tool
                and iteration == 1
                and is_tool_parameter_rejection(exc)
            )
            if downgradable:
                raise _ProtocolDowngrade(str(exc) or exc.__class__.__name__) from exc
            await self.emitter.emit_error(exc, phase="model", iteration=iteration)
            setattr(exc, "_slide_edit_error_emitted", True)
            raise

        if turn.looks_tool_blind and not executed_tool:
            raise _ProtocolDowngrade(
                "provider returned a text action instead of native tool_calls"
            )
        return turn

    async def _run_tool(
        self, adapter: ProtocolAdapter, call: ToolCall, iteration: int
    ) -> Dict[str, Any]:
        await self.emitter.emit(
            events.TOOL_STARTED,
            iteration=iteration,
            callId=call.id,
            tool=call.name,
            toolInput=call.arguments,
        )

        try:
            result = self.toolbox.execute(call.name, call.arguments)
        except Exception as exc:  # noqa: BLE001
            await self.emitter.emit_error(exc, phase="tool", iteration=iteration, tool=call.name)
            setattr(exc, "_slide_edit_error_emitted", True)
            raise

        observation = result.to_observation(call.name)
        await self.emitter.emit(
            events.TOOL_FINISHED,
            iteration=iteration,
            callId=call.id,
            tool=call.name,
            ok=result.ok,
            summary=result.summary,
            observation=observation,
        )

        if result.mutated and result.ok:
            await self._emit_draft_updated(result.summary)

        return observation

    async def _emit_draft_updated(self, summary: str) -> None:
        html = self.draft.clean_html()
        payload: Dict[str, Any] = {
            "revision": self.draft.revision,
            "changed": self.draft.changed,
            "summary": summary,
            "htmlHash": compute_slide_html_hash(html),
        }
        if len(html) <= _DRAFT_HTML_STREAM_LIMIT:
            payload["html"] = html
        else:
            payload["htmlOmitted"] = True
        await self.emitter.emit(events.DRAFT_UPDATED, **payload)

    # ------------------------------------------------------------------
    # 收尾
    # ------------------------------------------------------------------
    def _cancelled(self) -> bool:
        return bool(self.handle and self.handle.cancelled)

    async def _finish(
        self, status: str, iterations_used: int, *, summary: str = ""
    ) -> SlideEditRunResult:
        proposal = self._build_proposal(_finish_summary(status, summary, self.draft.changed))
        await self.emitter.emit(
            events.VALIDATION,
            valid=proposal.validation.valid,
            errors=proposal.validation.errors,
            warnings=proposal.validation.warnings,
        )

        result = SlideEditRunResult(
            run_id=self.context.run_id,
            status=status,  # type: ignore[arg-type]
            summary=proposal.summary,
            proposal=proposal,
            iterations_used=iterations_used or self._iterations_used,
        )
        await self.emitter.emit(events.RUN_FINISHED, **result.to_public_dict())
        return result

    def _build_proposal(self, summary: str) -> SlideEditProposal:
        cleaned_html = self.draft.clean_html()
        validation = validate_slide_html(cleaned_html, baseline_html=self.draft.base_html)
        if not validation.valid:
            summary = "草稿未通过安全校验，尚不能保存：" + "；".join(validation.errors)
        diff = self.draft.diff()
        slide_data = {
            **self.context.slide_data,
            "html_content": validation.sanitized_html,
            "is_user_edited": True,
        }
        return SlideEditProposal(
            proposal_id=new_proposal_id(),
            base_hash=self.draft.base_hash,
            summary=summary,
            changed_slide_indices=[self.context.slide_index],
            html_content=validation.sanitized_html,
            validation=validation,
            tool_transcript=list(self.toolbox.transcript),
            slide_data=slide_data,
            created_at=now(),
            revision=self.draft.revision,
            changed=self.draft.changed,
            diff=diff.get("diff", ""),
        )


def _finish_summary(status: str, summary: str, changed: bool) -> str:
    text = (summary or "").strip()
    if text:
        return text
    if status == "cancelled":
        return "已停止。以下是停止前的草稿。" if changed else "已停止，页面未做改动。"
    if status == "max_iterations":
        return "达到最大迭代轮数，返回当前草稿。"
    return "已完成编辑。" if changed else "未对页面做出改动。"


def _provider_role(request: SlideEditAgentRequest) -> str:
    has_vision_input = bool(
        request.slideScreenshot or request.elementScreenshot or request.images
    )
    return "vision_analysis" if request.visionEnabled and has_vision_input else "editor"


class SlideEditAgentService:
    """路由层的入口。"""

    async def run_agent(
        self,
        request: SlideEditAgentRequest,
        user_ppt_service: Any,
        event_callback: Optional[EventCallback] = None,
        *,
        handle: Optional[AgentRunHandle] = None,
    ) -> SlideEditRunResult:
        context = SlideEditAgentContext.from_request(request)
        run = SlideEditAgentRun(
            context,
            user_ppt_service,
            event_callback=event_callback,
            handle=handle,
        )
        return await run.execute()


__all__: List[str] = [
    "SlideEditAgentRun",
    "SlideEditAgentService",
]
