import json
from types import SimpleNamespace

import pytest

from landppt.ai.base import AIResponse, ImageContent, MessageRole, TextContent
from landppt.services.slide.edit_agent import prompt as agent_prompt
from landppt.services.slide.edit_agent.html_safety import has_new_executable_content
from landppt.services.slide.slide_edit_agent_service import (
    DraftRefError,
    SlideDraft,
    SlideEditAgentContext,
    SlideEditAgentRequest,
    SlideEditAgentService,
    SlideEditToolbox,
    ToolProtocol,
    ToolProtocolRegistry,
    agent_run_registry,
    coerce_agent_max_iterations,
    compute_slide_html_hash,
    sanitize_slide_html,
    strip_agent_ids,
    tool_protocol_registry,
    validate_slide_html,
)

BASE_HTML = (
    '<div class="slide" style="width:1280px;height:720px">'
    '<h1 class="title" style="color:#111">Long Original Title</h1>'
    '<ul class="points"><li>Alpha</li><li>Beta</li></ul>'
    "</div>"
)


# ---------------------------------------------------------------------------
# HTML 安全
# ---------------------------------------------------------------------------


def test_compute_slide_html_hash_is_stable_for_equivalent_text():
    assert compute_slide_html_hash(" <div>A</div>\n") == compute_slide_html_hash("<div>A</div>")
    assert compute_slide_html_hash("<div>A</div>") != compute_slide_html_hash("<div>B</div>")


def test_sanitize_slide_html_removes_scripts_event_handlers_and_agent_ids():
    html = (
        '<div data-agent-id="a1" onclick="bad()" style="width:1280px;height:720px">'
        '<a href="javascript:bad()">x</a><script>alert(1)</script>'
        "</div>"
    )

    sanitized = sanitize_slide_html(html)

    assert "<script" not in sanitized.lower()
    assert "onclick" not in sanitized.lower()
    assert "javascript:" not in sanitized.lower()
    assert "data-agent-id" not in strip_agent_ids(sanitized)


def test_validate_slide_html_reports_unsafe_original_html():
    result = validate_slide_html('<div><script>alert(1)</script><p onclick="x()">Hi</p></div>')

    assert result.valid is False
    assert "script tags are not allowed" in result.errors
    assert "inline event handlers are not allowed" in result.errors
    assert "<script" not in result.sanitized_html.lower()


def test_validate_slide_html_rejects_encoded_javascript_urls():
    result = validate_slide_html('<div><a href="java&#115;cript:alert(1)">x</a></div>')

    assert result.valid is False
    assert "javascript urls are not allowed" in result.errors
    assert "javascript:" not in result.sanitized_html.lower()
    assert "href=" not in result.sanitized_html.lower()


@pytest.mark.parametrize(
    "html",
    [
        '<div><a href="java&#10;script:alert(1)">x</a></div>',
        '<div><a href="jav&#x09;ascript:alert(1)">x</a></div>',
    ],
)
def test_validate_slide_html_rejects_encoded_control_javascript_urls(html):
    result = validate_slide_html(html)

    assert result.valid is False
    assert "javascript urls are not allowed" in result.errors
    assert "href=" not in result.sanitized_html.lower()


def test_validate_slide_html_rejects_srcdoc_attributes():
    result = validate_slide_html(
        '<div><iframe srcdoc="&lt;script&gt;alert(1)&lt;/script&gt;"></iframe></div>'
    )

    assert result.valid is False
    assert "srcdoc attributes are not allowed" in result.errors
    assert "srcdoc" not in result.sanitized_html.lower()
    assert "<script" not in result.sanitized_html.lower()


def test_validate_slide_html_accepts_clean_slide_html():
    result = validate_slide_html('<div style="width:1280px;height:720px"><h1>Hello</h1></div>')

    assert result.valid is True
    assert result.errors == []
    assert "Hello" in result.sanitized_html


SCRIPTED_HTML = (
    '<html><head><script src="/static/chart.js"></script></head><body>'
    '<h1 style="height:100px">Title</h1><canvas id="chart"></canvas>'
    '<script>const chart = document.getElementById("chart");</script>'
    '</body></html>'
)


def test_validation_preserves_unchanged_original_scripts_after_layout_edit():
    html = SCRIPTED_HTML.replace("height:100px", "height:120px")
    result = validate_slide_html(html, baseline_html=SCRIPTED_HTML)
    assert result.valid, result.errors
    assert 'height:120px' in result.sanitized_html
    assert '<script src="/static/chart.js"></script>' in result.sanitized_html
    assert 'const chart = document.getElementById("chart");' in result.sanitized_html
    assert not validate_slide_html(html).valid


