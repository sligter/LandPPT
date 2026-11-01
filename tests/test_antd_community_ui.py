"""Community administration contracts against built assets and isolated APIs."""

from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from test_app_ui import browser, ui_page  # noqa: F401
from test_antd_admin_management_ui import select


SYSTEM = dict(
    default_ai_provider="landppt",
    landppt_model="MODEL1",
    landppt_base_url="",
    landppt_api_key="",
    max_tokens=16384,
    temperature=0.7,
    top_p=1,
    llm_timeout_seconds=600,
    parallel_slides_count=3,
    research_provider="tavily",
    enable_parallel_generation=True,
    enable_per_slide_creative_guidance=True,
    tavily_api_key="",
    tavily_base_url="https://api.tavily.com",
    tavily_max_results=10,
    tavily_search_depth="advanced",
    deepseek_api_key="",
    deepseek_base_url="https://api.deepseek.com",
    deepseek_max_results=10,
    deepseek_timeout=30,
    searxng_host="",
    searxng_max_results=10,
    searxng_language="auto",
    searxng_timeout=30,
    research_max_content_length=5000,
    research_extraction_timeout=30,
    research_enable_content_extraction=True,
    tts_voice_zh="zh-CN-XiaoxiaoNeural",
    tts_voice_en="en-US-JennyNeural",
    comfyui_base_url="http://127.0.0.1:8188",
    comfyui_tts_workflow_path="tests/Qwen3-TD-TTS.json",
    comfyui_tts_timeout_seconds=600,
    comfyui_tts_chunk_chars=120,
    comfyui_tts_force_precision="",
    mineru_base_url="https://mineru.net/api/v4",
    mineru_api_key="",
    apryse_license_key="",
    enable_apryse_pptx_export=False,
)
SETTINGS = dict(
    daily_checkin_enabled=True,
    daily_checkin_reward_mode="random",
    daily_checkin_reward_fixed=5,
    daily_checkin_reward_min=2,
    daily_checkin_reward_max=8,
    invite_code_required_for_registration=True,
    sponsor_page_enabled=True,
    site_notice_enabled=True,
    site_notice_level="warning",
    site_notice_title="运营公告",
    site_notice_message="示例公告内容",
    site_notice_start_at=None,
    site_notice_end_at=None,
)
INVITES = [
    dict(
        id=1,
        code="INVITE-UNUSED",
        channel="universal",
        credits_amount=5,
        used_count=0,
        max_uses=2,
        expires_at=None,
        is_active=True,
        description="测试渠道",
    ),
    dict(
        id=2,
        code="INVITE-USED",
        channel="github",
        credits_amount=0,
        used_count=1,
        max_uses=1,
        expires_at=None,
        is_active=True,
        description=None,
    ),
]
SPONSORS = [
    dict(
        id=1,
        nickname="示例赞助者",
        bio="长期支持",
        amount="¥100",
        sort_order=1,
        note="年度赞助",
        avatar_url=None,
        link_url="https://example.invalid",
        is_active=True,
    ),
    dict(
        id=2,
        nickname="隐藏赞助者",
        bio=None,
        amount=None,
        sort_order=2,
        note=None,
        avatar_url=None,
        link_url="javascript:alert(1)",
        is_active=False,
    ),
]
SIZES = [(1440, 900), (1024, 768), (390, 844), (320, 568), (844, 390)]


