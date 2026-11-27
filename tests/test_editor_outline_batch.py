"""Atomic outline batches retain artwork and reject stale/foreign writes."""

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete, select, update

from test_editor_document_service import documents, save, snapshot  # noqa: F401
from landppt.auth.middleware import get_current_user_required
from landppt.database.models import (
    AsyncTask,
    Project,
    SlideData,
    SpeechScript,
    TodoBoard,
    TodoStage,
)
from landppt.services.editor_outline_batch_service import EditorOutlineBatchService
from landppt.web.route_modules import editor_document_routes as routes


@pytest_asyncio.fixture
async def batches(documents, monkeypatch):
    factory, original = documents
    monkeypatch.setattr(routes, "AsyncSessionLocal", factory)
    app = FastAPI()
    app.include_router(routes.router)
    user = SimpleNamespace(id=7, is_admin=False)
    app.dependency_overrides[get_current_user_required] = lambda: user
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            factory=factory, original=original, client=client, user=user
        )


URL = "/api/projects/document-test/editor-outline-batch"


async def read(state, indices=(0, 1)):
    response = await state.client.get(
        URL, params=[("indices", index) for index in indices]
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def patch(snapshot):
    return dict(
        project_revision=snapshot["project_revision"],
        pages=[
            dict(
                slide_index=item["slide_index"],
                slide_id=item["slide_id"],
                revision=item["outline_revision"],
                changes=dict(
                    title=f"新标题 {item['slide_index'] + 1}", slide_type="transition"
                ),
            )
            for item in snapshot["pages"]
        ],
    )


@pytest.mark.asyncio
async def test_batch_preserves_artwork_unknown_fields_and_other_documents(batches):
    state = batches
    before = await read(state)
    assert before["editable"] and "unchanged canvas" not in str(before)
    response = await state.client.patch(URL, json=patch(before))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["project_revision"] != before["project_revision"]
    assert [item["outline"]["title"] for item in result["pages"]] == [
        "新标题 1",
        "新标题 2",
    ]
    async with state.factory() as session:
        project = await session.scalar(select(Project))
        assert project.outline["custom"] == state.original["custom"]
        assert project.outline["slides"][0]["visual"] == {"layout": "cover"}
        assert project.outline["slides"][0]["content_points"] == ["原始要点"]
        assert (
            project.slides_html == "unchanged combined artwork"
            and project.slides_data[0]["html_content"] == "unchanged canvas"
        )
        assert project.version == 1 and project.status == "completed"
        assert project.confirmed_requirements == {
            "keep": True
        } and project.project_metadata == {"renderer": "svg"}
        slides = (
            await session.scalars(select(SlideData).order_by(SlideData.slide_index))
        ).all()
        assert [row.title for row in slides] == ["新标题 1", "新标题 2"]
        assert [row.html_content for row in slides] == [
            "unchanged canvas",
            "second canvas",
        ]
        assert slides[0].slide_metadata["locked"] and not slides[0].is_user_edited
        assert (await session.scalar(select(SpeechScript))).script_content == "原始讲稿"


@pytest.mark.asyncio
async def test_one_conflicting_page_prevents_every_write(batches):
    body = patch(await read(batches))
    body["pages"][1]["revision"] = "0" * 64
    assert (await batches.client.patch(URL, json=body)).status_code == 409
    async with batches.factory() as session:
        assert (await session.scalar(select(Project))).outline == batches.original
        assert (
            await session.scalar(select(SlideData).where(SlideData.slide_index == 0))
        ).title == "封面"


@pytest.mark.asyncio
async def test_outline_only_batch_edits_points_without_creating_slides(batches):
    async with batches.factory() as session:
        await session.execute(delete(SlideData))
        await session.execute(update(Project).values(slides_data=[]))
        await session.commit()
    before = await read(batches)
    assert all(page["slide_id"] is None for page in before["pages"])
    payload = patch(before)
    payload["pages"][0]["changes"] = {"content_points": ["新要点"]}
    payload["pages"][1]["changes"] = {"title": "新标题"}
    response = await batches.client.patch(URL, json=payload)
    assert response.status_code == 200, response.text
    async with batches.factory() as session:
        project = await session.scalar(select(Project))
        assert project.outline["slides"][0] == {
            **batches.original["slides"][0], "content_points": ["新要点"],
        }
        assert project.outline["slides"][1] == {
            **batches.original["slides"][1], "title": "新标题",
        }
        assert project.slides_data == []
        assert (await session.scalars(select(SlideData))).all() == []


@pytest.mark.asyncio
async def test_project_conflict_after_other_window_saves_preserves_that_write(batches):
    body = patch(await read(batches))
    await save(
        batches.factory,
        await snapshot(batches.factory),
        "outline",
        dict(title="另一个窗口", slide_type="content"),
    )
    response = await batches.client.patch(URL, json=body)
    assert response.status_code == 409
    async with batches.factory() as session:
        project = await session.scalar(select(Project))
        assert project.outline["slides"][0]["title"] == "另一个窗口"
        assert project.outline["slides"][1] == batches.original["slides"][1]


@pytest.mark.asyncio
@pytest.mark.parametrize("admin", [False, True])
async def test_owner_is_required_even_for_admin(batches, admin):
    body = patch(await read(batches))
    batches.user.id, batches.user.is_admin = 99, admin
    assert (await batches.client.get(URL, params=[("indices", 0)])).status_code == 404
    assert (await batches.client.patch(URL, json=body)).status_code == 404


@pytest.mark.asyncio
async def test_changed_page_identity_rejects_whole_batch(batches):
    body = patch(await read(batches))
    body["pages"][1]["slide_id"] = "stable-cover"
    assert (await batches.client.patch(URL, json=body)).status_code == 409
    async with batches.factory() as session:
        assert (await session.scalar(select(Project))).outline == batches.original


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["stage", "pending", "queued", "running"])
async def test_busy_project_cannot_save_batch(batches, kind):
    body = patch(await read(batches))
    async with batches.factory() as session:
        if kind == "stage":
            board = TodoBoard(project_id="document-test")
            session.add(board)
            await session.flush()
            session.add(
                TodoStage(
                    project_id="document-test",
                    todo_board_id=board.id,
                    stage_id="ppt_creation",
                    stage_index=3,
                    title="generate",
                    description="",
                    status="running",
                )
            )
        else:
            session.add(
                AsyncTask(
                    id="active",
                    project_id="document-test",
                    user_id=7,
                    task_type="unattended_generation",
                    status=kind,
                )
            )
        await session.commit()
    assert not (await read(batches))["editable"]
    assert (await batches.client.patch(URL, json=body)).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["project", "task"])
