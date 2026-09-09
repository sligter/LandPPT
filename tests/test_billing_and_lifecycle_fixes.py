"""Regression tests for billing consistency, task lifecycle and leftover defects."""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "landppt"


def _read(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _slice(source: str, marker: str, length: int = 1600) -> str:
    assert marker in source, f"marker not found: {marker}"
    return source[source.index(marker) :][:length]


def _class_methods(path: Path, class_name: str) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                m.name
                for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"class {class_name} not found in {path}")


class TestBillingOnlyForPersistedWork:
    def test_batch_regenerate_bills_persisted_count(self):
        source = _read("web/route_modules/slide_routes.py")
        assert "persisted_count = 0" in source
        assert "updated_count = persisted_count" in source
        body = _slice(source, "persisted_count = 0", 2200)
        assert "if saved:" in body
        assert "persisted_count += 1" in body

    def test_save_failure_is_reported_not_swallowed(self):
        source = _read("web/route_modules/slide_routes.py")
        assert "persist_error" in source
        assert "部分幻灯片保存失败" in source

    def test_failed_save_marks_the_result_unsuccessful(self):
        source = _read("web/route_modules/slide_routes.py")
        body = _slice(source, "persisted_count = 0", 2200)
        assert 'r["success"] = False' in body


class TestOutlineBillingParity:
    def test_non_streaming_bills_by_llm_call_count(self):
        source = _read("web/route_modules/outline_generation_routes.py")
        assert "_resolve_outline_llm_call_count(outline, default=1)" in source
        # Only the *charge* must scale; the pre-flight affordability check may
        # legitimately probe for a single credit.
        consume_blocks = [
            source[match:match + 400]
            for match in [
                index for index in range(len(source))
                if source.startswith("await consume_credits_for_operation(", index)
            ]
        ]
        assert consume_blocks, "no billing call found"
        assert not any(
            '"outline_generation", 1,' in block for block in consume_blocks
        ), "flat-rate billing diverged from the streaming route"

    def test_streaming_bills_before_yielding_done(self):
        source = _read("web/route_modules/outline_generation_routes.py")
        marker = "async for chunk in chunk_source:"
        body = _slice(source, marker, 2200)
        assert "consume_credits_for_operation" in body
        # The charge must be applied before the chunk reaches a client that may
        # then disconnect and close the generator.
        assert body.index("consume_credits_for_operation") < body.index("yield chunk")

    def test_stream_error_marks_the_stage_failed(self):
        source = _read("web/route_modules/outline_generation_routes.py")
        assert '"outline_generation", "failed"' in source


class TestSyncBatchRegenerateHasConcurrencyGuard:
    def test_sync_route_checks_for_an_active_task(self):
        source = _read("web/route_modules/slide_routes.py")
        marker = '@router.post("/api/projects/{project_id}/slides/batch-regenerate")'
        body = _slice(source, marker, 1500)
        assert "find_active_task_async" in body
        assert "already_processing" in body
        assert "status_code=409" in body


class TestStaleTaskRelease:
    def test_db_fallback_releases_stale_active_tasks(self):
        source = _read("services/background_tasks.py")
        marker = "task = await store.find_active_task(task_type, metadata_filter)"
        body = _slice(source, marker, 1600)
        assert "_is_task_stale(task)" in body
        assert "stale_active_task_released" in body
        assert "return None" in body


class TestOrphanedTasksAreCancelled:
    def test_outline_sse_generator_cancels_spawned_tasks(self):
        source = _read("web/route_modules/outline_support.py")
        assert "spawned_tasks: List[asyncio.Task] = []" in source
        assert "spawned_tasks.append(prepare_task)" in source
        assert "spawned_tasks.append(generation_task)" in source
        marker = "for task in spawned_tasks:"
        body = _slice(source, marker, 500)
        assert "task.cancel()" in body

    def test_research_stream_cancels_its_task(self):
        source = _read("services/outline/project_outline_streaming_service.py")
        assert "spawned_research_tasks: List[asyncio.Task] = []" in source
        marker = "for task in spawned_research_tasks:"
        body = _slice(source, marker, 500)
        assert "task.cancel()" in body