@pytest.mark.parametrize("transform", [
    lambda html: html.replace('/static/chart.js', '/new.js'),
    lambda html: html.replace('const chart =', 'window.evil ='),
    lambda html: html.replace('</body>', '<script>alert(1)</script></body>'),
    lambda html: html.replace('</body>', '<script src="/static/chart.js"></script></body>'),
    lambda html: html.replace('<head>', '<head><base href="https://example.com/">'),
    lambda html: html.replace('<canvas', '<canvas onclick="bad()"'),
    lambda html: html.replace('<canvas', '<canvas data-x="javascript:bad()"'),
])
def test_baseline_scripts_do_not_allow_new_active_content(transform):
    assert not validate_slide_html(transform(SCRIPTED_HTML), baseline_html=SCRIPTED_HTML).valid


def test_reordering_original_scripts_is_rejected():
    baseline = '<div>Title<script>first()</script><script>second()</script></div>'
    changed = '<div>Title<script>second()</script><script>first()</script></div>'
    assert not validate_slide_html(changed, baseline_html=baseline).valid


def test_script_identifiers_can_be_removed_without_changing_script_content():
    baseline = '<div>Title<script data-agent-id="a" data-quick-ai-id="b">draw()</script></div>'
    cleaned = strip_agent_ids(baseline)
    assert validate_slide_html(cleaned, baseline_html=baseline).valid


SRI_BASELINE = (
    '<div>Title<script src="https://cdn.example.com/chart.js" '
    'integrity="sha384-abc" crossorigin="anonymous"></script></div>'
)


def test_preview_stripped_sri_metadata_still_counts_as_unchanged_script():
    # 编辑器预览渲染前会剥掉 integrity/crossorigin，基于预览 DOM 的草稿就长这样。
    stripped = '<div>Title<script src="https://cdn.example.com/chart.js"></script></div>'
    result = validate_slide_html(stripped, baseline_html=SRI_BASELINE)
    assert result.valid, result.errors
    assert 'src="https://cdn.example.com/chart.js"' in result.sanitized_html


@pytest.mark.parametrize("html", [
    '<div>Title<script src="https://cdn.example.com/evil.js"></script></div>',
    '<div>Title<script src="https://cdn.example.com/chart.js">run()</script></div>',
    '<div>Title<script src="https://cdn.example.com/chart.js" async></script></div>',
])
def test_sri_tolerance_does_not_extend_to_url_body_or_other_attributes(html):
    assert not validate_slide_html(html, baseline_html=SRI_BASELINE).valid


def test_has_new_executable_content_accepts_live_draft_tree():
    draft = SlideDraft(SCRIPTED_HTML)
    assert not has_new_executable_content(draft.soup, SCRIPTED_HTML)
    draft.soup.find("script", src=True)["src"] = "/evil.js"
    assert has_new_executable_content(draft.soup, SCRIPTED_HTML)

    draft = SlideDraft(HANDLER_HTML)
    assert not has_new_executable_content(draft.soup, HANDLER_HTML)
    draft.soup.find("h1")["onclick"] = "bad()"
    assert has_new_executable_content(draft.soup, HANDLER_HTML)


HANDLER_HTML = (
    '<div class="slide"><h1 style="height:100px">Title</h1>'
    '<button class="tab" onclick="showTab(1)">Tab 1</button>'
    '<button class="tab" onclick="showTab(2)">Tab 2</button>'
    '<a href="javascript:void(0)" class="more">More</a></div>'
)


def test_unchanged_baseline_event_handlers_survive_a_layout_edit():
    html = HANDLER_HTML.replace("height:100px", "height:120px")
    result = validate_slide_html(html, baseline_html=HANDLER_HTML)
    assert result.valid, result.errors
    assert "height:120px" in result.sanitized_html
    assert result.sanitized_html.count('onclick="showTab(') == 2
    assert 'href="javascript:void(0)"' in result.sanitized_html
    assert not validate_slide_html(html).valid


@pytest.mark.parametrize("transform", [
    lambda html: html.replace('onclick="showTab(1)"', 'onclick="steal()"'),
    lambda html: html.replace("<h1 ", '<h1 onmouseover="bad()" '),
    lambda html: html.replace("</div>", '<button onclick="showTab(1)">Copy</button></div>'),
    lambda html: html.replace('<a href="javascript:void(0)"', '<a href="javascript:bad()"'),
    lambda html: html.replace('<button class="tab" onclick="showTab(1)"', '<div onclick="showTab(1)"').replace("Tab 1</button>", "Tab 1</div>"),
    lambda html: html.replace("<h1 ", '<h1 srcdoc="x" '),
])
def test_baseline_handlers_do_not_allow_new_or_modified_executable_attributes(transform):
    assert not validate_slide_html(transform(HANDLER_HTML), baseline_html=HANDLER_HTML).valid


