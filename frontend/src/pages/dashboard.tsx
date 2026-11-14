import { useLayoutEffect, useRef, useState } from 'react';
import { App, Button, Card, ConfigProvider, Empty, Flex, Grid, Progress, Typography } from 'antd';
import { ArrowRightOutlined, FileTextOutlined } from '@ant-design/icons';
import type { ApiData } from '../api';
import { progressPercent } from '../progress';
import { projectPath, ProjectCover, ProjectLibraryTitle, ProjectStatus, useProjectActions, type Project } from '../components/projects';
import CreateComposer from '../components/create-composer';

const summaries = [['总项目数', '/projects'], ['已完成', '/projects?status=completed'], ['进行中', '/projects?status=in_progress'], ['草稿', '/projects?status=draft']];
// The recent grid fills whole rows; below four columns that means more than one
// row so phones do not drop to a single card.
const MIN_RECENT_CARDS = 4;

function recentCardCount(columns: number) {
  return columns * Math.max(1, Math.ceil(MIN_RECENT_CARDS / columns));
}

export default function Dashboard({ data }: { data: ApiData }) {
  const [projects, setProjects] = useState<Project[]>(data.projects);
  // Start from the usual four-card desktop row; the grid is measured right after
  // mount so wider layouts grow before the first paint.
  const [columns, setColumns] = useState(MIN_RECENT_CARDS);
  const recentList = useRef<HTMLUListElement | null>(null);
  const { message } = App.useApp();
  const screens = Grid.useBreakpoint();
  useLayoutEffect(() => {
    const list = recentList.current;
    if (!list) return;
    const measure = () => {
      // `auto-fill` resolves the computed track list to the tracks that fit, so
      // this is the current column count of the grid.
      const tracks = getComputedStyle(list).gridTemplateColumns.split(' ').filter(Boolean).length;
      const next = Math.max(1, tracks);
      setColumns(current => (current === next ? current : next));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(list);
    return () => observer.disconnect();
  }, [projects.length]);
  const visibleProjects = projects.slice(0, recentCardCount(columns));
  async function refreshProjects(id: string, flags: Pick<Project, 'is_favorite' | 'is_pinned'>) {
    // Keep the confirmed flags even if the follow-up read fails. Updating this
    // section in place preserves the user's in-progress creation form.
    setProjects(previous => previous.map(project => project.project_id === id ? { ...project, ...flags } : project));
    try {
      const response = await fetch('/dashboard', { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'text/html' } });
      if (!response.ok) throw new Error('Read failed');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const updated = JSON.parse(doc.getElementById('antdData')?.textContent || '{}') as ApiData;
      if (updated.page !== 'dashboard' || updated.user?.username !== data.user?.username || !!updated.user?.is_admin !== !!data.user?.is_admin || !Array.isArray(updated.projects)) throw new Error('Invalid page');
      setProjects(updated.projects);
    } catch {
      message.warning('整理已保存，项目列表暂未刷新。请刷新页面查看完整排序。');
    }
  }
  const { actions, organize, renameDialog } = useProjectActions((id, title) => setProjects(previous => previous.map(project => project.project_id === id ? { ...project, title } : project)), refreshProjects);
  return <div id="dashboardRoot">
    <div className="page-heading dashboard-header"><h1 className="sr-only">首页</h1>
      <nav className="dashboard-summary" aria-label="项目概览">{summaries.map(([label, href], index) => <Button className="dashboard-stat" key={label} href={href} aria-label={`${label} ${Number(data.stats[index] || 0).toLocaleString()}`}><span className="stat-title">{label}</span><Typography.Text strong className="stat-number">{Number(data.stats[index] || 0).toLocaleString()}</Typography.Text></Button>)}</nav>
    </div>
    <section className="dashboard-create" aria-labelledby="dashboardCreateTitle"><Typography.Title level={2} id="dashboardCreateTitle" className="dashboard-create-title">想把什么，变成一场好演示？</Typography.Title><CreateComposer data={data} compact /></section>
    <div className={`dashboard-workspace${data.todos.length ? ' dashboard-workspace--with-tasks' : ''}`}>
      <section className="dashboard-recent" aria-labelledby="recentProjectsTitle">
        <div className="section-heading recent-projects-header"><h2 id="recentProjectsTitle">{projects.some(project => project.is_pinned) ? '置顶与最近项目' : '最近项目'}</h2><Flex gap={4}><Button type="text" href="/projects?favorite=true">我的收藏</Button><Button type="text" className="dashboard-all-projects" href="/projects">所有项目<ArrowRightOutlined aria-hidden /></Button></Flex></div>
        <div className="dashboard-projects">{projects.length ? <ul ref={recentList}>{visibleProjects.map(project => <li className="dashboard-project-item" key={project.project_id}>
          <Card hoverable size="small" cover={<a className="project-cover-link" href={projectPath(project)} aria-label={`打开项目 ${project.title}`}><ProjectCover project={project} /></a>}>
            <Card.Meta title={<ProjectLibraryTitle project={project} organize={organize} />} description={`更新于 ${project.updated}`} />
            <Flex className="dashboard-project-footer" justify="space-between" align="center" gap={8}><ProjectStatus project={project} /><ConfigProvider componentSize={screens.md ? 'small' : undefined}>{actions(project)}</ConfigProvider></Flex>
          </Card>
        </li>)}</ul> : <Empty image={<FileTextOutlined aria-hidden />} description="还没有项目"><Button type="primary" href="/scenarios">创建第一份演示文稿</Button></Empty>}</div>
      </section>
      {!!data.todos.length && <aside className="dashboard-tasks" aria-labelledby="dashboardTasksTitle"><div className="section-heading"><h2 id="dashboardTasksTitle">进行中的任务</h2><span className="subtle">{data.todos.length} 项</span></div><div className="dashboard-task-list">{data.todos.map((todo: ApiData) => <article key={todo.id}><a className="dashboard-task-title" href={`/projects/${encodeURIComponent(todo.id)}/todo`}>{todo.title}</a><Progress percent={progressPercent(todo.progress)} strokeColor="var(--lp-primary)" /><p className="subtle">当前阶段：{todo.stage}</p><Button href={`/projects/${encodeURIComponent(todo.id)}/todo`} icon={<ArrowRightOutlined aria-hidden />}>查看进度</Button></article>)}</div></aside>}
    </div>
    {renameDialog}
  </div>;
}