def community(page, load, tab="system-defaults", system=None, settings=None, **values):
    reads, writes = [], []

    def api(route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "GET":
            reads.append(request.url)
            if path == "/api/config/system":
                result = dict(success=True, config=SYSTEM if system is None else system)
            elif path == "/admin/api/community/settings":
                result = dict(
                    success=True, settings=SETTINGS if settings is None else settings
                )
            elif path == "/admin/api/invite-codes":
                query = parse_qs(urlsplit(request.url).query)
                result = dict(
                    success=True,
                    items=INVITES,
                    total=41,
                    page=int(query.get("page", [1])[0]),
                )
            else:
                result = dict(success=True, items=SPONSORS)
        else:
            writes.append((request.method, path, request.post_data_json))
            result = dict(
                success=True,
                items=[INVITES[0]],
                models=["MODEL2", "MODEL1"],
                response_preview="fixture response",
            )
        route.fulfill(json=result)

    page.route("**/admin/api/**", api)
    page.route("**/api/config/system", api)
    page.route("**/api/ai/providers/test", api)
    load("pages/admin/community.html", path="/admin/community#" + tab, **values)
    page.get_by_role("heading", name="运营设置", exact=True).wait_for()
    return reads, writes


def test_system_preserves_every_legacy_field_and_saved_fallback(ui_page):
    page, load = ui_page
    saved = {
        **SYSTEM,
        "default_ai_provider": "gemini",
        "max_tokens": "8192",
        "enable_parallel_generation": "false",
        "mineru_api_key": "stored-key",
    }
    reads, writes = community(page, load, system=saved)
    catalogue = page.evaluate(
        """() => [...document.querySelector('#communityBlueprint')
        .content.querySelectorAll('.system-config-block [name]')].map(e=>e.name)"""
    )
    assert set(catalogue) == set(SYSTEM)
    assert len(catalogue) == 38
    for name in catalogue:
        assert page.locator("#system_" + name).count() == 1, name
    page.locator("#system_max_tokens").fill("")
    page.locator("#system_tavily_base_url").fill("")
    page.locator("#system_mineru_api_key").fill("")
    page.locator("#system_comfyui_tts_workflow_path").fill("")
    page.locator("#saveSystemDefaultsBtn").click()
    page.get_by_text("系统默认配置已保存", exact=True).wait_for()
    assert writes == [
        (
            "POST",
            "/api/config/system",
            {
                "config": {
                    **SYSTEM,
                    "default_ai_provider": "google",
                    "max_tokens": 8192,
                    "enable_parallel_generation": False,
                    "comfyui_tts_workflow_path": "",
                }
            },
        )
    ]


def test_system_failed_save_keeps_values_and_retry(ui_page):
    page, load = ui_page
    community(page, load)
    writes = []

    def save(route):
        writes.append(route.request.post_data_json)
        route.fulfill(
            status=503 if len(writes) == 1 else 200,
            json={"detail": "保存暂时失败"} if len(writes) == 1 else {"success": True},
        )

    page.route("**/api/config/system", save)
    page.locator("#system_max_tokens").fill("4096")
    page.locator("#saveSystemDefaultsBtn").click()
    page.get_by_text("保存暂时失败", exact=True).wait_for()
    assert page.locator("#system_max_tokens").input_value() == "4096"
    page.locator("#saveSystemDefaultsBtn").click()
    page.get_by_text("系统默认配置已保存", exact=True).wait_for()
    assert writes == [{"config": {**SYSTEM, "max_tokens": 4096}}] * 2


@pytest.mark.parametrize(
    "tab,endpoint,key,button",
    [
        ("system-defaults", "/api/config/system", "config", "保存系统默认配置"),
        ("notice", "/admin/api/community/settings", "settings", "保存全部运营配置"),
    ],
)
def test_read_failure_blocks_save_and_retry_restores_settings(
    ui_page, tab, endpoint, key, button
):
    page, load = ui_page
    reads, writes = community(page, load, tab)
    calls = []

    def read(route):
        calls.append(route.request.method)
        route.fulfill(
            status=500 if len(calls) == 1 else 200,
            json=(
                {"detail": "读取暂时失败"}
                if len(calls) == 1
                else {"success": True, key: SYSTEM if key == "config" else SETTINGS}
            ),
        )

    page.route("**" + endpoint, read)
    page.reload(wait_until="networkidle")
    page.get_by_text("读取暂时失败", exact=True).wait_for()
    save = page.get_by_role("button", name=button, exact=True)
    assert save.is_disabled()
    page.get_by_role("button", name="重试", exact=True).click()
    page.wait_for_function(
        "!document.querySelector('.settings-savebar .ant-btn-primary').disabled"
    )
    assert calls == ["GET", "GET"]
    assert not writes


def test_system_pending_read_does_not_overwrite_edits(ui_page):
    page, load = ui_page
    page.add_init_script(
        """const oldFetch=window.fetch;window.fetch=(url,options)=>
      url==='/api/config/system'&&(!options||options.method==='GET')?
      new Promise(resolve=>window.releaseSystem=data=>resolve(new Response(JSON.stringify(data)))):
      oldFetch(url,options);"""
    )
    community(page, load)
    page.locator("#system_landppt_model").fill("typed-before-response")
    assert page.locator("#saveSystemDefaultsBtn").is_disabled()
    page.evaluate("data=>window.releaseSystem({success:true,config:data})", SYSTEM)
    page.wait_for_function("!document.querySelector('#saveSystemDefaultsBtn').disabled")
    assert (
        page.locator("#system_landppt_model").input_value() == "typed-before-response"
    )


def test_models_use_current_credentials_cache_and_preserve_custom_model(ui_page):
    page, load = ui_page
    reads, writes = community(page, load)
    page.locator("#system_landppt_api_key").fill("typed-key")
    page.locator("#system_landppt_base_url").fill("https://model.example.invalid/v1")
    page.locator("#system_landppt_model").fill("custom-model")
    page.get_by_role("button", name="加载 LandPPT 模型", exact=True).click()
    page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(
        has_text="MODEL1"
    ).wait_for()
    assert page.locator("#system_landppt_model").input_value() == "custom-model"
    page.keyboard.press("Escape")
    page.get_by_role("button", name="加载 LandPPT 模型", exact=True).click()
    assert len(writes) == 1
    page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(
        has_text="MODEL2"
    ).click()
    page.get_by_role("button", name="测试 LandPPT", exact=True).click()
    page.locator(".admin-test-result").get_by_text("fixture response").wait_for()
    assert writes == [
        (
            "POST",
            "/admin/api/system-landppt-models",
            {"api_key": "typed-key", "base_url": "https://model.example.invalid/v1"},
        ),
        (
            "POST",
            "/api/ai/providers/test",
            {
                "provider": "landppt",
                "api_key": "typed-key",
                "base_url": "https://model.example.invalid/v1",
                "model": "MODEL2",
            },
        ),
    ]
    page.locator("#system_landppt_api_key").fill("second-key")
    page.get_by_role("button", name="加载 LandPPT 模型", exact=True).click()
    page.locator(".ant-select-dropdown:visible").wait_for()
    assert writes[-1][2]["api_key"] == "second-key"


def test_initial_models_read_does_not_open_popup_or_replace_model(ui_page):
    page, load = ui_page
    reads, writes = community(
        page,
        load,
        system={
            **SYSTEM,
            "landppt_api_key": "saved-key",
            "landppt_base_url": "https://model.example.invalid",
            "landppt_model": "saved-model",
        },
    )
    assert len(writes) == 1
    assert writes[0][1] == "/admin/api/system-landppt-models"
    assert page.locator(".ant-select-dropdown:visible").count() == 0
    assert page.locator("#system_landppt_model").input_value() == "saved-model"


def test_hidden_operating_fields_and_local_dates_are_preserved_across_tabs(ui_page):
    page, load = ui_page
    reads, writes = community(page, load, "notice")
    page.get_by_label("公告标题", exact=True).fill("  更新公告  ")
    page.get_by_label("开始时间", exact=True).fill("2026-10-11T10:30")
    expected_date = page.evaluate(
        "Math.floor(new Date('2026-10-11T10:30').getTime()/1000)"
    )
    page.get_by_role("tab", name="每日签到", exact=True).click()
    page.get_by_label("随机最大积分", exact=True).fill("10")
    page.get_by_role("tab", name="邀请码注册", exact=True).click()
    page.get_by_role("button", name="保存全部运营配置", exact=True).click()
    page.get_by_text("运营配置已保存", exact=True).wait_for()
    assert writes == [
        (
            "POST",
            "/admin/api/community/settings",
            {
                **SETTINGS,
                "site_notice_title": "更新公告",
                "site_notice_start_at": expected_date,
                "daily_checkin_reward_max": 10,
            },
        )
    ]
    assert page.evaluate("location.hash") == "#invites"
    page.evaluate("location.hash='notice'")
    assert page.get_by_label("公告标题", exact=True).input_value() == "  更新公告  "


def test_notice_preview_renders_text_without_injecting_markup(ui_page):
    page, load = ui_page
    community(page, load, "notice")
    page.get_by_label("公告内容", exact=True).fill(
        '<img src=x onerror="window.injected=true">'
    )
    assert (
        page.locator(".community-preview")
        .get_by_text('<img src=x onerror="window.injected=true">', exact=True)
        .is_visible()
    )
    assert not page.evaluate("window.injected || false")


def test_operating_save_failure_retains_hidden_settings_for_retry(ui_page):
    page, load = ui_page
    community(page, load, "notice")
    writes = []

    def save(route):
        writes.append(route.request.post_data_json)
        route.fulfill(
            status=500 if len(writes) == 1 else 200,
            json={"detail": "公告保存失败"} if len(writes) == 1 else {"success": True},
        )

    page.route("**/admin/api/community/settings", save)
    page.get_by_label("公告标题", exact=True).fill("新公告")
    button = page.get_by_role("button", name="保存全部运营配置", exact=True)
    button.click()
    page.get_by_text("公告保存失败", exact=True).wait_for()
    assert page.get_by_label("公告标题", exact=True).input_value() == "新公告"
    button.click()
    page.get_by_text("运营配置已保存", exact=True).wait_for()
    assert writes == [{**SETTINGS, "site_notice_title": "新公告"}] * 2


def test_model_error_can_retry_without_discarding_credentials(ui_page):
    page, load = ui_page
    community(page, load)
    attempts = []

    def models(route):
        attempts.append(route.request.post_data_json)
        route.fulfill(
            json=(
                {"success": False, "error": "模型暂不可用"}
                if len(attempts) == 1
                else {"success": True, "models": ["MODEL1"]}
            )
        )

    page.route("**/admin/api/system-landppt-models", models)
    page.locator("#system_landppt_api_key").fill("retry-key")
    button = page.get_by_role("button", name="加载 LandPPT 模型", exact=True)
    button.click()
    page.get_by_text("模型暂不可用", exact=True).wait_for()
    assert page.locator("#system_landppt_api_key").input_value() == "retry-key"
    button.click()
    page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter(
        has_text="MODEL1"
    ).wait_for()
    assert attempts == [{"api_key": "retry-key", "base_url": ""}] * 2


def test_sponsors_read_failure_retries_without_writes(ui_page):
    page, load = ui_page
    community(page, load, "sponsors")
    reads = []

    def read(route):
        reads.append(route.request.method)
        route.fulfill(
            status=500 if len(reads) == 1 else 200,
            json=(
                {"detail": "赞助名单读取失败"}
                if len(reads) == 1
                else {"success": True, "items": SPONSORS}
            ),
        )

    page.route("**/admin/api/sponsors", read)
    page.get_by_role("button", name="刷新名单", exact=True).click()
    page.get_by_text("赞助名单读取失败", exact=True).wait_for()
    assert page.get_by_role("button", name="编辑 示例赞助者", exact=True).is_visible()
    page.locator(".community-sponsors").get_by_role(
        "button", name="重试", exact=True
    ).click()
    page.get_by_text("赞助名单读取失败", exact=True).wait_for(state="hidden")
    assert reads == ["GET", "GET"]


def test_invite_create_failure_preserves_fields_and_success_resets(ui_page):
    page, load = ui_page
    community(page, load, "invites")
    writes = []

    def create(route):
        if route.request.method == "GET":
            route.fallback()
            return
        writes.append(route.request.post_data_json)
        route.fulfill(
            status=500 if len(writes) == 1 else 200,
            json=(
                {"detail": "生成暂时失败"}
                if len(writes) == 1
                else {"success": True, "items": [INVITES[0]]}
            ),
        )

    page.route("**/admin/api/invite-codes", create)
    page.get_by_label("生成数量", exact=True).fill("3")
    page.get_by_label("赠送积分", exact=True).fill("12")
    page.get_by_label("最大使用次数", exact=True).fill("2")
    page.get_by_label("备注（可选）", exact=True).fill("  客户注册  ")
    select(page, "注册渠道", "GitHub")
    page.get_by_role("button", name="生成邀请码", exact=True).click()
    page.get_by_text("生成暂时失败", exact=True).wait_for()
    assert page.get_by_label("生成数量", exact=True).input_value() == "3"
    page.get_by_role("button", name="生成邀请码", exact=True).click()
    page.get_by_text("本次生成 1 个邀请码", exact=True).wait_for()
    assert page.get_by_label("生成数量", exact=True).input_value() == "5"
    assert (
        writes
        == [
            dict(
                count=3,
                channel="github",
                credits_amount=12,
                max_uses=2,
                description="客户注册",
                expires_in_days=None,
            )
        ]
        * 2
    )
    assert (
        page.get_by_role("link", name="导出 CSV").get_attribute("href")
        == "/admin/api/invite-codes/export"
    )


def test_invite_toggle_uses_patch_and_used_delete_is_blocked(ui_page):
    page, load = ui_page
    reads, writes = community(page, load, "invites")
    assert page.get_by_role("button", name="删除 INVITE-USED", exact=True).is_disabled()
    page.get_by_role("button", name="停用 INVITE-UNUSED", exact=True).click()
    page.get_by_text("邀请码状态已更新", exact=True).wait_for()
    assert writes == [("PATCH", "/admin/api/invite-codes/1", {"is_active": False})]


@pytest.mark.parametrize(
    "tab,button,title,endpoint",
    [
        ("invites", "删除 INVITE-UNUSED", "删除邀请码", "/admin/api/invite-codes/1"),
        ("sponsors", "删除 示例赞助者", "删除赞助信息", "/admin/api/sponsors/1"),
    ],
)
def test_delete_confirmation_failure_keeps_dialog_for_retry(
    ui_page, tab, button, title, endpoint
):
    page, load = ui_page
    community(page, load, tab)
    writes = []

    def remove(route):
        writes.append(route.request.method)
        route.fulfill(
            status=500 if len(writes) == 1 else 200,
            json={"detail": "删除暂时失败"} if len(writes) == 1 else {"success": True},
        )

    page.route("**" + endpoint, remove)
    trigger = page.get_by_role("button", name=button, exact=True)
    trigger.click()
    dialog = page.get_by_role("dialog", name=title, exact=True)
    dialog.get_by_role("button", name="确认", exact=True).click()
    page.get_by_text("删除暂时失败", exact=True).first.wait_for()
    assert dialog.is_visible()
    dialog.get_by_role("button", name="确认", exact=True).click()
    dialog.wait_for(state="hidden")
    assert writes == ["DELETE", "DELETE"]


def test_invite_page_size_and_pagination_retain_original_parameters(ui_page):
    page, load = ui_page
    reads, writes = community(page, load, "invites")
    page.get_by_title("2", exact=True).click()
    page.wait_for_function(
        "document.querySelector('.ant-pagination-item-2').classList.contains('ant-pagination-item-active')"
    )
    assert parse_qs(urlsplit(reads[-1]).query) == {"page_size": ["20"], "page": ["2"]}
    select(page, "每页数量", "50 / 页")
    page.get_by_title("1", exact=True).wait_for()
    page.wait_for_timeout(100)
    assert parse_qs(urlsplit(reads[-1]).query) == {"page_size": ["50"], "page": ["1"]}
    assert not writes


@pytest.mark.parametrize("edit", [False, True])
def test_sponsor_save_failure_keeps_inputs_and_exact_nullable_payload(ui_page, edit):
    page, load = ui_page
    community(page, load, "sponsors")
    writes = []

    def save(route):
        if route.request.method == "GET":
            route.fallback()
            return
        writes.append((route.request.method, route.request.post_data_json))
        route.fulfill(
            status=500 if len(writes) == 1 else 200,
            json={"detail": "赞助保存失败"} if len(writes) == 1 else {"success": True},
        )

    page.route("**/admin/api/sponsors**", save)
    page.get_by_role(
        "button", name="编辑 示例赞助者" if edit else "新增赞助", exact=True
    ).click()
    dialog = page.get_by_role(
        "dialog", name="编辑赞助" if edit else "新增赞助", exact=True
    )
    dialog.get_by_label("昵称", exact=True).fill("  新赞助者  ")
    dialog.get_by_label("赞助金额", exact=True).fill("¥200")
    dialog.get_by_label("排序值", exact=True).fill("3")
    for label in ["头像 URL", "主页 URL", "简介", "备注"]:
        dialog.get_by_label(label, exact=True).fill("")
    dialog.get_by_label("公开展示", exact=True).uncheck()
    dialog.get_by_role("button", name="保存赞助", exact=True).click()
    dialog.get_by_text("赞助保存失败", exact=True).wait_for()
    assert dialog.get_by_label("昵称", exact=True).input_value() == "  新赞助者  "
    dialog.get_by_role("button", name="保存赞助", exact=True).click()
    dialog.wait_for(state="hidden")
    expected = dict(
        nickname="新赞助者",
        amount="¥200",
        sort_order=3,
        is_active=False,
        avatar_url=None,
        link_url=None,
        bio=None,
        note=None,
    )
    assert writes == [("PUT" if edit else "POST", expected)] * 2


def test_sponsors_do_not_render_unsafe_links_or_change_get_parameters(ui_page):
    page, load = ui_page
    reads, writes = community(page, load, "sponsors")
    assert [url for url in reads if "/sponsors" in url] == [
        "http://ui.test/admin/api/sponsors"
    ]
    assert page.locator('.community-sponsors a[href^="javascript:"]').count() == 0
    link = page.get_by_role("link", name="访问主页", exact=True)
    assert link.get_attribute("href") == "https://example.invalid/"
    assert "noopener" in link.get_attribute("rel")
    assert not writes


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize(
    "tab", ["system-defaults", "notice", "checkin", "invites", "sponsors"]
)
def test_community_all_tabs_fit_viewport_without_errors_or_writes(
    ui_page, width, height, tab
):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=height))
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    reads, writes = community(page, load, tab)
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    assert not errors
    assert not writes
    if tab in ["invites", "sponsors"]:
        assert page.locator(
            ".account-mobile-list" if width <= 900 else ".account-table"
        ).is_visible()


