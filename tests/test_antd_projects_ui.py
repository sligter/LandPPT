"""Project library/detail contracts against real templates and built browser assets."""

import json
import re
from datetime import datetime

import pytest

from test_app_ui import browser, detail_project, ui_page  # noqa: F401


@pytest.mark.parametrize(
    "template", ["project_dashboard", "projects_list", "project_detail"]
)
@pytest.mark.parametrize("numeric", [True, False])
def test_project_pages_render_real_unix_timestamps_and_datetime(
    ui_page, detail_project, template, numeric
):
    page, load = ui_page
    date = datetime(2026, 10, 2, 9, 30)
    value = date.timestamp() if numeric else date
    project = {
        **detail_project,
        "created_at": value,
        "updated_at": value,
        "todo_board": None,
    }
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    load(
        f"pages/project/{template}.html",
        project=project,
        projects=[project],
        recent_projects=[project],
        todo_board=None,
        versions=[],
    )
    page.locator("#dashboardRoot, .projects-page, .project-detail-page").wait_for()
    data = json.loads(page.locator("#antdData").text_content())
    if template == "project_detail":
        assert data["project"]["created"] == "2026-10-02 09:30"
    else:
        assert data["projects"][0]["updated"] == "10-02 09:30"
    assert not errors


@pytest.mark.parametrize(
    "width,height", [(1440, 900), (1024, 768), (390, 844), (320, 568), (844, 390)]
)
@pytest.mark.parametrize("scene", ["empty", "recent", "tasks"])
def test_dashboard_overview_and_tasks_are_usable_without_overflow(
    ui_page, detail_project, width, height, scene
):
    page, load = ui_page
    page.set_viewport_size({"width": width, "height": height})
    project = {
        **detail_project,
        "updated_at": detail_project["created_at"],
        "todo_board": None,
    }
    boards = (
        [
            dict(
                task_id="task /中文",
                title="正在生成的项目与当前阶段" * 4,
                stages=[],
                current_stage_index=0,
                overall_progress=0,
            )
        ]
        if scene == "tasks"
        else []
    )
    load(
        "pages/project/project_dashboard.html",
        path="/dashboard",
        total_projects=0 if scene == "empty" else 41,
        completed_projects=40,
        in_progress_projects=1,
        draft_projects=0,
        recent_projects=[] if scene == "empty" else [project],
        active_todo_boards=boards,
    )
    page.get_by_role("heading", name="首页", exact=True).wait_for()
    overview = page.get_by_role("navigation", name="项目概览")
    assert [a.get_attribute("href") for a in overview.get_by_role("link").all()] == [
        "/projects",
        "/projects?status=completed",
        "/projects?status=in_progress",
        "/projects?status=draft",
    ]
    overview.get_by_role("link").first.focus()
    assert overview.get_by_role("link").first.evaluate(
        "e => e === document.activeElement"
    )
    if scene == "empty":
        assert (
            page.get_by_role("link", name="创建第一份演示文稿").get_attribute("href")
            == "/scenarios"
        )
        assert page.get_by_text("还没有项目", exact=True).is_visible()
    else:
        assert (
            page.locator(".dashboard-project-item")
            .get_by_role("link", name=project["title"], exact=True)
            .get_attribute("href")
            == "/projects/ui-detail"
        )
        assert page.get_by_role("button", name="重命名", exact=True).is_visible()
    if scene == "tasks":
        data = json.loads(page.locator("#antdData").text_content())
        assert data["todos"][0]["stage"] == "等待开始"
        assert (
            page.get_by_role("link", name="查看进度", exact=True).get_attribute("href")
            == "/projects/task%20%2F%E4%B8%AD%E6%96%87/todo"
        )
        assert "0%" in page.locator(".dashboard-tasks").inner_text()
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    for item in page.locator(
        ".dashboard-project-item, .dashboard-stat, .dashboard-task-list article"
    ).all():
        assert item.evaluate("e => e.scrollWidth <= e.clientWidth + 1")


