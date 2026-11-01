"""Model lists load through the backend proxy without replacing saved drafts."""
import re

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, ui_page  # noqa: F401
from test_antd_ui import settings

MODELS = ["agnes-3.0-flash", "gpt-4.1", "o3-mini"]
SIZES = [(1920, 1080), (1440, 900), (1024, 768), (390, 844), (320, 568), (844, 390)]
MODEL_PROXY = "**/api/ai/providers/openai/models"


def model_fixture(ui_page, current="agnes-3.0-flash", records=None, **config):
    page, load = ui_page
    reads, writes, errors = [], [], []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def list_models(route):
        assert route.request.method == "POST"
        reads.append(route.request.post_data_json)
        route.fulfill(json={"success": True, "models": records if records is not None else [{"id": model} for model in MODELS]})

    def save(route):
        if route.request.method == "POST":
            writes.append(route.request.post_data_json)
        route.fulfill(json={"success": True, "config": {}})

    page.route(MODEL_PROXY, list_models)
    page.route("**/api/config/ai_providers", save)
    settings(page, load, current_config={"openai_model": current, "openai_api_key": "fixture-key", "openai_base_url": "https://models.example.invalid/v1", **config})
    return page, reads, writes, errors


def refresh(page, name="openai_model"):
    field = page.locator(f"#field-{name}")
    page.locator(".model-control").filter(has=field).get_by_role("button", name=re.compile(r"^获取.*列表$")).click()
    return field


def options(page):
    return page.locator(".ant-select-dropdown:visible .ant-select-item-option-content")


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize("current", ["agnes-3.0-flash", "private-model"])
def test_fetched_models_open_in_full_without_overwriting_saved_name(ui_page, width, height, current):
    page, reads, writes, errors = model_fixture(ui_page, current)
    page.set_viewport_size(dict(width=width, height=height))
    field = refresh(page)
    expect(field).to_have_value(current)
    expect(field).to_have_attribute("aria-expanded", "true")
    expect(options(page)).to_have_text(MODELS)
    popup = page.locator(".ant-select-dropdown:visible").bounding_box()
    assert popup["x"] >= -1 and popup["x"] + popup["width"] <= width + 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    options(page).get_by_text("gpt-4.1", exact=True).click()
    expect(field).to_have_value("gpt-4.1")
    expect(field).to_have_attribute("aria-expanded", "false")
    field.locator("xpath=ancestor::*[contains(@class, 'model-control')][1]").get_by_role("button", name="展开默认模型列表", exact=True).click()
    expect(options(page)).to_have_text(MODELS)
    assert len(reads) == 1 and not writes and not errors


@pytest.mark.parametrize("width", [1440, 320])
def test_model_search_keyboard_custom_name_and_save_preserve_contract(ui_page, width):
    page, reads, writes, errors = model_fixture(ui_page)
    page.set_viewport_size(dict(width=width, height=900))
    field = refresh(page)
    field.fill("O3")
    expect(options(page)).to_have_text(["o3-mini"])
    field.press("ArrowDown"); field.press("Enter")
    expect(field).to_have_value("o3-mini")
    field.fill("my-custom-model-v2")
    field.press("Escape")
    page.get_by_role("button", name="保存 OpenAI", exact=True).click()
    expect(page.get_by_text("配置已保存，已实时生效", exact=True)).to_be_visible()
    assert len(reads) == 1 and len(writes) == 1
    assert writes[0]["config"]["openai_model"] == "my-custom-model-v2"
    assert writes[0]["config"]["openai_api_key"] == "fixture-key"
    assert writes[0]["config"]["openai_base_url"] == "https://models.example.invalid/v1"
    assert not errors


@pytest.mark.parametrize("failure", [
    {"status": 503, "json": {"detail": "unavailable"}},
    {"json": {"success": False, "error": "unavailable"}},
], ids=["http-error", "proxy-error"])
def test_empty_and_failed_model_refresh_preserve_draft_and_allow_retry(ui_page, failure):
    page, reads, writes, errors = model_fixture(ui_page, "private-model", records=[])
    field = refresh(page)
    expect(page.get_by_text("暂无可用模型，可手动填写", exact=True)).to_be_visible()
    expect(field).to_have_value("private-model")
    field.fill("custom-draft")
    page.route(MODEL_PROXY, lambda route: route.fulfill(**failure))
    refresh(page)
    expect(page.get_by_role("alert").filter(has_text="unavailable")).to_be_visible()
    expect(field).to_have_value("custom-draft")
    page.route(MODEL_PROXY, lambda route: route.fulfill(json={"success": True, "models": [None, {"id": "new-model"}, {"id": "new-model"}, {}, {"name": "another-model"}]}))
    refresh(page)
    expect(options(page)).to_have_text(["another-model", "new-model"])
    expect(field).to_have_value("custom-draft")
    assert not writes and not errors


def test_model_proxy_receives_unsaved_connection_settings(ui_page):
    page, reads, writes, errors = model_fixture(ui_page, llm_timeout_seconds=75)
    page.locator("#field-openai_api_key").fill("unsaved-fixture-key")
    page.locator("#field-openai_base_url").fill("http://192.0.2.10:8080/v1/")
    field = refresh(page)
    expect(options(page)).to_have_text(MODELS)
    expect(field).to_have_value(MODELS[0])
    assert reads == [{
        "base_url": "http://192.0.2.10:8080/v1",
        "api_key": "unsaved-fixture-key",
        "llm_timeout_seconds": 75,
    }]
    assert not writes and not errors


