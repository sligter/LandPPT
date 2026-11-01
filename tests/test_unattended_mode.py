"""Tests for the unattended (无人值守) generation pipeline.

Covers the stage plan, the runner's ordering / stop-at / cancel / failure
semantics, notification dispatch, the persistence additions, and the wiring that
would silently break the feature (handler registration, route mounting, form
field plumbing, monitor markup).
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "landppt"


def creation_page_data(html):
    return json.loads(
        html.split('<script id="antdData" type="application/json">', 1)[1].split(
            "</script>", 1
        )[0]
    )


# --------------------------------------------------------------------------- plan


class TestStagePlan:
    def test_stage_order_is_the_documented_pipeline(self):
        from landppt.services.unattended_service import STAGE_IDS

        assert STAGE_IDS == [
            "outline",
            "template",
            "ppt",
            "speech_script",
            "narration_audio",
            "video",
        ]

    def test_planned_stages_stop_at_and_include_the_target(self):
        from landppt.services.unattended_service import planned_stage_ids

        assert planned_stage_ids("outline") == ["outline"]
        assert planned_stage_ids("ppt") == ["outline", "template", "ppt"]
        assert planned_stage_ids("video") == [
            "outline",
            "template",
            "ppt",
            "speech_script",
            "narration_audio",
            "video",
        ]

    def test_unknown_stop_stage_falls_back_to_the_default(self):
        from landppt.services.unattended_service import DEFAULT_STOP_AFTER, normalize_stop_after

        assert normalize_stop_after("bogus") == DEFAULT_STOP_AFTER
        assert normalize_stop_after(None) == DEFAULT_STOP_AFTER
        assert normalize_stop_after("") == DEFAULT_STOP_AFTER
        assert normalize_stop_after("  VIDEO  ") == "video"

    def test_build_config_normalizes_form_strings(self):
        from landppt.services.unattended_service import build_config

        config = build_config(
            {
                "stop_after": "video",
                "language": "EN",
                "template_id": "12",
                "fps": "60",
                "render_mode": "weird",
                "embed_subtitles": "false",
                "notify_in_app": "true",
                "notify_email": "on",
            }
        )

        assert config["stop_after"] == "video"
        assert config["language"] == "en"
        assert config["template_id"] == 12
        assert config["fps"] == 60
        assert config["render_mode"] == "live"  # invalid value coerced
        assert config["embed_subtitles"] is False
        assert config["notify_in_app"] is True
        assert config["notify_email"] is True

    def test_build_config_treats_auto_template_as_default_pick(self):
        from landppt.services.unattended_service import build_config

        assert build_config({"template_id": "auto"})["template_id"] is None
        assert build_config({"template_id": ""})["template_id"] is None
        assert build_config({"template_id": "not-a-number"})["template_id"] is None


# ------------------------------------------------------------------------- runner


def _runner(stop_after="ppt", **kwargs):
    from landppt.services.unattended_service import UnattendedPipelineRunner

    return UnattendedPipelineRunner(
        project_id="project-1",
        user_id=7,
        config={"stop_after": stop_after, **kwargs},
    )


def _stub_stages(runner, order, failing=None):
    """Replace every stage handler with a recorder that marks itself completed."""

    async def make(stage_id):
        if failing == stage_id:
            raise RuntimeError(f"{stage_id} exploded")
        order.append(stage_id)
        await runner._set_stage(stage_id, status="completed", message="ok")

    for stage_id in ("outline", "template", "ppt", "speech_script", "narration_audio", "video"):
        setattr(runner, f"_run_{stage_id}", (lambda sid: (lambda: make(sid)))(stage_id))


@pytest.fixture(autouse=True)
def _no_project_load(monkeypatch):
    """The runner resolves the project topic up front; stub it out for unit tests."""
    from landppt.services import unattended_service

    async def fake_load(self):
        self.topic = "测试主题"
        return None

    monkeypatch.setattr(
        unattended_service.UnattendedPipelineRunner, "_load_project", fake_load, raising=True
    )


@pytest.mark.asyncio
async def test_runner_executes_planned_stages_in_order_and_skips_the_rest():
    runner = _runner("ppt")
    order = []
    _stub_stages(runner, order)

    snapshot = await runner.run()

    assert order == ["outline", "template", "ppt"]
    assert snapshot["status"] == "completed"
    assert snapshot["success"] is True
    assert snapshot["overall_progress"] == 100.0

    statuses = {stage["id"]: stage["status"] for stage in snapshot["stages"]}
    assert statuses == {
        "outline": "completed",
        "template": "completed",
        "ppt": "completed",
        "speech_script": "skipped",
        "narration_audio": "skipped",
        "video": "skipped",
    }


@pytest.mark.asyncio
async def test_runner_runs_every_stage_when_stopping_at_video():
    runner = _runner("video")
    order = []
    _stub_stages(runner, order)

    snapshot = await runner.run()

    assert order == ["outline", "template", "ppt", "speech_script", "narration_audio", "video"]
    assert all(stage["status"] == "completed" for stage in snapshot["stages"])


@pytest.mark.asyncio
async def test_runner_stops_at_the_failing_stage_and_reports_it():
    runner = _runner("video")
    order = []
    _stub_stages(runner, order, failing="ppt")

    snapshot = await runner.run()

    assert order == ["outline", "template"]
    assert snapshot["status"] == "failed"
    assert snapshot["success"] is False
    assert "ppt exploded" in snapshot["error"]

    ppt_stage = next(stage for stage in snapshot["stages"] if stage["id"] == "ppt")
    assert ppt_stage["status"] == "failed"
    assert "ppt exploded" in ppt_stage["error"]

    # Downstream stages never started.
    for stage_id in ("speech_script", "narration_audio", "video"):
        stage = next(s for s in snapshot["stages"] if s["id"] == stage_id)
        assert stage["status"] == "pending"


@pytest.mark.asyncio
async def test_runner_honours_a_cancellation_request(monkeypatch):
    from landppt.services import unattended_service

    runner = _runner("video")
    order = []
    _stub_stages(runner, order)

    async def fake_is_cancelled(project_id):
        # Allow the first two stages through, then cancel.
        return len(order) >= 2

    monkeypatch.setattr(unattended_service, "is_cancelled", fake_is_cancelled)

    snapshot = await runner.run()

    assert order == ["outline", "template"]
    assert snapshot["status"] == "cancelled"
    assert snapshot["error"] == "任务已取消"
    remaining = {
        stage["id"]: stage["status"]
        for stage in snapshot["stages"]
        if stage["id"] in ("ppt", "speech_script", "narration_audio", "video")
    }
    assert set(remaining.values()) == {"cancelled"}


@pytest.mark.asyncio
async def test_cancel_raised_inside_a_stage_is_not_reported_as_a_failure(monkeypatch):
    """Cancelling mid-PPT surfaces as a stage error ("生成已停止"), not UnattendedCancelled."""
    from landppt.services import unattended_service

    runner = _runner("ppt")
    cancelled = {"value": False}

    async def fake_is_cancelled(_project_id):
        return cancelled["value"]

    monkeypatch.setattr(unattended_service, "is_cancelled", fake_is_cancelled)

    async def explode_after_cancel():
        cancelled["value"] = True
        raise RuntimeError("PPT 生成失败：生成已停止")

    _stub_stages(runner, [])
    runner._run_ppt = explode_after_cancel

    snapshot = await runner.run()

    assert snapshot["status"] == "cancelled"
    assert snapshot["error"] == "任务已取消"


@pytest.mark.asyncio
async def test_runner_publishes_progress_to_the_callback():
    from landppt.services.unattended_service import UnattendedPipelineRunner

    seen = []

    async def callback(progress, snapshot):
        seen.append((progress, snapshot["current_stage"]))

    runner = UnattendedPipelineRunner(
        project_id="project-1",
        user_id=7,
        config={"stop_after": "ppt"},
        progress_callback=callback,
    )
    _stub_stages(runner, [])
    await runner.run()

    assert seen, "progress callback was never invoked"
    assert seen[-1][0] == 100.0
    # Progress is monotonically non-decreasing.
    values = [entry[0] for entry in seen]
    assert values == sorted(values)


@pytest.mark.asyncio
async def test_runner_never_raises_when_a_stage_blows_up():
    runner = _runner("outline")

    async def explode():
        raise ValueError("boom")

    runner._run_outline = explode

    snapshot = await runner.run()
    assert snapshot["status"] == "failed"
    assert "boom" in snapshot["error"]


# ------------------------------------------------- regressions from code review


@pytest.mark.asyncio
async def test_a_cancel_requested_before_the_run_starts_is_honoured(monkeypatch):
    """In queue mode a user can cancel while the job waits for a worker; the runner
    must not clear that flag when it finally starts."""
    from landppt.services import unattended_service

    async def always_cancelled(_project_id):
        return True

    monkeypatch.setattr(unattended_service, "is_cancelled", always_cancelled)

    runner = _runner("video")
    order = []
    _stub_stages(runner, order)

    snapshot = await runner.run()

    assert order == [], "no stage may run after a pre-start cancel"
    assert snapshot["status"] == "cancelled"


def test_the_runner_does_not_clear_the_cancel_flag_on_start():
    source = (SRC / "services" / "unattended_service.py").read_text(encoding="utf-8")
    run_body = source[source.index("    async def run(self)") :]
    run_body = run_body[: run_body.index("    # ------------------------------------------------------------ stage impls")]
    assert "await clear_cancel(self.project_id)" not in run_body.split("finally:")[0], (
        "clearing on start discards a cancel requested while the job was queued"
    )
    # Submission owns clearing the stale flag instead.
    support = (SRC / "web" / "route_modules" / "unattended_support.py").read_text(encoding="utf-8")
    assert "await clear_cancel(project_id)" in support


@pytest.mark.asyncio
async def test_an_aborted_run_does_not_report_full_progress():
    runner = _runner("video")
    _stub_stages(runner, [])
    snapshot = await runner._mark_cancelled() or runner.snapshot()

    assert snapshot["overall_progress"] == 0.0, "a run that did nothing must not show 100%"


@pytest.mark.asyncio
async def test_stage_progress_never_goes_backwards():
    """The outline stream drops from 0.9 to 0.0 when it switches to validating."""
    runner = _runner("outline")
    await runner._set_stage("outline", status="running")
    await runner._set_stage("outline", progress=90.0)
    await runner._set_stage("outline", progress=0.0, message="正在验证…")

    assert runner.stages["outline"].progress == 90.0
    assert runner.stages["outline"].message == "正在验证…"


@pytest.mark.asyncio
async def test_a_settled_stage_ignores_late_progress_ticks():
    """Speech-script callbacks are scheduled from a sync callback and can land late."""
    runner = _runner("speech_script")
    await runner._set_stage("speech_script", status="completed", message="完成")
    await runner._set_stage("speech_script", progress=40.0, message="演讲稿 4/10 页")

    assert runner.stages["speech_script"].status == "completed"
    assert runner.stages["speech_script"].progress == 100.0
    assert runner.stages["speech_script"].message == "完成"


@pytest.mark.asyncio
async def test_current_stage_keeps_naming_the_failed_stage():
    runner = _runner("video")
    _stub_stages(runner, [], failing="ppt")

    snapshot = await runner.run()

    assert snapshot["current_stage"] == "ppt", "must not blame the next, never-run stage"


def test_progress_callback_tasks_are_strongly_referenced():
    """asyncio only weakly references pending tasks, so a dropped handle can be GC'd."""
    source = (SRC / "services" / "unattended_service.py").read_text(encoding="utf-8")
    assert "self._pending_updates.add(task)" in source
    assert "task.add_done_callback(self._pending_updates.discard)" in source
    speech_body = source[source.index("async def _run_speech_script") :]
    speech_body = speech_body[: speech_body.index("async def _run_narration_audio")]
    assert "loop.create_task(" not in speech_body


