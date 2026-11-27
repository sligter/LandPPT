"""Actual create/research bundles, with isolated requests and no AI calls."""

import json
import re
from email import policy
from email.parser import BytesParser
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, ui_page  # noqa: F401

SIZES = [(1440, 900), (1024, 768), (390, 844), (320, 568), (844, 390)]
SCENARIOS = [dict(id="general", name="通用"), dict(id="technology", name="科技技术")]
PACKAGES = [
    dict(
        id=41,
        template_name="研究报告",
        status="published",
        version=2,
        manifest=dict(components=[{}]),
    ),
    dict(
        id=42,
        template_name="内部草稿",
        status="draft",
        version=3,
        manifest=dict(components=[]),
    ),
    dict(
        id=43,
        template_name="历史版本",
        status="retired",
        version=1,
        manifest=dict(components=[]),
    ),
]
STATUS = dict(
    available=True,
    tavily_configured=True,
    status=dict(ai_provider_type="landppt", max_results=12, search_depth="advanced"),
)
REPORTS = [
    dict(filename=f"研究报告 {index}.md", size=2048, created="2026-10-11T10:20:30")
    for index in range(25)
]
RESULT = dict(
    success=True,
    report_path="reports/研究报告.md",
    report=dict(
        topic="教育研究",
        total_duration=12.3,
        sources_count=0,
        steps_count=4,
        executive_summary="主要结论\n保留原有换行。",
        key_findings=["发现一"],
        recommendations=["建议一"],
    ),
)


def select(page, name, choice):
    page.get_by_role("combobox", name=name, exact=True).click()
    page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(
        has_text=re.compile("^" + re.escape(choice) + "$")
    ).click()


def multipart(req):
    message = BytesParser(policy=policy.default).parsebytes(
        (
            "Content-Type: "
            + req.headers["content-type"]
            + "\r\nMIME-Version: 1.0\r\n\r\n"
        ).encode()
        + req.post_data_buffer
    )
    fields, files = {}, []
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if part.get_filename():
            files.append((name, part.get_filename(), part.get_payload(decode=True)))
        else:
            fields[name] = part.get_payload(decode=True).decode("utf-8")
    return fields, files


def api(page):
    state = dict(
        reads=[],
        writes=[],
        packages=[dict(item) for item in PACKAGES],
        reports=[dict(item) for item in REPORTS],
        status=dict(STATUS),
        result=dict(RESULT),
    )

    def handle(route):
        req = route.request
        path = urlsplit(req.url).path
        if req.method == "GET":
            state["reads"].append(req.url)
        else:
            body = (
                multipart(req) if path.endswith("create-and-confirm") else req.post_data
            )
            state["writes"].append(
                (path, req.method, parse_qs(urlsplit(req.url).query), body)
            )
        if path.endswith("create-and-confirm"):
            route.fulfill(
                status=422, json=dict(status="error", message="保留草稿供重试")
            )
        elif path.endswith("/packages"):
            route.fulfill(json=dict(packages=state["packages"]))
        elif path.endswith("/status"):
            route.fulfill(json=state["status"])
        elif path.endswith("/conduct"):
            route.fulfill(json=state["result"])
        elif req.method == "DELETE":
            filename = unquote(path.rsplit("/", 1)[-1])
            state["reports"] = [
                item for item in state["reports"] if item["filename"] != filename
            ]
            route.fulfill(json=dict(success=True))
        else:
            route.fulfill(
                json=dict(
                    success=True,
                    reports=state["reports"],
                    total_count=len(state["reports"]),
                    reports_directory="reports/deep_research",
                )
            )

    page.route("**/projects/create-and-confirm", handle)
    page.route("**/api/global-master-templates/packages", handle)
    page.route("**/api/research/**", handle)
    return state


def creation(page, load, **kwargs):
    load(
        "pages/project/scenarios.html",
        path="/create",
        scenarios=SCENARIOS,
        selected_scenario="technology",
        template_options=[
            dict(id=3, name="商务简约", is_default=True),
            dict(id=9, name="科技风", is_default=False),
        ],
        **kwargs,
    )
    page.get_by_role("heading", name="创建 PPT", exact=True).wait_for()


def research(page, load):
    load("pages/project/research_status.html", path="/research")
    page.get_by_role("heading", name="深度研究", exact=True).wait_for()
    expect(page.get_by_text("服务可用", exact=True)).to_be_visible()