def test_model_list_remains_virtualized_scrollable_and_searchable(ui_page):
    page, _, _, errors = model_fixture(ui_page, records=[{"id": f"model-{i:04d}"} for i in range(500)])
    field = refresh(page)
    expect(field).to_have_attribute("aria-expanded", "true")
    assert options(page).count() < 40
    popup = page.locator(".ant-select-dropdown:visible")
    popup.hover();page.mouse.wheel(0, 1200)
    expect(options(page).first).not_to_have_text("model-0000")
    field.fill("model-0499")
    expect(options(page)).to_have_text(["model-0499"])
    options(page).click()
    expect(field).to_have_value("model-0499")
    assert not errors


def test_role_model_list_uses_selected_provider_and_invalidates_on_change(ui_page):
    page, reads, _, errors = model_fixture(ui_page, outline_model_provider="openai", outline_model_name="custom-outline")
    page.locator(".ant-collapse-header").filter(has_text="模型任务配置").click()
    field = refresh(page, "outline_model_name")
    expect(field).to_have_value("custom-outline")
    expect(options(page)).to_have_text(MODELS)
    field.press("Escape")
    provider = page.locator("#field-outline_model_provider")
    provider.click()
    options(page).get_by_text("landppt", exact=True).click()
    expect(page.locator(".model-control").filter(has=field).get_by_role("button", name=re.compile(r"^展开.*列表$"))).to_be_disabled()
    expect(field).to_have_value("custom-outline")
    page.route("**/api/ai/providers/landppt/models", lambda route: route.fulfill(json={"models": ["MODEL2", "MODEL1"]}))
    refresh(page, "outline_model_name")
    expect(options(page)).to_have_text(["MODEL1", "MODEL2"])
    assert len(reads) == 1 and not errors


def test_late_model_response_keeps_selected_tab_and_saved_name(ui_page):
    page, _ = ui_page
    page.add_init_script("""(() => {
      const original = fetch;
      window.fetch = (...args) => String(args[0]) === '/api/ai/providers/openai/models'
        ? new Promise(resolve => { window.resolveModels = resolve; }) : original(...args);
    })();""")
    page, _, _, errors = model_fixture(ui_page, "custom-draft")
    field = refresh(page)
    expect(field).to_be_disabled()
    page.get_by_role("tab", name="应用配置", exact=True).click()
    page.evaluate("models => window.resolveModels(new Response(JSON.stringify({success:true,models:models.map(id=>({id}))})))", MODELS)
    expect(page.get_by_text("已获取 3 个模型", exact=True)).to_be_visible()
    expect(page.get_by_role("tab", name="应用配置", exact=True)).to_have_attribute("aria-selected", "true")
    assert page.locator(".ant-select-dropdown:visible").count() == 0
    assert page.evaluate("document.activeElement.id !== 'field-openai_model'")
    page.get_by_role("tab", name="AI 提供者", exact=True).click()
    expect(field).to_have_value("custom-draft")
    field.click()
    expect(options(page)).to_have_text(MODELS)
    assert not errors


def test_default_provider_change_clears_implicit_role_list_without_changing_draft(ui_page):
    page, _, _, errors = model_fixture(ui_page, outline_model_name="custom-outline", outline_model_provider="")
    writes = []
    def choose(route):
        writes.append(route.request.post_data_json)
        route.fulfill(json={"success": True})
    page.route("**/api/config/default-provider", choose)
    page.locator(".ant-collapse-header").filter(has_text="模型任务配置").click()
    field = refresh(page, "outline_model_name")
    expect(options(page)).to_have_text(MODELS)
    field.press("Escape")
    page.locator(".provider-collapse .ant-collapse-header").filter(has_text="Anthropic Claude").click()
    provider = page.locator(".provider-collapse .ant-collapse-item").filter(has=page.locator("#field-anthropic_api_key"))
    provider.get_by_role("radio", name="设为默认", exact=True).click()
    expect(page.get_by_text("默认提供者已更新", exact=True)).to_be_visible()
    expect(provider.get_by_role("radio", name="设为默认", exact=True)).to_be_checked()
    expect(field).to_have_value("custom-outline")
    expect(page.locator(".model-control").filter(has=field).get_by_role("button", name=re.compile(r"^展开.*列表$"))).to_be_disabled()
    assert writes == [{"provider": "anthropic"}]
    assert not errors


def test_model_arrow_keyboard_open_and_escape_do_not_submit_or_reload(ui_page):
    page, reads, writes, errors = model_fixture(ui_page)
    field = refresh(page)
    expect(options(page)).to_have_text(MODELS)
    field.press("Escape")
    arrow = page.locator(".model-control").filter(has=field).get_by_role("button", name="展开默认模型列表", exact=True)
    arrow.focus();arrow.press("Space")
    expect(options(page)).to_have_text(MODELS)
    expect(field).to_be_focused()
    field.press("Escape")
    expect(field).to_have_attribute("aria-expanded", "false")
    expect(field).to_have_value(MODELS[0])
    field.fill("unlisted-custom-model")
    arrow.click()
    expect(options(page)).to_have_text(MODELS)
    expect(field).to_have_value("unlisted-custom-model")
    assert len(reads) == 1 and not writes and not errors
