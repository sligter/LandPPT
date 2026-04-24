"""
Database migration utilities for LandPPT
"""

import os
import time
import logging
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .database import AsyncSessionLocal, async_engine
from .models import Base, UserMetrics

logger = logging.getLogger(__name__)


class DatabaseMigration:
    """Database migration manager"""
    
    def __init__(self):
        self.migrations = []
        self._register_migrations()
    
    def _register_migrations(self):
        """Register all available migrations"""
        # Migration 001: Initial schema
        self.migrations.append({
            "version": "001",
            "name": "initial_schema",
            "description": "Create initial database schema",
            "up": self._migration_001_up,
            "down": self._migration_001_down
        })
        
        # Migration 002: Add indexes
        self.migrations.append({
            "version": "002",
            "name": "add_indexes",
            "description": "Add performance indexes",
            "up": self._migration_002_up,
            "down": self._migration_002_down
        })

        # Migration 003: Add project_id to todo_stages
        self.migrations.append({
            "version": "003",
            "name": "add_project_id_to_todo_stages",
            "description": "Add project_id column to todo_stages table for better indexing",
            "up": self._migration_003_up,
            "down": self._migration_003_down
        })

        # Migration 004: Add PPT templates table
        self.migrations.append({
            "version": "004",
            "name": "add_ppt_templates_table",
            "description": "Add PPT templates table and update slide_data table",
            "up": self._migration_004_up,
            "down": self._migration_004_down
        })

        # Migration 005: Add project_metadata column to projects table
        self.migrations.append({
            "version": "005",
            "name": "add_project_metadata_to_projects",
            "description": "Add project_metadata column to projects table for storing template selection and other metadata",
            "up": self._migration_005_up,
            "down": self._migration_005_down
        })

        # Migration 006: Add is_user_edited field to slide_data table
        self.migrations.append({
            "version": "006",
            "name": "add_is_user_edited_to_slide_data",
            "description": "Add is_user_edited field to slide_data table to track user manual edits",
            "up": self._migration_006_up,
            "down": self._migration_006_down
        })

        # Migration 007: Add speech script language + narration audio cache
        self.migrations.append({
            "version": "007",
            "name": "add_narration_audio_and_speech_language",
            "description": "Add language column to speech_scripts and create narration_audios table",
            "up": self._migration_007_up,
            "down": self._migration_007_down
        })

        # Migration 008: Add cues_json to narration_audios for timed subtitles
        self.migrations.append({
            "version": "008",
            "name": "add_narration_audio_cues_json",
            "description": "Add cues_json column to narration_audios for subtitle timing",
            "up": self._migration_008_up,
            "down": self._migration_008_down
        })

        # Migration 009: Update LandPPT default model from legacy gpt-4o to MODEL1
        self.migrations.append({
            "version": "009",
            "name": "update_landppt_default_model",
            "description": "Update system default landppt_model from gpt-4o to MODEL1",
            "up": self._migration_009_up,
            "down": self._migration_009_down,
        })

        # Migration 010: Add per-user ownership for global master templates
        self.migrations.append({
            "version": "010",
            "name": "add_user_scope_to_global_master_templates",
            "description": "Add user_id column/index to global_master_templates for per-user isolation",
            "up": self._migration_010_up,
            "down": self._migration_010_down,
        })

        # Migration 011: Community operations schema
        self.migrations.append({
            "version": "011",
            "name": "add_community_operations_schema",
            "description": "Add invite codes, daily check-ins, sponsor profiles, and registration source fields",
            "up": self._migration_011_up,
            "down": self._migration_011_down,
        })

        # Migration 012: User metrics summary table
        self.migrations.append({
            "version": "012",
            "name": "add_user_metrics_table",
            "description": "Add aggregated user_metrics table and backfill existing users",
            "up": self._migration_012_up,
            "down": self._migration_012_down,
        })

    @staticmethod
    def _dialect_name(session: AsyncSession) -> str:
        try:
            bind = session.get_bind()
        except Exception:
            bind = getattr(session, "bind", None)
        try:
            name = getattr(getattr(bind, "dialect", None), "name", None)
            return str(name or "").lower()
        except Exception:
            return ""

    async def _column_exists(self, session: AsyncSession, table_name: str, column_name: str) -> bool:
        dialect = self._dialect_name(session)
        table_name = (table_name or "").strip().lower()
        column_name = (column_name or "").strip().lower()
        if not table_name or not column_name:
            return False

        if dialect == "sqlite":
            result = await session.execute(text(f"PRAGMA table_info({table_name})"))
            columns = result.fetchall()
            existing = {str(col[1]).lower() for col in columns}
            return column_name in existing

        # PostgreSQL / other SQL databases: use information_schema
        result = await session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                  AND column_name = :column_name
                LIMIT 1
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        )
        return result.first() is not None

    async def _table_exists(self, session: AsyncSession, table_name: str) -> bool:
        """Dialect-aware table existence check (sqlite/postgres)."""
        dialect = self._dialect_name(session)
        table_name = (table_name or "").strip().lower()
        if not table_name:
            return False

        if dialect == "sqlite":
            result = await session.execute(
                text(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND lower(name) = :table_name
                    LIMIT 1
                    """
                ),
                {"table_name": table_name},
            )
            return result.first() is not None

        # PostgreSQL / other SQL databases: use information_schema
        result = await session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                LIMIT 1
                """
            ),
            {"table_name": table_name},
        )
        return result.first() is not None
    
    async def _migration_001_up(self, session: AsyncSession):
        """Create initial schema"""
        logger.info("Running migration 001: Creating initial schema")
        
        # Create all tables
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Migration 001 completed successfully")
    
    async def _migration_001_down(self, session: AsyncSession):
        """Drop initial schema"""
        logger.info("Rolling back migration 001: Dropping all tables")
        
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        
        logger.info("Migration 001 rollback completed")
    
    async def _migration_002_up(self, session: AsyncSession):
        """Add performance indexes"""
        logger.info("Running migration 002: Adding performance indexes")
        
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)",
            "CREATE INDEX IF NOT EXISTS idx_projects_scenario ON projects(scenario)",
            "CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_todo_stages_status ON todo_stages(status)",
            "CREATE INDEX IF NOT EXISTS idx_slide_data_slide_index ON slide_data(slide_index)",
            "CREATE INDEX IF NOT EXISTS idx_project_versions_timestamp ON project_versions(timestamp)"
        ]
        
        for index_sql in indexes:
            await session.execute(text(index_sql))
        
        await session.commit()
        logger.info("Migration 002 completed successfully")
    
    async def _migration_002_down(self, session: AsyncSession):
        """Remove performance indexes"""
        logger.info("Rolling back migration 002: Removing performance indexes")
        
        indexes = [
            "DROP INDEX IF EXISTS idx_projects_status",
            "DROP INDEX IF EXISTS idx_projects_scenario", 
            "DROP INDEX IF EXISTS idx_projects_created_at",
            "DROP INDEX IF EXISTS idx_todo_stages_status",
            "DROP INDEX IF EXISTS idx_slide_data_slide_index",
            "DROP INDEX IF EXISTS idx_project_versions_timestamp"
        ]
        
        for index_sql in indexes:
            await session.execute(text(index_sql))
        
        await session.commit()
        logger.info("Migration 002 rollback completed")

    async def _migration_003_up(self, session: AsyncSession):
        """Add project_id column to todo_stages table"""
        logger.info("Running migration 003: Adding project_id to todo_stages")

        try:
            # Check if project_id column already exists
            if not await self._column_exists(session, "todo_stages", "project_id"):
                # Add project_id column to todo_stages table
                await session.execute(text("""
                    ALTER TABLE todo_stages
                    ADD COLUMN project_id VARCHAR(36)
                """))
                logger.info("Added project_id column to todo_stages")
            else:
                logger.info("project_id column already exists in todo_stages")

            # Create index on project_id
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_todo_stages_project_id
                ON todo_stages(project_id)
            """))

            # Create index on stage_id for better performance
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_todo_stages_stage_id
                ON todo_stages(stage_id)
            """))

            # Populate project_id for existing records
            await session.execute(text("""
                UPDATE todo_stages
                SET project_id = (
                    SELECT tb.project_id
                    FROM todo_boards tb
                    WHERE tb.id = todo_stages.todo_board_id
                )
                WHERE project_id IS NULL
            """))

            await session.commit()
            logger.info("Migration 003 completed successfully")

        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 003 failed: {e}")
            raise

    async def _migration_003_down(self, session: AsyncSession):
        """Remove project_id column from todo_stages table"""
        logger.info("Rolling back migration 003: Removing project_id from todo_stages")

        try:
            # Drop indexes first
            await session.execute(text("DROP INDEX IF EXISTS idx_todo_stages_project_id"))
            await session.execute(text("DROP INDEX IF EXISTS idx_todo_stages_stage_id"))

            # Remove project_id column (SQLite doesn't support DROP COLUMN directly)
            # We need to recreate the table without the column
            await session.execute(text("""
                CREATE TABLE todo_stages_backup AS
                SELECT id, todo_board_id, stage_id, stage_index, title, description,
                       status, progress, result, created_at, updated_at
                FROM todo_stages
            """))

            await session.execute(text("DROP TABLE todo_stages"))

            await session.execute(text("""
                CREATE TABLE todo_stages (
                    id INTEGER PRIMARY KEY,
                    todo_board_id INTEGER NOT NULL,
                    stage_id VARCHAR(100) NOT NULL,
                    stage_index INTEGER NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    description TEXT NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    progress FLOAT DEFAULT 0.0,
                    result JSON,
                    created_at FLOAT,
                    updated_at FLOAT,
                    FOREIGN KEY (todo_board_id) REFERENCES todo_boards(id)
                )
            """))

            await session.execute(text("""
                INSERT INTO todo_stages
                SELECT * FROM todo_stages_backup
            """))

            await session.execute(text("DROP TABLE todo_stages_backup"))

            await session.commit()
            logger.info("Migration 003 rollback completed")

        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 003 rollback failed: {e}")
            raise

    async def _migration_004_up(self, session: AsyncSession):
        """Migration 004: Add PPT templates table and update slide_data table"""
        try:
            logger.info("Running migration 004: Adding PPT templates table")

            dialect = self._dialect_name(session)
            if dialect == "sqlite":
                # Create ppt_templates table (SQLite-specific DDL)
                create_templates_table_sql = """
                CREATE TABLE IF NOT EXISTS ppt_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id VARCHAR(36) NOT NULL,
                    template_type VARCHAR(50) NOT NULL,
                    template_name VARCHAR(255) NOT NULL,
                    description TEXT,
                    html_template TEXT NOT NULL,
                    applicable_scenarios JSON,
                    style_config JSON,
                    usage_count INTEGER DEFAULT 0,
                    created_at FLOAT NOT NULL,
                    updated_at FLOAT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects (project_id)
                )
                """
                await session.execute(text(create_templates_table_sql))
            else:
                # For PostgreSQL/others, rely on SQLAlchemy metadata to create the table correctly.
                conn = await session.connection()
                await conn.run_sync(Base.metadata.create_all, checkfirst=True)

            # Create indexes for ppt_templates
            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_ppt_templates_project_id
                ON ppt_templates (project_id)
            """))

            await session.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_ppt_templates_type
                ON ppt_templates (template_type)
            """))

            # Add template_id column to slide_data table
            if not await self._column_exists(session, "slide_data", "template_id"):
                await session.execute(
                    text(
                        """
                        ALTER TABLE slide_data
                        ADD COLUMN template_id INTEGER REFERENCES ppt_templates(id)
                        """
                    )
                )
            else:
                logger.info("template_id column already exists in slide_data table")

            await session.commit()
            logger.info("Migration 004 completed successfully")

        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 004 failed: {e}")
            raise

    async def _migration_004_down(self, session: AsyncSession):
        """Migration 004 rollback: Remove PPT templates table and template_id column"""
        try:
            logger.info("Rolling back migration 004")

            # Drop ppt_templates table
            await session.execute(text("DROP TABLE IF EXISTS ppt_templates"))

            # Remove template_id column from slide_data table
            # SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
            await session.execute(text("""
                CREATE TABLE slide_data_backup AS
                SELECT id, project_id, slide_index, slide_id, title, content_type,
                       html_content, slide_metadata, created_at, updated_at
                FROM slide_data
            """))

            await session.execute(text("DROP TABLE slide_data"))

            await session.execute(text("""
                CREATE TABLE slide_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id VARCHAR(36) NOT NULL,
                    slide_index INTEGER NOT NULL,
                    slide_id VARCHAR(100) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    content_type VARCHAR(50) NOT NULL,
                    html_content TEXT NOT NULL,
                    slide_metadata JSON,
                    created_at FLOAT NOT NULL,
                    updated_at FLOAT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects (project_id)
                )
            """))

            await session.execute(text("""
                INSERT INTO slide_data
                SELECT * FROM slide_data_backup
            """))

            await session.execute(text("DROP TABLE slide_data_backup"))

            await session.commit()
            logger.info("Migration 004 rollback completed")

        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 004 rollback failed: {e}")
            raise

    async def _migration_005_up(self, session: AsyncSession):
        """Migration 005: Add project_metadata column to projects table"""
        try:
            logger.info("Running migration 005: Adding project_metadata column to projects table")

            # Check if project_metadata column already exists
            if not await self._column_exists(session, "projects", "project_metadata"):
                # Add project_metadata column to projects table
                await session.execute(text("""
                    ALTER TABLE projects
                    ADD COLUMN project_metadata JSON
                """))
                logger.info("Added project_metadata column to projects table")
            else:
                logger.info("project_metadata column already exists in projects table")

            await session.commit()
            logger.info("Migration 005 completed successfully")

        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 005 failed: {e}")
            raise

    async def _migration_005_down(self, session: AsyncSession):
        """Migration 005 rollback: Remove project_metadata column from projects table"""
        try:
            logger.info("Rolling back migration 005: Removing project_metadata column from projects table")

            # SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
            await session.execute(text("""
                CREATE TABLE projects_backup AS
                SELECT id, project_id, title, scenario, topic, requirements, status,
                       outline, slides_html, slides_data, confirmed_requirements,
                       version, created_at, updated_at
                FROM projects
            """))

            await session.execute(text("DROP TABLE projects"))

            await session.execute(text("""
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id VARCHAR(36) UNIQUE NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    scenario VARCHAR(100) NOT NULL,
                    topic VARCHAR(255) NOT NULL,
                    requirements TEXT,
                    status VARCHAR(50) DEFAULT 'draft',
                    outline JSON,
                    slides_html TEXT,
                    slides_data JSON,
                    confirmed_requirements JSON,
                    version INTEGER DEFAULT 1,
                    created_at FLOAT NOT NULL,
                    updated_at FLOAT NOT NULL
                )
            """))

            await session.execute(text("""
                INSERT INTO projects
                SELECT * FROM projects_backup
            """))

            await session.execute(text("DROP TABLE projects_backup"))

            # Recreate indexes
            await session.execute(text("CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)"))
            await session.execute(text("CREATE INDEX IF NOT EXISTS idx_projects_scenario ON projects(scenario)"))
            await session.execute(text("CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects(created_at)"))

            await session.commit()
            logger.info("Migration 005 rollback completed")

        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 005 rollback failed: {e}")
            raise

    async def _migration_006_up(self, session: AsyncSession):
        """Migration 006: Add is_user_edited field to slide_data table"""
        try:
            logger.info("Running migration 006: Adding is_user_edited field to slide_data table")

            # Check if is_user_edited column already exists
            if not await self._column_exists(session, "slide_data", "is_user_edited"):
                # Add is_user_edited column to slide_data table
                default_value = "FALSE" if self._dialect_name(session).startswith("postgres") else "0"
                await session.execute(text("""
                    ALTER TABLE slide_data
                    ADD COLUMN is_user_edited BOOLEAN DEFAULT {default_value} NOT NULL
                """.format(default_value=default_value)))
                logger.info("Added is_user_edited column to slide_data table")
            else:
                logger.info("is_user_edited column already exists in slide_data table")

            await session.commit()
            logger.info("Migration 006 completed successfully")

        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 006 failed: {e}")
            raise

    async def _migration_006_down(self, session: AsyncSession):
        """Migration 006 rollback: Remove is_user_edited field from slide_data table"""
        try:
            logger.info("Rolling back migration 006: Removing is_user_edited field from slide_data table")

            # SQLite doesn't support DROP COLUMN directly, so we need to recreate the table
            await session.execute(text("""
                CREATE TABLE slide_data_backup AS
                SELECT id, project_id, slide_index, slide_id, title, content_type,
                       html_content, slide_metadata, template_id, created_at, updated_at
                FROM slide_data
            """))

            await session.execute(text("DROP TABLE slide_data"))

            await session.execute(text("""
                CREATE TABLE slide_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id VARCHAR(36) NOT NULL,
                    slide_index INTEGER NOT NULL,
                    slide_id VARCHAR(100) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    content_type VARCHAR(50) NOT NULL,
                    html_content TEXT NOT NULL,
                    slide_metadata JSON,
                    template_id INTEGER REFERENCES ppt_templates(id),
                    created_at FLOAT NOT NULL,
                    updated_at FLOAT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects (project_id)
                )
            """))

            await session.execute(text("""
                INSERT INTO slide_data
                SELECT * FROM slide_data_backup
            """))

            await session.execute(text("DROP TABLE slide_data_backup"))

            await session.commit()
            logger.info("Migration 006 rollback completed")

        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 006 rollback failed: {e}")
            raise

    async def _migration_007_up(self, session: AsyncSession):
        """Migration 007: Add language column to speech_scripts and create narration_audios table."""
        logger.info("Running migration 007: Adding speech script language and narration audio cache")
        try:
            dialect = self._dialect_name(session)

            # 1) speech_scripts.language (avoid transaction abort on PG by checking first)
            if not await self._column_exists(session, "speech_scripts", "language"):
                if dialect.startswith("postgres"):
                    await session.execute(
                        text(
                            "ALTER TABLE speech_scripts "
                            "ADD COLUMN language VARCHAR(10) NOT NULL DEFAULT 'zh'"
                        )
                    )
                else:
                    await session.execute(
                        text("ALTER TABLE speech_scripts ADD COLUMN language VARCHAR(10) DEFAULT 'zh'")
                    )
                logger.info("Added language column to speech_scripts")
            else:
                logger.info("language column already exists in speech_scripts")

            # Normalize existing rows (best-effort)
            await session.execute(
                text("UPDATE speech_scripts SET language='zh' WHERE language IS NULL OR language=''")
            )

            # Index for faster lookup by project/slide/language
            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_speech_scripts_project_slide_lang "
                    "ON speech_scripts(project_id, slide_index, language)"
                )
            )

            # 2) narration_audios table
            if dialect == "sqlite":
                await session.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS narration_audios (
                            id INTEGER PRIMARY KEY,
                            project_id VARCHAR(36) NOT NULL,
                            slide_index INTEGER NOT NULL,
                            language VARCHAR(10) NOT NULL DEFAULT 'zh',
                            provider VARCHAR(50) NOT NULL DEFAULT 'edge_tts',
                            voice VARCHAR(100) NOT NULL,
                            rate VARCHAR(20) NOT NULL DEFAULT '+0%',
                            audio_format VARCHAR(10) NOT NULL DEFAULT 'mp3',
                            content_hash VARCHAR(64) NOT NULL,
                            file_path TEXT NOT NULL,
                            duration_ms INTEGER,
                            created_at FLOAT NOT NULL,
                            updated_at FLOAT NOT NULL,
                            UNIQUE(project_id, slide_index, language, provider, voice, rate, content_hash)
                        )
                        """
                    )
                )
            else:
                # Let SQLAlchemy create the table with correct PK/identity for the DB.
                conn = await session.connection()
                await conn.run_sync(Base.metadata.create_all, checkfirst=True)

            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_narration_audios_project_slide_lang "
                    "ON narration_audios(project_id, slide_index, language)"
                )
            )
            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_narration_audios_content_hash "
                    "ON narration_audios(content_hash)"
                )
            )

            await session.commit()
            logger.info("Migration 007 completed successfully")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 007 failed: {e}")
            raise

    async def _migration_007_down(self, session: AsyncSession):
        """Migration 007 rollback (best-effort): Drop narration_audios and remove speech_scripts.language on SQLite."""
        logger.info("Rolling back migration 007: Removing narration_audios and speech_scripts.language")
        try:
            await session.execute(text("DROP INDEX IF EXISTS idx_narration_audios_project_slide_lang"))
            await session.execute(text("DROP INDEX IF EXISTS idx_narration_audios_content_hash"))
            await session.execute(text("DROP TABLE IF EXISTS narration_audios"))
            await session.execute(text("DROP INDEX IF EXISTS idx_speech_scripts_project_slide_lang"))

            # SQLite doesn't support DROP COLUMN; recreate speech_scripts without language.
            try:
                result = await session.execute(text("PRAGMA table_info(speech_scripts)"))
                columns = result.fetchall()
                column_names = [col[1] for col in columns]
                if "language" in column_names:
                    await session.execute(
                        text(
                            """
                            CREATE TABLE speech_scripts_backup AS
                            SELECT id, project_id, slide_index, slide_title, script_content, estimated_duration, speaker_notes,
                                   generation_type, tone, target_audience, custom_audience, language_complexity, speaking_pace,
                                   custom_style_prompt, include_transitions, include_timing_notes, created_at, updated_at
                            FROM speech_scripts
                            """
                        )
                    )
                    await session.execute(text("DROP TABLE speech_scripts"))
                    await session.execute(
                        text(
                            """
                            CREATE TABLE speech_scripts (
                                id INTEGER PRIMARY KEY,
                                project_id VARCHAR(36) NOT NULL,
                                slide_index INTEGER NOT NULL,
                                slide_title VARCHAR(255) NOT NULL,
                                script_content TEXT NOT NULL,
                                estimated_duration VARCHAR(50),
                                speaker_notes TEXT,
                                generation_type VARCHAR(20) NOT NULL,
                                tone VARCHAR(50) NOT NULL,
                                target_audience VARCHAR(100) NOT NULL,
                                custom_audience TEXT,
                                language_complexity VARCHAR(20) NOT NULL,
                                speaking_pace VARCHAR(20) NOT NULL,
                                custom_style_prompt TEXT,
                                include_transitions BOOLEAN NOT NULL DEFAULT 1,
                                include_timing_notes BOOLEAN NOT NULL DEFAULT 0,
                                created_at FLOAT NOT NULL,
                                updated_at FLOAT NOT NULL
                            )
                            """
                        )
                    )
                    await session.execute(
                        text(
                            """
                            INSERT INTO speech_scripts (
                                id, project_id, slide_index, slide_title, script_content, estimated_duration, speaker_notes,
                                generation_type, tone, target_audience, custom_audience, language_complexity, speaking_pace,
                                custom_style_prompt, include_transitions, include_timing_notes, created_at, updated_at
                            )
                            SELECT
                                id, project_id, slide_index, slide_title, script_content, estimated_duration, speaker_notes,
                                generation_type, tone, target_audience, custom_audience, language_complexity, speaking_pace,
                                custom_style_prompt, include_transitions, include_timing_notes, created_at, updated_at
                            FROM speech_scripts_backup
                            """
                        )
                    )
                    await session.execute(text("DROP TABLE speech_scripts_backup"))
            except Exception as column_error:
                logger.warning(f"Rollback of speech_scripts.language skipped/failed: {column_error}")

            await session.commit()
            logger.info("Migration 007 rollback completed")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 007 rollback failed: {e}")
            raise

    async def _migration_008_up(self, session: AsyncSession):
        """Migration 008: Add cues_json column to narration_audios for timed subtitles."""
        logger.info("Applying migration 008: Adding cues_json to narration_audios")
        try:
            if not await self._table_exists(session, "narration_audios"):
                logger.info("narration_audios table not found; skipping migration 008")
                return

            if await self._column_exists(session, "narration_audios", "cues_json"):
                logger.info("cues_json already exists on narration_audios; skipping migration 008")
                return

            dialect = self._dialect_name(session)
            if dialect == "sqlite":
                await session.execute(text("ALTER TABLE narration_audios ADD COLUMN cues_json TEXT"))
            else:
                await session.execute(text("ALTER TABLE narration_audios ADD COLUMN IF NOT EXISTS cues_json TEXT"))

            await session.commit()
            logger.info("Migration 008 completed successfully")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 008 failed: {e}")
            raise

    async def _migration_008_down(self, session: AsyncSession):
        """Migration 008 rollback (best-effort): Remove narration_audios.cues_json."""
        logger.info("Rolling back migration 008: Removing narration_audios.cues_json")
        try:
            if not await self._table_exists(session, "narration_audios"):
                return
            if not await self._column_exists(session, "narration_audios", "cues_json"):
                return

            dialect = self._dialect_name(session)
            if dialect == "sqlite":
                # SQLite doesn't support DROP COLUMN in older versions; best-effort no-op.
                logger.warning("SQLite DROP COLUMN not supported; skipping migration 008 down")
                return

            await session.execute(text("ALTER TABLE narration_audios DROP COLUMN IF EXISTS cues_json"))
            await session.commit()
            logger.info("Migration 008 rollback completed")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 008 rollback failed: {e}")
            raise

    async def _migration_009_up(self, session: AsyncSession):
        """Migration 009: Update system default landppt_model from legacy gpt-4o to MODEL1."""
        logger.info("Applying migration 009: Updating system default landppt_model to MODEL1")
        try:
            if not await self._table_exists(session, "user_configs"):
                logger.info("user_configs table not found; skipping migration 009")
                return

            now = time.time()
            await session.execute(
                text(
                    """
                    UPDATE user_configs
                    SET config_value = :new_value,
                        updated_at = :now
                    WHERE user_id IS NULL
                      AND config_key = :key
                      AND (config_value IS NULL OR TRIM(config_value) = :old_value)
                    """
                ),
                {
                    "new_value": "MODEL1",
                    "old_value": "gpt-4o",
                    "key": "landppt_model",
                    "now": now,
                },
            )
            await session.commit()
            logger.info("Migration 009 completed successfully")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 009 failed: {e}")
            raise

    async def _migration_009_down(self, session: AsyncSession):
        """Migration 009 rollback (best-effort): revert system default landppt_model to gpt-4o if currently MODEL1."""
        logger.info("Rolling back migration 009: Reverting system default landppt_model to gpt-4o (best-effort)")
        try:
            if not await self._table_exists(session, "user_configs"):
                return

            now = time.time()
            await session.execute(
                text(
                    """
                    UPDATE user_configs
                    SET config_value = :old_value,
                        updated_at = :now
                    WHERE user_id IS NULL
                      AND config_key = :key
                      AND TRIM(COALESCE(config_value, '')) = :new_value
                    """
                ),
                {
                    "new_value": "MODEL1",
                    "old_value": "gpt-4o",
                    "key": "landppt_model",
                    "now": now,
                },
            )
            await session.commit()
            logger.info("Migration 009 rollback completed")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 009 rollback failed: {e}")
            raise

    async def _migration_010_up(self, session: AsyncSession):
        """Migration 010: add user_id to global_master_templates for user isolation."""
        logger.info("Applying migration 010: Adding user_id to global_master_templates")
        try:
            if not await self._table_exists(session, "global_master_templates"):
                logger.info("global_master_templates table not found; skipping migration 010")
                return

            dialect = self._dialect_name(session)
            if not await self._column_exists(session, "global_master_templates", "user_id"):
                if dialect == "sqlite":
                    await session.execute(
                        text("ALTER TABLE global_master_templates ADD COLUMN user_id INTEGER")
                    )
                else:
                    await session.execute(
                        text(
                            "ALTER TABLE global_master_templates "
                            "ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id)"
                        )
                    )
                logger.info("Added user_id column to global_master_templates")
            else:
                logger.info("user_id column already exists in global_master_templates")

            # Move from global unique(template_name) to per-user uniqueness where possible.
            if dialect.startswith("postgres"):
                await session.execute(
                    text(
                        "ALTER TABLE global_master_templates "
                        "DROP CONSTRAINT IF EXISTS global_master_templates_template_name_key"
                    )
                )
            elif dialect == "sqlite":
                # SQLite cannot drop table-level UNIQUE constraints without table rebuild.
                # Legacy SQLite DBs may keep the old UNIQUE(template_name) behavior.
                logger.warning(
                    "SQLite legacy UNIQUE(template_name) cannot be dropped automatically; "
                    "new per-user uniqueness index will still be created"
                )

            await session.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_global_master_templates_user_name "
                    "ON global_master_templates(user_id, template_name) "
                    "WHERE user_id IS NOT NULL"
                )
            )

            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_global_master_templates_user_id "
                    "ON global_master_templates(user_id)"
                )
            )

            await session.commit()
            logger.info("Migration 010 completed successfully")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 010 failed: {e}")
            raise

    async def _migration_010_down(self, session: AsyncSession):
        """Migration 010 rollback (best-effort)."""
        logger.info("Rolling back migration 010: Removing user scope from global_master_templates")
        try:
            if not await self._table_exists(session, "global_master_templates"):
                return

            await session.execute(text("DROP INDEX IF EXISTS idx_global_master_templates_user_id"))
            await session.execute(text("DROP INDEX IF EXISTS uq_global_master_templates_user_name"))
            if not await self._column_exists(session, "global_master_templates", "user_id"):
                await session.commit()
                return

            dialect = self._dialect_name(session)
            if dialect == "sqlite":
                logger.warning("SQLite DROP COLUMN not supported; skipping migration 010 down column removal")
                await session.commit()
                return

            await session.execute(
                text("ALTER TABLE global_master_templates DROP COLUMN IF EXISTS user_id")
            )
            await session.commit()
            logger.info("Migration 010 rollback completed")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 010 rollback failed: {e}")
            raise

    async def _migration_011_up(self, session: AsyncSession):
        """Migration 011: add community operations schema."""
        logger.info("Applying migration 011: Adding community operations schema")
        try:
            if not await self._column_exists(session, "users", "registration_channel"):
                await session.execute(
                    text("ALTER TABLE users ADD COLUMN registration_channel VARCHAR(20)")
                )
                logger.info("Added registration_channel column to users")

            if not await self._column_exists(session, "users", "invite_code_id"):
                await session.execute(
                    text("ALTER TABLE users ADD COLUMN invite_code_id INTEGER")
                )
                logger.info("Added invite_code_id column to users")

            conn = await session.connection()
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)

            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_users_registration_channel "
                    "ON users(registration_channel)"
                )
            )
            await session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_users_invite_code_id "
                    "ON users(invite_code_id)"
                )
            )
            await session.execute(
                text(
                    "UPDATE users SET registration_channel = lower(oauth_provider) "
                    "WHERE registration_channel IS NULL "
                    "AND oauth_provider IN ('github', 'linuxdo', 'authentik')"
                )
            )
            await session.commit()
            logger.info("Migration 011 completed successfully")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 011 failed: {e}")
            raise

    async def _migration_011_down(self, session: AsyncSession):
        """Migration 011 rollback (best-effort)."""
        logger.info("Rolling back migration 011: Removing community operations schema")
        try:
            await session.execute(text("DROP TABLE IF EXISTS invite_code_usages"))
            await session.execute(text("DROP TABLE IF EXISTS daily_checkins"))
            await session.execute(text("DROP TABLE IF EXISTS sponsor_profiles"))
            await session.execute(text("DROP TABLE IF EXISTS invite_codes"))
            await session.execute(text("DROP INDEX IF EXISTS idx_users_registration_channel"))
            await session.execute(text("DROP INDEX IF EXISTS idx_users_invite_code_id"))

            dialect = self._dialect_name(session)
            if dialect.startswith("postgres"):
                await session.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS registration_channel"))
                await session.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS invite_code_id"))
            else:
                logger.warning("SQLite DROP COLUMN not supported; keeping users.registration_channel/invite_code_id")

            await session.commit()
            logger.info("Migration 011 rollback completed")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 011 rollback failed: {e}")
            raise

    async def _migration_012_up(self, session: AsyncSession):
        """Migration 012: add user_metrics table and backfill aggregates."""
        logger.info("Applying migration 012: Adding user_metrics table")
        try:
            conn = await session.connection()
            await conn.run_sync(Base.metadata.create_all, tables=[UserMetrics.__table__], checkfirst=True)

            user_rows = await session.execute(
                text(
                    """
                    SELECT id, created_at, last_login
                    FROM users
                    ORDER BY id
                    """
                )
            )

            now = time.time()
            for user_id, created_at, last_login in user_rows.fetchall():
                project_stats = await session.execute(
                    text(
                        """
                        SELECT
                            COUNT(*) AS projects_count,
                            MAX(created_at) AS last_project_created_at,
                            MAX(updated_at) AS last_project_updated_at
                        FROM projects
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id},
                )
                projects_count, last_project_created_at, last_project_updated_at = project_stats.one()

                credit_stats = await session.execute(
                    text(
                        """
                        SELECT
                            COALESCE(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 0) AS credits_consumed_total,
                            COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0) AS credits_recharged_total,
                            MAX(CASE WHEN amount < 0 THEN created_at ELSE NULL END) AS last_credit_consumed_at,
                            MAX(CASE WHEN amount > 0 THEN created_at ELSE NULL END) AS last_credit_recharged_at
                        FROM credit_transactions
                        WHERE user_id = :user_id
                        """
                    ),
                    {"user_id": user_id},
                )
                (
                    credits_consumed_total,
                    credits_recharged_total,
                    last_credit_consumed_at,
                    last_credit_recharged_at,
                ) = credit_stats.one()

                last_active_candidates = [
                    value
                    for value in (
                        last_project_updated_at,
                        last_credit_consumed_at,
                        last_credit_recharged_at,
                        last_login,
                        created_at,
                    )
                    if value is not None
                ]
                last_active_at = max(last_active_candidates) if last_active_candidates else now

                existing = await session.execute(
                    text("SELECT 1 FROM user_metrics WHERE user_id = :user_id LIMIT 1"),
                    {"user_id": user_id},
                )

                params = {
                    "user_id": user_id,
                    "last_active_at": last_active_at,
                    "projects_count": int(projects_count or 0),
                    "credits_consumed_total": int(credits_consumed_total or 0),
                    "credits_recharged_total": int(credits_recharged_total or 0),
                    "last_project_created_at": last_project_created_at,
                    "last_credit_consumed_at": last_credit_consumed_at,
                    "last_credit_recharged_at": last_credit_recharged_at,
                    "created_at": float(created_at or now),
                    "updated_at": now,
                }

                if existing.first():
                    await session.execute(
                        text(
                            """
                            UPDATE user_metrics
                            SET last_active_at = :last_active_at,
                                projects_count = :projects_count,
                                credits_consumed_total = :credits_consumed_total,
                                credits_recharged_total = :credits_recharged_total,
                                last_project_created_at = :last_project_created_at,
                                last_credit_consumed_at = :last_credit_consumed_at,
                                last_credit_recharged_at = :last_credit_recharged_at,
                                updated_at = :updated_at
                            WHERE user_id = :user_id
                            """
                        ),
                        params,
                    )
                else:
                    await session.execute(
                        text(
                            """
                            INSERT INTO user_metrics (
                                user_id,
                                last_active_at,
                                projects_count,
                                credits_consumed_total,
                                credits_recharged_total,
                                last_project_created_at,
                                last_credit_consumed_at,
                                last_credit_recharged_at,
                                created_at,
                                updated_at
                            ) VALUES (
                                :user_id,
                                :last_active_at,
                                :projects_count,
                                :credits_consumed_total,
                                :credits_recharged_total,
                                :last_project_created_at,
                                :last_credit_consumed_at,
                                :last_credit_recharged_at,
                                :created_at,
                                :updated_at
                            )
                            """
                        ),
                        params,
                    )

            await session.commit()
            logger.info("Migration 012 completed successfully")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 012 failed: {e}")
            raise

    async def _migration_012_down(self, session: AsyncSession):
        """Migration 012 rollback."""
        logger.info("Rolling back migration 012: Removing user_metrics table")
        try:
            await session.execute(text("DROP TABLE IF EXISTS user_metrics"))
            await session.commit()
            logger.info("Migration 012 rollback completed")
        except Exception as e:
            await session.rollback()
            logger.error(f"Migration 012 rollback failed: {e}")
            raise

    async def _create_migration_table(self, session: AsyncSession):
        """Create migration tracking table"""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(10) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            description TEXT,
            applied_at FLOAT NOT NULL,
            rollback_sql TEXT
        )
        """
        
        await session.execute(text(create_table_sql))
        await session.commit()
    
    async def _get_applied_migrations(self, session: AsyncSession) -> List[str]:
        """Get list of applied migration versions"""
        try:
            result = await session.execute(text("SELECT version FROM schema_migrations ORDER BY version"))
            return [row[0] for row in result.fetchall()]
        except Exception:
            # Table doesn't exist yet
            return []
    
    async def _record_migration(self, session: AsyncSession, migration: Dict[str, Any]):
        """Record a migration as applied"""
        insert_sql = """
        INSERT INTO schema_migrations (version, name, description, applied_at)
        VALUES (:version, :name, :description, :applied_at)
        """
        
        await session.execute(text(insert_sql), {
            "version": migration["version"],
            "name": migration["name"],
            "description": migration["description"],
            "applied_at": time.time()
        })
        await session.commit()
    
    async def _remove_migration_record(self, session: AsyncSession, version: str):
        """Remove migration record"""
        delete_sql = "DELETE FROM schema_migrations WHERE version = :version"
        await session.execute(text(delete_sql), {"version": version})
        await session.commit()
    
    async def migrate_up(self, target_version: str = None) -> bool:
        """Run migrations up to target version"""
        try:
            async with AsyncSessionLocal() as session:
                # Create migration table if it doesn't exist
                await self._create_migration_table(session)
                
                # Get applied migrations
                applied = await self._get_applied_migrations(session)
                
                # Find migrations to apply
                to_apply = []
                for migration in self.migrations:
                    if migration["version"] not in applied:
                        to_apply.append(migration)
                        if target_version and migration["version"] == target_version:
                            break
                
                if not to_apply:
                    logger.info("No migrations to apply")
                    return True
                
                # Apply migrations
                for migration in to_apply:
                    logger.info(f"Applying migration {migration['version']}: {migration['name']}")
                    
                    try:
                        await migration["up"](session)
                        await self._record_migration(session, migration)
                        logger.info(f"Migration {migration['version']} applied successfully")
                    except Exception as e:
                        logger.error(f"Failed to apply migration {migration['version']}: {e}")
                        raise
                
                logger.info("All migrations applied successfully")
                return True
                
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            return False
    
    async def migrate_down(self, target_version: str) -> bool:
        """Rollback migrations down to target version"""
        try:
            async with AsyncSessionLocal() as session:
                # Get applied migrations
                applied = await self._get_applied_migrations(session)
                
                # Find migrations to rollback
                to_rollback = []
                for migration in reversed(self.migrations):
                    if migration["version"] in applied and migration["version"] > target_version:
                        to_rollback.append(migration)
                
                if not to_rollback:
                    logger.info("No migrations to rollback")
                    return True
                
                # Rollback migrations
                for migration in to_rollback:
                    logger.info(f"Rolling back migration {migration['version']}: {migration['name']}")
                    
                    try:
                        await migration["down"](session)
                        await self._remove_migration_record(session, migration["version"])
                        logger.info(f"Migration {migration['version']} rolled back successfully")
                    except Exception as e:
                        logger.error(f"Failed to rollback migration {migration['version']}: {e}")
                        raise
                
                logger.info("Migrations rolled back successfully")
                return True
                
        except Exception as e:
            logger.error(f"Migration rollback failed: {e}")
            return False
    
    async def get_migration_status(self) -> Dict[str, Any]:
        """Get current migration status"""
        try:
            async with AsyncSessionLocal() as session:
                await self._create_migration_table(session)
                applied = await self._get_applied_migrations(session)
                
                status = {
                    "current_version": applied[-1] if applied else None,
                    "applied_migrations": applied,
                    "available_migrations": [m["version"] for m in self.migrations],
                    "pending_migrations": [m["version"] for m in self.migrations if m["version"] not in applied]
                }
                
                return status
                
        except Exception as e:
            logger.error(f"Failed to get migration status: {e}")
            return {"error": str(e)}


# Global migration manager instance
migration_manager = DatabaseMigration()
