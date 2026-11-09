"""Template catalogues and selection use production bundles with isolated APIs."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, ui_page  # noqa: F401
from test_antd_admin_management_ui import select

SIZES = [(1440, 900), (1024, 768), (390, 844), (320, 568), (844, 390)]
HTML = '<html><body style="margin:0;width:1280px;height:720px;background:#17263e;color:white"><h1>Original preview</h1><p>{{title}}</p></body></html>'
TEMPLATES = [
    dict(
        id=i,
        template_name=name,
        description="可重复使用的简洁母版",
        tags=["商务", "学术"],
        user_id=1 if i != 2 else None,
        usage_count=i,
        created_by="about",
        is_default=False,
        html_template=HTML,
    )
    for i, name in enumerate(
        ["科研汇报母版", "公共母版", '<img src=x onerror="window.injected=true">'], 1
    )
]
PACKAGES = [
    dict(
        id=i + 10,
        template_id=i,
        template_name=name,
        description="展示描述",
        user_id=1 if i != 2 else None,
        editable=i == 1,
        status="draft" if i == 1 else "published",
        version=i,
        content_hash="original-hash",
        manifest=dict(
            package_id=f"package-{i}",
            name=name,
            description="历史描述",
            components=[
                dict(id="cover", family="cover", description="研究主题", html=HTML),
                dict(id="points", family="points", description="研究结论", html=HTML),
            ],
        ),
    )
    for i, name in enumerate(["科研模板包", "公共模板包", "业务模板包"], 1)
]


def template_api(page):
    state = dict(
        reads=[],
        writes=[],
        templates=[dict(item) for item in TEMPLATES],
        packages=[dict(item) for item in PACKAGES],
        default=2,
        total=15,
    )

    def api(route):
        req = route.request
        path = urlsplit(req.url).path
        query = parse_qs(urlsplit(req.url).query)
        method = req.method
        if method == "GET":
            state["reads"].append(req.url)
        else:
            body = (
                req.post_data_json
                if req.headers.get("content-type", "").startswith("application/json")
                else None
            )
            state["writes"].append((path, method, body, query))
        if "/preview/" in path:
            route.fulfill(
                body=HTML.replace("{{title}}", "示例模板包"), content_type="text/html"
            )
            return
        if path.endswith("/global-master-templates/") and method == "GET":
            size = int(query.get("page_size", ["6"])[0])
            target = int(query.get("page", ["1"])[0])
            total = state["total"]
            result = dict(
                templates=state["templates"],
                pagination=dict(
                    current_page=target,
                    total_count=total,
                    total_pages=max(1, (total + size - 1) // size),
                ),
            )
        elif path.endswith("/default/template"):
            result = dict(id=state["default"])
        elif path.endswith("/packages") and method == "GET":
            result = dict(packages=state["packages"])
        elif "/packages/" in path and path.endswith("/export"):
            route.fulfill(
                body='{"package_id":"sample"}', content_type="application/json"
            )
            return
        elif path.endswith("/generate"):
            result = dict(
                success=True,
                data=dict(
                    template_name="AI 母版",
                    description="结果说明",
                    tags=["AI"],
                    html_template=HTML,
                    raw_response="<script>window.injected=true</script>",
                    extra_field="keep",
                ),
            )
        elif path.endswith("/adjust-template"):
            result = dict(
                html_template=HTML.replace("Original preview", "Adjusted preview"),
                template_name="AI 母版",
                extra_field="adjusted",
            )
        elif path.endswith("/packages-generate"):
            events = [
                dict(type="progress", message="正在设计封面", current=1, total=3),
                dict(type="complete", package=PACKAGES[0], partial=True),
            ]
            route.fulfill(
                body="".join(
                    "data: " + json.dumps(item, ensure_ascii=False) + "\r\n\r\n"
                    for item in events
                ),
                content_type="text/event-stream",
            )
            return
        elif path.rsplit("/", 1)[-1].isdigit() or path.endswith("/preview"):
            ident = int(
                path.split("/")[-2]
                if path.endswith("/preview")
                else path.rsplit("/", 1)[-1]
            )
            result = next(
                (item for item in state["templates"] if item["id"] == ident),
                TEMPLATES[0],
            )
        else:
            result = dict(success=True)
        route.fulfill(json=result)

    page.route("**/api/global-master-templates/**", api)
    page.route("**/api/projects/*/select-template", api)
    page.route("**/api/projects/*/template-package", api)
    return state


def management(page, load, tab="regular", **kwargs):
    load(
        "pages/template/global_master_templates.html",
        path="/global-master-templates?tab=" + tab,
        **kwargs,
    )
    page.get_by_role("heading", name="模板管理", exact=True).wait_for()


def selection(page, load, mode="freeform", **kwargs):
    load(
        "pages/template/template_selection.html",
        path="/projects/ui-test/template-selection?mode=" + mode,
        project_id="ui-test",
        project_topic="可复用模板与生成方式",
        **kwargs,
    )
    page.get_by_role("heading", name="选择 PPT 模板", exact=True).wait_for()


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize(
    "scene",
    ["management", "packages", "selection", "package-selection", "edit", "generate"],
)
def test_catalogue_responsive_geometry_and_original_canvas(
    ui_page, width, height, scene
):
    page, load = ui_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size(dict(width=width, height=height))
    state = template_api(page)
    if scene in {"selection", "package-selection"}:
        selection(page, load, "package" if scene == "package-selection" else "freeform")
    else:
        management(page, load, "packages" if scene == "packages" else "regular")
    page.locator(".template-card").first.wait_for()
    if width >= 1100 and scene in {"management", "selection"}:
        search = page.get_by_role("searchbox", name="搜索模板").bounding_box()
        tag = page.get_by_role("combobox", name="模板标签").bounding_box()
        assert search["width"] <= 360 and abs(search["y"] - tag["y"]) < 4
    if scene == "edit":
        page.locator("#createTemplateBtn").click()
    elif scene == "generate":
        page.get_by_role("button", name="AI 生成模板", exact=True).click()
    if scene in {"edit", "generate"}:
        container = page.locator(".ant-modal-container")
        bounds = container.bounding_box()
        assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= height + 1
        save = page.get_by_role(
            "button", name="保存模板" if scene == "edit" else "开始生成模板", exact=True
        ).bounding_box()
        assert save["y"] >= 0 and save["y"] + save["height"] <= height + 1
    else:
        for card in page.locator(".template-card").all():
            assert card.evaluate("el => el.scrollWidth <= el.clientWidth + 1")
        frame = page.frame_locator(".template-preview-iframe").first
        expect(frame.get_by_role("heading", name="Original preview")).to_be_visible()
        assert (
            frame.locator("body").evaluate("el => getComputedStyle(el).width")
            == "1280px"
        )
        assert (
            frame.locator("body").evaluate("el => getComputedStyle(el).backgroundColor")
            == "rgb(23, 38, 62)"
        )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    assert not errors and not state["writes"]
    assert not page.evaluate("!!window.injected")


def test_regular_create_keeps_draft_after_failed_save_and_exact_payload(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load)
    page.locator("#createTemplateBtn").click()
    page.get_by_label("模板名称", exact=True).fill("紧凑模板")
    page.get_by_label("描述", exact=True).fill("说明")
    page.get_by_label("标签", exact=True).fill("商务, 学术,,")
    page.get_by_label("HTML 模板", exact=True).fill(HTML)
    page.get_by_label("设为默认模板", exact=True).check()
    page.route(
        "**/api/global-master-templates/",
        lambda route: (
            route.fulfill(status=500, json=dict(detail="保存暂时失败"))
            if route.request.method == "POST"
            else route.fallback()
        ),
    )
    page.get_by_role("button", name="保存模板", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("保存暂时失败")
    expect(page.get_by_label("模板名称", exact=True)).to_have_value("紧凑模板")
    page.unroute("**/api/global-master-templates/")
    page.get_by_role("button", name="保存模板", exact=True).click()
    page.locator(".template-editor-modal").wait_for(state="hidden")
    assert state["writes"][0][:3] == (
        "/api/global-master-templates/",
        "POST",
        dict(
            template_name="紧凑模板",
            description="说明",
            html_template=HTML,
            tags=["商务", "学术"],
            is_default=True,
        ),
    )


def test_failed_template_detail_blocks_save_until_retry(ui_page):
    page, load = ui_page
    template_api(page)
    management(page, load)
    page.route(
        "**/api/global-master-templates/1",
        lambda route: route.fulfill(status=503, json=dict(detail="详情不可用")),
    )
    page.locator('[data-template-id="1"]').get_by_role(
        "button", name="编辑", exact=True
    ).click()
    expect(page.get_by_role("button", name="保存模板", exact=True)).to_be_disabled()
    expect(page.locator(".template-editor-modal")).to_contain_text("详情不可用")
    page.unroute("**/api/global-master-templates/1")
    page.locator(".template-editor-modal").get_by_role(
        "button", name="重试", exact=True
    ).click()
    expect(page.get_by_label("模板名称", exact=True)).to_have_value("科研汇报母版")
    expect(page.get_by_role("button", name="保存模板", exact=True)).to_be_enabled()


def test_public_templates_do_not_expose_edit_delete_or_default_to_regular_user(ui_page):
    page, load = ui_page
    template_api(page)
    management(page, load, user=dict(id=1, username="ordinary", is_admin=False))
    public = page.locator('[data-template-id="2"]')
    expect(public.get_by_role("button", name="编辑", exact=True)).to_have_count(0)
    public.get_by_role("button", name="公共母版更多操作").click()
    assert page.get_by_role("menuitem").count() == 3
    for name in ["编辑", "删除", "设为默认"]:
        expect(page.get_by_role("menuitem", name=name, exact=True)).to_have_count(0)


def test_search_tag_page_size_and_failed_read_retry_keep_existing_rows(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load)
    page.get_by_role("searchbox", name="搜索模板").fill("科研")
    page.wait_for_function(
        '() => new URL(location.href).pathname === "/global-master-templates"'
    )
    page.wait_for_timeout(350)
    select(page, "模板标签", "学术")
    page.wait_for_timeout(50)
    assert any(
        parse_qs(urlsplit(url).query).get("search") == ["科研"]
        and parse_qs(urlsplit(url).query).get("tags") == ["学术"]
        for url in state["reads"]
    )
    page.route(
        "**/api/global-master-templates/?*",
        lambda route: route.fulfill(status=503, json=dict(detail="列表读取失败")),
    )
    page.get_by_role("button", name="刷新普通模板").click()
    expect(page.get_by_role("alert")).to_contain_text("列表读取失败")
    assert page.locator("[data-template-id]").count() == 3
    page.unroute("**/api/global-master-templates/?*")
    page.get_by_role("button", name="重试", exact=True).click()
    page.get_by_role("alert").wait_for(state="hidden")
    page.locator(".ant-pagination-item-2").click()
    expect(page.locator(".ant-pagination-item-2")).to_have_class(
        "ant-pagination-item ant-pagination-item-2 ant-pagination-item-active"
    )
    assert parse_qs(urlsplit(state["reads"][-1]).query)["page"] == ["2"]


@pytest.mark.parametrize("mode", ["global", "free", "default"])
def test_selection_contract_redirect_and_failure_preserves_choice(ui_page, mode):
    page, load = ui_page
    state = template_api(page)
    selection(page, load)
    if mode == "global":
        page.locator('[data-template-id="1"]').get_by_role(
            "button", name="选择", exact=True
        ).click()
    elif mode == "free":
        page.get_by_role("button", name="选择自由模板", exact=True).click()
    button = page.get_by_role(
        "button",
        name="使用默认模板" if mode == "default" else "开始生成 PPT",
        exact=True,
    )
    failure = lambda route: route.fulfill(
        status=409, json=dict(detail="选择失败，请重试")
    )
    page.route("**/api/projects/*/select-template", failure)
    button.click()
    expect(page.get_by_role("alert")).to_contain_text("选择失败，请重试")
    expect(button).to_be_enabled()
    page.unroute("**/api/projects/*/select-template", failure)
    button.click()
    page.wait_for_url("**/todo-editor?auto_start=true")
    assert state["writes"][0][:3] == (
        "/api/projects/ui-test/select-template",
        "POST",
        dict(
            project_id="ui-test",
            selected_template_id=1 if mode == "global" else None,
            template_mode=mode,
        ),
    )


@pytest.mark.parametrize("mode", ["package", "invalid"])
def test_template_tab_restores_query_and_package_preference(ui_page, mode):
    page, load = ui_page
    state = template_api(page)
    selection(
        page,
        load,
        mode,
        package_preference=dict(mode="package", version_id=13),
        package_notice="原先选择的版本已停用，请重新选择",
    )
    expect(
        page.get_by_role("tab", name="快速模式 · 模板包", exact=True)
    ).to_have_attribute("aria-selected", "true")
    assert (
        page.locator("[data-package-id]").first.get_attribute("data-package-id") == "13"
    )
    expect(page.get_by_role("alert")).to_contain_text("原先选择的版本已停用")
    page.get_by_role("tab", name="自由设计", exact=True).click()
    assert parse_qs(urlsplit(page.url).query)["mode"] == ["freeform"]
    assert not state["writes"]


def test_package_selection_only_published_and_exact_options(ui_page):
    page, load = ui_page
    state = template_api(page)
    selection(page, load, "package")
    expect(
        page.locator('[data-package-id="11"]').get_by_role(
            "button", name="使用此包生成"
        )
    ).to_be_disabled()
    page.get_by_label("自动配图", exact=True).uncheck()
    page.get_by_label("图片预算", exact=True).fill("4")
    page.locator('[data-package-id="12"]').get_by_role(
        "button", name="使用此包生成"
    ).click()
    page.wait_for_url("**/todo-editor?auto_start=true")
    assert state["writes"][0][:3] == (
        "/api/projects/ui-test/template-package",
        "POST",
        dict(version_id=12, options=dict(allow_images=False, image_budget=4)),
    )


def test_package_description_clear_preserves_published_manifest(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load, "packages")
    original = json.dumps(state["packages"][2]["manifest"])
    card = page.locator('[data-package-id="13"]')
    card.get_by_role("button", name="业务模板包更多操作").click()
    page.get_by_role("menuitem", name="编辑描述", exact=True).click()
    expect(page.get_by_label("模板包描述", exact=True)).to_have_value("展示描述")
    page.get_by_label("模板包描述", exact=True).fill("")
    page.get_by_role("dialog").get_by_role("button", name="保存", exact=True).click()
    page.get_by_role("dialog").wait_for(state="hidden")
    assert state["writes"][0][:3] == (
        "/api/global-master-templates/package-templates/3",
        "PATCH",
        dict(description=""),
    )
    assert json.dumps(state["packages"][2]["manifest"]) == original


def test_package_copy_and_draft_delete_have_distinct_contracts(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load, "packages")
    card = page.locator('[data-package-id="11"]')
    card.get_by_role("button", name="科研模板包更多操作").click()
    page.get_by_role("menuitem", name="复制为新模板包", exact=True).click()
    page.wait_for_timeout(50)
    manifest = state["writes"][0][2]["manifest"]
    assert (
        manifest["description"] == "展示描述"
        and manifest["components"] == PACKAGES[0]["manifest"]["components"]
    )
    card.get_by_role("button", name="科研模板包更多操作").click()
    page.get_by_role("menuitem", name="删除此草稿", exact=True).click()
    assert len(state["writes"]) == 1
    page.get_by_role("button", name="确认", exact=True).click()
    page.get_by_role("dialog").wait_for(state="hidden")
    assert state["writes"][-1][:3] == (
        "/api/global-master-templates/packages/11",
        "DELETE",
        None,
    )


@pytest.mark.parametrize(
    "mode", ["text_only", "reference_style", "exact_replica", "pptx_extract"]
)
def test_ai_template_generation_reference_payload_and_manual_save(ui_page, mode):
    page, load = ui_page
    state = template_api(page)
    management(page, load)
    page.get_by_role("button", name="AI 生成模板", exact=True).click()
    page.get_by_label("设计要求", exact=True).fill("黑白配色，紧凑科研汇报")
    page.get_by_label("AI 模板名称", exact=True).fill("AI 母版")
    labels = dict(
        text_only="纯文本",
        reference_style="参考风格",
        exact_replica="精确复刻",
        pptx_extract="提取 PPTX",
    )
    page.get_by_role("radio", name=labels[mode], exact=True).check()
    if mode != "text_only":
        page.get_by_role("dialog").locator("input[type=file]").set_input_files(
            dict(
                name="reference.pptx" if mode == "pptx_extract" else "reference.png",
                mimeType=(
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                    if mode == "pptx_extract"
                    else "image/png"
                ),
                buffer=b"fixture",
            )
        )
    page.get_by_role("button", name="开始生成模板", exact=True).click()
    expect(page.get_by_role("button", name="保存生成模板", exact=True)).to_be_visible()
    body = state["writes"][0][2]
    assert body["generation_mode"] == mode and body["template_name"] == "AI 母版"
    if mode == "pptx_extract":
        assert body["reference_pptx"]["filename"] == "reference.pptx"
    elif mode != "text_only":
        assert body["reference_images"][0] == body["reference_image"]
        assert body["reference_image"]["data"].startswith("data:image/png;base64,")
    assert len(state["writes"]) == 1
    page.get_by_role("button", name="保存生成模板", exact=True).click()
    page.get_by_role("dialog").wait_for(state="hidden")
    assert state["writes"][-1][0] == "/api/global-master-templates/save-generated"
    assert state["writes"][-1][2]["extra_field"] == "keep"
    assert not page.evaluate("!!window.injected")


def test_ai_adjustment_sends_generated_draft_and_remains_unsaved(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load)
    page.get_by_role("button", name="AI 生成模板", exact=True).click()
    page.get_by_label("设计要求", exact=True).fill("科研风格")
    page.get_by_label("AI 模板名称", exact=True).fill("AI 母版")
    page.get_by_role("button", name="开始生成模板", exact=True).click()
    page.get_by_label("调整意见", exact=True).fill("放大标题")
    page.get_by_role("button", name="调整模板", exact=True).click()
    expect(
        page.frame_locator('iframe[title="AI 生成模板预览"]').get_by_role(
            "heading", name="Adjusted preview"
        )
    ).to_be_visible()
    assert state["writes"][1][2]["template_data"]["extra_field"] == "keep"
    assert state["writes"][1][2]["adjustment"] == "放大标题"
    assert len(state["writes"]) == 2


def start_master_stream(page, load):
    state = template_api(page)
    management(page, load)
    page.evaluate("""() => {
      const original = window.fetch;
      window.masterRequests = [];
      window.masterAborts = 0;
      window.fetch = (url, options) => {
        if (!String(url).includes('/global-master-templates/generate?stream=true')) return original(url, options);
        window.masterRequests.push({url, headers: options.headers, body: JSON.parse(options.body)});
        return Promise.resolve(new Response(new ReadableStream({start(writer) {
          window.masterWriter = writer;
          options.signal.addEventListener('abort', () => {
            window.masterAborts++;
            writer.error(new DOMException('已取消', 'AbortError'));
          }, {once: true});
        }}), {headers: {'Content-Type': 'text/event-stream'}}));
      };
      window.masterEmit = item => window.masterWriter.enqueue(new TextEncoder().encode('data: ' + JSON.stringify(item) + '\\r\\n\\r\\n'));
    }""")
    page.get_by_role("button", name="AI 生成模板", exact=True).click()
    page.get_by_label("设计要求", exact=True).fill("黑白商务设计")
    page.get_by_label("AI 模板名称", exact=True).fill("流式母版")
    page.get_by_role("button", name="开始生成模板", exact=True).click()
    page.wait_for_function("window.masterRequests.length === 1")
    return state


@pytest.mark.parametrize("size", [(1440, 900), (390, 844)])
def test_master_stream_renders_partial_preview_then_requires_manual_save(ui_page, size):
    page, load = ui_page
    page.set_viewport_size(dict(zip(["width", "height"], size)))
    state = start_master_stream(page, load)
    partial = '<html><body style="margin:0;width:1280px;height:720px"><h1>流式预览</h1>'
    page.evaluate("html => {masterEmit({type:'thinking',content:html});masterEmit({type:'preview',html_template:html})}", partial)
    expect(page.frame_locator('iframe[title="AI 生成模板实时预览"]').get_by_role("heading", name="流式预览")).to_be_visible()
    assert not state["writes"]
    assert page.get_by_role("button", name="保存生成模板", exact=True).count() == 0
    page.get_by_text("查看实时响应", exact=True).click()
    expect(page.locator(".template-raw")).to_have_text(partial)
    payload = page.evaluate("masterRequests[0]")
    assert payload["headers"]["Accept"] == "text/event-stream"
    assert payload["body"]["template_name"] == "流式母版"
    # Complete a second snapshot without closing the HTTP stream: the complete
    # event, rather than EOF, unlocks saving and stops the reader.
    complete = dict(template_name="流式母版", html_template=partial.replace("流式预览", "最终母版") + "</body></html>")
    page.evaluate("data => masterEmit({type:'complete',...data})", complete)
    expect(page.frame_locator('iframe[title="AI 生成模板预览"]').get_by_role("heading", name="最终母版")).to_be_visible()
    expect(page.get_by_role("button", name="保存生成模板", exact=True)).to_be_enabled()
    assert not state["writes"]
    if size[0] == 1440:
        page.get_by_role("button", name="保存生成模板", exact=True).click()
        page.get_by_role("dialog").wait_for(state="hidden")
        assert state["writes"][0][0].endswith("/save-generated")
        assert state["writes"][0][2]["html_template"] == complete["html_template"]
    else:
        page.get_by_role("button", name="重新生成", exact=True).click()
        expect(page.get_by_role("region", name="模板生成进度")).to_have_count(0)
        expect(page.get_by_role("button", name="开始生成模板", exact=True)).to_be_enabled()


@pytest.mark.parametrize("end", ["error", "eof", "abort"])
def test_incomplete_master_stream_keeps_preview_but_cannot_be_saved_or_auto_retried(ui_page, end):
    page, load = ui_page
    state = start_master_stream(page, load)
    partial = '<html><body style="margin:0;width:1280px;height:720px"><h1>未完成预览</h1>'
    page.evaluate("html => masterEmit({type:'preview',html_template:html})", partial)
    expect(page.frame_locator('iframe[title="AI 生成模板实时预览"]').get_by_role("heading", name="未完成预览")).to_be_visible()
    if end == "abort":
        page.get_by_role("button", name="停止接收", exact=True).click()
        page.wait_for_function("masterAborts === 1")
    elif end == "eof":
        page.evaluate("masterWriter.close()")
        expect(page.get_by_role("alert")).to_contain_text("未收到完成确认")
    else:
        page.evaluate("masterEmit({type:'error',message:'模型连接中断'})")
        expect(page.get_by_role("alert")).to_contain_text("模型连接中断")
    expect(page.get_by_role("button", name="开始生成模板", exact=True)).to_be_enabled()
    assert page.get_by_role("button", name="保存生成模板", exact=True).count() == 0
    assert page.evaluate("masterRequests.length") == 1
    assert not state["writes"]
    expect(page.frame_locator('iframe[title="AI 生成模板实时预览"]').get_by_role("heading", name="未完成预览")).to_be_visible()


@pytest.mark.parametrize("complete", [True, False])
def test_package_sse_requires_completion_before_success(ui_page, complete):
    page, load = ui_page
    template_api(page)
    management(page, load, "packages")
    if not complete:
        page.route(
            "**/api/global-master-templates/packages-generate",
            lambda route: route.fulfill(
                body='data: {"type":"progress","message":"正在设计封面"}\n\n',
                content_type="text/event-stream",
            ),
        )
    page.get_by_role("button", name="AI 创建模板包", exact=True).click()
    page.get_by_label("模板包设计要求").fill("科研汇报，黑白配色")
    page.get_by_role("button", name="开始设计", exact=True).click()
    if complete:
        expect(page.get_by_role("dialog")).to_contain_text("可用部分已保存为草稿")
        expect(page.get_by_role("button", name="开始设计", exact=True)).to_have_count(0)
    else:
        expect(page.get_by_role("dialog")).to_contain_text("未收到完成确认")
        expect(page.get_by_role("button", name="开始设计", exact=True)).to_be_enabled()


def test_package_editor_is_lazy_and_existing_ai_controls_remain_visible(ui_page):
    page, load = ui_page
    template_api(page)
    page.set_viewport_size(dict(width=390, height=844))
    management(page, load, "packages")
    assert not page.evaluate("!!window.PackageWorkspace")
    page.locator('[data-package-id="11"]').get_by_role(
        "button", name="编辑草稿", exact=True
    ).click()
    workspace = page.locator(".package-ant-workspace")
    workspace.wait_for()
    for field in ["此页修改要求", "整套模板修改要求"]:
        if field == "整套模板修改要求":
            workspace.get_by_text("AI 编辑", exact=True).click()
        box = workspace.get_by_role("textbox", name=field, exact=True).bounding_box()
        assert box["y"] >= 0 and box["y"] + box["height"] <= 844
    workspace.get_by_role("button", name="关闭", exact=True).click()
    workspace.wait_for(state="detached")


def test_regular_json_export_and_html_import_preserve_content(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load)
    page.locator('[data-template-id="1"]').get_by_role(
        "button", name="科研汇报母版更多操作"
    ).click()
    with page.expect_download() as event:
        page.get_by_role("menuitem", name="导出 JSON", exact=True).click()
    assert event.value.suggested_filename.endswith(".json")
    page.locator("input[type=file]").set_input_files(
        dict(name="imported.html", mimeType="text/html", buffer=HTML.encode())
    )
    page.wait_for_timeout(100)
    assert state["writes"][0][2]["html_template"] == HTML
    assert state["writes"][0][2]["template_name"] == "imported"


def test_package_pptx_import_opens_existing_slot_analyser_without_ai_call(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load, "packages")
    page.get_by_role("button", name="从 PPTX 创建", exact=True).click()
    expect(
        page.get_by_role("dialog", name="从 PPTX 创建模板包", exact=True)
    ).to_be_visible()
    assert not state["writes"]


def test_package_reply_progress_arrives_before_completion_and_blocks_duplicates(
    ui_page,
):
    page, load = ui_page
    template_api(page)
    management(page, load, "packages")
    page.evaluate(
        """() => {
      const original = window.fetch; window.generationCalls = [];
      window.fetch = (url, options) => {
        if (!String(url).endsWith('/packages-generate')) return original(url, options);
        window.generationCalls.push(JSON.parse(options.body));
        return Promise.resolve(new Response(new ReadableStream({start(controller) {
          window.sendTemplateEvent = event => {
            const bytes = new TextEncoder().encode('data: ' + JSON.stringify(event) + '\\r\\n\\r\\n');
            for (let index = 0; index < bytes.length; index += 3) controller.enqueue(bytes.slice(index, index + 3));
          };
        }}), {headers: {'Content-Type':'text/event-stream'}}));
      };
    }"""
    )
    page.get_by_role("button", name="AI 创建模板包", exact=True).click()
    page.get_by_label("模板包设计要求").fill("科研汇报")
    page.get_by_role("button", name="开始设计", exact=True).click()
    page.wait_for_function("window.generationCalls.length === 1")
    page.evaluate(
        "window.sendTemplateEvent({type:'progress',message:'正在生成研究流程 😀',current:1,total:3})"
    )
    expect(page.get_by_role("dialog")).to_contain_text("正在生成研究流程 😀")
    expect(page.get_by_role("button", name="关闭", exact=True)).to_be_disabled()
    page.get_by_role("dialog").locator("form").evaluate(
        'form => form.dispatchEvent(new Event("submit", {bubbles:true,cancelable:true}))'
    )
    assert page.evaluate("window.generationCalls.length") == 1
    page.evaluate(
        'pkg => window.sendTemplateEvent({type:"complete",package:pkg})', PACKAGES[0]
    )
    expect(page.get_by_role("dialog")).to_contain_text("草稿已保存")


def test_stale_template_search_cannot_replace_newer_result(ui_page):
    page, load = ui_page
    template_api(page)
    management(page, load)
    page.evaluate(
        """() => {
      const original = window.fetch;
      window.fetch = (url, options) => {
        if (String(url).includes('search=old')) return new Promise(resolve => {
          window.finishOldSearch = () => resolve(new Response(JSON.stringify({templates:[{id:99,template_name:'过期结果',tags:[]}],pagination:{current_page:1,total_count:1,total_pages:1}}),{headers:{'Content-Type':'application/json'}}));
        });
        return original(url, options);
      };
    }"""
    )
    page.get_by_role("searchbox", name="搜索模板").fill("old")
    page.wait_for_function("!!window.finishOldSearch")
    page.get_by_role("searchbox", name="搜索模板").fill("new")
    page.wait_for_timeout(400)
    page.evaluate("window.finishOldSearch()")
    page.wait_for_timeout(50)
    expect(page.get_by_role("heading", name="过期结果")).to_have_count(0)
    expect(page.get_by_role("heading", name="科研汇报母版", exact=True)).to_be_visible()


def test_json_and_zip_package_import_keep_original_manifest_and_multipart(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load, "packages")
    payload = json.dumps(PACKAGES[0]["manifest"]).encode()
    page.locator("input[type=file]").set_input_files(
        dict(name="sample.json", mimeType="application/json", buffer=payload)
    )
    page.wait_for_timeout(100)
    assert state["writes"][0][:3] == (
        "/api/global-master-templates/packages",
        "POST",
        dict(manifest=PACKAGES[0]["manifest"]),
    )
    with page.expect_request(
        "**/api/global-master-templates/packages-import"
    ) as pending:
        page.locator("input[type=file]").set_input_files(
            dict(name="sample.zip", mimeType="application/zip", buffer=b"zip-fixture")
        )
    assert pending.value.headers["content-type"].startswith(
        "multipart/form-data; boundary="
    )
    assert 'filename="sample.zip"' in pending.value.post_data
    page.wait_for_timeout(50)
    assert state["writes"][-1][:2] == (
        "/api/global-master-templates/packages-import",
        "POST",
    )


def test_pptx_export_reuses_existing_renderer_and_original_canvas(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load)
    page.evaluate(
        """() => { window.domToPptx = {
      __landpptPatchVersion: '2026-09-11-svg-native-v1',
      exportToPptx: async (slides, options) => {
        window.pptxOptions = options; window.pptxSlides = [];
        for await (const body of slides) window.pptxSlides.push({text:body.textContent,width:getComputedStyle(body).width});
      }
    }; }"""
    )
    page.locator('[data-template-id="1"]').get_by_role(
        "button", name="科研汇报母版更多操作"
    ).click()
    page.get_by_role("menuitem", name="导出 PPTX", exact=True).click()
    page.wait_for_function("window.pptxSlides?.length === 1")
    assert page.evaluate("window.pptxSlides[0].width") == "1280px"
    assert "Original preview" in page.evaluate("window.pptxSlides[0].text")
    assert page.evaluate("window.pptxOptions") == dict(
        fileName="科研汇报母版_PPTX模板.pptx",
        autoEmbedFonts=True,
        svgAsVector=False,
        slideNotes=[],
    )
    assert not state["writes"]


@pytest.mark.parametrize("width,height", SIZES)
def test_selection_actions_are_reachable_without_scrolling(ui_page, width, height):
    page, load = ui_page
    template_api(page)
    page.set_viewport_size(dict(width=width, height=height))
    selection(page, load)
    for name in ["使用默认模板", "开始生成 PPT"]:
        rect = page.get_by_role("button", name=name, exact=True).bounding_box()
        assert rect["y"] >= 0 and rect["y"] + rect["height"] <= height + 1
    assert page.evaluate("scrollY") == 0


def test_html_preview_scripts_are_isolated_from_application(ui_page):
    page, load = ui_page
    state = template_api(page)
    state["templates"][0]["html_template"] = (
        HTML
        + '<script>document.body.style.color="rgb(1,2,3)";try {parent.injected=true}catch{}</script>'
    )
    management(page, load)
    frame = page.frame_locator('[data-template-id="1"] iframe')
    expect(frame.get_by_role("heading", name="Original preview")).to_be_visible()
    assert (
        frame.locator("body").evaluate("el => getComputedStyle(el).color")
        == "rgb(1, 2, 3)"
    )
    assert not page.evaluate("!!window.injected")


@pytest.mark.parametrize(
    "status,body",
    [
        (402, {"detail": "余额不足"}),
        (200, {"status": "error", "message": "创建失败"}),
        (200, {"type": "error", "message": "模型生成失败"}),
    ],
)
def test_package_generation_errors_keep_prompt_and_never_report_saved(
    ui_page, status, body
):
    page, load = ui_page
    template_api(page)
    management(page, load, "packages")
    page.route(
        "**/api/global-master-templates/packages-generate",
        lambda route: route.fulfill(status=status, json=body),
    )
    page.get_by_role("button", name="AI 创建模板包", exact=True).click()
    page.get_by_label("模板包设计要求").fill("保留输入以便重试")
    page.get_by_role("button", name="开始设计", exact=True).click()
    expect(page.get_by_role("dialog").get_by_role("alert")).to_contain_text(
        body.get("detail", body.get("message"))
    )
    expect(page.get_by_label("模板包设计要求")).to_have_value("保留输入以便重试")
    expect(page.get_by_role("button", name="开始设计", exact=True)).to_be_enabled()
    expect(page.get_by_role("dialog")).not_to_contain_text("草稿已保存")


def test_package_public_actions_and_failed_read_are_bounded(ui_page):
    page, load = ui_page
    state = template_api(page)
    management(page, load, "packages")
    public = page.locator('[data-package-id="12"]')
    public.get_by_role("button", name="公共模板包更多操作").click()
    assert page.get_by_role("menuitem").count() == 2
    for name in ["删除模板包", "重命名", "编辑描述", "停用此版本"]:
        expect(page.get_by_role("menuitem", name=name, exact=True)).to_have_count(0)
    page.get_by_role("menuitem", name="导出模板包", exact=True).focus()
    page.keyboard.press("Escape")
    expect(public.get_by_role("button", name="公共模板包更多操作")).to_be_focused()
    failure = lambda route: route.fulfill(status=503, json={"detail": "模板包暂不可用"})
    page.route("**/api/global-master-templates/packages", failure)
    page.get_by_role("button", name="刷新模板包").click()
    expect(page.get_by_role("alert")).to_contain_text("模板包暂不可用")
    assert page.locator("[data-package-id]").count() == 3
    page.unroute("**/api/global-master-templates/packages", failure)
    page.get_by_role("button", name="重新加载", exact=True).click()
    page.get_by_role("alert").wait_for(state="hidden")
    assert not state["writes"]


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize(
    "scene", ["preview", "generate", "package-preview", "package-generate"]
)
def test_template_dialog_returns_focus_to_its_trigger(ui_page, width, height, scene):
    page, load = ui_page
    template_api(page)
    page.set_viewport_size(dict(width=width, height=height))
    management(page, load, "packages" if scene.startswith("package-") else "regular")
    if scene.endswith("preview"):
        trigger = page.locator(
            '[data-package-id="11"]'
            if scene.startswith("package-")
            else '[data-template-id="1"]'
        ).get_by_role("button", name="预览", exact=True)
    else:
        trigger = page.get_by_role(
            "button",
            name="AI 创建模板包" if scene.startswith("package-") else "AI 生成模板",
            exact=True,
        )
    for _ in range(2):
        trigger.click()
        page.get_by_role("dialog").wait_for()
        page.keyboard.press("Escape")
        page.get_by_role("dialog").wait_for(state="hidden")
        expect(trigger).to_be_focused()
