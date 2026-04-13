"""
Cache service using Valkey (Redis-compatible) for caching and session management
"""

import json
import logging
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class CacheService:
    """Valkey-based caching service"""
    
    def __init__(self, url: str = "valkey://localhost:6379", enabled: bool = True):
        self.url = url
        self.enabled = enabled
        self._client = None
        self._connected = False
    
    async def connect(self) -> bool:
        """Connect to Valkey server."""
        if not self.enabled:
            logger.info("Cache service is disabled")
            return False

        try:
            # Import valkey here to avoid import errors if not installed
            import valkey.asyncio as aioredis

            # Convert valkey:// to redis:// for compatibility
            redis_url = self.url.replace("valkey://", "redis://")

            self._client = await aioredis.from_url(
                redis_url,
                encoding="utf-8",
                decode_responses=True
            )

            # Test connection
            await self._client.ping()
            self._connected = True
            logger.info(f"Connected to Valkey at {self.url}")
            return True

        except ImportError:
            logger.warning("valkey package not installed; falling back to in-memory cache")
            self._client = None
            self._connected = False
            self.enabled = False
            return False
        except Exception as e:
            logger.warning(f"Failed to connect to Valkey at {self.url}; falling back to in-memory cache: {e}")
            self._client = None
            self._connected = False
            self.enabled = False
            return False
    
    async def disconnect(self):
        """Disconnect from Valkey server"""
        if self._client:
            await self._client.close()
            self._connected = False
            logger.info("Disconnected from Valkey")
    
    @property
    def is_connected(self) -> bool:
        """Check if connected to Valkey"""
        return self._connected
    
    async def get(self, key: str) -> Optional[str]:
        """Get value from cache"""
        if not self._connected:
            return None
        try:
            return await self._client.get(key)
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    async def set(self, key: str, value: str, ttl: int = 3600) -> bool:
        """Set value in cache with TTL"""
        if not self._connected:
            return False
        try:
            await self._client.set(key, value, ex=ttl)
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete value from cache"""
        if not self._connected:
            return False
        try:
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    async def exists(self, key: str) -> bool:
        """Check if key exists in cache"""
        if not self._connected:
            return False
        try:
            return await self._client.exists(key) > 0
        except Exception as e:
            logger.error(f"Cache exists error: {e}")
            return False

    async def incr_with_ttl(self, key: str, ttl: int) -> Optional[int]:
        """
        Atomically increment a counter and ensure it has a TTL (Valkey/Redis only).
        Returns the new counter value, or None when cache is unavailable.
        """
        if not self._connected:
            return None
        try:
            value = await self._client.incr(key)
            if int(value) == 1 and ttl:
                await self._client.expire(key, ttl)
            return int(value)
        except Exception as e:
            logger.error(f"Cache incr error: {e}")
            return None
    
    # Session management methods (TTL: 1 week = 604800 seconds)
    SESSION_TTL = 604800  # 1 week in seconds

    @staticmethod
    def _extract_session_user_id(user_data: Optional[Dict[str, Any]]) -> Optional[int]:
        if not isinstance(user_data, dict):
            return None
        raw_user_id = user_data.get("user_id", user_data.get("id"))
        try:
            if raw_user_id is None or raw_user_id == "":
                return None
            return int(raw_user_id)
        except Exception:
            return None

    @staticmethod
    def _session_index_key(user_id: int) -> str:
        return f"user:{int(user_id)}:sessions"
    
    async def set_session(self, session_id: str, user_data: Dict[str, Any], ttl: int = None) -> bool:
        """Store user session in cache (default TTL: 1 week)"""
        if ttl is None:
            ttl = self.SESSION_TTL
        key = f"session:{session_id}"
        try:
            value = json.dumps(user_data)
            saved = await self.set(key, value, ttl)
            if not saved:
                return False

            user_id = self._extract_session_user_id(user_data)
            if user_id is not None and self._connected:
                index_key = self._session_index_key(user_id)
                await self._client.sadd(index_key, session_id)
                await self._client.expire(index_key, ttl)
            return True
        except Exception as e:
            logger.error(f"Set session error: {e}")
            return False
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve user session from cache"""
        key = f"session:{session_id}"
        try:
            value = await self.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Get session error: {e}")
            return None
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete user session from cache"""
        key = f"session:{session_id}"
        if not self._connected:
            return False
        try:
            payload = await self.get_session(session_id)
            user_id = self._extract_session_user_id(payload)
            if user_id is not None:
                await self._client.srem(self._session_index_key(user_id), session_id)
            await self._client.delete(key)
            return True
        except Exception as e:
            logger.error(f"Delete session error: {e}")
            return False
    
    async def refresh_session(self, session_id: str, ttl: int = None) -> bool:
        """Refresh session TTL"""
        if ttl is None:
            ttl = self.SESSION_TTL
        if not self._connected:
            return False
        key = f"session:{session_id}"
        try:
            await self._client.expire(key, ttl)
            payload = await self.get_session(session_id)
            user_id = self._extract_session_user_id(payload)
            if user_id is not None:
                await self._client.expire(self._session_index_key(user_id), ttl)
            return True
        except Exception as e:
            logger.error(f"Refresh session error: {e}")
            return False

    async def delete_user_sessions(self, user_id: int) -> bool:
        """Delete all cached sessions for one user."""
        if not self._connected:
            return False
        index_key = self._session_index_key(user_id)
        try:
            session_ids = list(await self._client.smembers(index_key))
            session_keys = [f"session:{session_id}" for session_id in session_ids if session_id]
            if session_keys:
                await self._client.delete(*session_keys)
            await self._client.delete(index_key)
            return True
        except Exception as e:
            logger.error(f"Delete user sessions error: {e}")
            return False
    
    # OAuth state management (TTL: 30 minutes)
    OAUTH_STATE_TTL = 1800  # 30 minutes in seconds
    
    async def set_oauth_state(self, provider: str, state: str, data: Dict[str, Any], ttl: int = None) -> bool:
        """
        Store OAuth state data in cache.
        
        Args:
            provider: OAuth provider name (e.g., 'github', 'linuxdo')
            state: The OAuth state parameter
            data: State data dict (e.g., code_verifier, redirect_url)
            ttl: Time to live in seconds (default: 30 minutes)
        """
        if ttl is None:
            ttl = self.OAUTH_STATE_TTL
        key = f"oauth:{provider}:{state}"
        try:
            value = json.dumps(data)
            return await self.set(key, value, ttl)
        except Exception as e:
            logger.error(f"Set OAuth state error: {e}")
            return False
    
    async def get_oauth_state(self, provider: str, state: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve OAuth state data from cache.
        
        Args:
            provider: OAuth provider name
            state: The OAuth state parameter
            
        Returns:
            State data dict if found, None otherwise
        """
        key = f"oauth:{provider}:{state}"
        try:
            value = await self.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Get OAuth state error: {e}")
            return None
    
    async def delete_oauth_state(self, provider: str, state: str) -> bool:
        """
        Delete OAuth state from cache (consume after use).
        
        Args:
            provider: OAuth provider name
            state: The OAuth state parameter
        """
        key = f"oauth:{provider}:{state}"
        return await self.delete(key)
    
    async def get_and_consume_oauth_state(self, provider: str, state: str) -> Optional[Dict[str, Any]]:
        """
        Get OAuth state and delete it atomically (one-time use).
        
        Args:
            provider: OAuth provider name
            state: The OAuth state parameter
            
        Returns:
            State data dict if found, None otherwise
        """
        data = await self.get_oauth_state(provider, state)
        if data:
            await self.delete_oauth_state(provider, state)
        return data
    
    # Task management methods (TTL: 24 hours for task data)
    TASK_TTL = 86400  # 24 hours in seconds
    
    async def set_task_status(self, task_id: str, status: str, ttl: int = None) -> bool:
        """
        Store task status in cache.
        
        Args:
            task_id: Unique task identifier
            status: Task status (pending/running/completed/failed)
            ttl: Time to live in seconds (default: 24 hours)
        """
        if ttl is None:
            ttl = self.TASK_TTL
        key = f"task:{task_id}:status"
        return await self.set(key, status, ttl)
    
    async def get_task_status(self, task_id: str) -> Optional[str]:
        """Retrieve task status from cache"""
        key = f"task:{task_id}:status"
        return await self.get(key)
    
    async def set_task_progress(self, task_id: str, progress: Dict[str, Any], ttl: int = None) -> bool:
        """
        Store task progress in cache.
        
        Args:
            task_id: Unique task identifier
            progress: Progress data dict (e.g., {"current": 3, "total": 10, "message": "Processing..."})
            ttl: Time to live in seconds (default: 24 hours)
        """
        if ttl is None:
            ttl = self.TASK_TTL
        key = f"task:{task_id}:progress"
        try:
            value = json.dumps(progress)
            return await self.set(key, value, ttl)
        except Exception as e:
            logger.error(f"Set task progress error: {e}")
            return False
    
    async def get_task_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve task progress from cache"""
        key = f"task:{task_id}:progress"
        try:
            value = await self.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Get task progress error: {e}")
            return None
    
    async def delete_task(self, task_id: str) -> bool:
        """Delete all task data from cache"""
        try:
            await self.delete(f"task:{task_id}:status")
            await self.delete(f"task:{task_id}:progress")
            return True
        except Exception as e:
            logger.error(f"Delete task error: {e}")
            return False
    
    async def add_user_task(self, user_id: int, task_id: str, ttl: int = None) -> bool:
        """Add a task to user's task list"""
        if ttl is None:
            ttl = self.TASK_TTL
        if not self._connected:
            return False
        key = f"user:{user_id}:tasks"
        try:
            await self._client.sadd(key, task_id)
            await self._client.expire(key, ttl)
            return True
        except Exception as e:
            logger.error(f"Add user task error: {e}")
            return False
    
    async def get_user_tasks(self, user_id: int) -> List[str]:
        """Get all task IDs for a user"""
        if not self._connected:
            return []
        key = f"user:{user_id}:tasks"
        try:
            return list(await self._client.smembers(key))
        except Exception as e:
            logger.error(f"Get user tasks error: {e}")
            return []
    
    async def remove_user_task(self, user_id: int, task_id: str) -> bool:
        """Remove a task from user's task list"""
        if not self._connected:
            return False
        key = f"user:{user_id}:tasks"
        try:
            await self._client.srem(key, task_id)
            return True
        except Exception as e:
            logger.error(f"Remove user task error: {e}")
            return False


# Global cache service instance
_cache_service: Optional[CacheService] = None


async def get_cache_service() -> CacheService:
    """Get or create global cache service instance."""
    global _cache_service

    if _cache_service is None:
        from ..core.config import app_config

        cache_backend = str(getattr(app_config, 'cache_backend', 'memory') or 'memory').lower()
        valkey_url = getattr(app_config, 'valkey_url', 'valkey://localhost:6379')
        use_valkey = cache_backend == 'valkey'

        logger.info(f"CacheService init: backend={cache_backend}, enabled={use_valkey}, url={valkey_url}")
        _cache_service = CacheService(url=valkey_url, enabled=use_valkey)

        if use_valkey:
            connected = await _cache_service.connect()
            logger.info(f"CacheService connect result: {connected}")

    return _cache_service


async def close_cache_service():
    """Close global cache service"""
    global _cache_service
    
    if _cache_service:
        await _cache_service.disconnect()
        _cache_service = None