@pytest.mark.parametrize("width,height", SIZES)
def test_sponsor_dialog_bounds_keyboard_focus_and_restoration(ui_page, width, height):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=height))
    community(page, load, "sponsors")
    trigger = page.get_by_role("button", name="新增赞助", exact=True)
    trigger.click()
    dialog = page.get_by_role("dialog", name="新增赞助", exact=True)
    save = dialog.get_by_role("button", name="保存赞助", exact=True)
    box = save.bounding_box()
    assert 0 <= box["y"] and box["y"] + box["height"] <= height
    for _ in range(20):
        page.keyboard.press("Tab")
        assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
    page.keyboard.press("Escape")
    dialog.wait_for(state="hidden")
    assert trigger.evaluate("e=>e===document.activeElement")
    assert page.evaluate("document.documentElement.scrollWidth") <= width


@pytest.mark.parametrize("user", [None, dict(username="member", is_admin=False)])
def test_non_admin_has_no_community_reads_or_writes(ui_page, user):
    page, load = ui_page
    reads = []
    page.route(
        "**/admin/api/**",
        lambda route: (
            reads.append(route.request.url),
            route.fulfill(json={"success": True}),
        ),
    )
    load("pages/admin/community.html", path="/admin/community", user=user)
    page.get_by_text("需要管理员权限", exact=True).wait_for()
    assert not reads