def tab(page, name):
    page.get_by_role("tab", name=re.compile(re.escape(name) + r"$")).click()


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize(
    "scene",
    ["create", "package", "files", "urls", "advanced", "research", "result", "delete"],
)
def test_responsive_creation_research_geometry(ui_page, width, height, scene):
    page, load = ui_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size(dict(width=width, height=height))
    state = api(page)
    if scene in {"research", "result", "delete"}:
        research(page, load)
        if scene == "result":
            page.get_by_role("textbox", name="研究主题").fill("教育研究")
            page.get_by_role("button", name="开始研究", exact=True).click()
            expect(
                page.get_by_text("主要结论\n保留原有换行。", exact=True)
            ).to_be_visible()
        if scene == "delete":
            page.get_by_role("button", name="删除报告 研究报告 0.md").filter(
                visible=True
            ).click()
            bounds = page.locator(".ant-modal-container").bounding_box()
            assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height + 1
            confirm = page.get_by_role("button", name="确认", exact=True).bounding_box()
            assert confirm["y"] >= 0 and confirm["y"] + confirm["height"] <= height + 1
    else:
        creation(page, load)
        if scene == "package":
            select(page, "生成方式", "快速模式（模板包）")
            select(page, "已发布模板包", "研究报告 · v2")
        elif scene == "files":
            tab(page, "文件资料")
            page.locator('input[type="file"]').set_input_files(
                dict(name="研究资料.txt", mimeType="text/plain", buffer=b"source")
            )
        elif scene == "urls":
            tab(page, "网页链接")
            page.get_by_role("textbox", name="内容链接").fill(
                "https://example.invalid/research"
            )
        elif scene == "advanced":
            select(page, "目标受众", "自定义")
            select(page, "PPT 风格", "自定义风格")
            page.get_by_role("checkbox", name="无人值守", exact=True).check()
        page.evaluate("window.scrollTo(0, 0)")
        bounds = page.get_by_role("button", name="开始生成", exact=True).bounding_box()
        assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height + 1
        if width <= 600:
            assert bounds["height"] >= 44
            assert (
                page.get_by_role("textbox", name="PPT 主题").evaluate(
                    "el => getComputedStyle(el).fontSize"
                )
                == "16px"
            )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert not errors
    assert len(state["writes"]) == (1 if scene == "result" else 0)


def test_default_payload_and_failed_creation_preserve_draft(ui_page):
    page, load = ui_page
    state = api(page)
    creation(page, load)
    page.get_by_role("textbox", name="PPT 主题").fill("  测试主题  ")
    page.get_by_role("textbox", name="具体需求").fill("  自定义需求  ")
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("保留草稿供重试")).to_be_visible()
    fields, files = state["writes"][0][3]
    assert fields == dict(
        scenario="technology",
        topic="测试主题",
        requirements="自定义需求",
        language="zh",
        render_mode="html",
        generation_mode="freeform",
        package_version_id="0",
        network_mode="false",
        audience_type="普通大众",
        custom_audience="",
        page_count_mode="ai_decide",
        min_pages="8",
        max_pages="15",
        include_transition_pages="false",
        include_page_numbers="true",
        ppt_style="general",
        custom_style_prompt="",
        content_mode="presentation",
        content_source="manual",
        file_processing_mode="markitdown",
        content_analysis_depth="fast",
        unattended_mode="false",
        stop_at_stage="ppt",
        unattended_template_mode="auto",
        unattended_template_id="",
        unattended_notify_in_app="true",
        unattended_notify_email="false",
    )
    assert not files
    expect(page.get_by_role("textbox", name="PPT 主题")).to_have_value("  测试主题  ")
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_role("button", name="开始生成", exact=True)).to_be_enabled()
    assert len(state["writes"]) == 2


@pytest.mark.parametrize(
    "topic,audience,style",
    [("", False, False), ("主题", True, False), ("主题", False, True)],
)
def test_required_creation_fields_focus_and_block_submission(
    ui_page, topic, audience, style
):
    page, load = ui_page
    state = api(page)
    creation(page, load)
    page.get_by_role("textbox", name="PPT 主题").fill(topic)
    name, error = "PPT 主题", "请先填写 PPT 主题"
    if audience:
        select(page, "目标受众", "自定义")
        name, error = "自定义受众描述", "请描述自定义受众"
    if style:
        select(page, "PPT 风格", "自定义风格")
        name, error = "自定义风格描述", "请填写自定义风格描述"
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text(error, exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name=name, exact=True)).to_be_focused()
    assert not state["writes"]