def test_baseline_handlers_may_be_removed_or_reordered_with_their_elements():
    removed = HANDLER_HTML.replace('<button class="tab" onclick="showTab(2)">Tab 2</button>', "")
    assert validate_slide_html(removed, baseline_html=HANDLER_HTML).valid
    moved = HANDLER_HTML.replace(
        '<button class="tab" onclick="showTab(1)">Tab 1</button>'
        '<button class="tab" onclick="showTab(2)">Tab 2</button>',
        '<button class="tab" onclick="showTab(2)">Tab 2</button>'
        '<button class="tab" onclick="showTab(1)">Tab 1</button>',
    )
    assert validate_slide_html(moved, baseline_html=HANDLER_HTML).valid


def test_replace_slide_keeps_baseline_handlers_and_rejects_modified_ones():
    toolbox, draft = _toolbox(slideContent=HANDLER_HTML)
    assert toolbox.execute("set_style", {"selector": "h1", "styles": {"height": "120px"}}).ok
    assert toolbox.execute("validate_draft", {}).ok
    assert toolbox.execute("replace_slide", {"html": HANDLER_HTML.replace("Title", "New title")}).ok
    assert draft.html.count("onclick=") == 2
    blocked = toolbox.execute("replace_slide", {"html": draft.html.replace("showTab(1)", "steal()")})
    assert not blocked.ok
    assert "showTab(1)" in draft.html and "steal()" not in draft.html


def test_text_mentioning_script_tag_is_not_executable_code():
    result = validate_slide_html('<div><!-- <script example -->Use &lt;script&gt; carefully</div>')
    assert result.valid


def test_coerce_agent_max_iterations_defaults_and_clamps():
    assert coerce_agent_max_iterations(None) == 12
    assert coerce_agent_max_iterations(1) == 2
    assert coerce_agent_max_iterations(8) == 8
    assert coerce_agent_max_iterations(999) == 100
    assert coerce_agent_max_iterations("bad") == 12


# ---------------------------------------------------------------------------
# SlideDraft
# ---------------------------------------------------------------------------


def test_draft_refs_are_never_written_into_html():
    draft = SlideDraft(BASE_HTML)
    matches = draft.find(selector="h1")

    assert len(matches) == 1
    assert matches[0].ref.startswith("e")
    assert "data-agent-id" not in draft.html
    assert draft.html == BASE_HTML
    assert draft.changed is False


def test_draft_ref_survives_edits_to_other_elements():
    draft = SlideDraft(BASE_HTML)
    title_ref = draft.find(selector="h1")[0].ref
    list_node = draft.resolve(selector="ul")

    draft.begin_mutation()
    list_node.append(draft.parse_fragment("<li>Gamma</li>")[0])
    draft.commit_mutation()

    assert draft.resolve(ref=title_ref).name == "h1"


def test_draft_reports_stale_ref_after_removal():
    draft = SlideDraft(BASE_HTML)
    ref = draft.find(selector="li")[0].ref
    node = draft.resolve(ref=ref)

    draft.begin_mutation()
    node.decompose()
    draft.commit_mutation()

    with pytest.raises(DraftRefError) as exc:
        draft.resolve(ref=ref)
    assert "removed by an earlier edit" in str(exc.value)


def test_draft_undo_restores_previous_html():
    draft = SlideDraft(BASE_HTML)
    node = draft.resolve(selector="h1")

    draft.begin_mutation()
    node.string = "Short"
    draft.commit_mutation()
    assert "Short" in draft.html

    assert draft.undo() is True
    assert draft.html == BASE_HTML
    assert draft.undo() is False


def test_draft_diff_reports_changed_lines_only():
    draft = SlideDraft(BASE_HTML)
    node = draft.resolve(selector="h1")

    draft.begin_mutation()
    node.string = "Short"
    draft.commit_mutation()

    diff = draft.diff()
    changed = [line for line in diff["diff"].split("\n") if line[:1] in {"+", "-"}]

    assert diff["changed"] is True
    # 只有 <h1> 那一行进出，未改动的列表项仅作为上下文出现。
    assert [line[:4] for line in changed] == ["--- ", "+++ ", "-<h1", "+<h1"]
    assert "Long Original Title" in changed[2]
    assert "Short" in changed[3]


def test_draft_invalid_selector_raises_structured_error():
    draft = SlideDraft(BASE_HTML)

    with pytest.raises(DraftRefError) as exc:
        draft.find(selector="h1[")
    assert "invalid selector" in str(exc.value)


# ---------------------------------------------------------------------------
# 工具集
# ---------------------------------------------------------------------------