def test_narration_stage_reports_progress_without_an_n_squared_loop():
    """NarrationService only honours progress_callback on the custom_tts_api path, but
    a per-slide loop would re-hydrate the project and all speech scripts N times."""
    source = (SRC / "services" / "unattended_service.py").read_text(encoding="utf-8")
    body = source[source.index("async def _run_narration_audio") :]
    body = body[: body.index("async def _run_video")]

    assert "slide_indices=None" in body, "one call for the whole deck"
    assert "slide_indices=[index]" not in body, "per-slide calls are O(N^2)"
    assert "progress_callback=" not in body, "the callback is not honoured by most providers"
    # Progress instead comes from counting the rows the synthesis loop persists.
    assert "self._count_narration_audios()" in body
    assert "asyncio.ensure_future(" in body


def test_narration_progress_probe_never_fails_the_stage():
    source = (SRC / "services" / "unattended_service.py").read_text(encoding="utf-8")
    probe = source[source.index("async def _count_narration_audios") :]
    probe = probe[: probe.index("async def _run_narration_audio")]
    assert "return None" in probe, "a transient read error must only skip a tick"
    assert "repository.close()" in probe, "the sync repository session must be released"


def test_unusable_tts_providers_are_rejected_before_the_run():
    """comfyuiapi raises unless given a reference audio file, which an unattended run
    cannot supply, so it would fail on the first slide every time."""
    from landppt.services.unattended_service import (
        DEFAULT_TTS_PROVIDER,
        SUPPORTED_TTS_PROVIDERS,
        build_config,
    )

    assert "comfyuiapi" not in SUPPORTED_TTS_PROVIDERS
    assert build_config({"tts_provider": "comfyuiapi"})["tts_provider"] == DEFAULT_TTS_PROVIDER
    assert build_config({"tts_provider": "nonsense"})["tts_provider"] == DEFAULT_TTS_PROVIDER
    assert build_config({"tts_provider": "xiaomimimo"})["tts_provider"] == "xiaomimimo"
    assert build_config({})["tts_provider"] == DEFAULT_TTS_PROVIDER

    # The settings dropdown must not offer it either.
    settings = (
        SRC / "web" / "templates" / "components" / "settings" / "ai_config" / "content_1.html"
    ).read_text(encoding="utf-8")
    block = settings[settings.index('name="unattended_tts_provider"') :]
    block = block[: block.index("</select>")]
    assert "comfyuiapi" not in block


def test_ppt_progress_counts_pages_not_page_numbers():
    """The slide stream emits page NUMBERS; parallel batches finish out of order and a
    resume replays every existing page first."""
    source = (SRC / "services" / "unattended_service.py").read_text(encoding="utf-8")
    body = source[source.index("async def _run_ppt") : source.index("async def _run_speech_script")]
    assert "seen_pages" in body
    assert "len(seen_pages)" in body
    assert "(current / stage_total)" not in body


def test_an_aborted_stage_cannot_contribute_a_full_hundred():
    """The last tick before a failure can legitimately be 100 (final page emitted,
    then the stage failed overall)."""
    from landppt.services.unattended_service import UnattendedPipelineRunner

    runner = UnattendedPipelineRunner(project_id="p", user_id=1, config={"stop_after": "ppt"})
    runner.stages["outline"].status = "completed"
    runner.stages["template"].status = "completed"
    runner.stages["ppt"].status = "failed"
    runner.stages["ppt"].progress = 100.0

    assert runner.overall_progress() < 100.0


def test_queue_enqueue_failure_settles_the_task():
    """A PENDING task nothing will run blocks the project forever: find_active_task_async
    has no staleness release on its local-memory branch."""
    source = (SRC / "web" / "route_modules" / "unattended_support.py").read_text(encoding="utf-8")
    body = source[source.index("await enqueue_task(") - 200 :][:900]
    assert "except Exception" in body
    assert "TaskStatus.FAILED" in body
    assert "raise" in body


def test_outline_and_speech_stages_enforce_credits():
    """Credit checks live in the HTTP routes; driving services directly bypasses them."""
    source = (SRC / "services" / "unattended_service.py").read_text(encoding="utf-8")

    outline = source[source.index("async def _run_outline") : source.index("async def _run_template")]
    assert 'self._require_credits("outline_generation"' in outline
    assert 'self._charge_credits(\n            "outline_generation"' in outline

    speech = source[
        source.index("async def _run_speech_script") : source.index("async def _run_narration_audio")
    ]
    assert 'self._require_credits("ai_other"' in speech
    assert 'self._charge_credits(\n            "ai_other"' in speech


def test_workspace_stands_down_while_an_unattended_run_owns_the_project():
    source = (REPO / "frontend/src/controllers/outline-controller.ts").read_text(encoding="utf-8")
    resume = source[source.index("const shouldResume =") :][:300]
    assert resume.index("!options.unattended") < resume.index("options.confirmed")
    start = source[source.index("function startRun(") :][:350]
    assert "options.unattended" in start
    for module in ("project_workspace_routes.py", "outline_requirements_routes.py"):
        route = (SRC / "web/route_modules" / module).read_text(encoding="utf-8")
        assert '"unattended_active": await has_active_unattended_run' in route