def test_package_published_only_svg_and_refresh_failure_block_creation(ui_page):
    page, load = ui_page
    state = api(page)
    creation(page, load)
    select(page, "生成方式", "快速模式（模板包）")
    expect(page.get_by_role("combobox", name="页面绘制方式")).to_be_disabled()
    expect(page.get_by_text("SVG（实验）", exact=True)).to_be_visible()
    page.get_by_role("combobox", name="已发布模板包").click()
    expect(
        page.locator(".ant-select-dropdown:visible .ant-select-item-option-content")
    ).to_have_text(["研究报告 · v2"])
    page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").click()
    page.get_by_role("textbox", name="PPT 主题").fill("包测试")
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("保留草稿供重试")).to_be_visible()
    fields = state["writes"][0][3][0]
    assert (
        fields["generation_mode"] == "package"
        and fields["render_mode"] == "svg"
        and fields["package_version_id"] == "41"
    )

    def fail(route):
        route.fulfill(status=503, json=dict(detail="包列表暂不可用"))

    page.route("**/api/global-master-templates/packages", fail)
    page.get_by_role("button", name="刷新模板包").click()
    expect(page.get_by_text("包列表暂不可用")).to_be_visible()
    expect(page.get_by_role("button", name="开始生成", exact=True)).to_be_disabled()
    page.unroute("**/api/global-master-templates/packages", fail)
    state["packages"] = []
    page.get_by_role("button", name="刷新模板包").click()
    expect(page.get_by_text("暂无已发布模板包")).to_be_visible()
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("快速模式需要先选择一个已发布的模板包。")).to_be_visible()
    assert len(state["writes"]) == 1


def test_material_sources_file_dedup_remove_and_url_limit(ui_page):
    page, load = ui_page
    state = api(page)
    creation(page, load)
    page.get_by_role("textbox", name="PPT 主题").fill("来源测试")
    tab(page, "文件资料")
    file = dict(name="source.txt", mimeType="text/plain", buffer=b"source-text")
    page.locator('input[type="file"]').set_input_files(
        [
            file,
            file,
            dict(
                name="unsafe.exe", mimeType="application/octet-stream", buffer=b"skip"
            ),
        ]
    )
    expect(page.get_by_text("不支持的文件类型：unsafe.exe")).to_be_visible()
    expect(page.locator(".create-file")).to_have_count(1)
    select(page, "PDF 处理方式", "高质量 · Mineru（提取图片）")
    select(page, "解析深度", "深度解析")
    tab(page, "网页链接")
    links = [f"https://example.invalid/article/{i}" for i in range(51)]
    page.get_by_role("textbox", name="内容链接").fill(",\n".join(links))
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("保留草稿供重试")).to_be_visible()
    fields, uploads = state["writes"][0][3]
    assert fields["content_source"] == "mixed" and fields["content_urls"].splitlines() == links[:50]
    assert uploads == [("file_upload", "source.txt", b"source-text")]
    assert (
        fields["file_processing_mode"] == "magic_pdf"
        and fields["content_analysis_depth"] == "deep"
    )
    page.get_by_role("button", name="移除附件 source.txt").click()
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_role("button", name="开始生成", exact=True)).to_be_enabled()
    fields, uploads = state["writes"][1][3]
    assert (
        fields["content_source"] == "url"
        and fields["content_urls"].splitlines() == links[:50]
        and not uploads
    )


