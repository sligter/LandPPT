import { useEffect, useRef, useState } from 'react';
import { Button, Empty, Input, Pagination, Select, Space, Tabs } from 'antd';
import { SearchOutlined, CloseCircleFilled } from '@ant-design/icons';
import { ProjectCollection, projectStates, useProjectActions, type Project } from '../components/projects';
import type { ApiData } from '../api';
import { navigatePage } from '../navigation';

export default function Projects({ data }: { data: ApiData }) {
  const [{ projects, currentPage, total }, setListing] = useState({
    projects: data.projects as Project[], currentPage: data.currentPage as number, total: data.total as number,
  });
  const [search, setSearch] = useState<string>(data.searchQuery || '');
  const revision = useRef(0);
  const hasActiveProjects = projects.some(project => project.status === 'in_progress');
  const { actions, organize, renameDialog } = useProjectActions((id, title) => {
    revision.current += 1;
    setListing(previous => ({ ...previous, projects: previous.projects.map(project => project.project_id === id ? { ...project, title } : project) }));
  });
  function navigate(page: number, status = data.statusFilter || '', query = data.searchQuery || '', favorite = !!data.favoriteFilter, sort = data.sortOrder || 'pinned') {
    const url = new URL(location.href);
    if (status) url.searchParams.set('status', status); else url.searchParams.delete('status');
    if (query.trim()) url.searchParams.set('search', query.trim()); else url.searchParams.delete('search');
    if (page > 1) url.searchParams.set('page', String(page)); else url.searchParams.delete('page');
    if (favorite) url.searchParams.set('favorite', 'true'); else url.searchParams.delete('favorite');
    if (sort !== 'pinned') url.searchParams.set('sort', sort); else url.searchParams.delete('sort');
    navigatePage(url.toString());
  }
  useEffect(() => {
    if (!hasActiveProjects) return;
    const path = location.pathname;
    let query = location.search;
    let timer: number | undefined;
    let pending: AbortController | undefined;
    const isCurrentPage = () => location.pathname === path && location.search === query;

    function schedule() {
      if (!document.hidden && !pending) timer = window.setTimeout(refresh, 30000);
    }

    async function refresh() {
      if (document.hidden || pending || !isCurrentPage()) return;
      const controller = new AbortController();
      const version = revision.current;
      pending = controller;
      try {
        const url = path + query;
        const response = await fetch(url, { credentials: 'same-origin', cache: 'no-store', signal: controller.signal, headers: { Accept: 'text/html' } });
        if (!response.ok) return;
        const target = new URL(response.url || url, location.origin);
        if (target.origin !== location.origin || target.pathname !== path) return;
        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        const updated = JSON.parse(doc.getElementById('antdData')?.textContent || '{}') as ApiData;
        if (controller.signal.aborted || !isCurrentPage() || version !== revision.current) return;
        if (updated.page !== 'projects' || updated.user?.username !== data.user?.username || !!updated.user?.is_admin !== !!data.user?.is_admin || !Array.isArray(updated.projects)) return;

        // The server can move a favorites page back into range as rows change.
        if (target.search !== query) {
          target.hash = location.hash;
          history.replaceState(history.state, '', target.href);
          query = target.search;
        }
        setListing({ projects: updated.projects, currentPage: updated.currentPage, total: updated.total });
      } catch {
        // Keep the current rows and retry at the next check.
      } finally {
        if (pending === controller) {
          pending = undefined;
          schedule();
        }
      }
    }

    function stop() {
      window.clearTimeout(timer);
      pending?.abort();
      pending = undefined;
    }

    function onVisibilityChange() {
      stop();
      if (!document.hidden) void refresh();
    }

    schedule();
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [data.user, hasActiveProjects]);
  return <div className="projects-page">
    <div className="page-heading dashboard-header"><h1>项目列表</h1></div>
    <Tabs className="project-library-tabs" activeKey={data.favoriteFilter ? 'favorites' : 'all'} items={[{ key: 'all', label: '全部项目' }, { key: 'favorites', label: '我的收藏' }]} onChange={key => navigate(1, data.statusFilter || '', data.searchQuery || '', key === 'favorites')} />
    <div className="projects-toolbar"><Input.Search className="projects-search" role="searchbox" aria-label="搜索项目" placeholder="搜索标题、主题或项目 ID" value={search} onChange={event => setSearch(event.target.value)} allowClear={{ clearIcon: <CloseCircleFilled aria-label="清除搜索" /> }} enterButton={<Button aria-label="搜索" title="搜索" icon={<SearchOutlined aria-hidden />} />} onSearch={query => navigate(1, data.statusFilter || '', query)} /><div className="projects-status-filter"><label className="sr-only" htmlFor="statusFilter">状态筛选</label><Select id="statusFilter" value={data.statusFilter || ''} onChange={status => navigate(1, status)} options={[{ value: '', label: '全部状态' }, ...Object.entries(projectStates).map(([value, [label]]) => ({ value, label }))]} /></div><div className="projects-sort-filter"><label className="sr-only" htmlFor="projectSort">排序</label><Select id="projectSort" value={data.sortOrder || 'pinned'} onChange={sort => navigate(1, data.statusFilter || '', data.searchQuery || '', !!data.favoriteFilter, sort)} options={[{ value: 'pinned', label: '置顶优先' }, { value: 'updated', label: '最近更新' }]} /></div><span className="subtle">共 {total} 个项目</span></div>
    <ProjectCollection projects={projects} actions={actions} organize={organize} empty={<Empty description={data.searchQuery ? '没有找到匹配的项目' : data.statusFilter ? '没有符合当前状态的项目' : data.favoriteFilter ? '还没有收藏的项目' : '暂无项目'}><Space><Button type="primary" href="/scenarios">创建项目</Button>{(data.statusFilter || data.searchQuery || data.favoriteFilter) && <Button href="/projects">查看全部</Button>}</Space></Empty>} />
    <div className="projects-pagination"><Pagination current={currentPage} pageSize={data.pageSize} total={total} showSizeChanger={false} showLessItems onChange={page => navigate(page)} /></div>
    {renameDialog}
  </div>;
}