def test_a_cancelled_run_is_not_surfaced_as_a_failure():
    """execute_task maps success=False to FAILED, so the status route re-labels it.

    The relabel must not be conditioned on the task already being "failed": the
    snapshot flips to cancelled while the task record still says running, and during
    that window the UI would show a red error box for a deliberate stop.
    """
    routes = (SRC / "web" / "route_modules" / "unattended_routes.py").read_text(encoding="utf-8")
    assert 'if run_status == "cancelled":' in routes
    assert 'and task_status == "failed"' not in routes
    assert 'task_status = "cancelled"' in routes

    monitor = (SRC / "web" / "static" / "js" / "shared" / "unattended_monitor.js").read_text(
        encoding="utf-8"
    )
    assert "run.task_status !== 'cancelled'" in monitor


def test_a_terminal_run_is_reported_even_on_the_first_poll():
    """A short run can finish between the server render and the monitor's first poll."""
    monitor = (SRC / "web" / "static" / "js" / "shared" / "unattended_monitor.js").read_text(
        encoding="utf-8"
    )
    assert "this.wasActive = Boolean(options.initiallyActive);" in monitor
    assert "this.reportedTerminal = false;" in monitor
    assert "} else if (this.wasActive && !this.reportedTerminal) {" in monitor
    # The old guard keyed off lastStatus, which is null on the first render.
    assert "this.lastStatus" not in monitor

    for page in ("todo_board.html", "todo_board_with_editor.html"):
        source = (SRC / "web" / "templates" / "pages" / "project" / page).read_text(encoding="utf-8")
        if "components/project/workspace_planning_data.html" in source:
            source += (SRC / "web/templates/components/project/workspace_planning_data.html").read_text(encoding="utf-8")
        assert "unattendedActive" in source or "unattended_active" in source, f"{page} must tell the monitor if a run was live"


def test_a_failed_run_unsticks_the_workspace():
    """The board suppresses its own error/retry UI while a run is active, so the
    monitor must reload on failure and cancellation too, not only on success."""
    for page in ("todo.tsx", "generator-chrome.tsx"):
        source = (SRC.parent.parent / "frontend/src/pages" / page).read_text(encoding="utf-8")
        onComplete = source[source.index("onComplete={") :][:400]
        # Must fire for every terminal status, not just success — otherwise a failed
        # run leaves the workspace suppressing its own error UI forever.
        assert "if (run.task_status === 'completed')" not in onComplete
        # A 1.5s reload would destroy the monitor's 失败：<reason> toast unread.
        assert "6000" in onComplete, f"{page}: failures need a longer read window"


def test_the_workspace_refreshes_when_the_outline_lands():
    """Otherwise the page shows nothing until the whole pipeline finishes — which for
    a run ending in video export can be ten minutes after the outline was written."""
    source = (SRC.parent.parent / "frontend/src/pages/todo.tsx").read_text(
        encoding="utf-8"
    )
    assert "onUpdate={" in source
    on_update = source[source.index("onUpdate={") : source.index("onComplete={")]
    assert "'outline'" in on_update
    assert "'completed'" in on_update
    assert "reloadSoon" in on_update
    # One refresh only, however many polls report the transition.
    assert "if (reloading.current) return;" in source


def test_the_editor_workspace_stands_down_during_an_unattended_run():
    """Its 暂停/停止 buttons set only the slide cancel flag, which the pipeline reads
    as a generation failure and which abandons every remaining stage."""
    # Manual action guards and readonly unattended recovery are exercised by
    # frontend/tests/generator-controller.test.mjs and the real Ant UI tests.
    # Rendering documents cannot start work; the controller alone owns transport.
    surface = (REPO / "frontend/src/components/generator-documents.tsx").read_text(encoding="utf-8")
    assert "new EventSource" not in surface
    assert "slides/cancel" not in surface
    assert "slides/clear-cancel" not in surface
    assert "setInterval(checkPPTStatus" not in surface


def test_queue_dispatch_persists_the_task_id_before_enqueueing():
    """A worker can BRPOP the job the instant it is pushed."""
    source = (SRC / "web" / "route_modules" / "unattended_support.py").read_text(encoding="utf-8")
    body = source[source.index("async def submit_unattended_run") :]
    body = body[: body.index("async def has_active_unattended_run")]
    assert body.index("_remember_task_id") < body.index("enqueue_task")
    assert body.index("_remember_task_id") < body.index("asyncio.create_task")


# -------------------------------------------------------------- stage internals
#
# The tests above stub every `_run_*`. These drive the real stage bodies against
# fake service objects so a signature change in EnhancedPPTService is caught here
# rather than at runtime.


class _FakeProject:
    def __init__(self, **kwargs):
        self.project_id = "project-1"
        self.topic = "测试主题"
        self.user_id = 7
        self.outline = None
        self.slides_data = None
        self.project_metadata = {}
        self.confirmed_requirements = {"topic": "测试主题", "content_source": "manual"}
        self.__dict__.update(kwargs)


class _FakeService:
    def __init__(self, project, *, outline_events=None, slide_events=None):
        self.project = project
        self.outline_events = outline_events or []
        self.slide_events = slide_events or []
        self.calls = []
        self.project_manager = self
        self.slides = []
        # Mirrors the real service persisting the outline before the stream ends.
        self.outline_side_effect = None
        self.free_template_html = "<html>free</html>"
        self.free_template_events = None
        self.cleared_style_genes = False

    # --- project_manager surface -------------------------------------------
    async def get_project(self, project_id, user_id=None):
        self.calls.append(("get_project", project_id, user_id))
        return self.project

    async def update_stage_status(self, project_id, stage_id, status, progress=None, user_id=None):
        self.calls.append(("update_stage_status", stage_id, status))
        return True

    async def update_project_metadata(self, project_id, metadata, user_id=None):
        self.calls.append(("update_project_metadata", project_id))
        self.project.project_metadata = dict(metadata)
        return True

    async def list_slides(self, project_id, user_id=None):
        return self.slides

    # --- EnhancedPPTService surface ----------------------------------------
    async def generate_outline_streaming(self, project_id, *, force_regenerate=False):
        self.calls.append(("generate_outline_streaming", project_id, force_regenerate))
        for event in self.outline_events:
            yield event
        if self.outline_side_effect:
            self.outline_side_effect()

    async def select_global_template_for_project(self, project_id, template_id=None, user_id=None):
        self.calls.append(("select_global_template_for_project", project_id, template_id, user_id))
        return {
            "success": True,
            "message": "模板选择成功",
            "selected_template": {"id": template_id or 5, "template_name": "默认模板"},
        }

    async def get_selected_global_template(self, project_id, user_id=None):
        self.calls.append(("get_selected_global_template", project_id, user_id))
        return {"template_name": "AI 自由模板"}

    async def select_free_template_for_project(self, project_id, user_id=None):
        self.calls.append(("select_free_template_for_project", project_id))
        self.project.project_metadata = {
            **(self.project.project_metadata or {}),
            "template_mode": "free",
        }
        # The real service always returns selected_template=None on this path.
        return {"success": True, "message": "已切换为自由模板", "selected_template": None}

    async def stream_free_template_generation(self, project_id, user_id=None, force=False):
        self.calls.append(("stream_free_template_generation", project_id))
        events = self.free_template_events
        if events is None:
            events = [
                {"type": "status", "message": "正在整理项目大纲和需求..."},
                {"type": "preview", "message": "正在生成 HTML 预览..."},
                {"type": "complete", "template_name": "自由模板-abc", "html_template": self.free_template_html},
            ]
        for event in events:
            if event.get("type") == "complete":
                # Mirrors the real service persisting the template before completing.
                self.project.project_metadata = {
                    **(self.project.project_metadata or {}),
                    "free_template_html": self.free_template_html,
                    "free_template_name": event.get("template_name"),
                    "free_template_status": "ready",
                }
            yield event

    def clear_cached_style_genes(self, project_id=None):
        self.cleared_style_genes = True

    async def clear_cancel_slides_generation(self, project_id):
        self.calls.append(("clear_cancel_slides_generation", project_id))
        return True

    async def generate_slides_streaming(self, project_id):
        self.calls.append(("generate_slides_streaming", project_id))
        for event in self.slide_events:
            yield event


def _sse(payload):
    import json

    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _wire(runner, service, project):
    runner._service = lambda: service

    async def load():
        runner.topic = project.topic
        return project

    runner._load_project = load


