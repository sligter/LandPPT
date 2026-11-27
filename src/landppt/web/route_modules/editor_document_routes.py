"""Authenticated, revision-checked text editing for the presentation sidebar."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...auth.middleware import get_current_user_required
from ...database.database import AsyncSessionLocal
from ...database.models import User
from ...services.editor_document_service import EditorDocumentService
from ...services.editor_outline_batch_service import EditorOutlineBatchService

router = APIRouter()


class OutlinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=255)
    slide_type: str = Field(min_length=1, max_length=50)
    subtitle: str = Field(default="", max_length=10000)
    description: str = Field(default="", max_length=20000)
    content_points: list[str] = Field(default_factory=list, max_length=100)
    content: str = Field(default="", max_length=50000)


class SpeechPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    script_content: str = Field(min_length=1, max_length=100000)
    slide_title: str = Field(min_length=1, max_length=255)
    estimated_duration: str = Field(default="", max_length=50)
    speaker_notes: str = Field(default="", max_length=20000)


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["outline", "speech"]
    revision: str = Field(min_length=64, max_length=64)
    slide_id: str | None = Field(default=None, max_length=100)
    outline: OutlinePatch | None = None
    speech: SpeechPatch | None = None

    @model_validator(mode="after")
    def require_matching_payload(self):
        if (
            getattr(self, self.kind) is None
            or getattr(self, "speech" if self.kind == "outline" else "outline")
            is not None
        ):
            raise ValueError("Provide only the matching document payload")
        return self


class BatchOutlineChanges(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    slide_type: str | None = Field(default=None, min_length=1, max_length=50)
    content_points: list[Annotated[str, Field(min_length=1, max_length=2000)]] | None = Field(
        default=None, max_length=100
    )

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("Provide a title, page type, or content points")
        return self


class BatchOutlinePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slide_index: int = Field(ge=0, le=10000)
    slide_id: str | None = Field(max_length=100)
    revision: str = Field(min_length=64, max_length=64)
    changes: BatchOutlineChanges


class BatchOutlinePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_revision: str = Field(min_length=64, max_length=64)
    pages: list[BatchOutlinePage] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_pages(self):
        if len({page.slide_index for page in self.pages}) != len(self.pages):
            raise ValueError("Select each page only once")
        return self


@router.get("/api/projects/{project_id}/editor-outline-batch")
async def read_outline_batch(
    project_id: str,
    response: Response,
    indices: list[Annotated[int, Field(ge=0, le=10000)]] = Query(
        min_length=1, max_length=50
    ),
    user: User = Depends(get_current_user_required),
):
    response.headers["Cache-Control"] = "no-store"
    async with AsyncSessionLocal() as session:
        result = await EditorOutlineBatchService(session).read(
            project_id, user.id, indices
        )
    return {"success": True, **result}


@router.patch("/api/projects/{project_id}/editor-outline-batch")
async def save_outline_batch(
    project_id: str,
    body: BatchOutlinePatch,
    response: Response,
    user: User = Depends(get_current_user_required),
):
    response.headers["Cache-Control"] = "no-store"
    async with AsyncSessionLocal() as session:
        result = await EditorOutlineBatchService(session).save(
            project_id, user.id, body
        )
    return {"success": True, **result}


@router.get("/api/projects/{project_id}/editor-documents/{slide_index}")
async def get_editor_document(
    project_id: str,
    slide_index: int,
    response: Response,
    language: Literal["zh", "en"] = "zh",
    slide_id: str | None = Query(default=None, max_length=100),
    user: User = Depends(get_current_user_required),
):
    response.headers["Cache-Control"] = "no-store"
    async with AsyncSessionLocal() as session:
        document = await EditorDocumentService(session).read(
            project_id, user.id, slide_index, language, slide_id
        )
    return {"success": True, "document": document}


@router.patch("/api/projects/{project_id}/editor-documents/{slide_index}")
async def save_editor_document(
    project_id: str,
    slide_index: int,
    body: DocumentPatch,
    response: Response,
    language: Literal["zh", "en"] = "zh",
    user: User = Depends(get_current_user_required),
):
    response.headers["Cache-Control"] = "no-store"
    async with AsyncSessionLocal() as session:
        document = await EditorDocumentService(session).save(
            project_id, user.id, slide_index, language, body
        )
    return {"success": True, "document": document}