def test_disabled_credits_keeps_operating_controls_and_hides_credit_navigation(ui_page):
    page, load = ui_page
    reads, writes = community(page, load, "invites", credits_enabled=False)
    assert page.get_by_text(
        "积分系统未启用，签到奖励与邀请码赠分暂不生效。", exact=True
    ).is_visible()
    assert page.get_by_label("赠送积分", exact=True).is_visible()
    assert page.locator('.admin-navigation a[href="/admin/credits"]').count() == 0
    assert not writes


def test_mobile_secondary_actions_keep_save_visible_in_one_row(ui_page):
    page, load = ui_page
    page.set_viewport_size(dict(width=320, height=568))
    reads, writes = community(page, load)
    save = page.locator("#saveSystemDefaultsBtn")
    more = page.get_by_role("button", name="更多", exact=True)
    assert save.bounding_box()["y"] == more.bounding_box()["y"]
    assert page.locator(".system-config-block").first.bounding_box()["y"] < 568
    more.click()
    page.get_by_role("menuitem", name="测试 LandPPT", exact=True).click()
    page.locator(".admin-test-result").wait_for()
    assert writes == [
        (
            "POST",
            "/api/ai/providers/test",
            {
                "provider": "landppt",
                "api_key": "",
                "base_url": "",
                "model": "MODEL1",
            },
        )
    ]


