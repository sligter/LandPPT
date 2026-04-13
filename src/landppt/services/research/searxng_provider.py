"""
SearXNG Content Search Provider for Research Functionality

This module provides a SearXNG-based content search provider that can perform
web searches and return structured results for further processing in the research pipeline.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse
import aiohttp

from ...core.config import ai_config

logger = logging.getLogger(__name__)


class SearXNGSearchResult:
    """Represents a single search result from SearXNG"""
    
    def __init__(self, data: Dict[str, Any]):
        self.url = data.get('url', '')
        self.title = data.get('title', '')
        self.content = data.get('content', '')
        self.score = data.get('score', 0.0)
        self.category = data.get('category', '')
        self.engine = data.get('engine', '')
        self.parsed_url = data.get('parsed_url', [])
        self.template = data.get('template', '')
        self.positions = data.get('positions', [])
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'url': self.url,
            'title': self.title,
            'content': self.content,
            'score': self.score,
            'category': self.category,
            'engine': self.engine,
            'parsed_url': self.parsed_url,
            'template': self.template,
            'positions': self.positions
        }


class SearXNGSearchResponse:
    """Represents the complete search response from SearXNG"""
    
    def __init__(self, data: Dict[str, Any]):
        self.query = data.get('query', '')
        self.number_of_results = data.get('number_of_results', 0)
        self.results = [SearXNGSearchResult(result) for result in data.get('results', [])]
        self.answers = data.get('answers', [])
        self.corrections = data.get('corrections', [])
        self.infoboxes = data.get('infoboxes', [])
        self.suggestions = data.get('suggestions', [])
        self.unresponsive_engines = data.get('unresponsive_engines', [])
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'query': self.query,
            'number_of_results': self.number_of_results,
            'results': [result.to_dict() for result in self.results],
            'answers': self.answers,
            'corrections': self.corrections,
            'infoboxes': self.infoboxes,
            'suggestions': self.suggestions,
            'unresponsive_engines': self.unresponsive_engines
        }


class SearXNGContentProvider:
    """SearXNG content search provider for research functionality"""
    
    def __init__(self, user_id: Optional[int] = None):
        self.user_id = user_id
        self.host = ai_config.searxng_host
        self.max_results = ai_config.searxng_max_results
        self.language = ai_config.searxng_language
        self.timeout = ai_config.searxng_timeout
        self._request_times = []
        self.rate_limit_requests = 60  # requests per minute
        self.rate_limit_window = 60  # seconds
        self._config_initialized = False
    
    async def _ensure_config_initialized(self):
        """Ensure config is initialized from user database - always read fresh config"""
        # 每次都从数据库读取最新配置，确保配置更新能被及时应用
        if self.user_id is not None:
            try:
                from ..db_config_service import get_db_config_service
                db_config_service = get_db_config_service()
                user_config = await db_config_service.get_all_config(user_id=self.user_id)
                
                # 从数据库读取 SearXNG 配置
                host = user_config.get("searxng_host")
                if host:
                    self.host = host
                    logger.info(f"SearXNGContentProvider: Using host from user database (user_id={self.user_id}): {host}")
                
                max_results = user_config.get("searxng_max_results")
                if max_results:
                    self.max_results = int(max_results)
                
                language = user_config.get("searxng_language")
                if language:
                    self.language = language
                    
                timeout = user_config.get("searxng_timeout")
                if timeout:
                    self.timeout = int(timeout)
                    
            except Exception as e:
                logger.warning(f"Failed to get SearXNG config from database: {e}")

        
    def is_available(self) -> bool:
        """Check if SearXNG provider is available"""
        return bool(self.host and self.host.strip())

    
    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits"""
        current_time = time.time()
        
        # Clean old request times
        self._request_times = [
            req_time for req_time in self._request_times
            if current_time - req_time < self.rate_limit_window
        ]
        
        return len(self._request_times) < self.rate_limit_requests
    
    async def search(self, query: str, language: Optional[str] = None, 
                    max_results: Optional[int] = None) -> Optional[SearXNGSearchResponse]:
        """
        Perform a search using SearXNG
        
        Args:
            query: Search query
            language: Language for search (defaults to configured language)
            max_results: Maximum number of results (defaults to configured max)
            
        Returns:
            SearXNGSearchResponse object or None if search fails
        """
        # 确保从数据库加载配置
        await self._ensure_config_initialized()
        
        if not self.is_available():
            logger.warning("SearXNG provider not available - host not configured")
            return None

            
        if not self._check_rate_limit():
            logger.warning("SearXNG rate limit exceeded, skipping search")
            return None
            
        search_language = language or self.language
        search_max_results = max_results or self.max_results
        
        # Build search URL
        search_url = urljoin(self.host.rstrip('/'), '/search')
        
        # Prepare search parameters
        params = {
            'q': query,
            'language': search_language,
            'format': 'json',
            'theme': 'simple'
        }
        
        try:
            # Record request time for rate limiting
            self._request_times.append(time.time())
            
            logger.info(f"Searching SearXNG for: {query}")
            
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.get(search_url, params=params) as response:
                    if response.status != 200:
                        logger.error(f"SearXNG search failed with status {response.status}")
                        return None
                        
                    data = await response.json()
                    
            # Create response object
            search_response = SearXNGSearchResponse(data)
            
            # Limit results if needed
            if search_max_results and len(search_response.results) > search_max_results:
                search_response.results = search_response.results[:search_max_results]
                search_response.number_of_results = min(
                    search_response.number_of_results, search_max_results
                )
            
            logger.info(f"SearXNG search completed: {len(search_response.results)} results")
            return search_response
            
        except asyncio.TimeoutError:
            logger.error(f"SearXNG search timeout for query: {query}")
            return None
        except Exception as e:
            logger.error(f"SearXNG search error: {e}")
            return None
    
    async def search_multiple_queries(self, queries: List[str], 
                                    language: Optional[str] = None,
                                    max_results_per_query: Optional[int] = None,
                                    delay_between_requests: float = 1.0) -> List[SearXNGSearchResponse]:
        """
        Perform multiple searches with rate limiting
        
        Args:
            queries: List of search queries
            language: Language for searches
            max_results_per_query: Maximum results per query
            delay_between_requests: Delay between requests in seconds
            
        Returns:
            List of SearXNGSearchResponse objects
        """
        results = []
        
        for i, query in enumerate(queries):
            result = await self.search(query, language, max_results_per_query)
            if result:
                results.append(result)
            
            # Add delay between requests except for the last one
            if i < len(queries) - 1:
                await asyncio.sleep(delay_between_requests)
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get provider status information"""
        return {
            'provider': 'searxng',
            'available': self.is_available(),
            'host': self.host,
            'max_results': self.max_results,
            'language': self.language,
            'timeout': self.timeout,
            'rate_limit_requests': self.rate_limit_requests,
            'rate_limit_window': self.rate_limit_window,
            'recent_requests': len(self._request_times)
        }