@pytest.mark.asyncio
async def test_outline_stage_consumes_the_stream_and_verifies_persistence():
    project = _FakeProject()
    service = _FakeService(
        project,
        outline_events=[
            _sse({"status": {"step": "generating", "message": "生成中", "progress": 0.5}}),
            _sse({"outline": {"slides": [{"page_number": 1}]}}),
            _sse({"done": True, "llm_call_count": 2}),
        ],
    )
    runner = _runner("outline")
    _wire(runner, service, project)

    # The real streaming service persists the outline itself; the stage then
    # re-reads the project to confirm it landed.
    service.outline_side_effect = lambda: setattr(
        project, "outline", {"slides": [{"page_number": 1}, {"page_number": 2}]}
    )

    await runner._set_stage("outline", status="running")
    await runner._run_outline()

    assert runner.stages["outline"].status == "completed"
    assert runner.stages["outline"].detail["slide_count"] == 2
    assert ("generate_outline_streaming", "project-1", False) in service.calls


@pytest.mark.asyncio
async def test_outline_stage_fails_when_the_stream_reports_an_error():
    project = _FakeProject()
    service = _FakeService(project, outline_events=[_sse({"error": "模型不可用"})])
    runner = _runner("outline")
    _wire(runner, service, project)

    with pytest.raises(RuntimeError, match="模型不可用"):
        await runner._run_outline()


@pytest.mark.asyncio
async def test_outline_stage_reuses_an_existing_outline():
    project = _FakeProject(outline={"slides": [{"page_number": 1}]})
    service = _FakeService(project)
    runner = _runner("outline")
    _wire(runner, service, project)

    await runner._run_outline()

    assert runner.stages["outline"].status == "completed"
    assert runner.stages["outline"].detail["reused"] is True
    assert not any(call[0] == "generate_outline_streaming" for call in service.calls)


@pytest.mark.asyncio
async def test_outline_stage_requires_confirmed_requirements():
    project = _FakeProject(confirmed_requirements=None)
    service = _FakeService(project)
    runner = _runner("outline")
    _wire(runner, service, project)

    with pytest.raises(RuntimeError, match="需求"):
        await runner._run_outline()


@pytest.mark.asyncio
async def test_template_stage_selects_the_default_template():
    project = _FakeProject()
    service = _FakeService(project)
    runner = _runner("template")
    _wire(runner, service, project)

    await runner._run_template()

    assert runner.stages["template"].status == "completed"
    assert runner.stages["template"].detail["template_mode"] == "global"
    assert ("select_global_template_for_project", "project-1", None, 7) in service.calls


class TestTemplateModeResolution:
    """The template must be fully decided at setup: unattended skips the picker page."""

    def test_modes(self):
        from landppt.services.unattended_service import TEMPLATE_MODES

        assert TEMPLATE_MODES == ("auto", "global", "free")

    @pytest.mark.parametrize(
        "raw,expected_mode,expected_id",
        [
            ({}, "auto", None),
            ({"template_mode": "free"}, "free", None),
            ({"template_mode": "auto"}, "auto", None),
            ({"template_mode": "global", "template_id": "7"}, "global", 7),
            # "指定模板" with nothing picked is just the default pick.
            ({"template_mode": "global"}, "auto", None),
            ({"template_mode": "global", "template_id": ""}, "auto", None),
            # Legacy/implicit: a bare id means "use this global template".
            ({"template_id": "3"}, "global", 3),
            # A free run must never carry a stale template id.
            ({"template_mode": "free", "template_id": "9"}, "free", None),
            ({"template_mode": "bogus", "template_id": "9"}, "global", 9),
            ({"template_id": "auto"}, "auto", None),
        ],
    )
    def test_build_config_resolves_mode_and_id(self, raw, expected_mode, expected_id):
        from landppt.services.unattended_service import build_config

        config = build_config(raw)
        assert config["template_mode"] == expected_mode
        assert config["template_id"] == expected_id

    def test_requirements_block_carries_the_choice(self):
        from landppt.web.route_modules.unattended_support import build_unattended_requirements

        block = build_unattended_requirements(
            enabled=True, stop_at_stage="ppt", notify_in_app=True, notify_email=False,
            template_mode="global", template_id="12",
        )
        assert block["template_mode"] == "global"
        assert block["template_id"] == 12

        free = build_unattended_requirements(
            enabled=True, stop_at_stage="ppt", notify_in_app=True, notify_email=False,
            template_mode="free", template_id="12",
        )
        assert free["template_mode"] == "free"
        assert free["template_id"] is None

        bad = build_unattended_requirements(
            enabled=True, stop_at_stage="ppt", notify_in_app=True, notify_email=False,
            template_mode="nonsense", template_id="not-a-number",
        )
        assert bad["template_mode"] == "auto"
        assert bad["template_id"] is None


@pytest.mark.asyncio
async def test_template_stage_generates_and_confirms_a_free_template():
    """Confirmation is normally a human step; the pipeline must do it itself or the
    slides stream refuses to start."""
    project = _FakeProject(outline={"slides": [{"page_number": 1}]})
    service = _FakeService(project)
    runner = _runner("template", template_mode="free")
    _wire(runner, service, project)

    await runner._run_template()

    assert ("select_free_template_for_project", "project-1") in service.calls
    assert ("stream_free_template_generation", "project-1") in service.calls
    assert runner.stages["template"].status == "completed"
    assert runner.stages["template"].detail["template_mode"] == "free"
    # The metadata write the confirm endpoint would have made.
    assert project.project_metadata["free_template_confirmed"] is True
    assert project.project_metadata["free_template_status"] == "ready"
    assert project.project_metadata["free_template_confirmed_at"]
    assert service.cleared_style_genes is True


@pytest.mark.asyncio
async def test_free_template_stage_fails_when_no_html_is_produced():
    project = _FakeProject(outline={"slides": [{"page_number": 1}]})
    service = _FakeService(project)
    service.free_template_html = ""
    runner = _runner("template", template_mode="free")
    _wire(runner, service, project)

    with pytest.raises(RuntimeError, match="未产生模板内容"):
        await runner._run_template()


@pytest.mark.asyncio
async def test_free_template_stage_fails_when_the_stream_never_completes():
    project = _FakeProject(outline={"slides": [{"page_number": 1}]})
    service = _FakeService(project)
    service.free_template_events = [{"type": "status", "message": "生成中"}]
    runner = _runner("template", template_mode="free")
    _wire(runner, service, project)

    with pytest.raises(RuntimeError, match="未收到完成事件"):
        await runner._run_template()


@pytest.mark.asyncio
async def test_explicit_template_id_is_honoured():
    project = _FakeProject()
    service = _FakeService(project)
    runner = _runner("template", template_mode="global", template_id=42)
    _wire(runner, service, project)

    await runner._run_template()

    assert ("select_global_template_for_project", "project-1", 42, 7) in service.calls
    assert runner.stages["template"].detail["template_id"] == 42


@pytest.mark.asyncio
async def test_template_stage_keeps_a_confirmed_free_template():
    project = _FakeProject(
        project_metadata={"template_mode": "free", "free_template_confirmed": True}
    )
    service = _FakeService(project)
    runner = _runner("template")
    _wire(runner, service, project)

    await runner._run_template()

    assert runner.stages["template"].detail["template_mode"] == "free"
    assert not any(
        call[0] == "select_global_template_for_project" for call in service.calls
    )


@pytest.mark.asyncio
async def test_a_project_already_in_free_mode_gets_its_template_generated():
    """An unconfirmed free template used to dead-end the run; the pipeline now
    finishes the job instead of asking the user to go and confirm it by hand."""
    project = _FakeProject(project_metadata={"template_mode": "free"})
    service = _FakeService(project)
    runner = _runner("template")  # config mode defaults to "auto"
    _wire(runner, service, project)

    await runner._run_template()

    assert runner.stages["template"].status == "completed"
    assert project.project_metadata["free_template_confirmed"] is True
    assert not any(
        call[0] == "select_global_template_for_project" for call in service.calls
    ), "an explicit free-mode project must not be silently switched to a global template"


@pytest.mark.asyncio
async def test_an_explicit_global_choice_overrides_a_stale_free_mode():
    project = _FakeProject(project_metadata={"template_mode": "free"})
    service = _FakeService(project)
    runner = _runner("template", template_mode="global", template_id=5)
    _wire(runner, service, project)

    await runner._run_template()

    assert ("select_global_template_for_project", "project-1", 5, 7) in service.calls