def test_custom_guidance_page_range_and_admin_unattended_saved_defaults(ui_page):
    page, load = ui_page
    state = api(page)
    creation(
        page,
        load,
        unattended_defaults=dict(
            stop_after="video",
            notify_in_app=False,
            notify_email=True,
            private_key="must-not-leak",
        ),
    )
    assert "must-not-leak" not in page.locator("#antdData").text_content()
    page.get_by_role("textbox", name="PPT 主题").fill("定制主题")
    select(page, "目标受众", "自定义")
    page.get_by_role("textbox", name="自定义受众描述").fill("  产品经理  ")
    select(page, "PPT 风格", "自定义风格")
    page.get_by_role("textbox", name="自定义风格描述").fill("  黑白极简  ")
    select(page, "页数", "自定义范围")
    page.get_by_role("spinbutton", name="最少页数").fill("20")
    page.get_by_role("spinbutton", name="最多页数").fill("10")
    select(page, "语言", "English")
    select(page, "页面绘制方式", "SVG（实验）")
    page.get_by_role("checkbox", name="联网深度研究").check()
    page.get_by_role("checkbox", name="章节过渡页").check()
    page.get_by_role("checkbox", name="页码 / Footer").uncheck()
    # Unattended options only appear once the mode is switched on in the settings tray.
    page.get_by_role("checkbox", name="无人值守", exact=True).check()
    expect(page.get_by_text("导出讲解视频", exact=True)).to_be_visible()
    expect(page.get_by_role("checkbox", name="系统通知")).not_to_be_checked()
    expect(page.get_by_role("checkbox", name="邮件通知")).to_be_checked()
    select(page, "无人值守模板", "指定已有模板")
    select(page, "选择模板", "科技风")
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("保留草稿供重试")).to_be_visible()
    fields = state["writes"][0][3][0]
    for key, value in dict(
        custom_audience="产品经理",
        custom_style_prompt="黑白极简",
        min_pages="10",
        max_pages="20",
        language="en",
        render_mode="svg",
        network_mode="true",
        include_transition_pages="true",
        include_page_numbers="false",
        unattended_mode="true",
        stop_at_stage="video",
        unattended_template_mode="global",
        unattended_template_id="9",
        unattended_notify_in_app="false",
        unattended_notify_email="true",
    ).items():
        assert fields[key] == value


@pytest.mark.parametrize(
    "stage", ["outline", "template", "ppt", "speech_script", "narration_audio", "video"]
)
def test_every_unattended_stop_stage_reaches_existing_payload(ui_page, stage):
    page, load = ui_page
    state = api(page)
    creation(
        page,
        load,
        unattended_defaults=dict(
            stop_after=stage, notify_in_app=True, notify_email=False
        ),
    )
    page.get_by_role("textbox", name="PPT 主题").fill("无人值守")
    page.get_by_role("checkbox", name="无人值守", exact=True).check()
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("保留草稿供重试")).to_be_visible()
    assert state["writes"][0][3][0]["stop_at_stage"] == stage


def test_non_admin_has_no_unattended_controls_and_safe_payload(ui_page):
    page, load = ui_page
    state = api(page)
    user = dict(id=2, username="member", is_admin=False)
    creation(page, load, user=user)
    expect(page.get_by_text("无人值守", exact=True)).to_have_count(0)
    page.get_by_role("textbox", name="PPT 主题").fill("普通用户")
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("保留草稿供重试")).to_be_visible()
    assert state["writes"][0][3][0]["unattended_mode"] == "false"


def defer(page, path):
    page.evaluate(
        """path => {
      const original = window.fetch;
      window.pendingCalls = 0;
      window.fetch = (...args) => new URL(args[0], location.origin).pathname === path ?
        new Promise(resolve => { window.pendingCalls++; window.completeRequest = result => resolve(new Response(JSON.stringify(result), {status: 200, headers: {'Content-Type': 'application/json'}})); }) : original(...args);
    }""",
        path,
    )


def test_create_shortcut_pending_lock_success_redirect_and_partial_failure_link(
    ui_page,
):
    page, load = ui_page
    api(page)
    creation(page, load)
    page.get_by_role("textbox", name="PPT 主题").fill("快捷键")
    defer(page, "/projects/create-and-confirm")
    page.get_by_role("textbox", name="PPT 主题").press("Control+Enter")
    expect(page.get_by_role("button", name="开始生成", exact=True)).to_be_disabled()
    page.keyboard.press("Control+Enter")
    assert page.evaluate("window.pendingCalls") == 1
    page.evaluate(
        "window.completeRequest({status:'error',message:'大纲确认失败',redirect_url:'/projects/created/todo'})"
    )
    expect(page.get_by_role("link", name="前往看板")).to_have_attribute(
        "href", "/projects/created/todo"
    )
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_role("button", name="开始生成", exact=True)).to_be_disabled()
    page.evaluate(
        "window.completeRequest({status:'success',redirect_url:'/projects/created/todo?from=create'})"
    )
    expect(page).to_have_url(re.compile(r"/projects/created/todo\?from=create$"))


