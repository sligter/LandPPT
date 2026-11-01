"""DeepSeek research configuration and status against the built frontend."""

from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, ui_page  # noqa: F401
from test_antd_ui import settings
from test_antd_community_ui import community


@pytest.mark.parametrize("width", [1440, 320])
def test_deepseek_settings_select_save_and_blank_key_preservation(ui_page, width):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=900))
    saved = dict(
        research_provider="deepseek", deepseek_max_results=12, deepseek_timeout=45
    )
    page.route("**/api/config/all", lambda route: route.fulfill(json={"config": saved}))
    writes = []

    def capture(route):
        writes.append(route.request.post_data_json["config"])
        route.fulfill(json={"success": True})

    page.route("**/api/config/generation_params", capture)
    settings(page, load, current_config={**saved, "deepseek_api_key_configured": True})
    page.get_by_role("tab", name="生成参数", exact=True).click()
    provider = page.get_by_role("combobox", name="研究提供商", exact=True)
    expect(provider.locator("..")).to_have_attribute("title", "DeepSeek")
    # Select a different provider and return to prove the catalogue/save path.
    provider.click()
    page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option-content"
    ).get_by_text("Tavily", exact=True).click()
    provider.click()
    page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option-content"
    ).get_by_text("DeepSeek", exact=True).click()
    key = page.locator("#field-deepseek_api_key")
    expect(key).to_have_value("")
    expect(key).to_have_attribute("placeholder", "已配置，留空保留")
    page.locator("#field-deepseek_base_url").fill("")
    page.locator("#field-deepseek_max_results").fill("50")
    page.get_by_role("button", name="保存生成参数", exact=True).click()
    expect(page.get_by_text("配置已保存，已实时生效", exact=True)).to_be_visible()
    assert writes[-1]["research_provider"] == "deepseek"
    assert writes[-1]["deepseek_base_url"] == "https://api.deepseek.com"
    assert writes[-1]["deepseek_max_results"] == "50"
    assert writes[-1]["deepseek_timeout"] == "45"
    assert "deepseek_api_key" not in writes[-1]
    key.fill("sk-new-test")
    with page.expect_response("**/api/config/generation_params"):
        page.get_by_role("button", name="保存生成参数", exact=True).click()
    assert writes[-1]["deepseek_api_key"] == "sk-new-test"
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    directory = Path("artifacts/deepseek-research")
    directory.mkdir(parents=True, exist_ok=True)
    key.fill("")
    key.scroll_into_view_if_needed()
    page.screenshot(path=str(directory / f"settings-{width}.png"))


def test_admin_can_save_deepseek_system_defaults(ui_page):
    page, load = ui_page
    _, writes = community(page, load)
    provider = page.locator("#system_research_provider")
    provider.click()
    page.locator(
        ".ant-select-dropdown:visible .ant-select-item-option-content"
    ).get_by_text("DeepSeek", exact=True).click()
    page.locator("#system_deepseek_api_key").fill("sk-system-test")
    page.locator("#system_deepseek_max_results").fill("25")
    page.locator("#system_deepseek_base_url").fill("")
    page.locator("#saveSystemDefaultsBtn").click()
    expect(page.get_by_text("系统默认配置已保存", exact=True)).to_be_visible()
    config = writes[-1][2]["config"]
    assert config["research_provider"] == "deepseek"
    assert config["deepseek_api_key"] == "sk-system-test"
    assert config["deepseek_max_results"] == 25
    assert config["deepseek_base_url"] == "https://api.deepseek.com"


def test_research_status_displays_selected_deepseek_provider(ui_page):
    page, load = ui_page
    page.route(
        "**/api/research/status",
        lambda route: route.fulfill(
            json={
                "available": True,
                "deepseek_configured": True,
                "tavily_configured": False,
                "status": {
                    "research_provider": "deepseek",
                    "max_results": 20,
                    "ai_provider_type": "landppt",
                },
            }
        ),
    )
    page.route(
        "**/api/research/reports", lambda route: route.fulfill(json={"reports": []})
    )
    load("pages/project/research_status.html", path="/research")
    expect(page.get_by_text("DeepSeek 已配置", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="开始研究", exact=True)).to_be_enabled()
    expect(page.get_by_text("Tavily 未配置", exact=True)).to_have_count(0)