async def test_cas_rechecks_project_and_task_after_validation(
    batches, monkeypatch, race
):
    body = patch(await read(batches))
    original_load = EditorOutlineBatchService._load

    async def raced(self, *args, **kwargs):
        loaded = await original_load(self, *args, **kwargs)
        async with batches.factory() as session:
            if race == "project":
                await session.execute(
                    update(Project).values(updated_at=Project.updated_at + 1)
                )
            else:
                session.add(
                    AsyncTask(
                        id="raced",
                        project_id="document-test",
                        user_id=7,
                        task_type="unattended_generation",
                        status="queued",
                    )
                )
            await session.commit()
        return loaded

    monkeypatch.setattr(EditorOutlineBatchService, "_load", raced)
    assert (await batches.client.patch(URL, json=body)).status_code == 409
    async with batches.factory() as session:
        assert (await session.scalar(select(Project))).outline == batches.original


@pytest.mark.asyncio
async def test_legacy_json_only_page_uses_same_fallback_as_single_editor(batches):
    async with batches.factory() as session:
        await session.execute(delete(SlideData))
        project = await session.scalar(select(Project))
        project.outline = None
        await session.commit()
    result = await read(batches, (0,))
    assert result["pages"][0]["slide_id"] is None
    response = await batches.client.patch(URL, json=patch(result))
    assert response.status_code == 200
    async with batches.factory() as session:
        project = await session.scalar(select(Project))
        assert project.slides_data[0]["html_content"] == "unchanged canvas"
        assert project.slides_data[0]["custom"] == "keep"
        assert project.outline["slides"][0]["title"] == "新标题 1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"title": " "},
        {"title": None},
        {"slide_type": None},
        {"title": "a" * 256},
        {"html_content": "forbidden"},
    ],
)
async def test_invalid_fields_fail_before_any_write(batches, changes):
    body = patch(await read(batches))
    body["pages"][1]["changes"] = changes
    assert (await batches.client.patch(URL, json=body)).status_code == 422
    async with batches.factory() as session:
        assert (await session.scalar(select(Project))).outline == batches.original


@pytest.mark.asyncio
async def test_duplicate_empty_missing_and_oversized_selections(batches):
    snapshot = await read(batches)
    body = patch(snapshot)
    for indices, expected in [
        ([], 422),
        ([0, 0], 422),
        ([-1], 422),
        ([999], 409),
        (list(range(51)), 422),
    ]:
        assert (
            await batches.client.get(
                URL, params=[("indices", index) for index in indices]
            )
        ).status_code == expected
    for pages in [[], [body["pages"][0]] * 2, [body["pages"][0]] * 51]:
        assert (
            await batches.client.patch(URL, json={**body, "pages": pages})
        ).status_code == 422


@pytest.mark.asyncio
async def test_title_only_patch_does_not_rewrite_type_or_unselected_page(batches):
    before = await read(batches, (0,))
    body = patch(before)
    body["pages"][0]["changes"] = {"title": "仅更新标题"}
    assert (await batches.client.patch(URL, json=body)).status_code == 200
    async with batches.factory() as session:
        project = await session.scalar(select(Project))
        assert project.outline["slides"][0]["slide_type"] == "title"
        assert project.outline["slides"][1] == batches.original["slides"][1]
