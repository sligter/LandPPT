"""The maintained settings UI saves the runtime provider choice."""
import pytest
from playwright.sync_api import expect
from test_app_ui import browser, ui_page  # noqa: F401
from test_antd_ui import settings


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
