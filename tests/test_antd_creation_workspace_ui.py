"""Shared creation session, navigation and title covers; isolated HTTP/AI calls."""

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, ui_page  # noqa: F401
from test_antd_creation_research_ui import api, select
from test_antd_navigation_ui import navigation_app, open_navigation


def workspace(page, path="/dashboard"):
    state = navigation_app(page)
    state["values"]["selected_scenario"] = "technology"
    calls = api(page)
    page.goto("http://ui.test" + path, wait_until="networkidle")
    expect(page.get_by_role("textbox", name="PPT 主题", exact=True)).to_be_visible()
    return state, calls


@pytest.mark.parametrize("width", [1440, 390, 320])
def test_four_primary_destinations_keep_creation_and_settings_accessible(
    ui_page, width
):
    page, _ = ui_page
    page.set_viewport_size(dict(width=width, height=900))
    state, calls = workspace(page)
    if width < 901:
        page.get_by_role("button", name="菜单", exact=True).click()
    nav = page.get_by_role("navigation", name="主导航", exact=True)
    assert nav.get_by_role("link").all_text_contents() == [
        "首页",
        "项目",
        "模板",
        "素材",
    ]
    assert (
        page.get_by_role("link", name="系统配置", exact=True)
        .filter(visible=True)
        .count()
        == 1
    )
    expect(page.locator('.app-header a[href="/create"]')).to_have_count(0)
    expect(page.locator(".dashboard-header a[href='/scenarios']")).to_have_count(0)
    if width < 901:
        expect(page.get_by_role("link", name="创建 PPT", exact=True)).to_be_visible()
        page.keyboard.press("Escape")
    advanced = page.get_by_role("button", name="高级参数", exact=True)
    expect(advanced).to_be_in_viewport()
    expect(page.locator("#creationAdvancedSummary")).to_have_text(
        "中文 · AI 智能页数 · 通用场景"
    )
    assert advanced.bounding_box()["height"] >= (44 if width <= 600 else 32)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    open_navigation(page, "/projects")
    expect(page.locator('.app-header a[href="/create"]')).to_have_count(0)
    open_navigation(page, "/dashboard")
    expect(page.locator('.app-header a[href="/create"]')).to_have_count(0)
    assert not calls["writes"] and not state["errors"]


@pytest.mark.parametrize("path", ["/dashboard", "/create"])
def test_shared_composer_submits_the_same_defaults_and_preserves_failed_input(
    ui_page, path
):
    page, _ = ui_page
    state, calls = workspace(page, path)
    page.get_by_role("textbox", name="PPT 主题", exact=True).fill("  共同主题  ")
    page.get_by_role("textbox", name="具体需求", exact=True).fill("  完整需求  ")
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("保留草稿供重试", exact=True)).to_be_visible()
    fields, files = calls["writes"][0][3]
    assert fields["topic"] == "共同主题"
    assert fields["requirements"] == "完整需求"
    assert fields["scenario"] == "technology"
    assert fields["audience_type"] == "普通大众"
    assert fields["generation_mode"] == "freeform"
    assert fields["render_mode"] == "html"
    assert fields["content_source"] == "manual"
    assert fields["package_version_id"] == "0"
    assert fields["min_pages"] == "8" and fields["max_pages"] == "15"
    assert not files and not state["errors"]
    expect(page.get_by_role("textbox", name="PPT 主题", exact=True)).to_have_value(
        "  共同主题  "
    )


def test_draft_files_and_advanced_values_survive_both_creation_presentations(ui_page):
    page, _ = ui_page
    state, calls = workspace(page)
    page.get_by_role("textbox", name="PPT 主题", exact=True).fill("会话中的创作")
    page.get_by_role("textbox", name="具体需求", exact=True).fill("保留原始需求")
    page.get_by_role("button", name="高级参数", exact=True).click()
    select(page, "目标受众", "自定义")
    page.get_by_role("textbox", name="自定义受众描述", exact=True).fill("产品团队")
    page.locator(".create-advanced-trigger").click()
    page.locator(".composer-toolbar .ant-segmented").get_by_text(
        "文件资料", exact=True
    ).click()
    expect(page.get_by_role("radio", name="文件资料", exact=True)).to_be_checked()
    page.locator("input[type=file]").set_input_files(
        dict(name="notes.txt", mimeType="text/plain", buffer=b"draft file")
    )
    open_navigation(page, "/projects")
    open_navigation(page, "/create")
    expect(page.get_by_role("textbox", name="PPT 主题", exact=True)).to_have_value(
        "会话中的创作"
    )
    expect(
        page.get_by_role("textbox", name="自定义受众描述", exact=True)
    ).to_have_value("产品团队")
    expect(
        page.get_by_role("button", name="移除附件 notes.txt", exact=True)
    ).to_be_visible()
    open_navigation(page, "/dashboard")
    expect(page.get_by_role("textbox", name="具体需求", exact=True)).to_have_value(
        "保留原始需求"
    )
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_text("保留草稿供重试", exact=True)).to_be_visible()
    fields, files = calls["writes"][0][3]
    assert fields["custom_audience"] == "产品团队"
    assert fields["content_source"] == "file"
    assert files == [("file_upload", "notes.txt", b"draft file")]
    assert not state["errors"]