def _request(**overrides):
    data = {
        "projectId": "p1",
        "slideIndex": 1,
        "userRequest": "Make the title shorter",
        "slideTitle": "Original",
        "slideContent": BASE_HTML,
        "projectInfo": {"title": "Project", "topic": "Topic", "scenario": "Pitch"},
        "slideOutline": {"title": "Original", "content_points": ["Alpha"]},
    }
    data.update(overrides)
    return SlideEditAgentRequest(**data)


def _toolbox(**overrides):
    context = SlideEditAgentContext.from_request(_request(**overrides))
    draft = SlideDraft(context.base_html)
    return SlideEditToolbox(context, draft), draft


def test_tool_schemas_cover_every_handler_and_stay_in_sync():
    toolbox, _ = _toolbox()
    native = {item["function"]["name"] for item in SlideEditToolbox.native_schemas()}
    text = {item["name"] for item in SlideEditToolbox.text_reference()}

    assert native == set(SlideEditToolbox.tool_names())
    assert text == native


def test_layout_tool_and_validation_work_on_scripted_slide():
    toolbox, draft = _toolbox(slideContent=SCRIPTED_HTML)
    edited = toolbox.execute("set_style", {"selector": "h1", "styles": {"height": "120px"}})
    assert edited.ok
    assert toolbox.execute("validate_draft", {}).ok
    assert draft.html.count("<script") == 2


@pytest.mark.parametrize("tool,args", [
    ("set_text", {"selector": "script", "text": "bad()"}),
    ("set_attributes", {"selector": "script", "attributes": {"src": "/evil.js"}}),
    ("insert_html", {"selector": "body", "position": "append", "html": "<script>bad()</script>"}),
    ("replace_slide", {"html": SCRIPTED_HTML.replace('/static/chart.js', '/evil.js')}),
])
def test_tools_reject_script_mutations_and_leave_draft_unchanged(tool, args):
    toolbox, draft = _toolbox(slideContent=SCRIPTED_HTML)
    result = toolbox.execute(tool, args)
    assert not result.ok
    assert draft.html == SCRIPTED_HTML
    assert not draft.changed


def test_replace_slide_can_preserve_existing_scripts():
    toolbox, draft = _toolbox(slideContent=SCRIPTED_HTML)
    result = toolbox.execute("replace_slide", {"html": SCRIPTED_HTML.replace('Title', 'New title')})
    assert result.ok
    assert toolbox.execute("validate_draft", {}).ok
    assert draft.html.count("<script") == 2


def test_read_slide_returns_structure_with_usable_refs():
    toolbox, draft = _toolbox()

    result = toolbox.execute("read_slide", {})

    assert result.ok is True
    refs = [entry["ref"] for entry in result.data["structure"]]
    assert refs
    assert draft.resolve(ref=refs[0]).name == "div"
    assert "html" not in result.data


def test_read_slide_can_include_bounded_html():
    toolbox, _ = _toolbox()

    result = toolbox.execute("read_slide", {"include_html": True, "max_chars": 40})

    assert result.data["html_truncated"] is True
    assert len(result.data["html"]) == 40


def test_set_text_refuses_to_silently_delete_child_elements():
    toolbox, draft = _toolbox()

    result = toolbox.execute("set_text", {"selector": "ul", "text": "oops"})

    assert result.ok is False
    assert "child element" in result.summary
    assert draft.html == BASE_HTML


def test_set_text_replaces_children_when_explicitly_allowed():
    toolbox, draft = _toolbox()

    result = toolbox.execute(
        "set_text", {"selector": "ul", "text": "oops", "replace_children": True}
    )

    assert result.ok is True
    assert "<li>" not in draft.html


def test_set_style_allows_layout_properties_the_old_whitelist_blocked():
    toolbox, draft = _toolbox()

    result = toolbox.execute(
        "set_style",
        {"selector": "ul", "styles": {"gap": "12px", "grid-template-columns": "1fr 1fr"}},
    )

    assert result.ok is True
    assert "gap: 12px" in draft.html
    assert "grid-template-columns: 1fr 1fr" in draft.html


def test_set_style_rejects_unsafe_values_without_mutating_draft():
    toolbox, draft = _toolbox()

    result = toolbox.execute(
        "set_style",
        {"selector": "h1", "styles": {"background": "url(javascript:alert(1))"}},
    )

    assert result.ok is False
    assert draft.html == BASE_HTML


def test_set_style_merge_keeps_existing_declarations():
    toolbox, draft = _toolbox()

    toolbox.execute("set_style", {"selector": "h1", "styles": {"font-size": "40px"}})

    assert "color: #111" in draft.html
    assert "font-size: 40px" in draft.html