@pytest.mark.parametrize("enabled", [False, True])
def test_admin_can_preview_sponsors_before_publishing(ui_page, enabled):
    page, load = ui_page
    reads, writes = community(
        page, load, "sponsors", settings={**SETTINGS, "sponsor_page_enabled": enabled}
    )
    preview = page.get_by_role("link", name="预览感谢页", exact=True)
    expect(preview).to_be_enabled()
    assert preview.get_attribute("href") == "/sponsors"
    expect(page.get_by_text("名单与页面开关分别保存", exact=True)).to_be_visible()
    assert not writes


@pytest.mark.parametrize("enabled", [False, True])
def test_saved_sponsor_visibility_updates_footer_without_reload(ui_page, enabled):
    page, load = ui_page
    public = {"sponsor_page_enabled": not enabled, "site_notice": None}
    page.route("**/api/community/public-settings", lambda route: route.fulfill(json=public))
    community(page, load, "sponsors", settings={**SETTINGS, "sponsor_page_enabled": not enabled})
    footer = page.locator("#navSponsorLink")
    expect(footer).to_have_text("赞助预览" if enabled else "赞助感谢")
    page.evaluate("window.sponsorHeader = document.querySelector('.app-header')")
    page.get_by_label("公开赞助感谢页", exact=True).set_checked(enabled)
    expect(footer).to_have_text("赞助预览" if enabled else "赞助感谢")
    writes = []

    def save(route):
        body = route.request.post_data_json
        writes.append(body)
        public["sponsor_page_enabled"] = body["sponsor_page_enabled"]
        route.fulfill(json={"success": True, "settings": body})

    page.route("**/admin/api/community/settings", save)
    page.get_by_role("button", name="保存全部运营配置", exact=True).click()
    expect(footer).to_have_text("赞助感谢" if enabled else "赞助预览")
    assert len(writes) == 1 and writes[0]["sponsor_page_enabled"] is enabled
    assert page.evaluate("window.sponsorHeader === document.querySelector('.app-header')")