def test_collapsed_required_field_reopens_before_focusing_validation_error(ui_page):
    page, _ = ui_page
    _, calls = workspace(page)
    page.get_by_role("textbox", name="PPT 主题", exact=True).fill("需要受众")
    page.get_by_role("button", name="高级参数", exact=True).click()
    select(page, "目标受众", "自定义")
    select(page, "语言", "English")
    page.locator(".create-advanced-trigger").click()
    expect(page.locator("#creationAdvancedSummary")).to_have_text(
        "English · AI 智能页数 · 通用场景"
    )
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(
        page.get_by_role("textbox", name="自定义受众描述", exact=True)
    ).to_be_focused()
    assert not calls["writes"]


def test_pending_submit_stays_locked_when_switching_to_create(ui_page):
    page, _ = ui_page
    state, _ = workspace(page)
    pending = []
    page.route("**/projects/create-and-confirm", lambda route: pending.append(route))
    page.get_by_role("textbox", name="PPT 主题", exact=True).fill("仅创建一次")
    page.get_by_role("button", name="开始生成", exact=True).click()
    expect(page.get_by_role("button", name="开始生成", exact=True)).to_be_disabled()
    open_navigation(page, "/projects")
    open_navigation(page, "/create")
    expect(page.get_by_role("button", name="开始生成", exact=True)).to_be_disabled()
    page.keyboard.press("Control+Enter")
    assert len(pending) == 1
    pending[0].fulfill(status=500, json={"status": "error", "message": "可以继续重试"})
    expect(page.get_by_text("可以继续重试", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="开始生成", exact=True)).to_be_enabled()
    expect(page.get_by_role("textbox", name="PPT 主题", exact=True)).to_have_value(
        "仅创建一次"
    )
    assert not state["errors"]


def test_ime_composition_does_not_submit_creation(ui_page):
    page, _ = ui_page
    _, calls = workspace(page)
    field = page.get_by_role("textbox", name="PPT 主题", exact=True)
    field.fill("中文输入中")
    field.dispatch_event(
        "keydown", dict(key="Enter", code="Enter", ctrlKey=True, isComposing=True)
    )
    assert not calls["writes"]


def test_dashboard_configuration_rejects_wrong_account_and_can_retry(ui_page):
    page, _ = ui_page
    state = navigation_app(page)
    state["handlers"]["/create"] = lambda route: route.fulfill(
        body='<script id="antdData" type="application/json">{"page":"create-project","user":{"username":"another"}}</script>',
        content_type="text/html",
    )
    page.goto("http://ui.test/dashboard", wait_until="networkidle")
    expect(
        page.get_by_text("创建设置不可用，请刷新页面重试", exact=True)
    ).to_be_visible()
    assert page.get_by_role("button", name="开始生成", exact=True).count() == 0
    del state["handlers"]["/create"]
    page.get_by_role("button", name="重试", exact=True).click()
    expect(page.get_by_role("textbox", name="PPT 主题", exact=True)).to_be_visible()


@pytest.mark.parametrize("role_change", [True, False])
def test_account_or_role_change_discards_in_memory_creation_draft(ui_page, role_change):
    page, _ = ui_page
    state, _ = workspace(page)
    page.get_by_role("textbox", name="PPT 主题", exact=True).fill("不得进入另一个账户")
    state["values"]["user"] = dict(
        username="nav-user" if role_change else "another-user", is_admin=False
    )
    open_navigation(page, "/projects")
    open_navigation(page, "/create")
    expect(page.get_by_role("textbox", name="PPT 主题", exact=True)).to_have_value("")


@pytest.mark.parametrize("width", [1440, 390, 320])
def test_title_covers_and_list_view_keep_actions_and_never_request_images(
    ui_page, width
):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=844))
    requests = []
    page.on("request", lambda req: requests.append(req))
    load("pages/project/projects_list.html")
    expect(page.locator(".project-cover-link:visible")).to_have_count(1)
    page.get_by_role("button", name="列表", exact=True).click()
    expect(page.locator(".project-cover-link:visible")).to_have_count(0)
    expect(
        page.get_by_role("button", name="重命名", exact=True).filter(visible=True)
    ).to_be_visible()
    page.get_by_role("button", name="封面", exact=True).click()
    expect(page.locator(".project-cover-link:visible")).to_have_count(1)
    assert not any(
        req.resource_type == "image" and "/projects/" in req.url for req in requests
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