def test_set_style_replace_drops_existing_declarations():
    toolbox, draft = _toolbox()

    toolbox.execute(
        "set_style", {"selector": "h1", "styles": {"font-size": "40px"}, "mode": "replace"}
    )

    assert "color" not in draft.html.split("<h1")[1].split(">")[0]
    assert "font-size: 40px" in draft.html


def test_set_attributes_rejects_event_handlers_but_applies_safe_ones():
    toolbox, draft = _toolbox()

    result = toolbox.execute(
        "set_attributes",
        {"selector": "h1", "attributes": {"onclick": "bad()", "data-role": "title"}},
    )

    assert result.ok is True
    assert "onclick" in result.data["rejected"]
    assert 'data-role="title"' in draft.html


def test_set_attributes_removes_attribute_on_empty_value():
    toolbox, draft = _toolbox()

    toolbox.execute("set_attributes", {"selector": "h1", "attributes": {"class": ""}})

    assert 'class="title"' not in draft.html


@pytest.mark.parametrize(
    "position,expected",
    [
        ("append", "<li>Alpha</li><li>Beta</li><li>New</li>"),
        ("prepend", "<li>New</li><li>Alpha</li><li>Beta</li>"),
    ],
)
def test_insert_html_positions(position, expected):
    toolbox, draft = _toolbox()

    result = toolbox.execute(
        "insert_html", {"selector": "ul", "position": position, "html": "<li>New</li>"}
    )

    assert result.ok is True
    assert expected in draft.html


def test_insert_html_rejects_unsafe_fragment_without_mutating_draft():
    toolbox, draft = _toolbox()

    result = toolbox.execute(
        "insert_html",
        {"selector": "ul", "position": "append", "html": "<li onclick='x()'>bad</li>"},
    )

    assert result.ok is False
    assert draft.html == BASE_HTML


def test_replace_element_preserves_quick_ai_id_of_the_target():
    toolbox, draft = _toolbox(
        slideContent='<div><h1 data-quick-ai-id="q7">Old</h1></div>',
        selectedElementId="q7",
    )

    result = toolbox.execute("replace_element", {"html": "<h2>New</h2>"})

    assert result.ok is True
    assert 'data-quick-ai-id="q7"' in draft.html
    assert "<h2" in draft.html


def test_element_mode_tools_default_to_the_selected_element():
    toolbox, draft = _toolbox(
        slideContent='<div><h1 data-quick-ai-id="q7">Old</h1><p>Body</p></div>',
        selectedElementId="q7",
        mode="element",
    )

    result = toolbox.execute("set_text", {"text": "New"})

    assert result.ok is True
    assert "<h1 data-quick-ai-id=\"q7\">New</h1>" in draft.html
    assert "<p>Body</p>" in draft.html


def test_missing_target_fails_without_mutating_draft():
    toolbox, draft = _toolbox()

    result = toolbox.execute("set_text", {"ref": "e999", "text": "x"})

    assert result.ok is False
    assert "unknown element ref" in result.summary
    assert draft.html == BASE_HTML


def test_replace_slide_rejects_invalid_html_without_mutating_draft():
    toolbox, draft = _toolbox()

    result = toolbox.execute("replace_slide", {"html": "<div><script>x</script></div>"})

    assert result.ok is False
    assert draft.html == BASE_HTML


def test_undo_last_edit_reverts_the_previous_tool_call():
    toolbox, draft = _toolbox()
    toolbox.execute("set_text", {"selector": "h1", "text": "Short"})
    assert "Short" in draft.html

    result = toolbox.execute("undo_last_edit", {})

    assert result.ok is True
    assert draft.html == BASE_HTML


def test_unsupported_tool_reports_available_tools():
    toolbox, _ = _toolbox()

    result = toolbox.execute("teleport", {})

    assert result.ok is False
    assert "read_slide" in result.data["available_tools"]


def test_transcript_records_every_call_with_outcome():
    toolbox, _ = _toolbox()
    toolbox.execute("read_slide", {})
    toolbox.execute("set_text", {"selector": "ul", "text": "oops"})

    assert [entry["tool"] for entry in toolbox.transcript] == ["read_slide", "set_text"]
    assert [entry["ok"] for entry in toolbox.transcript] == [True, False]


# ---------------------------------------------------------------------------
# 协议选择
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message,expected",
    [
        ("400 invalid_request_error: Unsupported parameter: 'tools'", True),
        ("Unknown parameter: tool_choice", True),
        ("this model does not support function calling", True),
        ("429 rate limit exceeded for tools tier", False),
        ("connection reset by peer", False),
        ("tool execution failed", False),
    ],
)
def test_tool_parameter_rejection_detection_is_narrow(message, expected):
    from landppt.services.slide.edit_agent import is_tool_parameter_rejection

    assert is_tool_parameter_rejection(RuntimeError(message)) is expected