class TestCssDeclarationParsing:
    def test_data_url_is_not_split(self):
        from landppt.services.slide.edit_agent.html_safety import parse_style_declarations

        style = "background-image:url(data:image/svg+xml;base64,AAAA); color: red"
        parsed = parse_style_declarations(style)
        assert parsed["background-image"] == "url(data:image/svg+xml;base64,AAAA)"
        assert parsed["color"] == "red"

    def test_quoted_semicolon_is_preserved(self):
        from landppt.services.slide.edit_agent.html_safety import parse_style_declarations

        parsed = parse_style_declarations("content: 'a;b'; color: blue")
        assert parsed["content"] == "'a;b'"
        assert parsed["color"] == "blue"

    def test_nested_parens(self):
        from landppt.services.slide.edit_agent.html_safety import parse_style_declarations

        parsed = parse_style_declarations(
            "background: linear-gradient(to right, rgba(0,0,0,0.5), url(data:x;y)); margin: 0"
        )
        assert parsed["margin"] == "0"
        assert "linear-gradient" in parsed["background"]
        assert "data:x;y" in parsed["background"]

    def test_round_trip_keeps_the_data_url_intact(self):
        from landppt.services.slide.edit_agent.html_safety import (
            parse_style_declarations,
            serialize_style_declarations,
        )

        style = "background-image:url(data:image/svg+xml;base64,AAAA)"
        merged = parse_style_declarations(style)
        merged["color"] = "red"
        result = serialize_style_declarations(merged)
        assert "base64,AAAA)" in result
        assert parse_style_declarations(result)["color"] == "red"

    def test_plain_declarations_still_work(self):
        from landppt.services.slide.edit_agent.html_safety import parse_style_declarations

        parsed = parse_style_declarations("color: red; font-size: 12px;")
        assert parsed == {"color": "red", "font-size": "12px"}


class TestAwaitOnSyncMethodFixed:
    def test_creative_design_does_not_await_the_sync_fallback(self):
        source = _read("services/slide/creative_design_service.py")
        assert "await self._generate_fallback_slide_html(" not in source, (
            "every definition of this method is synchronous"
        )
        assert "self._generate_fallback_slide_html(" in source


class TestRegenerateSlideHandlesDictOutline:
    def test_outline_is_treated_as_a_dict(self):
        source = _read("services/slide/slide_streaming_service.py")
        # Ignore comments: the fix documents the old broken expression by name.
        code_lines = [
            line for line in source.splitlines() if not line.strip().startswith("#")
        ]
        assert not any("project.outline.slides" in line for line in code_lines), (
            "PPTProject.outline is a dict; attribute access raised AttributeError"
        )
        body = _slice(source, "async def regenerate_slide(", 2200)
        assert "outline.get('slides')" in body
        assert "isinstance(slides, list)" in body


class TestCachedDefaultsAreRetryable:
    def test_style_genes_failure_does_not_cache_defaults(self):
        source = _read("services/slide/creative_design_service.py")
        body = _slice(source, "提取项目 %s 的设计基因失败", 900)
        assert "extraction_failed = True" in body
        assert "events_dict.pop(project_id, None)" in body

    def test_constitution_failure_does_not_cache_defaults(self):
        source = _read("services/slide/creative_design_service.py")
        body = _slice(source, "生成全局宪法失败", 900)
        assert "constitution_failed = True" in body
        assert "events.pop(cache_key, None)" in body

    def test_page_brief_failure_is_retryable(self):
        source = _read("services/slide/creative_design_service.py")
        body = _slice(source, "生成页面类型指导失败", 900)
        assert "events.pop(cache_key, None)" in body

    def test_event_lookups_tolerate_a_popped_entry(self):
        """The three caches that now pop on failure must not index blindly.

        The fourth lookup (in the superseded _get_or_extract_style_genes_and_guide,
        which has no live callers) is already guarded by an `in` check.
        """
        source = _read("services/slide/creative_design_service.py")
        assert source.count("event = events_dict.get(project_id)") == 1
        assert source.count("event = events.get(cache_key)") == 2
        # The one remaining bare index is preceded by an explicit membership test.
        bare_index = "event = events_dict[project_id]"
        assert source.count(bare_index) == 1
        preceding = source[: source.index(bare_index)]
        assert "if project_id and project_id in events_dict:" in preceding


class TestRestoreProjectVersionWorks:
    def test_db_service_implements_restore(self):
        methods = _class_methods(SRC / "database" / "service.py", "DatabaseService")
        assert "restore_project_version" in methods

    def test_manager_forwards_restore(self):
        methods = _class_methods(
            SRC / "services" / "db_project_manager.py", "DatabaseProjectManager"
        )
        assert "restore_project_version" in methods

    def test_restore_replaces_slide_rows(self):
        source = _read("database/service.py")
        body = _slice(source, "async def restore_project_version(", 2600)
        assert "delete_slides_by_project_id" in body
        assert "create_slides" in body


class TestDuplicateUploadRouteRemoved:
    def test_only_one_upload_route_is_registered(self):
        source = _read("api/landppt_api.py")
        assert source.count('@router.post("/upload")') == 0
        assert source.count('@router.post("/upload", response_model=FileUploadResponse)') == 1


class TestDeadCodeRemoved:
    def test_unreachable_block_after_return_is_gone(self):
        source = _read("web/route_modules/outline_generation_routes.py")
        marker = '"message": "Outline regeneration scheduled"'
        first = source.index(marker)
        tail = source[first : first + 400]
        # The next statement after this return must be the else branch, not more code.
        assert "# Check if file path exists" not in tail


class TestLxmlIsDeclared:
    def test_pyproject_declares_lxml(self):
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert "lxml>=" in pyproject, (
            "lxml is imported directly; relying on it transitively made behaviour "
            "differ between installs"
        )