def test_failed_sponsor_visibility_save_keeps_footer_and_draft(ui_page):
    page, load = ui_page
    reads = []

    def public_settings(route):
        reads.append(route.request.url)
        route.fulfill(json={"sponsor_page_enabled": False})

    page.route("**/api/community/public-settings", public_settings)
    community(page, load, "sponsors", settings={**SETTINGS, "sponsor_page_enabled": False})
    expect(page.locator("#navSponsorLink")).to_have_text("赞助预览")
    page.get_by_label("公开赞助感谢页", exact=True).check()
    page.route("**/admin/api/community/settings", lambda route: route.fulfill(status=500, json={"detail": "展示设置保存失败"}))
    count = len(reads)
    page.get_by_role("button", name="保存全部运营配置", exact=True).click()
    expect(page.get_by_text("展示设置保存失败", exact=True)).to_be_visible()
    expect(page.get_by_label("公开赞助感谢页", exact=True)).to_be_checked()
    expect(page.locator("#navSponsorLink")).to_have_text("赞助预览")
    assert len(reads) == count


def test_older_public_settings_response_cannot_replace_saved_visibility(ui_page):
    page, load = ui_page
    page.add_init_script("""
      const originalFetch = window.fetch;
      window.sponsorSettingsReads = [];
      window.fetch = (url, options) => url === '/api/community/public-settings'
        ? new Promise(resolve => window.sponsorSettingsReads.push(value =>
          resolve(new Response(JSON.stringify(value)))))
        : originalFetch(url, options);
    """)
    community(page, load, "sponsors")
    page.wait_for_function("window.sponsorSettingsReads.length === 1")
    page.evaluate("window.dispatchEvent(new Event('landppt:community-settings-saved'))")
    page.wait_for_function("window.sponsorSettingsReads.length === 2")
    page.evaluate("window.sponsorSettingsReads[1]({sponsor_page_enabled: true})")
    expect(page.locator("#navSponsorLink")).to_have_text("赞助感谢")
    page.evaluate("""async () => {
      window.sponsorSettingsReads[0]({sponsor_page_enabled: false});
      await new Promise(requestAnimationFrame);
    }""")
    expect(page.locator("#navSponsorLink")).to_have_text("赞助感谢")


