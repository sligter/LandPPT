"""
Narration Audio Repository
Stores slide-level TTS audio cache entries.
"""

import time
from typing import Optional, List

from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..database.database import SessionLocal
from ..database.models import NarrationAudio


class NarrationAudioRepository:
    def __init__(self, db: Session = None):
        self.db = db
        self._should_close_db = db is None
        if self.db is None:
            self.db = SessionLocal()

    async def get_cached_audio(
        self,
        *,
        project_id: str,
        slide_index: int,
        language: str,
        provider: str,
        voice: str,
        rate: str,
        content_hash: str,
    ) -> Optional[NarrationAudio]:
        return (
            self.db.query(NarrationAudio)
            .filter(
                and_(
                    NarrationAudio.project_id == project_id,
                    NarrationAudio.slide_index == slide_index,
                    NarrationAudio.language == (language or "zh"),
                    NarrationAudio.provider == provider,
                    NarrationAudio.voice == voice,
                    NarrationAudio.rate == rate,
                    NarrationAudio.content_hash == content_hash,
                )
            )
            .first()
        )

    async def upsert_audio(
        self,
        *,
        project_id: str,
        slide_index: int,
        language: str,
        provider: str,
        voice: str,
        rate: str,
        audio_format: str,
        content_hash: str,
        file_path: str,
        duration_ms: Optional[int],
        cues_json: Optional[str] = None,
    ) -> NarrationAudio:
        existing = await self.get_cached_audio(
            project_id=project_id,
            slide_index=slide_index,
            language=language,
            provider=provider,
            voice=voice,
            rate=rate,
            content_hash=content_hash,
        )

        if existing:
            existing.audio_format = audio_format
            existing.file_path = file_path
            existing.duration_ms = duration_ms
            if cues_json is not None:
                existing.cues_json = cues_json
            existing.updated_at = time.time()
            self.db.commit()
            self.db.refresh(existing)
            return existing

        row = NarrationAudio(
            project_id=project_id,
            slide_index=slide_index,
            language=(language or "zh"),
            provider=provider,
            voice=voice,
            rate=rate,
            audio_format=audio_format,
            content_hash=content_hash,
            file_path=file_path,
            duration_ms=duration_ms,
            cues_json=cues_json,
            created_at=time.time(),
            updated_at=time.time(),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    async def list_by_project(self, *, project_id: str, language: str = "zh") -> List[NarrationAudio]:
        return (
            self.db.query(NarrationAudio)
            .filter(
                and_(
                    NarrationAudio.project_id == project_id,
                    NarrationAudio.language == (language or "zh"),
                )
            )
            .order_by(NarrationAudio.slide_index.asc())
            .all()
        )

    async def get_latest_for_slide(
        self, *, project_id: str, slide_index: int, language: str = "zh"
    ) -> Optional[NarrationAudio]:
        return (
            self.db.query(NarrationAudio)
            .filter(
                and_(
                    NarrationAudio.project_id == project_id,
                    NarrationAudio.slide_index == slide_index,
                    NarrationAudio.language == (language or "zh"),
                )
            )
            .order_by(NarrationAudio.updated_at.desc())
            .first()
        )

    def close(self):
        if self._should_close_db and self.db:
            self.db.close()