@pytest.mark.parametrize(
    "width,height", [(1600, 900), (1440, 900), (1180, 800), (1024, 768), (768, 1024), (390, 844)]
)
def test_dashboard_recent_projects_fill_whole_card_rows(
    ui_page, detail_project, width, height
):
    page, load = ui_page
    page.set_viewport_size({"width": width, "height": height})
    candidates = [
        {
            **detail_project,
            "project_id": f"recent-{index}",
            "title": f"最近项目 {index}",
            "updated_at": detail_project["created_at"] + index,
            "todo_board": None,
        }
        for index in range(8)
    ]
    load(
        "pages/project/project_dashboard.html",
        path="/dashboard",
        total_projects=len(candidates),
        completed_projects=len(candidates),
        in_progress_projects=0,
        draft_projects=0,
        recent_projects=candidates,
    )
    page.locator(".dashboard-project-item").first.wait_for()
    # The grid tracks decide the card count, so every rendered card must belong
    # to a complete row instead of a lone leftover beneath the last full row.
    columns = page.evaluate(
        "() => getComputedStyle(document.querySelector('.dashboard-projects ul'))"
        ".gridTemplateColumns.split(' ').filter(Boolean).length"
    )
    cards = page.locator(".dashboard-project-item")
    count = cards.count()
    rows = -(-count // columns)
    assert count == min(len(candidates), columns * -(-4 // columns))
    assert count % columns == 0
    tops = [round(cards.nth(index).bounding_box()["y"]) for index in range(count)]
    for row in range(rows):
        assert len(set(tops[row * columns : (row + 1) * columns])) == 1
    assert page.get_by_role(
        "link", name=candidates[count - 1]["title"], exact=True
    ).is_visible()
    assert page.get_by_role(
        "link", name=candidates[count]["title"], exact=True
    ).count() == 0


def detail(page, load, project, **values):
    load(
        "pages/project/project_detail.html",
        path="/projects/ui-detail",
        project=project,
        todo_board=None,
        versions=[],
        **values,
    )
    page.get_by_role("heading", name=project["title"], exact=True).wait_for()


def test_project_filter_and_pagination_preserve_route_query(ui_page):
    page, load = ui_page
    load(
        "pages/project/projects_list.html",
        path="/projects?status=completed&page=2",
        status_filter="completed",
        page=2,
        page_size=10,
        total=35,
    )
    page.locator(".ant-pagination-next button").click()
    page.wait_for_url("**/projects?status=completed&page=3")
    page.locator("#statusFilter").click()
    page.locator(".ant-select-dropdown:visible").get_by_text("草稿", exact=True).click()
    page.wait_for_url("**/projects?status=draft")
    assert "page=" not in page.url


@pytest.mark.parametrize(
    "width,height", [(1440, 900), (390, 844), (320, 568), (844, 390)]
)
def test_empty_filtered_library_retains_controls_and_bounds(ui_page, width, height):
    page, load = ui_page
    page.set_viewport_size({"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    load(
        "pages/project/projects_list.html",
        projects=[],
        status_filter="archived",
        total=0,
    )
    assert page.locator("#statusFilter").is_visible()
    assert page.get_by_role("link", name="查看全部", exact=True).is_visible()
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    assert not errors


@pytest.mark.parametrize("progress", [None, 0])
def test_library_does_not_turn_missing_progress_into_zero(
    ui_page, detail_project, progress
):
    page, load = ui_page
    page.set_viewport_size({"width": 390, "height": 844})
    project = {
        **detail_project,
        "status": "in_progress",
        "updated_at": detail_project["created_at"],
        "todo_board": None if progress is None else {"overall_progress": progress},
    }
    load("pages/project/projects_list.html", projects=[project])
    status = page.locator(".mobile-projects .project-status")
    page.get_by_role("heading", name="项目列表").wait_for()
    assert status.get_by_text("进行中", exact=True).is_visible()
    assert status.locator(".ant-progress").count() == (progress is not None)
    if progress == 0:
        assert "0%" in status.inner_text()


@pytest.mark.parametrize("template", ["project_dashboard", "projects_list"])
def test_project_rename_failure_retains_text_and_retry_updates_row(ui_page, template):
    page, load = ui_page
    writes = []

    def respond(route):
        writes.append(route.request.post_data_json)
        route.fulfill(
            status=500 if len(writes) == 1 else 200,
            json=(
                {"detail": "暂时无法保存"}
                if len(writes) == 1
                else {"status": "success"}
            ),
        )

    page.route("**/api/projects/*/rename", respond)
    load(f"pages/project/{template}.html")
    page.get_by_role("button", name="重命名", exact=True).first.click()
    dialog = page.get_by_role("dialog", name="重命名项目")
    field = dialog.get_by_role("textbox", name="项目名称")
    field.fill("  <新的项目名称>  ")
    dialog.get_by_role("button", name="保存", exact=True).click()
    page.get_by_text("暂时无法保存", exact=True).wait_for()
    assert field.input_value() == "  <新的项目名称>  "
    dialog.get_by_role("button", name="保存", exact=True).click()
    page.wait_for_function(
        "!document.querySelector('.ant-modal-wrap:not([style*=\"display: none\"])')"
    )
    assert page.locator(".project-title:visible").inner_text() == "<新的项目名称>"
    assert writes == [{"title": "<新的项目名称>"}] * 2


def test_detail_delete_keeps_two_confirmations_and_cancel_is_read_only(
    ui_page, detail_project
):
    page, load = ui_page
    detail(page, load, detail_project)
    page.get_by_role("button", name="项目更多操作", exact=True).click()
    page.get_by_role("menuitem", name="删除项目", exact=True).click()
    first = page.get_by_role("dialog", name="确认删除项目", exact=True)
    first.get_by_role("button", name="继续", exact=True).click()
    final = page.get_by_role("dialog", name="再次确认删除项目", exact=True)
    final.get_by_role("button", name="取消", exact=True).click()
    assert not final.is_visible()
    assert page.get_by_role("button", name="项目更多操作", exact=True).evaluate("e => e === document.activeElement")
    # The fixture rejects every non-GET request unless explicitly intercepted.
    page.get_by_role("button", name="项目更多操作", exact=True).click()
    page.get_by_role("menuitem", name="归档项目", exact=True).click()
    page.get_by_role("dialog", name="归档项目", exact=True).get_by_role(
        "button", name="取消", exact=True
    ).click()


def test_outline_move_failure_leaves_order_and_sends_existing_operation(
    ui_page, detail_project
):
    page, load = ui_page
    writes = []

    def respond(route):
        writes.append(route.request.post_data_json)
        route.fulfill(status=500, json={"detail": "排序保存失败"})

    page.route("**/projects/*/update-outline", respond)
    project = {
        **detail_project,
        "outline": {
            "metadata": {"language": "zh"},
            "slides": [{"title": "A", "custom": 7}, {"title": "B"}],
        },
    }
    detail(page, load, project)
    page.get_by_role("button", name="第 1 页更多操作", exact=True).click()
    page.get_by_role("menuitem", name="下移", exact=True).click()
    page.get_by_text("排序保存失败", exact=True).wait_for()
    assert page.locator("#compactView h3").all_text_contents() == ["A", "B"]
    payload = writes[0]
    assert payload["operation"] == {"type": "move", "slide_index": 0, "to_index": 1}
    outline = json.loads(payload["outline_content"])
    assert [slide["title"] for slide in outline["slides"]] == ["B", "A"]
    assert [slide["page_number"] for slide in outline["slides"]] == [1, 2]
    assert outline["slides"][1]["custom"] == 7


def test_outline_drag_and_delete_send_synchronizing_operations(ui_page, detail_project):
    page, load = ui_page
    writes = []

    def respond(route):
        writes.append(route.request.post_data_json)
        route.fulfill(status=500, json={"detail": "写入失败"})

    page.route("**/projects/*/update-outline", respond)
    detail(page, load, detail_project)
    cards = page.locator("#compactView .outline-slide-card")
    cards.first.drag_to(cards.nth(1))
    page.get_by_text("写入失败", exact=True).wait_for()
    assert writes[0]["operation"] == {"type": "move", "slide_index": 0, "to_index": 1}
    page.get_by_role("button", name="第 1 页更多操作", exact=True).click()
    page.get_by_role("menuitem", name="删除此页", exact=True).click()
    dialog = page.get_by_role("dialog", name="删除大纲页面")
    dialog.get_by_role("button", name="取消", exact=True).click()
    assert len(writes) == 1
    assert page.get_by_role("button", name="第 1 页更多操作", exact=True).evaluate("e => e === document.activeElement")
    page.get_by_role("button", name="第 1 页更多操作", exact=True).click()
    page.get_by_role("menuitem", name="删除此页", exact=True).click()
    with page.expect_response("**/projects/*/update-outline") as response:
        dialog.get_by_role("button", name="删除", exact=True).click()
    assert response.value.status == 500
    assert writes[1]["operation"] == {"type": "delete", "slide_index": 0}
    outline = json.loads(writes[1]["outline_content"])
    assert len(outline["slides"]) == 2
    assert len(cards.all()) == 3  # The failed deletion leaves the visible state intact.


def test_detail_copy_navigates_to_created_project(ui_page, detail_project):
    page, load = ui_page
    writes = []

    def respond(route):
        writes.append((route.request.method, route.request.url))
        route.fulfill(json={"status": "success", "project_id": "created-project"})

    page.route("**/api/projects/*/duplicate", respond)
    detail(page, load, detail_project)
    assert (
        page.get_by_role("navigation", name="主导航")
        .locator('a[aria-current="page"]')
        .get_attribute("href")
        == "/projects"
    )
    page.get_by_role("button", name="项目更多操作", exact=True).click()
    page.get_by_role("menuitem", name="复制项目", exact=True).click()
    page.wait_for_url("**/projects/created-project")
    assert writes == [("POST", "http://ui.test/api/projects/ui-detail/duplicate")]


def test_single_page_optimization_is_draft_until_saved(ui_page, detail_project):
    page, load = ui_page
    writes = []

    def optimize(route):
        writes.append(("optimize", route.request.post_data_json))
        route.fulfill(
            json={
                "success": True,
                "optimized_content": json.dumps(
                    {
                        "title": "改进后的标题",
                        "slide_type": "content",
                        "content_points": ["优化要点"],
                    }
                ),
            }
        )

    def save(route):
        writes.append(("save", route.request.post_data_json))
        route.fulfill(status=500, json={"detail": "保存失败，请重试"})

    page.route("**/api/ai/optimize-outline", optimize)
    page.route("**/projects/*/update-outline", save)
    project = {
        **detail_project,
        "outline": {
            "title": "完整大纲",
            "metadata": {
                "language": "en",
                "target_audience": "自定义",
                "custom_audience": "研发团队",
            },
            "slides": [
                {
                    "title": "原始标题",
                    "custom": {"keep": True},
                    "content_points": ["原始要点"],
                }
            ],
        },
    }
    detail(page, load, project)
    page.get_by_role("button", name="编辑此页", exact=True).click()
    editor = page.get_by_role("dialog", name="编辑第 1 页", exact=True)
    editor.get_by_role("button", name="AI 优化", exact=True).click()
    optimizer = page.get_by_role("dialog", name="AI 优化第 1 页", exact=True)
    optimizer.get_by_role("textbox", name="优化要求").fill("简化内容")
    optimizer.get_by_role("button", name="开始优化").click()
    editor.get_by_role("textbox", name="标题", exact=True).wait_for()
    page.wait_for_function(
        "document.querySelector('.slide-edit-form input')?.value === '改进后的标题'"
    )
    assert len(writes) == 1
    payload = writes[0][1]
    assert payload["optimization_type"] == "single" and payload["slide_index"] == 0
    assert payload["language"] == "en"
    assert payload["project_info"]["target_audience"] == "研发团队"
    assert editor.get_by_role("button", name="AI 优化", exact=True).evaluate(
        "e => e === document.activeElement"
    )
    editor.get_by_role("button", name="保存修改", exact=True).click()
    editor.get_by_text("保存失败，请重试", exact=True).wait_for()
    saved = json.loads(writes[1][1]["outline_content"])
    assert saved["slides"][0]["title"] == "改进后的标题"
    assert saved["slides"][0]["custom"] == {"keep": True}
    assert saved["metadata"] == project["outline"]["metadata"]
    assert (
        editor.get_by_role("textbox", name="标题", exact=True).input_value()
        == "改进后的标题"
    )


def test_full_outline_invalid_json_and_nested_modal_cancel_keep_edits(
    ui_page, detail_project
):
    page, load = ui_page
    detail(page, load, detail_project)
    page.get_by_role("button", name="编辑大纲", exact=True).click()
    editor = page.get_by_role("dialog", name="编辑 PPT 大纲", exact=True)
    field = editor.get_by_role("textbox", name="大纲 JSON")
    field.fill("{bad json")
    editor.get_by_role("button", name="保存修改").click()
    editor.get_by_text(re.compile("JSON 格式错误")).wait_for()
    assert field.input_value() == "{bad json"
    value = json.dumps(detail_project["outline"], ensure_ascii=False)
    field.fill(value)
    trigger = editor.get_by_role("button", name="优化大纲", exact=True)
    trigger.click()
    optimizer = page.get_by_role("dialog", name="AI 优化大纲", exact=True)
    optimizer.get_by_role("textbox", name="优化要求").fill("优化结构")
    for _ in range(8):
        page.keyboard.press("Tab")
        assert optimizer.evaluate("e => e.contains(document.activeElement)")
    page.keyboard.press("Escape")
    assert not optimizer.is_visible()
    assert trigger.evaluate("e => e === document.activeElement")
    assert field.input_value() == value


def test_restore_failure_preserves_version_and_allows_retry(ui_page, detail_project):
    page, load = ui_page
    writes = []

    def respond(route):
        writes.append((route.request.method, route.request.url))
        route.fulfill(status=500, json={"detail": "无法恢复此版本"})

    page.route("**/api/projects/*/versions/*/restore", respond)
    load(
        "pages/project/project_detail.html",
        path="/projects/ui-detail",
        project=detail_project,
        todo_board=None,
        versions=[
            {
                "version": 2,
                "description": "历史版本",
                "timestamp": detail_project["created_at"],
            }
        ],
    )
    page.get_by_role("button", name="恢复此版本").click()
    dialog = page.get_by_role("dialog", name="恢复到 v2")
    dialog.get_by_role("button", name="恢复", exact=True).click()
    page.get_by_text("无法恢复此版本", exact=True).wait_for()
    assert dialog.is_visible()
    assert writes == [
        ("POST", "http://ui.test/api/projects/ui-detail/versions/2/restore")
    ]
    dialog.get_by_role("button", name="取消", exact=True).click()
