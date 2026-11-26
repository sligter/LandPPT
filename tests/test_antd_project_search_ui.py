"""Project search submits URL filters, retains pagination and fits narrow screens."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, ui_page  # noqa: F401

SIZES = [(1920, 1080), (1440, 900), (1024, 768), (390, 844), (320, 568), (844, 390)]


def library(browser_page, load, path="/projects", **values):
    load("pages/project/projects_list.html", path=path, **values)
    browser_page.get_by_role("heading", name="项目列表", exact=True).wait_for()


@pytest.mark.parametrize("width,height", SIZES)
def test_search_input_button_and_clear_preserve_status_and_fit_page(
    ui_page, width, height
):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=height))
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    library(
        page,
        load,
        path="/projects?status=draft&page=3&search=old",
        search_query="old",
        status_filter="draft",
        page=3,
        total=21,
    )
    field = page.get_by_role("searchbox", name="搜索项目", exact=True)
    expect(field).to_have_value("old")
    field.fill("  数据 & 50%_ / +  ")
    assert parse_qs(urlsplit(page.url).query)["search"] == ["old"]
    toolbar = page.locator(".projects-toolbar")
    toolbar.get_by_role("button", name="搜索", exact=True).click()
    page.wait_for_url(
        lambda url: parse_qs(urlsplit(url).query).get("search") == ["数据 & 50%_ / +"]
    )
    params = parse_qs(urlsplit(page.url).query)
    assert params["status"] == ["draft"] and "page" not in params
    for element in [
        field,
        toolbar.get_by_role("button", name="搜索", exact=True),
        page.locator(".projects-status-filter"),
    ]:
        box = element.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
    search = toolbar.get_by_role("button", name="搜索", exact=True)
    assert search.bounding_box()["height"] >= (44 if width <= 600 else 32)
    if width <= 600:
        assert search.bounding_box()["width"] >= 44
    field.fill("clear me")
    page.get_by_role("button", name="清除搜索", exact=True).click()
    page.wait_for_url(lambda url: "search" not in parse_qs(urlsplit(url).query))
    assert parse_qs(urlsplit(page.url).query)["status"] == ["draft"]
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert not errors


def test_filter_and_pagination_preserve_committed_search(ui_page):
    page, load = ui_page
    query = "Research & 数据"
    library(
        page,
        load,
        path="/projects?search=Research+%26+%E6%95%B0%E6%8D%AE&status=draft&page=2",
        search_query=query,
        status_filter="draft",
        page=2,
        page_size=10,
        total=35,
    )
    page.locator(".ant-pagination-next button").click()
    page.wait_for_url(lambda url: parse_qs(urlsplit(url).query).get("page") == ["3"])
    assert parse_qs(urlsplit(page.url).query)["search"] == [query]
    page.locator("#statusFilter").click()
    page.locator(".ant-select-dropdown:visible").get_by_text(
        "已完成", exact=True
    ).click()
    page.wait_for_url(
        lambda url: parse_qs(urlsplit(url).query).get("status") == ["completed"]
    )
    assert parse_qs(urlsplit(page.url).query)["search"] == [query]
    assert "page" not in parse_qs(urlsplit(page.url).query)


@pytest.mark.parametrize("width", [1440, 320])
def test_enter_empty_result_and_refresh_restore_query(ui_page, width):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=900))
    library(
        page,
        load,
        path="/projects?search=no-match",
        search_query="no-match",
        projects=[],
        total=0,
    )
    field = page.get_by_role("searchbox", name="搜索项目", exact=True)
    expect(page.locator(".ant-empty-description:visible")).to_have_text(
        "没有找到匹配的项目"
    )
    expect(page.get_by_role("link", name="查看全部", exact=True)).to_have_attribute(
        "href", "/projects"
    )
    page.reload(wait_until="networkidle")
    expect(field).to_have_value("no-match")
    field.fill("  中文 search  ")
    field.press("Enter")
    page.wait_for_url(
        lambda url: parse_qs(urlsplit(url).query).get("search") == ["中文 search"]
    )
    assert "page" not in parse_qs(urlsplit(page.url).query)


def test_background_refresh_preserves_unsubmitted_search_after_blur(ui_page):
    page, load = ui_page
    page.clock.install()
    library(
        page,
        load,
        path="/projects?search=demo",
        search_query="demo",
        projects=[
            dict(
                project_id="running",
                title="生成中",
                topic="demo",
                scenario="general",
                status="in_progress",
                updated_at=1760000000,
                todo_board=None,
            )
        ],
    )
    committed_url = page.url
    payload = json.loads(page.locator("#antdData").text_content())
    payload["projects"][0]["progress"] = 50
    page.route(
        committed_url,
        lambda route: route.fulfill(
            body=f'<script id="antdData" type="application/json">{json.dumps(payload)}</script>',
            content_type="text/html",
        ),
    )
    field = page.get_by_role("searchbox", name="搜索项目", exact=True)
    field.fill("unsaved draft")
    field.blur()

    page.clock.fast_forward(31_000)
    expect(page.locator(".project-status:visible").get_by_text("50%", exact=True)).to_be_visible()
    expect(field).to_have_value("unsaved draft")
    assert page.url == committed_url