def test_research_query_contract_pending_feedback_and_safe_result(ui_page):
    page, load = ui_page
    state = api(page)
    research(page, load)
    page.get_by_role("textbox", name="研究主题").fill("  教育 + 研究 & 趋势  ")
    page.get_by_role("button", name="开始研究", exact=True).click()
    expect(page.get_by_text("主要结论\n保留原有换行。", exact=True)).to_be_visible()
    path, method, query, body = state["writes"][0]
    assert (path, method, query, body) == (
        "/api/research/conduct",
        "POST",
        dict(topic=["教育 + 研究 & 趋势"], language=["zh"]),
        None,
    )
    assert (
        len([url for url in state["reads"] if urlsplit(url).path.endswith("/reports")])
        == 2
    )
    defer(page, "/api/research/conduct")
    page.get_by_role("button", name="开始研究", exact=True).click()
    expect(page.get_by_text(re.compile("研究进行中，已等待"))).to_be_visible()
    expect(page.get_by_role("textbox", name="研究主题")).to_be_disabled()
    assert page.evaluate("window.pendingCalls") == 1
    page.evaluate("window.completeRequest({success:false,message:'研究请求失败'})")
    expect(page.get_by_text("研究请求失败", exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name="研究主题")).to_have_value(
        "  教育 + 研究 & 趋势  "
    )
    expect(page.get_by_text("主要结论\n保留原有换行。", exact=True)).to_be_visible()
    state["result"]["report"][
        "executive_summary"
    ] = '<img src=x onerror="window.injected=true">'
    page.evaluate("window.completeRequest = undefined; location.reload()")
    page.get_by_role("textbox", name="研究主题").fill("注入测试")
    page.get_by_role("button", name="开始研究", exact=True).click()
    expect(
        page.get_by_text('<img src=x onerror="window.injected=true">', exact=True)
    ).to_be_visible()
    assert not page.evaluate("!!window.injected")


def test_research_unavailable_failed_status_retry_and_empty_reports(ui_page):
    page, load = ui_page
    state = api(page)
    state["status"] = dict(
        available=False, tavily_configured=False, message="配置未完成"
    )
    state["reports"] = []
    load("pages/project/research_status.html", path="/research")
    expect(page.get_by_text("配置未完成", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="开始研究", exact=True)).to_be_disabled()
    expect(
        page.get_by_text("暂无保存的研究报告", exact=True).filter(visible=True)
    ).to_be_visible()

    def fail(route):
        route.fulfill(status=503, json=dict(detail="服务读取失败"))

    page.route("**/api/research/status", fail)
    page.get_by_role("button", name="刷新状态").click()
    expect(page.get_by_text("服务读取失败", exact=True)).to_be_visible()
    page.unroute("**/api/research/status", fail)
    state["status"] = dict(STATUS)
    page.get_by_role("button", name="重试", exact=True).click()
    expect(page.get_by_role("button", name="开始研究", exact=True)).to_be_enabled()
    assert not state["writes"]


def test_keenable_status_and_search_error(ui_page):
    page, load = ui_page
    state = api(page)
    state["status"] = dict(
        available=True,
        research_provider="keenable",
        keenable_configured=False,
        status=dict(research_provider="keenable", max_results=7),
    )
    research(page, load)
    expect(page.get_by_text("Keenable 公开搜索", exact=True)).to_be_visible()
    expect(page.get_by_text("Tavily 未配置", exact=True)).to_have_count(0)

    state["status"]["keenable_configured"] = True
    page.get_by_role("button", name="刷新状态").click()
    expect(page.get_by_text("Keenable 已配置", exact=True)).to_be_visible()

    message = "Keenable 搜索失败，请检查 API Key 或稍后重试。"
    page.route(
        "**/api/research/conduct?**",
        lambda route: route.fulfill(status=502, json={"detail": message}),
    )
    page.get_by_role("textbox", name="研究主题").fill("测试检索失败")
    page.get_by_role("button", name="开始研究", exact=True).click()
    expect(page.get_by_text(message, exact=True)).to_be_visible()
    expect(page.get_by_text("研究结果", exact=True)).to_have_count(0)