def test_protocol_registry_defaults_to_native_and_caches_downgrades():
    registry = ToolProtocolRegistry()
    key = ToolProtocolRegistry.key_for("proxy", "mystery")

    assert registry.preferred(key) is ToolProtocol.NATIVE

    registry.mark_text_only(key, "ignored tool schemas")

    assert registry.preferred(key) is ToolProtocol.TEXT
    assert registry.downgrade_reason(key) == "ignored tool schemas"
    assert registry.preferred(ToolProtocolRegistry.key_for("openai", "gpt")) is ToolProtocol.NATIVE


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------


def test_prompt_inlines_small_slide_html():
    context = SlideEditAgentContext.from_request(_request())
    payload = agent_prompt.build_initial_context(
        context, SlideDraft(context.base_html), max_iterations=12
    )

    assert payload["slide_html"] == BASE_HTML
    assert "slide_structure" not in payload


def test_prompt_swaps_huge_html_for_a_structure_outline():
    big = '<div class="slide">' + "".join(f"<p>Line {i} " + "x" * 80 + "</p>" for i in range(200)) + "</div>"
    context = SlideEditAgentContext.from_request(_request(slideContent=big))

    payload = agent_prompt.build_initial_context(
        context, SlideDraft(context.base_html), max_iterations=12
    )

    assert "slide_html" not in payload
    assert payload["slide_structure"]
    assert "read_slide" in payload["slide_html_note"]


def test_prompt_sanitizes_and_limits_conversation_history():
    history = [{"role": "system", "content": "ignored"}]
    history += [{"role": "user", "content": f"msg {i}"} for i in range(20)]
    context = SlideEditAgentContext.from_request(_request(chatHistory=history))

    cleaned = agent_prompt.conversation_history_context(context.request)

    assert len(cleaned) == agent_prompt.MAX_CONVERSATION_HISTORY_MESSAGES
    assert all(item["role"] in {"user", "assistant"} for item in cleaned)
    assert cleaned[-1]["content"] == "msg 19"


def test_prompt_truncates_overlong_history_messages():
    long_message = "x" * 5000
    context = SlideEditAgentContext.from_request(
        _request(chatHistory=[{"role": "user", "content": long_message}])
    )

    cleaned = agent_prompt.conversation_history_context(context.request)

    assert len(cleaned[0]["content"]) == agent_prompt.MAX_CONVERSATION_HISTORY_MESSAGE_CHARS
    assert cleaned[0]["content"].endswith("...")


def test_prompt_omits_data_urls_from_the_text_payload():
    context = SlideEditAgentContext.from_request(
        _request(slideScreenshot="data:image/png;base64,AAAA", visionEnabled=True)
    )

    payload = agent_prompt.build_initial_context(
        context, SlideDraft(context.base_html), max_iterations=12
    )

    assert payload["vision"]["attachments"][0]["url"] == "[attached data URL omitted from text prompt]"
    assert payload["vision"]["attached_image_count"] == 1


# ---------------------------------------------------------------------------
# 循环
# ---------------------------------------------------------------------------


def _response(content="", tool_calls=None):
    return AIResponse(content=content, model="fake", usage={}, tool_calls=tool_calls or [])


def _native_call(call_id, name, arguments):
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


def _text_action(name, arguments, thought="because"):
    return _response(
        json.dumps({"thought": thought, "action": name, "action_input": arguments})
    )


class _ScriptedPPTService:
    def __init__(self, script, provider="openai", model="m"):
        self.script = list(script)
        self.calls = []
        self._provider = provider
        self._model = model

    async def get_role_provider_async(self, role):
        return None, {"provider": self._provider, "model": self._model}

    async def _chat_completion_for_role(self, role, **kwargs):
        # 适配器会持续复用同一个 messages 列表，这里必须快照，否则断言看到的是终态。
        self.calls.append({"role": role, **kwargs, "messages": list(kwargs["messages"])})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def _run(service, request, handle=None, cancel_on=None):
    events = []

    async def emit(event):
        events.append(event)
        if cancel_on and handle and event["type"] == cancel_on:
            handle.cancel("test")

    result = await SlideEditAgentService().run_agent(request, service, emit, handle=handle)
    return result, events


@pytest.fixture(autouse=True)
def _reset_protocol_registry():
    tool_protocol_registry.reset()
    yield
    tool_protocol_registry.reset()