@pytest.mark.parametrize("width", [1440, 320])
@pytest.mark.parametrize("role", ["guest", "user", "admin"])
@pytest.mark.parametrize("enabled", [False, True])
def test_sponsor_footer_visibility_follows_public_setting_and_role(ui_page, width, role, enabled):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=900))
    page.route("**/api/community/public-settings", lambda route: route.fulfill(json={"sponsor_page_enabled": enabled}))
    user = None if role == "guest" else dict(username="sponsor-user", is_admin=role == "admin")
    load("pages/community/sponsor_thanks.html", path="/sponsors", user=user, sponsors=[])
    expect(page.get_by_role("heading", name="赞助感谢", exact=True)).to_be_visible()
    if width == 320:
        page.get_by_role("button", name="菜单", exact=True).click()
    footer = page.locator("#mobileSponsorLink" if width == 320 else "#navSponsorLink")
    if enabled or role == "admin":
        expect(footer).to_be_visible()
        expect(footer).to_have_text("赞助感谢" if enabled else "赞助预览")
        assert footer.get_attribute("href") == "/sponsors"
        if width == 320:
            assert footer.bounding_box()["height"] >= 44
    else:
        expect(footer).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth") <= width


@pytest.mark.parametrize("width,height", SIZES)
@pytest.mark.parametrize("empty", [False, True])
def test_public_sponsors_fit_viewport_without_api_writes(ui_page, width, height, empty):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=height))
    errors, writes = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: writes.append(request.url) if request.method != "GET" else None,
    )
    load(
        "pages/community/sponsor_thanks.html",
        path="/sponsors",
        user=None,
        sponsors=[] if empty else [SPONSORS[0]],
        preview_mode=False,
    )
    page.get_by_role("heading", name="赞助感谢", exact=True).wait_for()
    if empty:
        assert page.get_by_text(
            "赞助感谢页已开启，暂无赞助信息。", exact=True
        ).is_visible()
    else:
        assert page.get_by_role("heading", name="示例赞助者", exact=True).is_visible()
        assert page.get_by_text("长期支持", exact=True).is_visible()
        assert (
            page.get_by_role("link", name="访问主页", exact=True).get_attribute("rel")
            == "noopener noreferrer"
        )
    assert not errors and not writes
    assert page.evaluate("document.documentElement.scrollWidth") <= width


