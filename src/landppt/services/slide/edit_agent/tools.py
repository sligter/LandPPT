"""Slide edit agent 的工具集。

工具规格（名字 / 描述 / JSON Schema）在这里只写一份，native tool-calling 的
schema 和文本协议提示词里的工具清单都由它派生，避免两份 schema 各自漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple

from bs4.element import Tag

from .draft import DraftRefError, SlideDraft
from .html_safety import (
    css_declaration_error,
    has_new_executable_content,
    is_safe_attribute,
    parse_style_declarations,
    serialize_style_declarations,
    validate_slide_html,
)
from .schema import SlideEditAgentContext

_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_STRING_MAP = {"type": "object", "additionalProperties": {"type": "string"}}

_TARGET_PROPERTIES = {
    "ref": {
        "type": "string",
        "description": "read_slide / find_elements 返回的元素引用，优先使用。",
    },
    "selector": {
        "type": "string",
        "description": "CSS 选择器，在没有 ref 时使用。",
    },
}

_INSERT_POSITIONS = ("before", "after", "prepend", "append")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    properties: Dict[str, Any] = field(default_factory=dict)
    required: Tuple[str, ...] = ()
    mutating: bool = False

    def json_schema(self) -> Dict[str, Any]:
        schema: Dict[str, Any] = {
            "type": "object",
            "properties": dict(self.properties),
            "additionalProperties": False,
        }
        if self.required:
            schema["required"] = list(self.required)
        return schema

    def to_native_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.json_schema(),
            },
        }

    def to_text_reference(self) -> Dict[str, Any]:
        reference: Dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "action_input": {
                key: value.get("type", "string") for key, value in self.properties.items()
            },
        }
        if self.required:
            reference["required"] = list(self.required)
        return reference


TOOL_SPECS: Tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_context",
        description="读取项目信息、页面大纲、编辑模式与当前选中元素。",
    ),
    ToolSpec(
        name="read_slide",
        description=(
            "读取当前草稿的结构树（每个节点带 ref，可直接用于后续编辑）。"
            "include_html=true 时附带原始 HTML。"
        ),
        properties={
            "include_html": _BOOLEAN,
            "max_chars": _INTEGER,
        },
    ),
    ToolSpec(
        name="find_elements",
        description="按 CSS 选择器或文本内容查找元素，返回 ref 列表。只读，不改动草稿。",
        properties={
            "selector": _STRING,
            "text": _STRING,
            "limit": _INTEGER,
        },
    ),
    ToolSpec(
        name="read_element",
        description="读取单个元素的完整 HTML。",
        properties={**_TARGET_PROPERTIES, "max_chars": _INTEGER},
    ),
    ToolSpec(
        name="set_text",
        description=(
            "修改元素的文字内容。元素内含子元素时会被拒绝，"
            "除非显式传 replace_children=true。"
        ),
        properties={
            **_TARGET_PROPERTIES,
            "text": _STRING,
            "replace_children": _BOOLEAN,
        },
        required=("text",),
        mutating=True,
    ),
    ToolSpec(
        name="set_attributes",
        description="设置元素属性；传空字符串表示删除该属性。",
        properties={**_TARGET_PROPERTIES, "attributes": _STRING_MAP},
        required=("attributes",),
        mutating=True,
    ),
    ToolSpec(
        name="set_style",
        description=(
            "改写元素的内联样式。mode=merge（默认）只更新给定声明，"
            "mode=replace 用给定声明替换整个 style。"
        ),
        properties={
            **_TARGET_PROPERTIES,
            "styles": _STRING_MAP,
            "mode": {"type": "string", "enum": ["merge", "replace"]},
        },
        required=("styles",),
        mutating=True,
    ),
    ToolSpec(
        name="insert_html",
        description="在目标元素的 before / after / prepend / append 位置插入 HTML 片段。",
        properties={
            **_TARGET_PROPERTIES,
            "position": {"type": "string", "enum": list(_INSERT_POSITIONS)},
            "html": _STRING,
        },
        required=("html",),
        mutating=True,
    ),
    ToolSpec(
        name="replace_element",
        description="用新的 HTML 片段整体替换目标元素。",
        properties={**_TARGET_PROPERTIES, "html": _STRING},
        required=("html",),
        mutating=True,
    ),
    ToolSpec(
        name="remove_element",
        description="删除目标元素。",
        properties=dict(_TARGET_PROPERTIES),
        mutating=True,
    ),
    ToolSpec(
        name="replace_slide",
        description="整页重写。仅在局部编辑无法完成时使用，改动面大。",
        properties={"html": _STRING},
        required=("html",),
        mutating=True,
    ),
    ToolSpec(
        name="validate_draft",
        description="校验当前草稿 HTML 是否安全、结构完整。",
    ),
    ToolSpec(
        name="diff_draft",
        description="查看草稿相对原始页面的改动（unified diff）。",
        properties={"max_lines": _INTEGER},
    ),
    ToolSpec(
        name="undo_last_edit",
        description="撤销自己上一步编辑。撤销后此前的 ref 全部失效，需要重新查询。",
        mutating=True,
    ),
)

TOOL_SPECS_BY_NAME: Dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: Dict[str, Any] = field(default_factory=dict)
    mutated: bool = False
    revision: int = 0

    def to_observation(self, tool: str) -> Dict[str, Any]:
        observation: Dict[str, Any] = {"tool": tool, "ok": self.ok, "summary": self.summary}
        observation.update(self.data)
        if self.mutated:
            observation["revision"] = self.revision
        return observation


def normalize_tool_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_")


class SlideEditToolbox:
    """把工具调用落到 SlideDraft 上，并记录一份可读的执行流水。"""

    def __init__(self, context: SlideEditAgentContext, draft: SlideDraft):
        self.context = context
        self.draft = draft
        self.transcript: List[Dict[str, Any]] = []
        self._handlers: Dict[str, Callable[[Dict[str, Any]], ToolResult]] = {
            "get_context": self._get_context,
            "read_slide": self._read_slide,
            "find_elements": self._find_elements,
            "read_element": self._read_element,
            "set_text": self._set_text,
            "set_attributes": self._set_attributes,
            "set_style": self._set_style,
            "insert_html": self._insert_html,
            "replace_element": self._replace_element,
            "remove_element": self._remove_element,
            "replace_slide": self._replace_slide,
            "validate_draft": self._validate_draft,
            "diff_draft": self._diff_draft,
            "undo_last_edit": self._undo_last_edit,
        }
        missing = [spec.name for spec in TOOL_SPECS if spec.name not in self._handlers]
        if missing:
            raise ValueError(f"Missing slide edit tool handlers: {', '.join(missing)}")

    # ------------------------------------------------------------------
    # 规格
    # ------------------------------------------------------------------
    @staticmethod
    def tool_names() -> List[str]:
        return [spec.name for spec in TOOL_SPECS]

    @staticmethod
    def native_schemas() -> List[Dict[str, Any]]:
        return [spec.to_native_schema() for spec in TOOL_SPECS]

    @staticmethod
    def text_reference() -> List[Dict[str, Any]]:
        return [spec.to_text_reference() for spec in TOOL_SPECS]

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------
    def execute(self, tool_name: str, tool_input: Any) -> ToolResult:
        name = normalize_tool_name(tool_name)
        args = tool_input if isinstance(tool_input, dict) else {}
        handler = self._handlers.get(name)

        if handler is None:
            result = ToolResult(
                ok=False,
                summary=f"unsupported tool: {name}",
                data={"available_tools": self.tool_names()},
            )
        else:
            try:
                result = handler(args)
            except DraftRefError as exc:
                result = ToolResult(ok=False, summary=str(exc))
            except ValueError as exc:
                result = ToolResult(ok=False, summary=str(exc))

        self.transcript.append(
            {
                "tool": name,
                "input": args,
                "ok": result.ok,
                "summary": result.summary,
            }
        )
        return result

    # ------------------------------------------------------------------
    # 目标解析
    # ------------------------------------------------------------------
    def _target(self, args: Dict[str, Any]) -> Tag:
        ref = str(args.get("ref") or "").strip()
        selector = str(args.get("selector") or "").strip()
        if not ref and not selector:
            selector = self._selected_element_selector()
            if not selector:
                raise DraftRefError("either ref or selector is required")
        return self.draft.resolve(ref=ref, selector=selector)

    def _selected_element_selector(self) -> str:
        element_id = str(self.context.selected_element_id or "").strip()
        if not element_id or '"' in element_id or "\\" in element_id:
            return ""
        return f'[data-quick-ai-id="{element_id}"], [data-agent-id="{element_id}"]'

    def _mutate(self, apply: Callable[[], None]) -> int:
        self.draft.begin_mutation()
        try:
            apply()
            if has_new_executable_content(self.draft.soup, self.draft.base_html):
                raise ValueError(
                    "existing scripts and event handlers are read-only; "
                    "new or modified executable content is not allowed"
                )
        except Exception:
            self.draft.rollback_mutation()
            raise
        return self.draft.commit_mutation()

    def _mutation_result(self, summary: str, revision: int, **data: Any) -> ToolResult:
        return ToolResult(
            ok=True,
            summary=summary,
            data=data,
            mutated=True,
            revision=revision,
        )

    # ------------------------------------------------------------------
    # 只读工具
    # ------------------------------------------------------------------
    def _get_context(self, args: Dict[str, Any]) -> ToolResult:
        selected: Dict[str, Any] = {}
        selector = self._selected_element_selector()
        if selector:
            try:
                node = self.draft.resolve(selector=selector)
                selected = self.draft._summarize(node).to_dict()
            except DraftRefError:
                selected = {"error": "selected element not found in the current draft"}

        return ToolResult(
            ok=True,
            summary="Loaded project, outline, and selection context.",
            data={
                "project": self.context.project_info,
                "slide_index": self.context.slide_index,
                "slide_title": self.context.slide_data.get("title"),
                "mode": self.context.mode,
                "outline": self.context.slide_outline,
                "selected_element": selected,
            },
        )

    def _read_slide(self, args: Dict[str, Any]) -> ToolResult:
        outline = self.draft.outline()
        data: Dict[str, Any] = {
            "revision": self.draft.revision,
            "structure": outline,
            "node_count": len(outline),
        }
        if bool(args.get("include_html")):
            max_chars = _positive_int(args.get("max_chars"), default=8000, maximum=40000)
            html = self.draft.html
            data["html"] = html[:max_chars]
            data["html_truncated"] = len(html) > max_chars
        return ToolResult(
            ok=True,
            summary=f"Read draft structure: {len(outline)} elements.",
            data=data,
        )

    def _find_elements(self, args: Dict[str, Any]) -> ToolResult:
        limit = _positive_int(args.get("limit"), default=20, maximum=100)
        matches = self.draft.find(
            selector=str(args.get("selector") or ""),
            text=str(args.get("text") or ""),
            limit=limit,
        )
        return ToolResult(
            ok=True,
            summary=f"Found {len(matches)} elements.",
            data={"matches": [match.to_dict() for match in matches]},
        )

    def _read_element(self, args: Dict[str, Any]) -> ToolResult:
        node = self._target(args)
        max_chars = _positive_int(args.get("max_chars"), default=4000, maximum=20000)
        return ToolResult(
            ok=True,
            summary=f"Read <{node.name}> html.",
            data={
                "ref": self.draft.ref_for(node),
                "html": self.draft.element_html(node, max_chars=max_chars),
            },
        )

    def _validate_draft(self, args: Dict[str, Any]) -> ToolResult:
        validation = validate_slide_html(self.draft.html, baseline_html=self.draft.base_html)
        return ToolResult(
            ok=validation.valid,
            summary="Draft HTML is valid." if validation.valid else "Draft HTML failed validation.",
            data={"errors": validation.errors, "warnings": validation.warnings},
        )

    def _diff_draft(self, args: Dict[str, Any]) -> ToolResult:
        max_lines = _positive_int(args.get("max_lines"), default=160, maximum=600)
        diff = self.draft.diff(max_lines=max_lines)
        summary = "Draft differs from the base slide." if diff["changed"] else "Draft still matches the base slide."
        return ToolResult(ok=True, summary=summary, data=diff)

    # ------------------------------------------------------------------
    # 变更工具
    # ------------------------------------------------------------------
    def _set_text(self, args: Dict[str, Any]) -> ToolResult:
        node = self._target(args)
        text = str(args.get("text") or "")
        child_elements = [child for child in node.children if isinstance(child, Tag)]
        if child_elements and not bool(args.get("replace_children")):
            return ToolResult(
                ok=False,
                summary=(
                    f"<{node.name}> contains {len(child_elements)} child element(s); "
                    "set_text would delete them. Target a leaf element, use replace_element, "
                    "or pass replace_children=true on purpose."
                ),
                data={"child_tags": [child.name for child in child_elements][:10]},
            )

        def apply() -> None:
            node.clear()
            node.append(text)

        revision = self._mutate(apply)
        return self._mutation_result(
            f"Set text on <{node.name}>.",
            revision,
            ref=self.draft.ref_for(node),
        )

    def _set_attributes(self, args: Dict[str, Any]) -> ToolResult:
        node = self._target(args)
        raw = args.get("attributes")
        if not isinstance(raw, dict) or not raw:
            return ToolResult(ok=False, summary="attributes must be a non-empty object")

        updates: Dict[str, str] = {}
        removals: List[str] = []
        rejected: List[str] = []
        for name, value in raw.items():
            key = str(name or "").strip()
            text_value = "" if value is None else str(value)
            if not is_safe_attribute(key, text_value):
                rejected.append(key or str(name))
                continue
            if text_value == "":
                removals.append(key)
            else:
                updates[key] = text_value

        if not updates and not removals:
            return ToolResult(
                ok=False,
                summary="no safe attribute left to apply",
                data={"rejected": rejected},
            )

        def apply() -> None:
            for key in removals:
                node.attrs.pop(key, None)
            for key, value in updates.items():
                node[key] = value

        revision = self._mutate(apply)
        data: Dict[str, Any] = {"ref": self.draft.ref_for(node)}
        if rejected:
            data["rejected"] = rejected
        return self._mutation_result(
            f"Updated {len(updates)} and removed {len(removals)} attribute(s) on <{node.name}>.",
            revision,
            **data,
        )

    def _set_style(self, args: Dict[str, Any]) -> ToolResult:
        node = self._target(args)
        raw = args.get("styles")
        if not isinstance(raw, dict) or not raw:
            return ToolResult(ok=False, summary="styles must be a non-empty object")

        mode = str(args.get("mode") or "merge").strip().lower()
        if mode not in {"merge", "replace"}:
            return ToolResult(ok=False, summary='mode must be "merge" or "replace"')

        accepted: Dict[str, str] = {}
        rejected: List[str] = []
        for prop, value in raw.items():
            prop_name = str(prop or "").strip().lower()
            css_value = str(value or "").strip()
            error = css_declaration_error(prop_name, css_value)
            if error:
                rejected.append(error)
                continue
            accepted[prop_name] = css_value

        if not accepted:
            return ToolResult(
                ok=False,
                summary="no safe css declaration left to apply",
                data={"rejected": rejected},
            )

        declarations = {} if mode == "replace" else parse_style_declarations(str(node.get("style") or ""))
        declarations.update(accepted)

        def apply() -> None:
            node["style"] = serialize_style_declarations(declarations)

        revision = self._mutate(apply)
        data: Dict[str, Any] = {"ref": self.draft.ref_for(node), "style": node.get("style", "")}
        if rejected:
            data["rejected"] = rejected
        return self._mutation_result(
            f"Applied {len(accepted)} css declaration(s) to <{node.name}> ({mode}).",
            revision,
            **data,
        )

    def _insert_html(self, args: Dict[str, Any]) -> ToolResult:
        node = self._target(args)
        position = str(args.get("position") or "append").strip().lower()
        if position not in _INSERT_POSITIONS:
            return ToolResult(
                ok=False,
                summary=f"position must be one of {', '.join(_INSERT_POSITIONS)}",
            )
        fragment = self.draft.parse_fragment(str(args.get("html") or ""))
        if position in {"before", "after"} and node.parent is None:
            return ToolResult(
                ok=False,
                summary="cannot insert next to the draft root; use prepend or append instead",
            )

        def apply() -> None:
            nodes = [child.extract() for child in fragment]
            if position == "append":
                for child in nodes:
                    node.append(child)
            elif position == "prepend":
                for offset, child in enumerate(nodes):
                    node.insert(offset, child)
            elif position == "before":
                for child in nodes:
                    node.insert_before(child)
            else:
                for child in reversed(nodes):
                    node.insert_after(child)

        revision = self._mutate(apply)
        return self._mutation_result(
            f"Inserted {len(fragment)} node(s) {position} <{node.name}>.",
            revision,
            ref=self.draft.ref_for(node),
        )

    def _replace_element(self, args: Dict[str, Any]) -> ToolResult:
        node = self._target(args)
        fragment = self.draft.parse_fragment(str(args.get("html") or ""))
        if node.parent is None:
            return ToolResult(
                ok=False,
                summary="cannot replace the draft root; use replace_slide instead",
            )

        replacement = fragment[0]
        # 保留原元素上的定位属性，否则元素模式下的选中态会在替换后丢失。
        for attr in ("data-quick-ai-id", "id"):
            value = node.get(attr)
            if value and not replacement.get(attr):
                replacement[attr] = value

        def apply() -> None:
            nodes = [child.extract() for child in fragment]
            node.replace_with(nodes[0])
            previous = nodes[0]
            for child in nodes[1:]:
                previous.insert_after(child)
                previous = child

        revision = self._mutate(apply)
        return self._mutation_result(
            f"Replaced <{node.name}> with <{replacement.name}>.",
            revision,
            ref=self.draft.ref_for(replacement),
        )

    def _remove_element(self, args: Dict[str, Any]) -> ToolResult:
        node = self._target(args)
        if node.parent is None:
            return ToolResult(ok=False, summary="cannot remove the draft root")
        tag_name = node.name

        def apply() -> None:
            node.decompose()

        revision = self._mutate(apply)
        return self._mutation_result(f"Removed <{tag_name}>.", revision)

    def _replace_slide(self, args: Dict[str, Any]) -> ToolResult:
        html = str(args.get("html") or "").strip()
        validation = validate_slide_html(html, baseline_html=self.draft.base_html)
        if not validation.valid:
            return ToolResult(
                ok=False,
                summary="replacement slide html failed validation",
                data={"errors": validation.errors},
            )

        self.draft.replace_all(validation.sanitized_html)
        return self._mutation_result(
            "Replaced the whole slide draft; earlier refs are invalid now.",
            self.draft.revision,
            refs_invalidated=True,
        )

    def _undo_last_edit(self, args: Dict[str, Any]) -> ToolResult:
        if not self.draft.undo():
            return ToolResult(ok=False, summary="there is no edit to undo")
        return self._mutation_result(
            "Undid the last edit; earlier refs are invalid now.",
            self.draft.revision,
            refs_invalidated=True,
        )


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return min(parsed, maximum)
