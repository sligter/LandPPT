"""
Project Share Service
Handles generation and validation of public share links for presentations
"""

import secrets
import logging
from typing import Optional
from sqlalchemy.orm import Session
from ..database.models import Project
from ..auth.request_context import current_user_id, USER_SCOPE_ALL

logger = logging.getLogger(__name__)


class ShareService:
    """Service for managing project sharing functionality"""

    def __init__(self, db: Session):
        self.db = db

    def _effective_user_id(self, user_id: Optional[int]) -> Optional[int]:
        if user_id == USER_SCOPE_ALL:
            return None
        if user_id is None:
            return current_user_id.get()
        return user_id

    def generate_share_token(self, project_id: str, user_id: Optional[int] = None) -> Optional[str]:
        """
        Generate a unique share token for a project, or return existing one

        Args:
            project_id: The project ID to generate a share link for

        Returns:
            The generated share token, or None if project not found
        """
        try:
            effective_user_id = self._effective_user_id(user_id)
            # Get the project
            query = self.db.query(Project).filter(Project.project_id == project_id)
            if effective_user_id is not None:
                query = query.filter(Project.user_id == effective_user_id)
            project = query.first()

            if not project:
                logger.error(f"Project {project_id} not found")
                return None

            # If project already has a valid share token, return it
            if project.share_token:
                # Enable sharing if it was disabled
                if not project.share_enabled:
                    project.share_enabled = True
                    self.db.commit()
                    logger.info(f"Re-enabled sharing for project {project_id}")
                else:
                    logger.info(f"Returning existing share token for project {project_id}")
                return project.share_token

            # Generate a new secure random token
            share_token = secrets.token_urlsafe(32)

            # Update project with share token and enable sharing
            project.share_token = share_token
            project.share_enabled = True
            self.db.commit()

            logger.info(f"Generated new share token for project {project_id}")
            return share_token

        except Exception as e:
            logger.error(f"Error generating share token: {e}")
            self.db.rollback()
            return None

    def disable_sharing(self, project_id: str, user_id: Optional[int] = None) -> bool:
        """
        Disable sharing for a project

        Args:
            project_id: The project ID to disable sharing for

        Returns:
            True if successful, False otherwise
        """
        try:
            effective_user_id = self._effective_user_id(user_id)
            query = self.db.query(Project).filter(Project.project_id == project_id)
            if effective_user_id is not None:
                query = query.filter(Project.user_id == effective_user_id)
            project = query.first()

            if not project:
                logger.error(f"Project {project_id} not found")
                return False

            project.share_enabled = False
            self.db.commit()

            logger.info(f"Disabled sharing for project {project_id}")
            return True

        except Exception as e:
            logger.error(f"Error disabling sharing: {e}")
            self.db.rollback()
            return False

    def validate_share_token(self, share_token: str) -> Optional[Project]:
        """
        Validate a share token and return the associated project

        Args:
            share_token: The share token to validate

        Returns:
            The Project object if valid, None otherwise
        """
        try:
            project = self.db.query(Project).filter(
                Project.share_token == share_token,
                Project.share_enabled == True
            ).first()

            if not project:
                logger.warning(f"Invalid or disabled share token")
                return None

            # Refresh project from database to ensure we have the latest data
            # This prevents SQLAlchemy session cache from returning stale slides_data
            self.db.refresh(project)

            return project

        except Exception as e:
            logger.error(f"Error validating share token: {e}")
            return None

    def get_share_info(self, project_id: str, user_id: Optional[int] = None) -> dict:
        """
        Get sharing information for a project

        Args:
            project_id: The project ID

        Returns:
            Dictionary with share information
        """
        try:
            effective_user_id = self._effective_user_id(user_id)
            query = self.db.query(Project).filter(Project.project_id == project_id)
            if effective_user_id is not None:
                query = query.filter(Project.user_id == effective_user_id)
            project = query.first()

            if not project:
                return {
                    "enabled": False,
                    "share_token": None,
                    "share_url": None
                }

            return {
                "enabled": project.share_enabled,
                "share_token": project.share_token,
                "share_url": f"/share/{project.share_token}" if project.share_token else None
            }

        except Exception as e:
            logger.error(f"Error getting share info: {e}")
            return {
                "enabled": False,
                "share_token": None,
                "share_url": None
            }