@pytest.mark.parametrize("admin,preview", [(True, True), (True, False), (False, True)])
def test_public_sponsor_admin_preview_banner(ui_page, admin, preview):
    page, load = ui_page
    load(
        "pages/community/sponsor_thanks.html",
        path="/sponsors",
        user=dict(username="preview", is_admin=admin),
        sponsors=[],
        preview_mode=preview,
    )
    page.get_by_role("heading", name="赞助感谢", exact=True).wait_for()
    assert page.get_by_text(
        "管理员预览：当前赞助感谢页尚未公开。", exact=True
    ).count() == int(admin and preview)


@pytest.mark.parametrize("width", [390, 320])
def test_mobile_sponsor_preview_keeps_settings_action_below_explanation(ui_page, width):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=844))
    load("pages/community/sponsor_thanks.html", path="/sponsors", sponsors=[], preview_mode=True)
    action = page.get_by_role("link", name="前往设置", exact=True)
    expect(action).to_be_visible()
    explanation = page.locator(".sponsor-thanks-page > .ant-alert .ant-alert-section")
    text_box, action_box = explanation.bounding_box(), action.bounding_box()
    assert action_box["y"] >= text_box["y"] + text_box["height"]
    assert action.get_attribute("href") == "/admin/community#sponsors"
    assert page.evaluate("document.documentElement.scrollWidth") <= width


def test_public_sponsor_payload_contains_only_public_fields_and_escapes_text(ui_page):
    page, load = ui_page
    sponsor = {
        **SPONSORS[0],
        "nickname": '<img src=x onerror="window.injected=true">',
        "private_secret": "must-not-be-serialized",
        "link_url": "javascript:alert(1)",
    }
    load("pages/community/sponsor_thanks.html", path="/sponsors", sponsors=[sponsor])
    page.get_by_role("heading", name="赞助感谢", exact=True).wait_for()
    data = page.locator("#antdData").evaluate("e=>JSON.parse(e.textContent)")
    assert set(data["sponsors"][0]) == {
        "nickname",
        "avatar_url",
        "link_url",
        "amount",
        "bio",
        "note",
    }
    assert "must-not-be-serialized" not in page.content()
    assert page.get_by_role(
        "heading", name=sponsor["nickname"], exact=True
    ).is_visible()
    assert page.locator('.sponsor-thanks-page a[href^="javascript:"]').count() == 0
    assert not page.evaluate("window.injected || false")


@pytest.mark.parametrize("width", [1440, 320])
@pytest.mark.parametrize(
    "tab,label", [("notice", "公告标题"), ("checkin", "固定奖励积分")]
)
def test_operating_labels_align_above_inputs(ui_page, width, tab, label):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=844))
    community(page, load, tab)
    control = page.get_by_label(label, exact=True)
    field_label = page.get_by_text(label, exact=True)
    assert (
        field_label.bounding_box()["y"] + field_label.bounding_box()["height"]
        <= control.bounding_box()["y"] + 1
    )


def test_single_public_sponsor_card_remains_compact_on_wide_screen(ui_page):
    page, load = ui_page
    load(
        "pages/community/sponsor_thanks.html", path="/sponsors", sponsors=[SPONSORS[0]]
    )
    page.get_by_role("heading", name="赞助感谢", exact=True).wait_for()
    assert page.locator(".sponsor-thanks-card").bounding_box()["width"] < 500


@pytest.mark.parametrize("width", [1440, 320])
def test_model_input_matches_control_height_and_mobile_target(ui_page, width):
    page, load = ui_page
    page.set_viewport_size(dict(width=width, height=844))
    community(page, load)
    model_height = page.locator("#system_landppt_model").evaluate(
        "e=>e.closest('.ant-input-affix-wrapper').getBoundingClientRect().height"
    )
    provider_height = page.locator("#system_default_ai_provider").evaluate(
        "e=>e.closest('.ant-select').getBoundingClientRect().height"
    )
    assert abs(model_height - provider_height) <= 1
    if width == 320:
        box = page.get_by_role(
            "button", name="加载 LandPPT 模型", exact=True
        ).bounding_box()
        assert box["width"] >= 44 and box["height"] >= 44
