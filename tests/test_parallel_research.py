"""Exercise the research resolver, real MCP SDK transport and report consumers.

Model output is scripted; only the remote HTTP server is replaced.
"""
import asyncio
import json
from collections import defaultdict
from uuid import UUID

import httpx
import pytest
from unittest.mock import AsyncMock

from landppt.core.config import AIConfig, ai_config
from landppt.services.research.enhanced_research_service import EnhancedResearchService
from landppt.services.research.parallel_provider import (
    MCP_URL, ParallelSearchError, ParallelSearchProvider, public_http_url,
)
from landppt.services.runtime.ai_execution import is_provider_protocol_error


class MCPServer:
    def __init__(self):
        self.requests = []
        self.failure = None
        self.started = asyncio.Event()

    async def handle(self, request):
        assert str(request.url) == MCP_URL
        assert request.headers['user-agent'].startswith('LandPPT/')
        assert 'authorization' not in request.headers
        body = json.loads(request.content)
        self.requests.append(body)
        method = body['method']
        if method.startswith('notifications/'):
            return httpx.Response(202)
        if method == 'initialize':
            result = dict(protocolVersion=body['params']['protocolVersion'], capabilities={'tools': {}}, serverInfo={'name': 'fixture', 'version': '1'})
        elif method == 'tools/list':
            result = {'tools': [{'name': name, 'inputSchema': {'type': 'object'}} for name in ['web_search', 'web_fetch']]}
        elif method == 'tools/call':
            self.started.set()
            if self.failure == 'timeout':
                await asyncio.sleep(60)
            if self.failure in {'http', 'permission'}:
                return httpx.Response(403 if self.failure == 'permission' else 503, text='unavailable')
            if self.failure == 'quota' or (self.failure == 'fetch_quota' and body['params']['name'] == 'web_fetch'):
                result = {'isError': True, 'content': [{'type': 'text', 'text': 'Free anonymous quota exceeded'}]}
            elif self.failure == 'malformed':
                result = {'content': [{'type': 'text', 'text': 'not JSON'}]}
            else:
                name = body['params']['name']
                payload = {'results': [{'url': 'https://example.com/evidence', 'title': 'Evidence', 'excerpts': ['FETCHED EVIDENCE' if name == 'web_fetch' else 'SEARCH EVIDENCE']}]}
                result = {'structuredContent': payload, 'content': [{'type': 'text', 'text': json.dumps(payload)}]}
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})

    @property
    def calls(self):
        return [r['params'] for r in self.requests if r['method'] == 'tools/call']


@pytest.fixture
def research(monkeypatch):
    for key in ['PARALLEL_API_KEY', 'TAVILY_API_KEY', 'SEARXNG_HOST', 'RESEARCH_PROVIDER']:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(ai_config, 'research_provider', 'auto')
    monkeypatch.setattr(ai_config, 'tavily_api_key', None)
    monkeypatch.setattr(ai_config, 'searxng_host', None)
    monkeypatch.setattr(ai_config, 'enable_network_mode', True)
    monkeypatch.setattr(ai_config, 'research_enable_content_extraction', True)
    service = EnhancedResearchService()
    server = MCPServer()
    original_client = service.parallel_provider._http_client
    def client(timeout):
        real = original_client(timeout)
        headers = dict(real.headers)
        # No resources are opened until the client is used.
        return httpx.AsyncClient(transport=httpx.MockTransport(server.handle), headers=headers, timeout=timeout)
    monkeypatch.setattr(service.parallel_provider, '_http_client', client)
    prompts = []
    async def scripted_model(prompt, *, stage, **kwargs):
        prompts.append((stage, prompt))
        if stage == 'enhanced_research_plan':
            return json.dumps([{'query': f'{prompt.splitlines()[0]} presentation research facts', 'description': 'Evidence'}])
        return 'Evidence-backed presentation summary'
    monkeypatch.setattr(service, '_collect_llm_response', scripted_model)
    return service, server, prompts


