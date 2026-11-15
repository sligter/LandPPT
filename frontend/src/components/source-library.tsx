import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Collapse, Empty, Flex, Input, Pagination, Select, Space, Spin, Tag, Typography } from 'antd';
import { FileTextOutlined, LinkOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons';
import { request, type ApiData } from '../api';
import { ProjectSources, type SourceSummary } from './project-sources';

const labels: Record<string, string> = { file: '文件资料', url: '网页链接', mixed: '混合资料', manual: '仅文字' };

function validProject(project: ApiData) {
  return project && typeof project.id === 'string' && !!project.id && typeof project.title === 'string'
    && Array.isArray(project.files) && project.files.every((value: unknown) => typeof value === 'string')
    && Array.isArray(project.urls) && project.urls.every((value: unknown) => typeof value === 'string' && /^https?:\/\//.test(value))
    && ['file_count', 'url_count', 'invalid_url_count'].every(key => Number.isInteger(project[key]) && project[key] >= 0)
    && project.file_count >= project.files.length && project.url_count >= project.urls.length + project.invalid_url_count;
}

function SourceItems({ project, expanded }: { project: ApiData; expanded?: boolean }) {
  const files: string[] = expanded ? project.files : project.files.slice(0, 3), urls: string[] = expanded ? project.urls : project.urls.slice(0, 2);
  return <Space orientation="vertical" size="small" className="source-library-items">
    {!!project.file_count && <Flex align="center" wrap gap={8}><Typography.Text type="secondary"><FileTextOutlined aria-hidden /> 附件 {project.file_count}</Typography.Text>{files.map((name, index) => <Tag key={index}><Typography.Text ellipsis={{ tooltip: name }}>{name}</Typography.Text></Tag>)}</Flex>}
    {!!project.url_count && <Space orientation="vertical" size={4} className="source-library-urls"><Typography.Text type="secondary"><LinkOutlined aria-hidden /> 链接 {project.url_count}</Typography.Text>{urls.map((url, index) => <Typography.Link key={index} href={url} target="_blank" rel="noopener noreferrer" ellipsis title={url}>{url}</Typography.Link>)}</Space>}
    {!!project.invalid_url_count && <Typography.Text type="warning">{project.invalid_url_count} 条链接无效，请在管理资料中检查。</Typography.Text>}
    {!project.file_count && !project.url_count && <Typography.Text type="secondary">暂无附件或链接，可通过管理资料添加。</Typography.Text>}
    {expanded && (project.file_count > project.files.length || project.url_count - project.invalid_url_count > project.urls.length) && <Typography.Text type="secondary">此处最多展示每类 50 条，完整记录请打开管理资料。</Typography.Text>}
  </Space>;
}

export function SourceLibrary({ active, projectId: fixedProjectId, onSourcesSaved }: { active: boolean; projectId?: string; onSourcesSaved?: (projectId: string, summary: SourceSummary) => void }) {
  const [projects, setProjects] = useState<ApiData[]>([]), [page, setPage] = useState(1), [total, setTotal] = useState(0);
  const [search, setSearch] = useState(''), [query, setQuery] = useState(''), [kind, setKind] = useState(''), [sort, setSort] = useState('newest');
  const [projectId, setProjectId] = useState(() => fixedProjectId ?? (new URLSearchParams(location.search).get('project') || '')), [scope, setScope] = useState<ApiData | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState(''), [reload, setReload] = useState(0), [editing, setEditing] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null), region = useRef<HTMLElement>(null), returnProject = useRef<string | null>(null);
  useEffect(() => { if (active) { const id = fixedProjectId ?? (new URLSearchParams(location.search).get('project') || ''); if (id !== projectId) { setProjectId(id); setScope(null); setPage(1); } } }, [active, fixedProjectId]);
  useEffect(() => { const timer = setTimeout(() => setQuery(search), 200); return () => clearTimeout(timer); }, [search]);
  useEffect(() => {
    if (!active || editing || projectId !== (fixedProjectId ?? (new URLSearchParams(location.search).get('project') || ''))) return;
    const controller = new AbortController();
    let correctingPage = false;
    setLoading(true); setError('');
    const params = new URLSearchParams({ page: String(page), per_page: '6', search: query, kind, sort });
    if (projectId) params.set('project_id', projectId);
    request('/api/source-library?' + params, 'GET', undefined, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(result.projects) || !Number.isInteger(result.pagination?.total_count) || result.pagination.total_count < 0 || !Number.isInteger(result.pagination?.current_page) || result.pagination.current_page < 1 || result.pagination.current_page > Math.max(1, Math.ceil(result.pagination.total_count / 6)) || !result.projects.every(validProject)) throw new Error('资料列表数据不完整，请重试');
      setProjects(result.projects); setTotal(result.pagination.total_count); setScope(result.project || null);
      if (result.pagination.current_page !== page) { correctingPage = true; setPage(result.pagination.current_page); }
    }).catch(reason => { if (!controller.signal.aborted) { setError(reason.message); setProjects([]); setTotal(0); } }).finally(() => {
      if (controller.signal.aborted) return;
      // Keep controls disabled until the corrected page's own read completes.
      if (!correctingPage) setLoading(false);
    });
    return () => controller.abort();
  }, [active, editing, page, query, kind, sort, projectId, reload]);
  useEffect(() => {
    if (!active) { returnProject.current = null; return; }
    if (loading || !returnProject.current) return;
    // Effects run after the refreshed cards and enabled triggers reach the DOM.
    // An animation frame scheduled by the request can precede that commit.
    const id = returnProject.current; returnProject.current = null;
    if (document.activeElement !== document.body) return;
    const card = Array.from(region.current?.querySelectorAll<HTMLElement>('[data-source-project]') || []).find(node => node.dataset.sourceProject === id);
    (card?.querySelector<HTMLButtonElement>('.source-library-project-heading button') || heading.current)?.focus({ preventScroll: true });
  }, [active, loading, projects]);
  function clearScope() { setProjectId(''); setScope(null); setPage(1); const url = new URL(location.href); url.searchParams.delete('project'); history.replaceState(history.state, '', url); }
  const clear = () => { setSearch(''); setQuery(''); setKind(''); setSort('newest'); setPage(1); };
  return <div className="source-library settings-stack">
    <div className="page-heading"><div><h1 ref={heading} tabIndex={-1}>项目资料</h1><p>按项目整理附件和网页链接</p></div><Button href="/projects">打开项目</Button></div>
    <Typography.Text type="secondary">修改资料后，需重新生成大纲才会应用到内容。</Typography.Text>
    {projectId && <Flex align="center" gap={8} className="source-library-scope"><Tag><Typography.Text ellipsis={{ tooltip: scope?.title }}>项目：{scope?.title || '当前项目'}</Typography.Text></Tag>{!fixedProjectId && <Button type="link" size="small" disabled={!!editing} aria-label="查看所有项目资料" onClick={clearScope}>所有项目</Button>}</Flex>}
    <Card size="small"><div className="source-library-toolbar">
      <Input.Search aria-label="搜索资料项目" placeholder="搜索项目名称或主题" maxLength={200} allowClear disabled={!!editing} value={search} enterButton={<Button className="source-library-search-submit" aria-label="搜索资料项目" icon={<SearchOutlined aria-hidden />} />} onChange={event => { setSearch(event.target.value); setPage(1); }} onSearch={value => { setQuery(value); setPage(1); }} />
      <Select aria-label="项目资料类型" disabled={!!editing} value={kind} options={[{ value: '', label: '全部资料' }, { value: 'file', label: '文件资料' }, { value: 'url', label: '网页链接' }]} onChange={value => { setKind(value); setPage(1); }} />
      <Select aria-label="项目资料排序" disabled={!!editing} value={sort} options={[{ value: 'newest', label: '最近更新' }, { value: 'oldest', label: '最早更新' }]} onChange={value => { setSort(value); setPage(1); }} />
      <Button aria-label="刷新项目资料" disabled={!!editing} loading={loading && !editing} icon={<ReloadOutlined aria-hidden />} onClick={() => setReload(value => value + 1)} />
    </div></Card>
    {error && <Alert showIcon type="error" title="项目资料读取失败" description={error} action={<Button onClick={() => setReload(value => value + 1)}>重试</Button>} />}
    {loading && !editing && <div role="status"><Spin size="small" /> 正在读取项目资料…</div>}
    <section ref={region} aria-label="资料项目列表" aria-busy={loading && !editing} className="source-library-projects">{projects.map(project => <Card key={project.id} size="small" data-source-project={project.id}>
      <Flex justify="space-between" align="flex-start" gap={12} className="source-library-project-heading"><Space orientation="vertical" size={8}><Typography.Link strong ellipsis href={`/projects/${encodeURIComponent(project.id)}`} title={project.title}>{project.title}</Typography.Link><Flex gap={8} align="center" wrap><Tag>{labels[project.source_kind] || '项目资料'}</Tag><Typography.Text type="secondary">更新于 {new Date(project.updated_at * 1000).toLocaleString('zh-CN', { hour12: false })}</Typography.Text></Flex></Space>
        <ProjectSources projectId={project.id} disabled={editing ? editing !== project.id : loading} onSaved={summary => onSourcesSaved?.(project.id, summary)} onOpenChange={open => { if (open) setEditing(project.id); }} onAfterClose={() => { returnProject.current = project.id; setEditing(null); }} />
      </Flex>
      {project.files.length > 3 || project.urls.length > 2 ? <Collapse ghost size="small" items={[{ key: 'sources', label: `查看资料 · ${project.file_count} 个附件 · ${project.url_count} 个链接`, children: <SourceItems project={project} expanded /> }]} /> : <SourceItems project={project} />}
    </Card>)}</section>
    {!loading && !error && !projects.length && <Card size="small"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={query || kind ? '没有匹配的资料项目' : '暂无包含资料的项目'}>{query || kind ? <Button onClick={clear}>清除筛选</Button> : <Button href="/dashboard">开始创作</Button>}</Empty></Card>}
    <Space className="projects-pagination"><Typography.Text type="secondary">共 {total} 个项目</Typography.Text><Pagination current={page} pageSize={6} total={total} showSizeChanger={false} showLessItems disabled={loading || !!editing} onChange={setPage} /></Space>
  </div>;
}