@pytest.mark.asyncio
async def test_ppt_stage_requires_every_page_to_render():
    project = _FakeProject(outline={"slides": [{"page_number": 1}, {"page_number": 2}]})
    service = _FakeService(
        project,
        slide_events=[
            _sse({"type": "progress", "current": 1, "total": 2}),
            _sse({"type": "complete", "total": 2}),
        ],
    )
    # Only one page actually persisted, and the other is flagged failed.
    service.slides = [
        {"page_number": 1, "html_content": "<div>ok</div>"},
        {"page_number": 2, "html_content": "<div>err</div>", "generation_failed": True},
    ]
    runner = _runner("ppt")
    _wire(runner, service, project)

    with pytest.raises(RuntimeError, match="1/2"):
        await runner._run_ppt()


@pytest.mark.asyncio
async def test_ppt_stage_completes_and_clears_the_sticky_cancel_flag():
    project = _FakeProject(outline={"slides": [{"page_number": 1}, {"page_number": 2}]})
    service = _FakeService(
        project,
        slide_events=[_sse({"type": "progress", "current": 2, "total": 2})],
    )
    service.slides = [
        {"page_number": 1, "html_content": "<div>a</div>"},
        {"page_number": 2, "html_content": "<div>b</div>"},
    ]
    runner = _runner("ppt")
    _wire(runner, service, project)

    await runner._run_ppt()

    assert runner.stages["ppt"].status == "completed"
    assert runner.stages["ppt"].detail["slide_count"] == 2
    # A stale flag from an earlier manual stop would abort the first batch.
    assert ("clear_cancel_slides_generation", "project-1") in service.calls


@pytest.mark.asyncio
async def test_narration_stage_polls_progress_and_returns_every_item(monkeypatch):
    """Exercises the real polling loop: it must terminate, publish progress, and
    return the synthesis result rather than the poller's."""
    import asyncio
    from types import SimpleNamespace

    project = _FakeProject(slides_data=[{"page_number": i + 1} for i in range(4)])
    service = _FakeService(project)
    runner = _runner("narration_audio")
    _wire(runner, service, project)

    produced = []

    class FakeNarrationService:
        def __init__(self, *, user_id=None):
            self.user_id = user_id

        async def generate_project_slide_audios(self, **kwargs):
            assert kwargs["slide_indices"] is None, "must be one call for the whole deck"
            for index in range(4):
                await asyncio.sleep(0)
                produced.append(index)
            return [
                SimpleNamespace(slide_index=index, cached=False) for index in range(4)
            ]

    monkeypatch.setattr(
        "landppt.services.narration_service.NarrationService", FakeNarrationService
    )
    monkeypatch.setattr(
        "landppt.services.narration_service.is_ffmpeg_available", lambda: True
    )
    monkeypatch.setattr(
        type(runner), "_count_narration_audios", lambda self: _async_value(len(produced))
    )

    await runner._run_narration_audio()

    assert runner.stages["narration_audio"].status == "completed"
    assert runner.stages["narration_audio"].detail["audio_count"] == 4


@pytest.mark.asyncio
async def test_narration_stage_fails_on_incomplete_coverage(monkeypatch):
    """Video export hard-fails on a gap, so the audio stage must catch it first."""
    from types import SimpleNamespace

    project = _FakeProject(slides_data=[{"page_number": i + 1} for i in range(3)])
    service = _FakeService(project)
    runner = _runner("narration_audio")
    _wire(runner, service, project)

    class PartialNarrationService:
        def __init__(self, *, user_id=None):
            pass

        async def generate_project_slide_audios(self, **kwargs):
            return [SimpleNamespace(slide_index=0, cached=False)]

    monkeypatch.setattr(
        "landppt.services.narration_service.NarrationService", PartialNarrationService
    )
    monkeypatch.setattr(
        "landppt.services.narration_service.is_ffmpeg_available", lambda: True
    )
    monkeypatch.setattr(
        type(runner), "_count_narration_audios", lambda self: _async_value(1)
    )

    with pytest.raises(RuntimeError, match="配音生成不完整"):
        await runner._run_narration_audio()


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_ppt_stage_progress_tracks_distinct_pages_not_page_numbers():
    """A resume replays existing page numbers first; page 8 of 10 must not read 80%."""
    from landppt.services.unattended_service import UnattendedPipelineRunner

    seen_progress = []

    async def capture(_progress, snapshot):
        stage = next(s for s in snapshot["stages"] if s["id"] == "ppt")
        if stage["status"] == "running":
            seen_progress.append(stage["progress"])

    project = _FakeProject(outline={"slides": [{"page_number": i + 1} for i in range(10)]})
    service = _FakeService(
        project,
        slide_events=[
            # Replay of two already-persisted pages, out of order and high-numbered.
            _sse({"type": "progress", "current": 8, "total": 10}),
            _sse({"type": "progress", "current": 3, "total": 10}),
        ],
    )
    runner = UnattendedPipelineRunner(
        project_id="project-1", user_id=7, config={"stop_after": "ppt"},
        progress_callback=capture,
    )
    _wire(runner, service, project)
    service.slides = [
        {"page_number": i + 1, "html_content": "<div>x</div>"} for i in range(10)
    ]

    await runner._set_stage("ppt", status="running")
    await runner._run_ppt()

    # Two distinct pages seen out of ten => 10% then 20%. Reporting the page number
    # would have produced 80% on the very first event.
    assert seen_progress, "the stage published no progress"
    assert max(seen_progress) == 20.0, f"expected a 20% peak, got {seen_progress}"
    assert runner.stages["ppt"].status == "completed"


@pytest.mark.asyncio
async def test_ppt_stage_surfaces_stream_errors():
    project = _FakeProject(outline={"slides": [{"page_number": 1}]})
    service = _FakeService(
        project, slide_events=[_sse({"type": "error", "message": "生成已停止"})]
    )
    runner = _runner("ppt")
    _wire(runner, service, project)

    with pytest.raises(RuntimeError, match="生成已停止"):
        await runner._run_ppt()


# ------------------------------------------------------------------ notifications


@pytest.mark.asyncio
async def test_completion_notification_reports_success(monkeypatch):
    from landppt.services import unattended_service

    captured = {}

    async def fake_notify_user(**kwargs):
        captured.update(kwargs)
        return {"in_app": True, "email": False}

    monkeypatch.setattr(
        "landppt.services.notification_service.notify_user", fake_notify_user
    )

    runner = _runner("ppt")
    _stub_stages(runner, [])
    snapshot = await runner.run()

    await unattended_service.send_completion_notification(
        snapshot=snapshot, user_id=7, config=runner.config
    )

    assert captured["level"] == "success"
    assert "完成" in captured["title"]
    assert captured["notification_type"] == "unattended_run"
    assert captured["project_id"] == "project-1"
    assert captured["link_url"] == "/projects/project-1/todo"
    assert captured["send_in_app"] is True


