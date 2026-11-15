"""Project source tab reuses the real material drawer and isolated API fixtures."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, detail_project, ui_page  # noqa: F401
from test_antd_admin_management_ui import select
from test_antd_artifact_library_ui import SIZES, library_setup
from test_antd_todo_ui import multipart

OUT = Path("artifacts/source-library-20261022")


def source_setup(page, load, path="/image-gallery"):
    deferred = []
    state = library_setup(
        page, lambda *args, **kwargs: deferred.append((args, kwargs)), path=path
    )
    state.update(
        source_reads=[],
        source_writes=[],
        source_fail=False,
        source_malformed=False,
        save_fail=False,
        source_busy=False,
        hold=False,
        held=[],
    )
    projects = []
    for index in range(19):
        kind = ["file", "url", "mixed"][index % 3]
        files = (
            [
                "原始资料" * 40 + ".txt",
                "资料%_2.pdf",
                '<img src=x onerror="window.sourceInjected=true">.txt',
                "补充资料.txt",
            ]
            if kind != "url"
            else []
        )
        urls = (
            [
                "https://example.invalid/" + "long-path-" * 60,
                "https://example.invalid/article",
            ]
            if kind != "file"
            else []
        )
        projects.append(
            dict(
                id=f"source-{index:02d}",
                title="资料项目" * 35 if index == 0 else f"资料项目 {index:02d}",
                updated_at=1790000000 - index,
                source_kind=kind,
                files=files,
                file_count=len(files),
                urls=urls,
                url_count=len(urls),
                invalid_url_count=0,
            )
        )
    state["source_projects"] = projects

    def endpoint(route):
        params = {
            key: values[0]
            for key, values in parse_qs(
                urlsplit(route.request.url).query, keep_blank_values=True
            ).items()
        }
        state["source_reads"].append(params)
        if state["hold"]:
            state["hold"] = False
            state["held"].append(route)
            return
        if state["source_fail"]:
            route.fulfill(status=503, json={"detail": "资料服务暂不可用"})
            return
        if state["source_malformed"]:
            route.fulfill(
                json={
                    "projects": [{}],
                    "pagination": {"current_page": 1, "total_count": 1},
                }
            )
            return
        found = [item for item in projects if item["source_kind"] != "manual"]
        if params.get("project_id"):
            found = [item for item in projects if item["id"] == params["project_id"]]
        if params.get("search"):
            found = [item for item in found if params["search"] in item["title"]]
        if params.get("kind"):
            found = [
                item
                for item in found
                if item["source_kind"] in [params["kind"], "mixed"]
            ]
        if params.get("sort") == "oldest":
            found = list(reversed(found))
        current = min(int(params["page"]), max(1, (len(found) + 5) // 6))
        scope = next(
            (
                {"id": item["id"], "title": item["title"]}
                for item in projects
                if item["id"] == params.get("project_id")
            ),
            None,
        )
        route.fulfill(
            json={
                "success": True,
                "projects": found[(current - 1) * 6 : current * 6],
                "pagination": {
                    "current_page": current,
                    "per_page": 6,
                    "total_count": len(found),
                },
                "project": scope,
            }
        )

    def editor(route):
        identifier = urlsplit(route.request.url).path.split("/")[-2]
        project = next(item for item in projects if item["id"] == identifier)
        if route.request.method == "POST":
            fields, files = multipart(route.request)
            state["source_writes"].append((identifier, fields, files))
            if state["save_fail"]:
                route.fulfill(status=409, json={"detail": "资料已更新，草稿已保留"})
                return
            retained = json.loads(fields["retained_files"])
            project["files"] = [
                name
                for index, name in enumerate(project["files"])
                if f"old-{index}" in retained
            ] + [name for name, _ in files]
            project["urls"] = fields["content_urls"].splitlines()
            project["file_count"], project["url_count"] = len(project["files"]), len(
                project["urls"]
            )
            project["source_kind"] = (
                "mixed"
                if project["files"] and project["urls"]
                else (
                    "file"
                    if project["files"]
                    else "url" if project["urls"] else "manual"
                )
            )
        route.fulfill(
            json={
                "success": True,
                "sources": {
                    "revision": "a" * 64,
                    "files": [
                        {"id": f"old-{index}", "filename": name}
                        for index, name in enumerate(project["files"])
                    ],
                    "urls": project["urls"],
                    "editable": not state["source_busy"],
                },
            }
        )

    page.route("**/api/source-library?*", endpoint)
    page.route("**/projects/source-*/sources", editor)
    args, kwargs = deferred[0]
    load(*args, **kwargs)
    return state


def source_tab(page):
    page.get_by_role("tab", name="项目资料", exact=True).click()
    expect(page.get_by_role("heading", name="项目资料", exact=True)).to_be_visible()
    return page.get_by_role("region", name="资料项目列表", exact=True)


@pytest.mark.parametrize("width,height", SIZES)
def test_sources_lazy_load_and_long_records_fit_native_cards(ui_page, width, height):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=height))
    state = source_setup(page, load)
    assert not state["source_reads"]
    region = source_tab(page)
    expect(page.get_by_text("共 19 个项目", exact=True)).to_be_visible()
    expect(region.locator(".ant-card")).to_have_count(6)
    region.get_by_role(
        "button", name="查看资料 · 4 个附件 · 0 个链接", exact=True
    ).first.click()
    expect(
        region.get_by_text(state["source_projects"][0]["files"][2], exact=True).first
    ).to_be_visible()
    assert page.evaluate(
        "!window.sourceInjected && document.documentElement.scrollWidth<=innerWidth+1"
    )
    assert region.evaluate("e=>e.scrollWidth<=e.clientWidth+1")
    link = region.locator('a[target="_blank"]').first
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    assert (
        not state["source_writes"]
        and not state["images"]["writes"]
        and not state["errors"]
    )
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(
        path=str(OUT / f"source-library-{width}x{height}.png"), animations="disabled"
    )


def test_project_search_filters_sort_and_pagination_keep_server_queries(ui_page):
    page, load = ui_page
    state = source_setup(page, load)
    source_tab(page)
    expect(page.get_by_text("共 19 个项目", exact=True)).to_be_visible()
    page.locator(".source-library .ant-pagination-item").filter(has_text="4").click()
    expect(page.get_by_text("共 19 个项目", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="资料项目 18", exact=True)).to_be_visible()
    assert state["source_reads"][-1]["page"] == "4"
    select(page, "项目资料类型", "网页链接")
    expect(page.get_by_text("共 12 个项目", exact=True)).to_be_visible()
    assert (
        state["source_reads"][-1]["page"] == "1"
        and state["source_reads"][-1]["kind"] == "url"
    )
    select(page, "项目资料排序", "最早更新")
    expect(
        page.get_by_role("region", name="资料项目列表")
        .locator('a[href^="/projects/"]')
        .first
    ).to_have_text("资料项目 17")
    search = page.get_by_role("searchbox", name="搜索资料项目", exact=True)
    search.fill("不存在")
    expect(page.get_by_text("没有匹配的资料项目", exact=True)).to_be_visible()
    page.get_by_role("button", name="清除筛选", exact=True).click()
    expect(search).to_have_value("")
    expect(page.get_by_text("共 19 个项目", exact=True)).to_be_visible()


@pytest.mark.parametrize("malformed", [False, True])
def test_failed_catalogue_retries_without_resetting_filters(ui_page, malformed):
    page, load = ui_page
    state = source_setup(page, load)
    source_tab(page)
    expect(page.get_by_text("共 19 个项目", exact=True)).to_be_visible()
    state["source_malformed" if malformed else "source_fail"] = True
    search = page.get_by_role("searchbox", name="搜索资料项目", exact=True)
    search.fill("资料项目 12")
    expect(page.get_by_text("项目资料读取失败", exact=True)).to_be_visible()
    expect(search).to_have_value("资料项目 12")
    state["source_malformed"] = state["source_fail"] = False
    page.get_by_role("button", name="重试", exact=True).click()
    expect(page.get_by_text("共 1 个项目", exact=True)).to_be_visible()
    assert not state["source_writes"] and not state["errors"]


@pytest.mark.parametrize("width,height", [(1440, 900), (320, 568)])
def test_existing_material_drawer_preserves_conflict_draft_and_refreshes_after_close(
    ui_page, width, height
):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=height))
    state = source_setup(
        page, load, path="/image-gallery?tab=sources&project=source-01"
    )
    expect(page.get_by_text("共 1 个项目", exact=True)).to_be_visible()
    region = page.get_by_role("region", name="资料项目列表", exact=True)
    trigger = region.get_by_role("button", name="管理资料", exact=True)
    trigger.click()
    drawer = page.get_by_role("dialog", name="管理参考资料", exact=True)
    editor = drawer.get_by_role("textbox", name="参考资料链接", exact=True)
    editor.fill("https://example.invalid/replacement")
    before = len(state["source_reads"])
    state["save_fail"] = True
    drawer.get_by_role("button", name="保存资料", exact=True).click()
    expect(drawer.get_by_text("资料已更新，草稿已保留", exact=True)).to_be_visible()
    expect(editor).to_have_value("https://example.invalid/replacement")
    assert len(state["source_reads"]) == before
    state["save_fail"] = False
    drawer.get_by_role("button", name="保存资料", exact=True).click()
    expect(drawer).not_to_be_visible()
    expect(
        region.get_by_role(
            "link", name="https://example.invalid/replacement", exact=True
        )
    ).to_be_visible()
    expect(trigger).to_be_focused()
    assert len(state["source_writes"]) == 2
    assert (
        state["source_reads"][-1]["project_id"] == "source-01"
        and len(state["source_reads"]) > before
    )
    assert not state["images"]["writes"] and not state["errors"]


@pytest.mark.parametrize("refresh", ["immediate", "held", "moved_focus"])
def test_clear_last_project_on_last_page_returns_to_valid_page_and_restores_focus(
    ui_page, refresh
):
    page, load = ui_page
    state = source_setup(page, load)
    held = []
    if refresh != "immediate":
        def hold_corrected_page(route):
            if parse_qs(urlsplit(route.request.url).query).get("page") == ["3"]:
                held.append(route)
                page.evaluate("window.correctedReadHeld = true")
            else:
                route.fallback()

        page.route("**/api/source-library?*", hold_corrected_page)
    source_tab(page)
    expect(page.get_by_text("共 19 个项目", exact=True)).to_be_visible()
    page.locator(".source-library .ant-pagination-item").filter(has_text="4").click()
    page.locator('[data-source-project="source-18"]').get_by_role(
        "button", name="管理资料", exact=True
    ).click()
    drawer = page.get_by_role("dialog", name="管理参考资料", exact=True)
    remove = drawer.get_by_role("button", name="移除已存附件")
    for _ in range(remove.count()):
        remove.first.click()
    drawer.get_by_role("textbox", name="参考资料链接", exact=True).fill("")
    drawer.get_by_role("button", name="保存资料", exact=True).click()
    expect(drawer).not_to_be_visible()
    expect(page.get_by_text("共 18 个项目", exact=True)).to_be_visible()
    expect(page.locator(".source-library .ant-pagination-item-active")).to_have_text(
        "3"
    )
    destination = page.get_by_role("heading", name="项目资料", exact=True)
    if refresh != "immediate":
        page.wait_for_function("window.correctedReadHeld === true")
        region = page.get_by_role("region", name="资料项目列表", exact=True)
        expect(region).to_have_attribute("aria-busy", "true")
        expect(region.get_by_role("button", name="管理资料").first).to_be_disabled()
        if refresh == "moved_focus":
            destination = page.get_by_role("link", name="打开项目", exact=True)
            destination.focus()
        held[0].fallback()
    expect(page.get_by_role("region", name="资料项目列表")).to_have_attribute(
        "aria-busy", "false"
    )
    expect(destination).to_be_focused()
    assert state["source_reads"][-1]["page"] == "3"


def test_scope_clear_and_tab_change_abort_pending_reads_and_retain_search(ui_page):
    page, load = ui_page
    state = source_setup(
        page, load, path="/image-gallery?tab=sources&project=source-01"
    )
    expect(page.get_by_text("共 1 个项目", exact=True)).to_be_visible()
    page.get_by_role("button", name="查看所有项目资料", exact=True).click()
    expect(page.get_by_text("共 19 个项目", exact=True)).to_be_visible()
    assert "project=" not in page.url
    state["hold"] = True
    search = page.get_by_role("searchbox", name="搜索资料项目", exact=True)
    search.fill("资料项目 12")
    expect(page.get_by_text("正在读取项目资料…", exact=True)).to_be_visible()
    assert len(state["held"]) == 1
    page.get_by_role("tab", name="图片素材", exact=True).click()
    source_tab(page)
    expect(page.get_by_text("共 1 个项目", exact=True)).to_be_visible()
    expect(search).to_have_value("资料项目 12")
    assert not state["source_writes"] and not state["errors"]


def test_busy_source_project_is_readable_but_existing_drawer_prevents_writes(ui_page):
    page, load = ui_page
    state = source_setup(
        page, load, path="/image-gallery?tab=sources&project=source-01"
    )
    state["source_busy"] = True
    page.get_by_role("region", name="资料项目列表").get_by_role(
        "button", name="管理资料", exact=True
    ).click()
    drawer = page.get_by_role("dialog", name="管理参考资料", exact=True)
    expect(
        drawer.get_by_text("项目任务进行中，完成后可重新打开修改资料。", exact=True)
    ).to_be_visible()
    expect(
        drawer.get_by_role("textbox", name="参考资料链接", exact=True)
    ).to_be_disabled()
    expect(drawer.get_by_role("button", name="保存资料", exact=True)).to_be_disabled()
    assert not state["source_writes"]


def test_project_source_menu_link_never_opens_delete_confirmation(
    ui_page, detail_project
):
    page, load = ui_page
    source_setup(page, load)
    load(
        "pages/project/project_detail.html",
        path="/projects/ui-detail",
        project=detail_project,
    )
    page.get_by_role("button", name="项目更多操作", exact=True).click()
    link = page.get_by_role("link", name="查看项目资料", exact=True)
    expect(link).to_have_attribute(
        "href", "/image-gallery?tab=sources&project=ui-detail"
    )
    link.evaluate("e=>e.addEventListener('click',event=>event.preventDefault())")
    link.click()
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_project_scope_follows_url_when_switching_existing_asset_panes(ui_page):
    page, load = ui_page
    state = source_setup(page, load, path="/image-gallery?tab=exports&project=ui-a")
    state["source_projects"][0]["id"] = "ui-a"
    expect(page.get_by_text("共 31 个文件", exact=True)).to_be_visible()
    source_tab(page)
    expect(page.get_by_text("共 1 个项目", exact=True)).to_be_visible()
    page.get_by_role("button", name="查看所有项目资料", exact=True).click()
    expect(page.get_by_text("共 19 个项目", exact=True)).to_be_visible()
    page.get_by_role("tab", name="导出文件", exact=True).click()
    expect(page.get_by_text("共 61 个文件", exact=True)).to_be_visible()
    assert "project_id" not in state["reads"][-1] and "project=" not in page.url