@pytest.mark.asyncio
async def test_agent_runs_native_tool_calls_and_returns_a_proposal():
    service = _ScriptedPPTService(
        [
            _response("looking", [_native_call("c1", "find_elements", {"selector": "h1"})]),
            _response("", [_native_call("c2", "set_text", {"selector": "h1", "text": "Short"})]),
            _response("Shortened the title."),
        ]
    )

    result, events = await _run(service, _request())

    assert result.status == "completed"
    assert result.summary == "Shortened the title."
    assert "<h1 class=\"title\" style=\"color:#111\">Short</h1>" in result.proposal.html_content
    assert result.proposal.changed is True
    assert result.proposal.validation.valid is True

    assert service.calls[0]["tool_choice"] == "auto"
    assert len(service.calls[0]["tools"]) == len(SlideEditToolbox.tool_names())
    assert [event["type"] for event in events][:4] == [
        "run_started",
        "turn_started",
        "thinking",
        "tool_started",
    ]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert all(event["runId"] == result.run_id for event in events)


@pytest.mark.asyncio
async def test_agent_layout_edit_proposal_preserves_original_scripts():
    service = _ScriptedPPTService([
        _response("", [_native_call("c1", "set_style", {"selector": "h1", "styles": {"height": "120px"}})]),
        _response("", [_native_call("c2", "validate_draft", {})]),
        _response("Adjusted title height."),
    ])
    result, events = await _run(service, _request(slideContent=SCRIPTED_HTML))
    assert result.proposal.validation.valid
    assert result.proposal.html_content.count("<script") == 2
    assert "height: 120px" in result.proposal.html_content
    assert next(e for e in events if e["type"] == "validation")["valid"]


@pytest.mark.asyncio
async def test_invalid_final_draft_does_not_claim_success():
    service = _ScriptedPPTService([_response("Everything fixed successfully.")])
    # 原页面里的 onclick 会作为未改动内容保留，所以用校验器一定拒绝的 CSS javascript: URL 造一个无法修复的草稿。
    unfixable = '<div><style>a{background:url(javascript:x)}</style>Title</div>'
    result, events = await _run(service, _request(slideContent=unfixable))
    assert not result.proposal.validation.valid
    assert "尚不能保存" in result.summary
    assert "Everything fixed successfully" not in events[-1]["summary"]


@pytest.mark.asyncio
async def test_agent_emits_draft_updated_only_for_successful_mutations():
    service = _ScriptedPPTService(
        [
            _response("", [_native_call("c1", "read_slide", {})]),
            _response("", [_native_call("c2", "set_text", {"selector": "ul", "text": "no"})]),
            _response("", [_native_call("c3", "set_text", {"selector": "h1", "text": "Short"})]),
            _response("done"),
        ]
    )

    _, events = await _run(service, _request())

    drafts = [event for event in events if event["type"] == "draft_updated"]
    assert len(drafts) == 1
    assert drafts[0]["revision"] == 1
    assert drafts[0]["changed"] is True
    assert "Short" in drafts[0]["html"]


@pytest.mark.asyncio
async def test_agent_downgrades_when_provider_ignores_native_tool_schemas():
    service = _ScriptedPPTService(
        [
            _text_action("find_elements", {"selector": "h1"}),
            _text_action("set_text", {"selector": "h1", "text": "Short"}),
            _text_action("final", {"summary": "done via text protocol"}),
        ],
        provider="proxy",
        model="mystery",
    )

    result, events = await _run(service, _request())

    types = [event["type"] for event in events]
    assert "protocol_changed" in types
    assert result.status == "completed"
    assert result.summary == "done via text protocol"
    assert "Short" in result.proposal.html_content
    # 后续请求直接从文本协议起步，不再浪费一轮。
    key = ToolProtocolRegistry.key_for("proxy", "mystery")
    assert tool_protocol_registry.preferred(key) is ToolProtocol.TEXT


@pytest.mark.asyncio
async def test_agent_downgrades_when_provider_rejects_the_tools_parameter():
    service = _ScriptedPPTService(
        [
            RuntimeError("400 invalid_request_error: Unsupported parameter: 'tools'"),
            _text_action("set_text", {"selector": "h1", "text": "Short"}),
            _text_action("final", {"summary": "fallback worked"}),
        ],
        provider="weird",
    )

    result, events = await _run(service, _request())

    assert result.status == "completed"
    assert "Short" in result.proposal.html_content
    assert any(event["type"] == "protocol_changed" for event in events)
    assert "tools" not in service.calls[-1]


@pytest.mark.asyncio
async def test_agent_does_not_downgrade_on_unrelated_model_errors():
    service = _ScriptedPPTService([RuntimeError("429 rate limit exceeded for tools tier")])
    events = []

    async def emit(event):
        events.append(event)

    with pytest.raises(RuntimeError, match="rate limit"):
        await SlideEditAgentService().run_agent(_request(), service, emit)

    assert not any(event["type"] == "protocol_changed" for event in events)
    error_events = [event for event in events if event["type"] == "error"]
    assert error_events and error_events[0]["phase"] == "model"


