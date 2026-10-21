# Presentation research search providers

The presentation outline's enhanced research workflow can search the web and fetch
page excerpts with [Parallel Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp).
Parallel search uses Fast mode and needs no account or API key. The service has
free usage limits; provider errors are reported without switching to another
search provider.

For a fresh installation, leave `TAVILY_API_KEY` and `SEARXNG_HOST` empty and use:

```dotenv
RESEARCH_PROVIDER=auto
```

Enable network research when creating a presentation. An AI provider is still
needed to plan the research and summarize its sources. `auto` uses configured
Tavily credentials first, then a configured SearXNG host, and otherwise Parallel.
Existing saved provider selections take precedence and are not migrated.

To select Parallel explicitly, choose **Parallel** under **Settings → Generation
parameters → Research provider** (设置 → 生成参数 → 研究提供商), or set
`RESEARCH_PROVIDER=parallel` for environment-based configuration. The administrator
can also choose a system default. User selections override system defaults;
explicit environment selections remain effective when the database only supplies
the new `auto` default.

`RESEARCH_PROVIDER=tavily`, `searxng` and `both` remain available. Tavily's advanced
search settings and the legacy Tavily-only ReAct research endpoint retain their
existing behavior. This integration applies to enhanced presentation research,
including `/research/enhanced/conduct`; it does not change the legacy
`/research/conduct` endpoint or image search.

With Parallel selected, page extraction uses MCP `web_fetch` excerpts from the
search results. Turn off **content extraction** (`RESEARCH_ENABLE_CONTENT_EXTRACTION=false`)
to perform search only. The existing network-mode opt-out and global
`ENABLE_NETWORK_MODE=false` stop enhanced research. Each research run has its own
opaque session identifier, reused for its searches and fetches. Requests use
`https://search.parallel.ai/mcp` with a configurable research extraction timeout
(`RESEARCH_EXTRACTION_TIMEOUT`, default 30 seconds per MCP operation).