def test_report_pagination_refresh_failure_keep_rows_delete_retry_and_focus(ui_page):
    page, load = ui_page
    state = api(page)
    research(page, load)
    page.get_by_title("3", exact=True).click()
    expect(
        page.get_by_text("研究报告 20.md", exact=True).filter(visible=True)
    ).to_be_visible()

    def fail_read(route):
        route.fulfill(status=503, json=dict(detail="报告读取失败"))

    page.route("**/api/research/reports", fail_read)
    page.get_by_role("button", name="刷新报告").click()
    expect(page.get_by_text("报告读取失败", exact=True)).to_be_visible()
    expect(
        page.get_by_text("研究报告 20.md", exact=True).filter(visible=True)
    ).to_be_visible()
    page.unroute("**/api/research/reports", fail_read)
    page.get_by_role("button", name="重试", exact=True).click()
    expect(page.get_by_role("button", name="刷新报告")).to_be_enabled()
    trigger = page.get_by_role("button", name="删除报告 研究报告 20.md").filter(
        visible=True
    )

    def fail_delete(route):
        route.fulfill(status=500, json=dict(detail="删除失败可重试"))

    page.route("**/api/research/reports/*", fail_delete)
    trigger.click()
    page.get_by_role("button", name="确认", exact=True).click()
    expect(page.get_by_text("删除失败可重试", exact=True).first).to_be_visible()
    expect(page.get_by_role("dialog")).to_be_visible()
    page.unroute("**/api/research/reports/*", fail_delete)
    page.get_by_role("button", name="取消", exact=True).click()
    expect(trigger).to_be_focused()
    trigger.click()
    page.get_by_role("button", name="确认", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(
        page.get_by_text("研究报告 20.md", exact=True).filter(visible=True)
    ).to_have_count(0)
    assert (
        state["writes"][0][0]
        == "/api/research/reports/%E7%A0%94%E7%A9%B6%E6%8A%A5%E5%91%8A%2020.md"
    )


def test_package_mode_switch_ignores_a_late_catalogue_response(ui_page):
    page, load = ui_page
    api(page)
    creation(page, load)
    page.evaluate(
        """() => {
      const original = fetch; window.packageRequests = [];
      window.fetch = (...args) => new URL(args[0], location.origin).pathname.endsWith('/global-master-templates/packages') ? new Promise(resolve => window.packageRequests.push(resolve)) : original(...args);
    }"""
    )
    select(page, "生成方式", "快速模式（模板包）")
    expect(page.get_by_role("combobox", name="已发布模板包")).to_be_disabled()
    select(page, "生成方式", "自由设计")
    select(page, "生成方式", "快速模式（模板包）")
    page.wait_for_function("window.packageRequests.length === 2")
    page.evaluate(
        "items => window.packageRequests[1](new Response(JSON.stringify({packages:items})))",
        PACKAGES,
    )
    select(page, "已发布模板包", "研究报告 · v2")
    page.evaluate(
        "window.packageRequests[0](new Response(JSON.stringify({packages:[]})))"
    )
    selected_package = page.locator(".ant-select").filter(
        has=page.get_by_role("combobox", name="已发布模板包", exact=True)
    )
    expect(selected_package).to_be_visible()
    expect(selected_package).to_contain_text("研究报告 · v2")
    expect(page.get_by_text("暂无已发布模板包", exact=True)).to_have_count(0)


@pytest.mark.parametrize("endpoint", ["status", "reports"])
def test_invalid_research_response_has_retry(ui_page, endpoint):
    page, load = ui_page
    state = api(page)

    def invalid(route):
        route.fulfill(json={})

    page.route("**/api/research/" + endpoint, invalid)
    load("pages/project/research_status.html", path="/research")
    expect(page.get_by_text("服务返回的数据无效，请重试", exact=True)).to_be_visible()
    page.unroute("**/api/research/" + endpoint, invalid)
    page.get_by_role("button", name="重试", exact=True).click()
    expect(page.get_by_text("服务返回的数据无效，请重试", exact=True)).to_have_count(0)
    assert not state["writes"]


@pytest.mark.parametrize("width,height", SIZES)
def test_footer_links_stay_on_home_and_off_the_creation_page(ui_page, width, height):
    page, load = ui_page
    api(page)
    page.set_viewport_size(dict(width=width, height=height))
    creation(page, load)
    # The page footer is reserved for the product home; app pages use the sidebar.
    expect(page.locator(".app-footer")).to_have_count(0)
    load("pages/home/index.html", path="/home")
    page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    for name, href in [
        ("GitHub", "https://github.com/sligter/LandPPT"),
        ("商务合作", "mailto:support@landppt.com"),
    ]:
        link = page.get_by_role("link", name=name, exact=True)
        expect(link).to_be_visible()
        expect(link).to_have_attribute("href", href)
        assert link.inner_text() == ""
        assert link.locator("svg").count() == 1
        assert link.bounding_box()["height"] >= (44 if width <= 600 else 32)
        assert link.evaluate(
            "el => { const r = el.getBoundingClientRect(); return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest('a') === el; }"
        )
        link.focus()
        expect(page.get_by_role("tooltip")).to_have_text(name)


@pytest.mark.parametrize("width,height", [(1920, 1080), *SIZES])
def test_creation_width_matches_dashboard_workspace(ui_page, width, height):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=height))
    state = api(page)
    load("pages/project/project_dashboard.html", path="/dashboard")
    page.get_by_role("heading", name="首页", exact=True).wait_for()
    dashboard = page.locator(".page-heading").bounding_box()
    load("pages/project/scenarios.html", path="/scenarios", scenarios=SCENARIOS)
    page.get_by_role("heading", name="创建 PPT", exact=True).wait_for()
    creation_bounds = page.locator(
        ".create-project-page > .page-heading"
    ).bounding_box()
    assert abs(creation_bounds["x"] - dashboard["x"]) <= 1
    assert abs(creation_bounds["width"] - dashboard["width"]) <= 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert not state["writes"]