@pytest.mark.asyncio
async def test_agent_retries_once_when_text_protocol_reply_is_unstructured():
    tool_protocol_registry.mark_text_only(
        ToolProtocolRegistry.key_for("proxy", "m"), "test"
    )
    service = _ScriptedPPTService(
        [
            _response("I will just chat instead of returning JSON."),
            _text_action("set_text", {"selector": "h1", "text": "Short"}),
            _text_action("final", {"summary": "recovered"}),
        ],
        provider="proxy",
    )

    result, _ = await _run(service, _request())

    assert result.summary == "recovered"
    assert "Short" in result.proposal.html_content


@pytest.mark.asyncio
async def test_agent_stops_at_the_next_checkpoint_when_cancelled():
    service = _ScriptedPPTService(
        [
            _response("", [_native_call("c1", "set_text", {"selector": "h1", "text": "Half"})]),
            _response("should never run"),
        ]
    )
    handle = agent_run_registry.register("run-cancel-test", 1)

    result, events = await _run(service, _request(), handle=handle, cancel_on="draft_updated")
    agent_run_registry.release("run-cancel-test")

    assert result.status == "cancelled"
    assert len(service.calls) == 1
    # 停止前的改动仍然作为草稿返回，用户可以自行决定保留还是撤销。
    assert "Half" in result.proposal.html_content
    assert events[-1]["type"] == "run_finished"
    assert events[-1]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_agent_finishes_with_max_iterations_status():
    service = _ScriptedPPTService(
        [_response("", [_native_call(f"c{i}", "read_slide", {})]) for i in range(5)]
    )

    result, _ = await _run(service, _request(maxIterations=3))

    assert result.status == "max_iterations"
    assert result.iterations_used == 3
    assert len(service.calls) == 3
    assert result.proposal.changed is False


@pytest.mark.asyncio
async def test_agent_reports_unsupported_tool_and_keeps_going():
    service = _ScriptedPPTService(
        [
            _response("", [_native_call("c1", "teleport", {})]),
            _response("recovered"),
        ]
    )

    result, events = await _run(service, _request())

    failed = [
        event for event in events if event["type"] == "tool_finished" and event["ok"] is False
    ]
    assert failed and "unsupported tool" in failed[0]["summary"]
    assert result.status == "completed"


@pytest.mark.asyncio
async def test_agent_emits_error_event_when_a_tool_raises(monkeypatch):
    def boom(self, tool_name, tool_input):
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(SlideEditToolbox, "execute", boom)
    service = _ScriptedPPTService(
        [_response("", [_native_call("c1", "read_slide", {})])]
    )
    events = []

    async def emit(event):
        events.append(event)

    with pytest.raises(RuntimeError, match="tool exploded"):
        await SlideEditAgentService().run_agent(_request(), service, emit)

    error_events = [event for event in events if event["type"] == "error"]
    assert error_events == [
        {
            "type": "error",
            "runId": error_events[0]["runId"],
            "seq": error_events[0]["seq"],
            "phase": "tool",
            "message": "tool exploded",
            "errorType": "RuntimeError",
            "iteration": 1,
            "tool": "read_slide",
        }
    ]


@pytest.mark.asyncio
async def test_agent_sends_multimodal_content_in_vision_mode():
    service = _ScriptedPPTService([_response("looked at it")])

    await _run(
        service,
        _request(
            visionEnabled=True,
            slideScreenshot="data:image/png;base64,AAAA",
            images=[{"url": "https://example.com/ref.png", "name": "ref"}],
        ),
    )

    assert service.calls[0]["role"] == "vision_analysis"
    user_message = service.calls[0]["messages"][1]
    assert user_message.role is MessageRole.USER
    assert isinstance(user_message.content[0], TextContent)
    image_urls = [
        part.image_url["url"] for part in user_message.content if isinstance(part, ImageContent)
    ]
    assert image_urls == ["data:image/png;base64,AAAA", "https://example.com/ref.png"]


@pytest.mark.asyncio
async def test_agent_uses_editor_role_without_vision_inputs():
    service = _ScriptedPPTService([_response("done")])

    await _run(service, _request(visionEnabled=True))

    assert service.calls[0]["role"] == "editor"


@pytest.mark.asyncio
async def test_tool_results_are_fed_back_as_tool_role_messages():
    service = _ScriptedPPTService(
        [
            _response("", [_native_call("c1", "read_slide", {})]),
            _response("done"),
        ]
    )

    await _run(service, _request())

    roles = [message.role for message in service.calls[-1]["messages"]]
    assert roles == [
        MessageRole.SYSTEM,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    tool_message = service.calls[-1]["messages"][-1]
    assert tool_message.tool_call_id == "c1"
    assert json.loads(tool_message.content)["tool"] == "read_slide"