@pytest.mark.asyncio
async def test_unconfigured_research_consumes_search_and_fetch_in_report(research, tmp_path):
    service, server, prompts = research
    assert AIConfig(_env_file=None).research_provider == 'auto'
    assert await service._get_research_provider_async() == 'parallel'
    report = await service.conduct_enhanced_research('Presentation research', 'en')
    assert [call['name'] for call in server.calls] == ['web_search', 'web_fetch']
    assert any('SEARCH EVIDENCE' in prompt and 'FETCHED EVIDENCE' in prompt for stage, prompt in prompts if stage == 'enhanced_step_analysis')
    assert report.steps[0].parallel_results[0]['title'] == 'Evidence'
    assert report.sources == ['https://example.com/evidence']
    from landppt.services.research.enhanced_report_generator import EnhancedReportGenerator
    markdown = EnhancedReportGenerator(str(tmp_path)).generate_markdown_report(report)
    assert report.sources[0] in markdown
    assert report.executive_summary in markdown
    assert report.provider_stats['parallel'] == 1
    assert report.content_analysis['content_stats']['parallel_results'] == 1
    assert server.calls[1]['arguments']['urls'] == report.sources
    assert server.calls[1]['arguments']['search_queries'] == server.calls[0]['arguments']['search_queries']
    assert server.calls[1]['arguments']['full_content'] is False
    assert any(r['method'] == 'initialize' for r in server.requests)
    assert any(r['method'] == 'tools/list' for r in server.requests)


@pytest.mark.asyncio
async def test_shared_provider_isolates_concurrent_runs_and_new_runs(research, monkeypatch):
    service, server, _ = research
    async def plan(*args, **kwargs):
        return [{'query': 'first research evidence', 'description': 'First'}, {'query': 'followup research evidence', 'description': 'Followup'}]
    monkeypatch.setattr(service, '_generate_research_plan', plan)
    await asyncio.gather(service.conduct_enhanced_research('A'), service.conduct_enhanced_research('B'))
    groups = defaultdict(list)
    for call in server.calls:
        groups[call['arguments']['session_id']].append(call['name'])
    assert len(groups) == 2
    for session_id, calls in groups.items():
        UUID(session_id)
        assert calls == ['web_search', 'web_fetch', 'web_search', 'web_fetch']
    await service.conduct_enhanced_research('new research')
    new_id = server.calls[-1]['arguments']['session_id']
    assert new_id not in groups


@pytest.mark.asyncio
async def test_explicit_and_configured_incumbents_are_preserved(research, monkeypatch):
    service, server, _ = research
    monkeypatch.setattr(ai_config, 'tavily_api_key', 'configured-key')
    assert await service._get_research_provider_async() == 'tavily'
    monkeypatch.setattr(ai_config, 'tavily_api_key', None)
    monkeypatch.setattr(ai_config, 'searxng_host', 'https://search.example.org')
    assert await service._get_research_provider_async() == 'searxng'
    for provider in ['tavily', 'searxng', 'both', 'parallel', 'none']:
        monkeypatch.setattr(ai_config, 'research_provider', provider)
        assert await service._get_research_provider_async() == provider
    monkeypatch.setattr(ai_config, 'research_provider', 'tavily')
    monkeypatch.setattr(service, '_search_with_tavily', AsyncMock(return_value=None))
    await service.conduct_enhanced_research('failed explicit Tavily')
    assert server.calls == []