@pytest.mark.asyncio
async def test_completion_notification_reports_failure_with_reason(monkeypatch):
    from landppt.services import unattended_service

    captured = {}

    async def fake_notify_user(**kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(
        "landppt.services.notification_service.notify_user", fake_notify_user
    )

    runner = _runner("video")
    _stub_stages(runner, [], failing="narration_audio")
    snapshot = await runner.run()

    await unattended_service.send_completion_notification(
        snapshot=snapshot, user_id=7, config=runner.config
    )

    assert captured["level"] == "error"
    assert "失败" in captured["title"]
    assert "narration_audio exploded" in captured["body"]


@pytest.mark.asyncio
async def test_notify_user_skips_email_when_the_account_has_none(monkeypatch):
    from landppt.services import notification_service

    async def fake_create(**_kwargs):
        return "notification-1"

    async def fake_get_email(_user_id):
        return None

    monkeypatch.setattr(notification_service, "create_in_app_notification", fake_create)
    monkeypatch.setattr(notification_service, "get_user_email", fake_get_email)

    result = await notification_service.notify_user(
        user_id=7,
        title="任务完成",
        send_in_app=True,
        send_email_notification=True,
    )

    assert result["in_app"] is True
    assert result["notification_id"] == "notification-1"
    assert result["email"] is False
    assert result["email_message"] == "用户未绑定邮箱"


def test_email_html_escapes_caller_supplied_text():
    from landppt.services.notification_service import render_email_html

    html = render_email_html(
        title="<script>alert(1)</script>",
        body="a & b",
        detail_rows=[("主题", "<b>x</b>")],
        action_url="https://example.com/p?a=1&b=2",
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "a &amp; b" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "https://example.com/p?a=1&amp;b=2" in html


def test_notification_level_is_coerced_to_a_known_value():
    from landppt.services.notification_service import _normalize_level

    assert _normalize_level("success") == "success"
    assert _normalize_level("SUCCESS") == "success"
    assert _normalize_level("nonsense") == "info"
    assert _normalize_level(None) == "info"


# -------------------------------------------------------------------- persistence


def test_notification_model_matches_the_repository_conventions():
    from landppt.database.models import Notification

    assert Notification.__tablename__ == "notifications"
    columns = Notification.__table__.columns
    assert columns["project_id"].nullable is True
    assert columns["user_id"].nullable is False
    # Project-scoped children FK to the string project_id, never projects.id.
    assert {fk.target_fullname for fk in columns["project_id"].foreign_keys} == {
        "projects.project_id"
    }
    # Timestamps are Float epoch seconds throughout the schema.
    assert columns["created_at"].type.python_type is float


@pytest.mark.asyncio
async def test_notification_repository_round_trip(tmp_path):
    """Ownership, ordering, and idempotence of the bell's backing store."""
    import time
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from landppt.database.models import Base
    from landppt.database.repositories import NotificationRepository

    db_path = tmp_path / "notifications.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with maker() as session:
            repository = NotificationRepository(session)

            created_ids = []
            for index in range(3):
                notification = await repository.create(
                    {
                        "id": str(uuid.uuid4()),
                        "user_id": 1,
                        "project_id": None,
                        "notification_type": "unattended_run",
                        "level": "success",
                        "title": f"任务 {index}",
                        "body": "完成",
                        "link_url": "/projects/p/todo",
                        "payload": {"index": index},
                        "is_read": False,
                        "created_at": time.time() + index,
                    }
                )
                created_ids.append(notification.id)

            await repository.create(
                {
                    "id": str(uuid.uuid4()),
                    "user_id": 2,
                    "notification_type": "unattended_run",
                    "level": "info",
                    "title": "别人的通知",
                    "is_read": False,
                    "created_at": time.time(),
                }
            )

            assert await repository.count_unread(1) == 3
            assert await repository.count_unread(2) == 1

            rows = await repository.list_for_user(1, limit=10)
            assert [row.title for row in rows] == ["任务 2", "任务 1", "任务 0"]
            assert rows[0].payload == {"index": 2}
            assert len(await repository.list_for_user(1, unread_only=True)) == 3

            assert await repository.mark_read(created_ids[0], 1) is True
            assert await repository.count_unread(1) == 2
            # Already read -> no second update.
            assert await repository.mark_read(created_ids[0], 1) is False
            # Another user's id must not be markable.
            assert await repository.mark_read(created_ids[1], 999) is False

            assert await repository.mark_all_read(1) == 2
            assert await repository.count_unread(1) == 0
            assert await repository.count_unread(2) == 1, "other users must be untouched"
    finally:
        await engine.dispose()


def test_migration_018_is_registered_once():
    from landppt.database.migrations import DatabaseMigration

    versions = [migration["version"] for migration in DatabaseMigration().migrations]
    assert versions.count("018") == 1
    assert versions.count("021") == 1
    assert versions.count("022") == 1
    assert versions[-1] == "022"
    assert sorted(versions) == versions, "migrations must stay in ascending order"


def test_project_delete_also_removes_notifications():
    """A project-scoped table missing from the cascade blocks project deletion."""
    source = (SRC / "database" / "repositories.py").read_text(encoding="utf-8")
    delete_body = source[source.index("async def delete(self, project_id"):]
    delete_body = delete_body[: delete_body.index("class ")]
    assert "delete(Notification).where(Notification.project_id == project_id)" in delete_body


# ------------------------------------------------------------------------- wiring


def test_unattended_handler_is_registered_for_the_worker():
    from landppt.services.unattended_service import UNATTENDED_TASK_TYPE
    from landppt.tasks.registry import get_handler

    handler = get_handler(UNATTENDED_TASK_TYPE)
    assert handler.__name__ == "run_unattended"


def test_registry_can_resolve_handlers_from_more_than_one_module():
    """The lazy import used to bail out as soon as any handler was registered."""
    from landppt.tasks.registry import get_handler

    assert get_handler("pdf_generation") is not None
    assert get_handler("unattended_pipeline") is not None


def test_unattended_task_type_is_cleaned_from_the_active_index():
    source = (SRC / "services" / "background_tasks.py").read_text(encoding="utf-8")
    index_block = source[source.index("task_types = ["):]
    index_block = index_block[: index_block.index("]")]
    assert '"unattended_pipeline"' in index_block


def test_unattended_and_notification_routes_are_mounted():
    from landppt.web.routes import router

    paths = {route.path for route in router.routes}
    assert "/api/projects/{project_id}/unattended/start" in paths
    assert "/api/projects/{project_id}/unattended/status" in paths
    assert "/api/projects/{project_id}/unattended/cancel" in paths
    assert "/api/notifications" in paths
    assert "/api/notifications/unread-count" in paths
    assert "/api/notifications/read-all" in paths
    assert "/api/notifications/{notification_id}/read" in paths


@pytest.mark.parametrize(
    ("module_name", "path", "request_kwargs"),
    [
        ("unattended_routes", "/api/projects/proj-1/unattended/start", {"json": {}}),
        (
            "project_lifecycle_routes",
            "/projects/create-and-confirm",
            {"data": {"topic": "test", "unattended_mode": "true"}},
        ),
        (
            "outline_requirements_routes",
            "/projects/proj-1/confirm-requirements",
            {"data": {"topic": "test", "audience_type": "general", "unattended_mode": "true"}},
        ),
    ],
)
def test_non_admin_cannot_start_unattended_mode(module_name, path, request_kwargs):
    from importlib import import_module
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    module = import_module(f"landppt.web.route_modules.{module_name}")
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.get_current_user_required] = lambda: SimpleNamespace(
        id=7, is_admin=False
    )

    response = TestClient(app).post(path, **request_kwargs)

    assert response.status_code == 403
    assert response.json()["detail"] == "无权限"


def test_config_keys_are_registered_in_generation_params():
    from landppt.services.db_config_service import DatabaseConfigService

    schema = DatabaseConfigService().config_schema
    for key in (
        "unattended_default_stop_stage",
        "unattended_notify_in_app",
        "unattended_notify_email",
        "unattended_tts_provider",
        "unattended_video_fps",
        "unattended_video_render_mode",
    ):
        assert key in schema, f"{key} must be registered or the settings POST drops it"
        assert schema[key]["category"] == "generation_params"
        # admin_only keys are writable by non-admins on this endpoint and would be
        # persisted at system scope, so unattended settings must stay per-user.
        assert not schema[key].get("admin_only")


@pytest.mark.asyncio
async def test_saved_settings_flow_through_to_the_run_config(monkeypatch):
    """The settings page writes strings; build_config must turn them into a usable run."""
    from landppt.services import unattended_service

    class FakeConfigService:
        def __init__(self):
            self.calls = 0

        async def get_all_config(self, user_id=None):
            self.calls += 1
            return {
                "unattended_default_stop_stage": "narration_audio",
                "unattended_notify_in_app": False,
                "unattended_notify_email": True,
                "unattended_tts_provider": "xiaomimimo",
                "unattended_video_fps": 60,
                "unattended_video_render_mode": "static",
                "some_unrelated_key": "ignored",
            }

    fake = FakeConfigService()
    monkeypatch.setattr(
        "landppt.services.db_config_service.get_db_config_service", lambda: fake
    )

    defaults = await unattended_service.load_config_defaults(7)
    config = unattended_service.build_config(defaults)

    assert config["stop_after"] == "narration_audio"
    assert config["notify_in_app"] is False
    assert config["notify_email"] is True
    assert config["tts_provider"] == "xiaomimimo"
    assert config["fps"] == 60
    assert config["render_mode"] == "static"
    # One resolved read, not one per key — this runs on every creation-page load.
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_config_defaults_survive_a_config_service_failure(monkeypatch):
    """A config outage must not stop someone from starting an unattended run."""
    from landppt.services import unattended_service

    class BrokenConfigService:
        async def get_all_config(self, user_id=None):
            raise RuntimeError("db down")

    monkeypatch.setattr(
        "landppt.services.db_config_service.get_db_config_service", lambda: BrokenConfigService()
    )

    defaults = await unattended_service.load_config_defaults(7)
    assert defaults["stop_after"] == unattended_service.DEFAULT_STOP_AFTER
    assert defaults["tts_provider"] == "edge_tts"


def test_config_defaults_cover_every_schema_key():
    from landppt.services.db_config_service import DatabaseConfigService
    from landppt.services.unattended_service import CONFIG_KEY_DEFAULTS

    schema = DatabaseConfigService().config_schema
    for key in CONFIG_KEY_DEFAULTS:
        assert key in schema


class TestCreationFormPlumbing:
    """The React form consumes explicit public JSON; browser tests cover controls."""

    @pytest.fixture(scope="class")
    def render(self):
        from types import SimpleNamespace
        from jinja2 import Environment, FileSystemLoader

        env = Environment(
            loader=FileSystemLoader(SRC / "web" / "templates"), autoescape=True
        )

        def render(**values):
            user = values.pop("user", dict(username="admin", is_admin=True))
            return creation_page_data(
                env.get_template("pages/project/scenarios.html").render(
                    request=SimpleNamespace(state=SimpleNamespace(user=user)), **values
                )
            )

        return render

    def test_unattended_defaults_fall_back_without_saved_configuration(self, render):
        data = render()
        assert data["createDefaults"] == dict(
            stop_at_stage="ppt",
            unattended_notify_in_app=True,
            unattended_notify_email=False,
        )

    def test_request_user_role_reaches_frontend_without_private_fields(self, render):
        data = render(
            user=dict(username="member", is_admin=False, password_hash="private")
        )
        assert data["user"] == dict(username="member", is_admin=False)

    def test_every_saved_stop_stage_reaches_frontend(self, render):
        from landppt.services.unattended_service import STAGE_IDS

        for stage_id in STAGE_IDS:
            data = render(
                unattended_defaults=dict(
                    stop_after=stage_id,
                    notify_in_app=False,
                    notify_email=True,
                    private_key="private",
                )
            )
            assert data["createDefaults"] == dict(
                stop_at_stage=stage_id,
                unattended_notify_in_app=False,
                unattended_notify_email=True,
            )


class TestBothConfirmEndpointsAcceptTheFields:
    """The two requirement-confirmation paths have diverged before; keep them in sync."""

    @pytest.mark.parametrize(
        "module",
        ["project_lifecycle_routes.py", "outline_requirements_routes.py"],
    )
    def test_form_fields_and_dispatch(self, module):
        source = (SRC / "web" / "route_modules" / module).read_text(encoding="utf-8")
        assert "unattended_mode: bool = Form(False)" in source
        assert 'stop_at_stage: str = Form("ppt")' in source
        assert "unattended_notify_in_app: bool = Form(True)" in source
        assert "unattended_notify_email: bool = Form(False)" in source
        assert "build_unattended_requirements(" in source
        assert "maybe_start_unattended_run(" in source


def test_task_id_is_persisted_before_the_pipeline_can_touch_metadata():
    """The template stage rewrites project_metadata; a later write would race it."""
    source = (SRC / "web" / "route_modules" / "unattended_support.py").read_text(encoding="utf-8")
    body = source[source.index("async def submit_unattended_run") :]
    body = body[: body.index("def default_stage_snapshot")]
    assert body.index("_remember_task_id") < body.index("asyncio.create_task")


class TestMonitorSurfaces:
    def test_monitor_mounts_on_both_workspace_templates(self):
        templates = SRC / "web" / "templates"
        todo_board = (templates / "pages" / "project" / "todo_board.html").read_text(encoding="utf-8")
        editor = (templates / "pages" / "project" / "todo_board_with_editor.html").read_text(
            encoding="utf-8"
        )

        for source in (todo_board, editor):
            assert "unattended_monitor.js" in source
        component = (SRC.parent.parent / "frontend/src/components/unattended.tsx").read_text(encoding="utf-8")
        assert "initiallyActive" in component
        assert "factory.mount(" in component

    def test_monitor_containers_exist(self):
        component = (REPO / "frontend/src/pages/todo.tsx").read_text(encoding="utf-8")
        editor = (REPO / "frontend/src/pages/generator-chrome.tsx").read_text(encoding="utf-8")
        for source in (component, editor):
            assert source.count('id={active ? "unattendedMonitor" : undefined}') == 1
            assert "active && <UnattendedPanel" in source

    def test_notification_bell_is_in_the_logged_in_nav_only(self):
        base = (SRC / "web" / "templates" / "base.html").read_text(encoding="utf-8")
        assert 'id="navNotificationBell"' in base
        assert 'id="navNotificationBadge"' in base
        assert "notification_center.js" in base
        assert "notification_center.css" in base

        # The bell must sit inside the `{% if current_user %}` nav-user block, and
        # the mount call must be guarded, or anonymous visitors poll a 401 endpoint.
        logged_in_block = base[base.index("{% if current_user %}") : base.index("{% else %}")]
        assert 'id="navNotificationBell"' in logged_in_block
        assert "{% if current_user %}\n        window.NotificationCenter?.mount(" in base

    def test_monitor_js_has_no_control_characters(self):
        source = (
            SRC / "web" / "static" / "js" / "shared" / "unattended_monitor.js"
        ).read_text(encoding="utf-8")
        for char in source:
            if ord(char) < 32 and char not in "\t\n\r":
                pytest.fail(f"unexpected control character {ord(char)!r}")

    def test_monitor_and_center_escape_server_data(self):
        """Titles and stage messages come from the DB and are injected via innerHTML."""
        shared = SRC / "web" / "static" / "js" / "shared"
        for name in ("unattended_monitor.js", "notification_center.js"):
            source = (shared / name).read_text(encoding="utf-8")
            assert "function escapeHtml(" in source, name
            assert ".replace(/</g, '&lt;')" in source, name


class TestTemplatesRender:
    """Render the touched templates for real — static string assertions elsewhere in
    this file cannot catch a Jinja syntax error or a missing context variable."""

    @pytest.fixture(scope="class")
    def env(self):
        from landppt.web.route_modules.support import templates

        return templates

    @pytest.fixture(scope="class")
    def fixtures(self):
        import time
        from types import SimpleNamespace

        def stage(stage_id, name, status="pending"):
            return SimpleNamespace(
                id=stage_id, name=name, description="", status=status, progress=0.0,
                subtasks=[], result={}, created_at=time.time(), updated_at=time.time(),
            )

        todo_board = SimpleNamespace(
            task_id="proj-1", title="测试主题",
            stages=[
                stage("requirements_confirmation", "需求确认", "completed"),
                stage("outline_generation", "大纲生成", "running"),
                stage("ppt_creation", "PPT生成"),
            ],
            current_stage_index=1, overall_progress=33.0,
            created_at=time.time(), updated_at=time.time(),
        )
        project = SimpleNamespace(
            project_id="proj-1", title="测试", scenario="general", topic="测试主题",
            user_id=1, requirements=None, status="in_progress",
            outline={"slides": [{"page_number": 1, "title": "封面"}]},
            slides_html=None,
            slides_data=[{"page_number": 1, "html_content": "<div>x</div>", "title": "封面"}],
            confirmed_requirements={"topic": "测试主题"},
            project_metadata={"language": "zh"}, todo_board=todo_board,
            version=1, versions=[], created_at=time.time(), updated_at=time.time(),
        )
        user = SimpleNamespace(id=1, username="admin", is_admin=True, email="a@b.c")
        request = SimpleNamespace(
            state=SimpleNamespace(user=user), url=SimpleNamespace(path="/"),
            scope={"type": "http"}, query_params={},
        )
        return SimpleNamespace(
            todo_board=todo_board, project=project, user=user, request=request
        )

    def test_creation_page_seeds_controls_from_saved_settings(self, env, fixtures):
        html = env.get_template("pages/project/scenarios.html").render(
            request=fixtures.request,
            scenarios=[
                {"id": "general", "name": "通用", "description": "d", "icon": "📚"}
            ],
            selected_scenario="general",
            unattended_defaults={
                "stop_after": "video",
                "notify_in_app": True,
                "notify_email": True,
                "language": "zh",
                "template_id": None,
                "tts_provider": "edge_tts",
                "tts_voice": None,
                "tts_rate": "+0%",
                "fps": 30,
                "render_mode": "live",
                "embed_subtitles": True,
            },
        )
        data = creation_page_data(html)
        assert data["createDefaults"] == dict(
            stop_at_stage="video",
            unattended_notify_in_app=True,
            unattended_notify_email=True,
        )
        assert data["user"]["is_admin"] is True

    def test_creation_page_offers_the_template_choice(self, env, fixtures):
        """Unattended skips the template-selection page, so the choice must be here."""
        html = env.get_template("pages/project/scenarios.html").render(
            request=fixtures.request,
            scenarios=[
                {"id": "general", "name": "通用", "description": "d", "icon": "📚"}
            ],
            selected_scenario="general",
            template_options=[
                {"id": 3, "name": "商务简约", "is_default": True},
                {"id": 9, "name": "科技风", "is_default": False},
            ],
            user=fixtures.user,
        )
        assert creation_page_data(html)["templateOptions"] == [
            {"id": 3, "name": "商务简约", "is_default": True},
            {"id": 9, "name": "科技风", "is_default": False},
        ]

    def test_creation_page_survives_an_empty_template_list(self, env, fixtures):
        """Template listing failures must not break project creation."""
        html = env.get_template("pages/project/scenarios.html").render(
            request=fixtures.request,
            scenarios=[
                {"id": "general", "name": "通用", "description": "d", "icon": "📚"}
            ],
            selected_scenario="general",
            template_options=[],
            user=fixtures.user,
        )
        assert creation_page_data(html)["templateOptions"] == []

    def test_workspace_shows_an_honest_placeholder_not_a_fake_skeleton(self, env, fixtures):
        html = env.get_template("pages/project/todo_board.html").render(
            request=fixtures.request, todo_board=fixtures.todo_board,
            project=fixtures.project, unattended_active=True, user=fixtures.user,
        )
        assert creation_page_data(html)["unattendedActive"] is True
        assert 'outline-placeholder' not in html and 'loading-brain' not in html

    def test_the_outline_card_has_a_real_anchor(self, env, fixtures):
        source = (REPO / "frontend/src/components/todo-outline.tsx").read_text(encoding="utf-8")
        assert 'aria-label="PPT 大纲工作区"' in source
        assert 'todoLegacyHost' not in source and 'workspace-body' not in source

    def test_the_dead_stage_poller_is_off_during_a_run(self, env, fixtures):
        source = (REPO / "frontend/src/controllers/outline-controller.ts").read_text(encoding="utf-8")
        policy = source[source.index("function shouldPoll()") :][:250]
        assert '!options.unattended' in policy

    def test_creation_page_falls_back_when_no_defaults_are_passed(self, env, fixtures):
        html = env.get_template("pages/project/scenarios.html").render(
            request=fixtures.request,
            scenarios=[
                {"id": "general", "name": "通用", "description": "d", "icon": "📚"}
            ],
            selected_scenario="general",
            user=fixtures.user,
        )
        assert creation_page_data(html)["createDefaults"]["stop_at_stage"] == "ppt"

    @pytest.mark.parametrize("active,expected", [(True, "true"), (False, "false")])
    def test_todo_board_exposes_the_unattended_flag(
        self, env, fixtures, active, expected
    ):
        html = env.get_template("pages/project/todo_board.html").render(
            request=fixtures.request,
            todo_board=fixtures.todo_board,
            project=fixtures.project,
            unattended_active=active,
            user=fixtures.user,
        )
        assert creation_page_data(html)["unattendedActive"] is active
        assert '"page": "todo"' in html

    def test_todo_board_defaults_the_flag_to_false_when_absent(self, env, fixtures):
        """A route that forgets the flag must not crash or auto-enable stand-down."""
        html = env.get_template("pages/project/todo_board.html").render(
            request=fixtures.request, todo_board=fixtures.todo_board,
            project=fixtures.project, user=fixtures.user,
        )
        assert creation_page_data(html)["unattendedActive"] is False

    def test_editor_workspace_wires_the_monitor_to_the_project(self, env, fixtures):
        html = env.get_template("pages/project/todo_board_with_editor.html").render(
            request=fixtures.request, todo_board=fixtures.todo_board,
            project=fixtures.project, unattended_active=False, auto_start=False,
            user=fixtures.user,
        )
        assert '"projectId": "proj-1"' in html
        assert "unattended_monitor.js" in html
        assert creation_page_data(html)["unattendedActive"] is False

    def test_editor_workspace_stands_down_when_a_run_is_active(self, env, fixtures):
        html = env.get_template("pages/project/todo_board_with_editor.html").render(
            request=fixtures.request, todo_board=fixtures.todo_board,
            project=fixtures.project, unattended_active=True, auto_start=True,
            user=fixtures.user,
        )
        assert creation_page_data(html)["unattendedActive"] is True

    def test_editor_workspace_defaults_the_flag_to_false_when_absent(self, env, fixtures):
        """A route that forgets the variable must render a safe, permissive page."""
        html = env.get_template("pages/project/todo_board_with_editor.html").render(
            request=fixtures.request, todo_board=fixtures.todo_board,
            project=fixtures.project, auto_start=False, user=fixtures.user,
        )
        assert creation_page_data(html)["unattendedActive"] is False

    def test_settings_page_round_trips_saved_values(self, env, fixtures):
        html = env.get_template("pages/settings/ai_config.html").render(
            request=fixtures.request, user=fixtures.user,
            current_provider="openai", available_providers=["openai"], provider_status={},
            current_config={
                "unattended_default_stop_stage": "narration_audio",
                "unattended_notify_in_app": True,
                "unattended_notify_email": True,
                "unattended_tts_provider": "xiaomimimo",
                "unattended_video_fps": "60",
                "unattended_video_render_mode": "static",
            },
        )
        assert 'name="unattended_default_stop_stage"' in html
        assert 'value="narration_audio" selected' in html
        assert 'value="xiaomimimo" selected' in html
        assert 'value="static" selected' in html
        assert 'value="60"' in html

    @pytest.mark.parametrize(
        "page,extra",
        [
            ("pages/project/todo_board.html", {}),
            ("pages/project/todo_board_with_editor.html", {"auto_start": False}),
        ],
    )
    def test_workspaces_render_data_without_retired_inline_controllers(self, env, fixtures, page, extra):
        """Both workspaces load built controllers and explicit, parseable JSON."""
        import re

        html = env.get_template(page).render(
            request=fixtures.request, todo_board=fixtures.todo_board,
            project=fixtures.project, unattended_active=True, user=fixtures.user, **extra
        )
        blocks = re.findall(
            r'<script(?![^>]*\bsrc=)(?![^>]*type="application/json")[^>]*>(.*?)</script>',
            html,
            re.S,
        )
        assert not blocks
        data = creation_page_data(html)
        if data["page"] == "todo":
            assert data["outlineInitial"]["stageStatus"]
            assert "outline_ui_bridge.js" not in html
        else:
            assert data["page"] == "generator-workspace"
            assert isinstance(data["generationInitial"]["slides"], list)
            assert data["unattendedActive"] is True
            assert "LandPPTGeneratorSurface" not in html

    def test_anonymous_visitors_get_no_bell_and_no_polling(self, env, fixtures):
        from types import SimpleNamespace

        anon_request = SimpleNamespace(
            state=SimpleNamespace(user=None), url=SimpleNamespace(path="/"),
            scope={"type": "http"}, query_params={},
        )
        html = env.get_template("pages/project/todo_board.html").render(
            request=anon_request, todo_board=fixtures.todo_board,
            project=fixtures.project, user=None,
        )
        assert 'id="navNotificationBell"' not in html
        assert "NotificationCenter?.mount(" not in html

    def test_logged_in_visitors_get_the_bell(self, env, fixtures):
        html = env.get_template("pages/project/todo_board.html").render(
            request=fixtures.request, todo_board=fixtures.todo_board,
            project=fixtures.project, user=fixtures.user,
        )
        data = creation_page_data(html)
        assert data["user"]["username"] == fixtures.user.username
        shell = (SRC.parent.parent / "frontend/src/shell.tsx").read_text(encoding="utf-8")
        assert 'id="navNotificationBell"' in shell
        assert 'id="navNotificationBadge"' in shell
        assert "NotificationCenter?.mount(" in shell


def test_smtp_send_does_not_block_the_event_loop():
    """SMTP is blocking; sending it inline stalls every request on the worker."""
    source = (SRC / "services" / "email_service.py").read_text(encoding="utf-8")
    smtp_block = source[source.index("# Default to SMTP") :]
    assert "await asyncio.to_thread(_send_smtp)" in smtp_block


def test_ppt_project_carries_its_owner():
    """Narration/video export resolves per-user TTS config via project.user_id."""
    from landppt.api.models import PPTProject

    assert "user_id" in PPTProject.model_fields
    source = (SRC / "database" / "service.py").read_text(encoding="utf-8")
    assert 'user_id=getattr(db_project, "user_id", None),' in source
