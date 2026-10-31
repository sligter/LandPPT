"""Settings layout and draft consistency after field-scoped rendering changes."""

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, ui_page  # noqa: F401
from test_antd_ui import settings

SIZES = [(1920, 1080), (1440, 900), (1024, 768), (390, 844), (320, 568), (844, 390)]


@pytest.mark.parametrize("width,height", SIZES)
def test_settings_width_matches_dashboard(ui_page, width, height):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=height))
    load("pages/project/project_dashboard.html", path="/dashboard")
    page.get_by_role("heading", name="首页", exact=True).wait_for()
    dashboard = page.locator(".page-heading").bounding_box()
    settings(page, load)
    bounds = page.locator(".settings-page > .page-heading").bounding_box()
    assert abs(bounds["x"] - dashboard["x"]) <= 1
    assert abs(bounds["width"] - dashboard["width"]) <= 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")


def choose(page, field, label):
    field.click()
    page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option-content"
    ).get_by_text(label, exact=True).click()


@pytest.mark.parametrize("width", [1440, 320])
def test_settings_repeated_switches_preserve_drafts_dependencies_and_save(
    ui_page, width
):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=900))
    errors, writes = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def capture(route):
        if route.request.method == "POST":
            writes.append((route.request.url, route.request.post_data_json))
        route.fulfill(json=dict(success=True, config={}))

    page.route("**/api/config/**", capture)
    page.route(
        "**/packages/settings",
        lambda route: route.fulfill(
            json=dict(configured=True, enabled=True, model="saved-model")
        ),
    )
    settings(
        page,
        load,
        current_config=dict(enable_image_service=True, enable_ai_generation=True),
    )
    page.get_by_role("tab", name="生成参数", exact=True).click()
    speed = page.locator('[name="custom_tts_api_speed"]')
    speed.fill("1.25")
    temperature = page.locator("#field-temperature")
    temperature.fill("1.2")
    page.get_by_role("tab", name="决策模型配置", exact=True).click()
    model = page.locator("#jev-config #model")
    model.fill("unsaved-model")
    page.get_by_role("tab", name="图片服务", exact=True).click()
    quality = page.locator("#field-ai_image_quality")
    choose(page, quality, "高清质量")
    toggle = page.locator("#field-enable_ai_generation")
    toggle.click()
    expect(quality).to_have_count(0)
    toggle.click()
    expect(quality.locator("..")).to_have_attribute("title", "高清质量")
    for _ in range(4):
        for label in ["AI 提供者", "应用配置", "生成参数", "决策模型配置", "图片服务"]:
            page.get_by_role("tab", name=label, exact=True).click()
    expect(quality.locator("..")).to_have_attribute("title", "高清质量")
    page.get_by_role("tab", name="决策模型配置", exact=True).click()
    expect(model).to_have_value("unsaved-model")
    page.get_by_role("tab", name="生成参数", exact=True).click()
    expect(speed).to_have_value("1.25")
    expect(temperature).to_have_value("1.2")
    page.get_by_role("button", name="保存生成参数", exact=True).click()
    expect(page.get_by_text("配置已保存，已实时生效", exact=True)).to_be_visible()
    assert len(writes) == 1
    assert writes[0][0].endswith("/generation_params")
    assert writes[0][1]["config"]["custom_tts_api_speed"] == "1.25"
    assert writes[0][1]["config"]["temperature"] == "1.2"
    assert not errors


def test_settings_late_loading_does_not_overwrite_edits(ui_page):
    page, load = ui_page
    page.add_init_script(
        """(() => {
      const original = fetch;
      window.fetch = (...args) => new URL(args[0], location.origin).pathname === '/api/config/all'
        ? new Promise(resolve => { window.resolveSettings = resolve; }) : original(...args);
    })();"""
    )
    settings(page, load)
    key = page.locator('[name="openai_api_key"]')
    key.fill("draft-key")
    page.evaluate(
        "() => window.resolveSettings(new Response(JSON.stringify({config:{openai_api_key:'saved-key',openai_enable_reasoning:true,openai_reasoning_effort:'high'}})))"
    )
    expect(key).to_have_value("draft-key")
    reasoning = page.locator("#field-openai_reasoning_effort")
    expect(reasoning).to_be_enabled()
    expect(reasoning.locator("..")).to_have_attribute("title", "high")
    page.locator("#field-openai_enable_reasoning").click()
    expect(reasoning).to_be_disabled()
    page.locator("#field-openai_enable_reasoning").click()
    expect(reasoning).to_be_enabled()
    expect(reasoning.locator("..")).to_have_attribute("title", "high")


@pytest.mark.parametrize("width", [1440, 320])
def test_settings_dropdown_search_and_keyboard_preserve_other_edits(ui_page, width):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=900))
    settings(page, load)
    page.get_by_role("tab", name="生成参数", exact=True).click()
    draft = page.locator('[name="custom_tts_api_speed"]')
    draft.fill("1.5")
    field = page.locator("#field-unattended_tts_provider")
    field.fill("小米")
    options = page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option-content"
    )
    expect(options).to_have_text(["小米 MiMo"])
    field.press("ArrowDown")
    field.press("Enter")
    expect(field.locator("..")).to_have_attribute("title", "小米 MiMo")
    expect(draft).to_have_value("1.5")
    page.get_by_role("tab", name="应用配置", exact=True).click()
    page.get_by_role("tab", name="生成参数", exact=True).click()
    expect(field.locator("..")).to_have_attribute("title", "小米 MiMo")
    field.click()
    field.press("Escape")
    expect(field).to_have_attribute("aria-expanded", "false")
    expect(draft).to_have_value("1.5")


@pytest.mark.parametrize('saved', ['auto', 'tavily'])
def test_research_provider_is_visible_and_saved(ui_page, saved):
    page, load = ui_page
    writes = []
    def api(route):
        if route.request.method == 'POST':
            writes.append(route.request.post_data_json)
        route.fulfill(json={'success': True, 'config': {'research_provider': saved}})
    page.route('**/api/config/**', api)
    settings(page, load, current_config={'research_provider': saved})
    page.get_by_role('tab', name='生成参数', exact=True).click()
    field = page.locator('#field-research_provider')
    expect(field.locator('..')).to_have_attribute('title', 'Tavily' if saved == 'tavily' else '自动（保留已配置的搜索服务）')
    field.click()
    page.locator('.ant-select-dropdown:visible .ant-select-item-option-content').get_by_text('Parallel（免费，无需密钥）', exact=True).click()
    page.get_by_role('button', name='保存生成参数', exact=True).click()
    expect(page.get_by_text('配置已保存，已实时生效', exact=True)).to_be_visible()
    assert writes[-1]['config']['research_provider'] == 'parallel'
