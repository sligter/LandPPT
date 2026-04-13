"""
Speech Script Repository
数据访问层，处理演讲稿的数据库操作
"""

import time
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from ..database.models import SpeechScript
from ..database.database import get_db, SessionLocal


class SpeechScriptRepository:
    """演讲稿数据访问层"""

    def __init__(self, db: Session = None):
        self.db = db
        self._should_close_db = db is None
        if self.db is None:
            self.db = SessionLocal()
    
    async def save_speech_script(
        self,
        project_id: str,
        slide_index: int,
        language: str,
        slide_title: str,
        script_content: str,
        generation_params: Dict[str, Any],
        estimated_duration: Optional[str] = None,
        speaker_notes: Optional[str] = None
    ) -> SpeechScript:
        """保存演讲稿到数据库，如果已存在则覆盖"""

        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                # 先查找是否已存在该页面的演讲稿
                existing_script = self.db.query(SpeechScript).filter(
                    and_(
                        SpeechScript.project_id == project_id,
                        SpeechScript.slide_index == slide_index,
                        SpeechScript.language == (language or "zh"),
                    )
                ).first()

                if existing_script:
                    # 更新现有记录
                    existing_script.slide_title = slide_title
                    existing_script.script_content = script_content
                    existing_script.language = (language or "zh")
                    existing_script.estimated_duration = estimated_duration
                    existing_script.speaker_notes = speaker_notes
                    existing_script.generation_type = generation_params.get('generation_type', 'single')
                    existing_script.tone = generation_params.get('tone', 'conversational')
                    existing_script.target_audience = generation_params.get('target_audience', 'general_public')
                    existing_script.custom_audience = generation_params.get('custom_audience')
                    existing_script.language_complexity = generation_params.get('language_complexity', 'moderate')
                    existing_script.speaking_pace = generation_params.get('speaking_pace', 'normal')
                    existing_script.custom_style_prompt = generation_params.get('custom_style_prompt')
                    existing_script.include_transitions = generation_params.get('include_transitions', True)
                    existing_script.include_timing_notes = generation_params.get('include_timing_notes', False)
                    existing_script.updated_at = time.time()

                    self.db.commit()
                    self.db.refresh(existing_script)
                    return existing_script
                else:
                    # 创建新记录
                    speech_script = SpeechScript(
                        project_id=project_id,
                        slide_index=slide_index,
                        language=(language or "zh"),
                        slide_title=slide_title,
                        script_content=script_content,
                        estimated_duration=estimated_duration,
                        speaker_notes=speaker_notes,
                        generation_type=generation_params.get('generation_type', 'single'),
                        tone=generation_params.get('tone', 'conversational'),
                        target_audience=generation_params.get('target_audience', 'general_public'),
                        custom_audience=generation_params.get('custom_audience'),
                        language_complexity=generation_params.get('language_complexity', 'moderate'),
                        speaking_pace=generation_params.get('speaking_pace', 'normal'),
                        custom_style_prompt=generation_params.get('custom_style_prompt'),
                        include_transitions=generation_params.get('include_transitions', True),
                        include_timing_notes=generation_params.get('include_timing_notes', False),
                        created_at=time.time(),
                        updated_at=time.time()
                    )

                    self.db.add(speech_script)
                    self.db.commit()
                    self.db.refresh(speech_script)
                    return speech_script

            except Exception as e:
                self.db.rollback()
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    import asyncio
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    raise
    
    async def get_speech_scripts_by_project(
        self,
        project_id: str,
        language: str = "zh",
        limit: Optional[int] = None
    ) -> List[SpeechScript]:
        """获取项目的所有演讲稿"""
        
        query = self.db.query(SpeechScript).filter(
            and_(
                SpeechScript.project_id == project_id,
                SpeechScript.language == (language or "zh"),
            )
        ).order_by(
            SpeechScript.slide_index.asc(),
            SpeechScript.created_at.desc()
        )
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    async def get_speech_scripts_by_slide(
        self,
        project_id: str,
        slide_index: int,
        language: str = "zh",
        limit: Optional[int] = None
    ) -> List[SpeechScript]:
        """获取特定幻灯片的演讲稿历史"""
        
        query = self.db.query(SpeechScript).filter(
            and_(
                SpeechScript.project_id == project_id,
                SpeechScript.slide_index == slide_index,
                SpeechScript.language == (language or "zh"),
            )
        ).order_by(desc(SpeechScript.created_at))
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    async def get_current_speech_scripts_by_project(
        self,
        project_id: str,
        language: str = "zh",
    ) -> List[SpeechScript]:
        """获取项目每个幻灯片的当前演讲稿（每页只有一个）"""

        return self.db.query(SpeechScript).filter(
            and_(
                SpeechScript.project_id == project_id,
                SpeechScript.language == (language or "zh"),
            )
        ).order_by(SpeechScript.slide_index.asc()).all()

    async def get_speech_script_by_slide(
        self,
        project_id: str,
        slide_index: int,
        language: str = "zh",
    ) -> Optional[SpeechScript]:
        """获取特定幻灯片的演讲稿"""

        return self.db.query(SpeechScript).filter(
            and_(
                SpeechScript.project_id == project_id,
                SpeechScript.slide_index == slide_index,
                SpeechScript.language == (language or "zh"),
            )
        ).first()
    
    async def get_speech_script_by_id(self, script_id: int) -> Optional[SpeechScript]:
        """根据ID获取演讲稿"""
        return self.db.query(SpeechScript).filter(SpeechScript.id == script_id).first()
    
    async def delete_speech_script(self, script_id: int) -> bool:
        """删除演讲稿"""
        script = await self.get_speech_script_by_id(script_id)
        if script:
            self.db.delete(script)
            self.db.commit()
            return True
        return False
    
    async def delete_speech_scripts_by_project(self, project_id: str) -> int:
        """删除项目的所有演讲稿"""
        count = self.db.query(SpeechScript).filter(
            SpeechScript.project_id == project_id
        ).count()
        
        self.db.query(SpeechScript).filter(
            SpeechScript.project_id == project_id
        ).delete()
        
        self.db.commit()
        return count
    
    async def get_speech_scripts_grouped_by_slide(
        self,
        project_id: str,
        language: str = "zh",
    ) -> Dict[int, List[SpeechScript]]:
        """获取按幻灯片分组的演讲稿"""
        
        scripts = await self.get_speech_scripts_by_project(project_id, language=language)
        grouped = {}
        
        for script in scripts:
            if script.slide_index not in grouped:
                grouped[script.slide_index] = []
            grouped[script.slide_index].append(script)
        
        return grouped

    def close(self):
        """关闭数据库连接"""
        if self._should_close_db and self.db:
            self.db.close()