def readable_select(element):
    """Measure rendered contrast, including the open select's inherited opacity."""
    return element.evaluate(
        """e => {
      const rgb = value => value.match(/[\\d.]+/g).slice(0, 3).map(Number);
      const luminance = values => values.map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((s, v, i) => s + v * [.2126, .7152, .0722][i], 0);
      let background = [255, 255, 255], opacity = 1;
      for (let node = e; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        opacity *= Number(style.opacity);
        if (style.backgroundColor !== 'rgba(0, 0, 0, 0)') { background = rgb(style.backgroundColor); break; }
      }
      const foreground = rgb(getComputedStyle(e).color).map((v, i) => v * opacity + background[i] * (1 - opacity));
      const values = [luminance(foreground), luminance(background)].sort((a, b) => a - b);
      return (values[1] + .05) / (values[0] + .05);
    }"""
    )


@pytest.mark.parametrize("width", [1440, 320])
@pytest.mark.parametrize(
    "name,current,choice,key,steps",
    [
        ("生成方式", "自由设计", "快速模式（模板包）", "ArrowUp", 1),
        ("场景", "科技技术", "通用", "ArrowDown", 1),
        ("目标受众", "普通大众", "自定义", "ArrowUp", 1),
        ("页数", "AI 智能决定", "自定义范围", "ArrowUp", 1),
        ("PPT 风格", "通用场景", "技术图解视频", "ArrowUp", 2),
        ("PPT 风格", "通用场景", "自定义风格", "ArrowUp", 3),
        ("语言", "中文", "English", "ArrowUp", 1),
        ("页面绘制方式", "HTML（默认）", "SVG（实验）", "ArrowUp", 1),
    ],
)
def test_creation_selects_remain_readable_and_support_mouse_and_keyboard(
    ui_page, width, name, current, choice, key, steps
):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=900))
    state = api(page)
    creation(page, load)
    combo = page.get_by_role("combobox", name=name, exact=True)
    content = combo.locator("..")
    expect(content).to_have_attribute("title", current)
    combo.click()
    expect(combo).to_have_attribute("aria-expanded", "true")
    assert readable_select(content) >= 4.5
    selected = page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option-selected"
    )
    assert readable_select(selected) >= 4.5
    selected.hover()
    assert readable_select(selected) >= 4.5
    option = page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option-content"
    ).get_by_text(choice, exact=True)
    option.click()
    expect(content).to_have_attribute("title", choice)
    expect(combo).to_have_attribute("aria-expanded", "false")
    combo.press("ArrowDown")
    active = page.locator(".ant-select-dropdown:visible .ant-select-item-option-active")
    expect(active).to_have_text(choice)
    for _ in range(steps):
        combo.press(key)
    expect(active).to_have_text(current)
    assert readable_select(active) >= 4.5
    combo.press("Enter")
    expect(content).to_have_attribute("title", current)
    expect(combo).to_have_attribute("aria-expanded", "false")
    combo.click()
    combo.press("Escape")
    expect(content).to_have_attribute("title", current)
    expect(combo).to_have_attribute("aria-expanded", "false")
    assert not state["writes"]