@pytest.mark.asyncio
async def test_saved_choices_override_and_db_failure_does_not_enable_search(research, monkeypatch):
    from landppt.services import db_config_service
    service, server, _ = research
    service.user_id = 7
    config = db_config_service.DatabaseConfigService()
    get = AsyncMock(return_value={'research_provider': 'searxng'})
    monkeypatch.setattr(config, 'get_all_config', get)
    monkeypatch.setattr(config, 'is_user_override', AsyncMock(return_value=True))
    monkeypatch.setattr(db_config_service, 'get_db_config_service', lambda: config)
    monkeypatch.setattr(ai_config, 'research_provider', 'parallel')
    assert await service._get_research_provider_async() == 'searxng'
    get.return_value = {'research_provider': 'auto'}
    monkeypatch.setattr(service.deep_research_service, '_get_tavily_api_key_candidates_async', AsyncMock(return_value=[]))
    assert await service._get_research_provider_async() == 'parallel'
    get.return_value = {'research_provider': 'auto', 'tavily_api_key': 'stored-key'}
    assert await service._get_research_provider_async() == 'tavily'
    get.return_value = {'research_provider': 'auto', 'searxng_host': 'https://search.example.org'}
    assert await service._get_research_provider_async() == 'searxng'
    get.side_effect = RuntimeError('DB unavailable')
    with pytest.raises(RuntimeError, match='DB unavailable'):
        await service._get_research_provider_async()
    assert server.calls == []
    # Existing saved values survive schema resolution; new databases get auto.
    assert config._resolve_config_values({'research_provider': {'value': 'tavily'}}, {})['research_provider'] == 'tavily'
    assert config._resolve_config_values({}, {})['research_provider'] == 'auto'


@pytest.mark.asyncio
async def test_disable_controls_stop_network_or_fetch(research, monkeypatch):
    service, server, _ = research
    monkeypatch.setattr(ai_config, 'enable_network_mode', False)
    with pytest.raises(ValueError, match='disabled'):
        await service.conduct_enhanced_research('Offline')
    assert server.requests == []
    monkeypatch.setattr(ai_config, 'enable_network_mode', True)
    monkeypatch.setattr(ai_config, 'research_enable_content_extraction', False)
    report = await service.conduct_enhanced_research('Search only')
    assert [call['name'] for call in server.calls] == ['web_search']
    assert report.steps[0].extracted_content is None


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['quota', 'malformed', 'http', 'permission', 'timeout'])
async def test_provider_errors_propagate_without_fallback(research, monkeypatch, failure):
    service, server, _ = research
    server.failure = failure
    monkeypatch.setattr(ai_config, 'research_extraction_timeout', 1 if failure == 'timeout' else 30)
    with pytest.raises(ParallelSearchError) as error:
        await service.conduct_enhanced_research('Failing research')
    assert is_provider_protocol_error(error.value)
    assert [call['name'] for call in server.calls] == ['web_search']


@pytest.mark.asyncio
async def test_cancelled_caller_keeps_cancellation(research):
    service, server, _ = research
    server.failure = 'timeout'
    task = asyncio.create_task(service.conduct_enhanced_research('Cancel research'))
    await asyncio.wait_for(server.started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(server.calls) == 1


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://localhost', 'http://127.0.0.1', 'http://[::1]', 'https://user:pass@example.com', 'http://192.168.1.1', 'https://service.internal'])
def test_private_and_non_http_urls_are_filtered(url):
    assert not public_http_url(url)
    assert ParallelSearchProvider._results({'results': [{'url': url, 'excerpts': ['bad']}]}) == []


def test_cited_public_urls_are_preserved():
    url = 'https://example.com/source?q=a%20b#section'
    assert ParallelSearchProvider._results({'results': [{'url': url, 'excerpts': ['evidence']}]})[0]['url'] == url


@pytest.mark.asyncio
async def test_quota_fetch_keeps_successful_search_identity(research):
    service, server, _ = research
    server.failure = 'fetch_quota'
    events = []
    with pytest.raises(ParallelSearchError, match='Free anonymous quota exceeded'):
        await service.conduct_enhanced_research('Quota after search', event_callback=events.append)
    # The production run owns both identities; no manually supplied test IDs.
    assert [call['name'] for call in server.calls] == ['web_search', 'web_fetch']
    session_ids = {call['arguments']['session_id'] for call in server.calls}
    assert len(session_ids) == 1
    UUID(next(iter(session_ids)))
    search_event = next(event for event in events if event['type'] == 'search_results')
    assert search_event['parallel_results'][0]['content'] == 'SEARCH EVIDENCE'
    assert not any(event['type'] == 'report_ready' for event in events)
