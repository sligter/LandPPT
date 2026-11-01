import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Card, Descriptions, Empty, Form, Input, Pagination, Space, Spin, Table, Tag } from 'antd';
import { DeleteOutlined, ReloadOutlined } from '@ant-design/icons';
import { request, type ApiData } from '../api';
import { formatTime } from '../forms';
import { useAdminActions } from '../components/admin-data';

function useResearchRead(endpoint: string) {
  const [data, setData] = useState<ApiData>(); const [error, setError] = useState(''); const [loading, setLoading] = useState(true); const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError('');
    request(endpoint, 'GET', undefined, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (endpoint.endsWith('/reports') ? !Array.isArray(result.reports) : typeof result.available !== 'boolean') throw new Error('服务返回的数据无效，请重试');
      setData(result);
    })
      .catch(reason => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [endpoint, revision]);
  return { data, error, loading, refresh: () => setRevision(value => value + 1) };
}
const number = (value: unknown) => Number.isFinite(Number(value)) ? Number(value) : 0;
const text = (value: unknown) => typeof value === 'string' ? value : value == null ? '' : JSON.stringify(value);

export default function Research() {
  const status = useResearchRead('/api/research/status'); const reports = useResearchRead('/api/research/reports'); const actions = useAdminActions();
  const [pending, setPending] = useState(false); const locked = useRef(false); const [error, setError] = useState(''); const [result, setResult] = useState<ApiData>(); const [elapsed, setElapsed] = useState(0);
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(10);
  const rows: ApiData[] = Array.isArray(reports.data?.reports) ? reports.data.reports : [];
  const current = Math.min(page, Math.max(1, Math.ceil(rows.length / pageSize)));
  useEffect(() => {
    if (!pending) return;
    const start = Date.now(); setElapsed(0); const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [pending]);
  async function conduct(values: ApiData) {
    if (locked.current || !status.data?.available || status.loading || status.error) return;
    locked.current = true; setPending(true); setError('');
    try {
      // FastAPI's existing endpoint takes query parameters, not a form body.
      const query = new URLSearchParams({ topic: values.topic.trim(), language: 'zh' });
      const response = await request('/api/research/conduct?' + query, 'POST');
      if (!response.report) throw new Error('研究结果为空，请重试');
      setResult(response); reports.refresh();
    } catch (reason) { setError((reason as Error).message); }
    finally { locked.current = false; setPending(false); }
  }
  function remove(row: ApiData) {
    actions.confirm('删除研究报告', `确定删除「${row.filename}」？此操作无法撤销。`, async () => {
      await actions.run('/api/research/reports/' + encodeURIComponent(row.filename), 'DELETE');
      actions.message.success('报告已删除'); reports.refresh();
    }, true);
  }
  const removeButton = (row: ApiData) => <Button danger type="text" icon={<DeleteOutlined />} disabled={actions.pending || reports.loading} aria-label={`删除报告 ${row.filename}`} onClick={() => remove(row)}>删除</Button>;
  const report = result?.report;
  return <div className="research-page">
    <div className="page-heading"><h1>深度研究</h1><Button href="/scenarios">创建 PPT</Button></div>
    <div className="research-top-grid">
      <Card size="small" title="服务状态" extra={<Button icon={<ReloadOutlined aria-hidden />} loading={status.loading} onClick={status.refresh}>刷新状态</Button>}>
        {status.error && <Alert type="error" title={status.error} action={<Button onClick={status.refresh}>重试</Button>} className="page-error" />}
        {status.loading && !status.data ? <div role="status"><Spin /> 正在检查研究服务…</div> : status.data && <>
          <Space wrap className="research-service-tags"><Tag color={status.data.available ? 'success' : 'default'}>{status.data.available ? '服务可用' : '服务不可用'}</Tag><Tag>{status.data.status?.research_provider === 'deepseek' ? (status.data.deepseek_configured ? 'DeepSeek 已配置' : 'DeepSeek 未配置') : (status.data.tavily_configured ? 'Tavily 已配置' : 'Tavily 未配置')}</Tag></Space>
          <Descriptions size="small" column={1} items={[
            { key: 'provider', label: 'AI 提供商', children: text(status.data.status?.ai_provider_type) || '—' },
            { key: 'results', label: '最大搜索结果', children: status.data.status?.max_results ?? '—' },
            { key: 'depth', label: '搜索深度', children: text(status.data.status?.search_depth) || '—' },
          ]} />
          {!status.data.available && <Alert type="warning" title="研究服务尚未就绪" description={<span>{text(status.data.message) || '请检查研究服务配置。'} <a href="/ai-config">前往系统配置</a></span>} />}
        </>}
        <p className="subtle research-method">DEEP：定义目标 → 深入探索 → 评估信息 → 生成报告</p>
      </Card>
      <Card size="small" title="运行研究">
        <Form layout="vertical" disabled={pending} onFinish={conduct}>
          <Form.Item name="topic" label="研究主题" rules={[{ required: true, whitespace: true, message: '请输入研究主题' }]}><Input.TextArea aria-label="研究主题" autoSize={{ minRows: 2, maxRows: 5 }} placeholder="例如：人工智能在教育领域的应用趋势" /></Form.Item>
          <Space wrap><Button type="primary" htmlType="submit" aria-label="开始研究" aria-busy={pending} loading={pending} disabled={pending || status.loading || !!status.error || !status.data?.available}>开始研究</Button>
            {pending ? <span role="status">研究进行中，已等待 {elapsed} 秒…</span> : <span className="subtle">生成中文报告，完成后刷新报告列表。</span>}</Space>
        </Form>
        {error && <Alert type="error" title="研究失败" description={error} className="page-error" />}
      </Card>
    </div>
    {report && <Card size="small" title="研究结果" className="research-result">
      <Descriptions size="small" column={{ xs: 1, sm: 2, lg: 4 }} items={[
        { key: 'topic', label: '主题', children: text(report.topic) },
        { key: 'duration', label: '耗时', children: `${number(report.total_duration).toFixed(2)} 秒` },
        { key: 'sources', label: '信息源', children: number(report.sources_count) },
        { key: 'steps', label: '研究步骤', children: number(report.steps_count) },
      ]} />
      {result?.report_path && <p className="subtle">报告已保存：{text(result.report_path)}</p>}
      <h2>执行摘要</h2><p className="research-summary">{text(report.executive_summary) || '未返回执行摘要'}</p>
      {['key_findings', 'recommendations'].map(key => Array.isArray(report[key]) && report[key].length > 0 && <div key={key}><h2>{key === 'key_findings' ? '主要发现' : '建议'}</h2><ul>{report[key].map((item: unknown, index: number) => <li key={index}>{text(item)}</li>)}</ul></div>)}
    </Card>}
    <Card size="small" title="已保存的报告" extra={<Button icon={<ReloadOutlined aria-hidden />} loading={reports.loading} disabled={actions.pending} onClick={reports.refresh}>刷新报告</Button>}>
      {reports.error && <Alert type="error" title={reports.error} action={<Button onClick={reports.refresh}>重试</Button>} className="page-error" />}
      {actions.error && <Alert type="error" title={actions.error} className="page-error" />}
      {reports.data?.reports_directory && <p className="subtle research-directory">保存位置：{text(reports.data.reports_directory)}</p>}
      <div className="account-table"><Table<ApiData> size="small" rowKey="filename" loading={reports.loading} dataSource={rows.slice((current - 1) * pageSize, current * pageSize)} pagination={false} locale={{ emptyText: <Empty description="暂无保存的研究报告" /> }} columns={[
        { title: '报告名称', dataIndex: 'filename', render: value => <span className="research-filename">{value}</span> },
        { title: '大小', width: 110, render: (_, row) => `${(number(row.size) / 1024).toFixed(1)} KB` },
        { title: '创建时间', width: 180, render: (_, row) => formatTime(row.created) },
        { title: '操作', width: 100, render: (_, row) => removeButton(row) },
      ]} /></div>
      <div className="account-mobile-list">{reports.loading && <p role="status">正在加载报告…</p>}{rows.length ? rows.slice((current - 1) * pageSize, current * pageSize).map(row => <Card size="small" key={row.filename}><p className="research-filename">{row.filename}</p><p className="subtle">{(number(row.size) / 1024).toFixed(1)} KB · {formatTime(row.created)}</p>{removeButton(row)}</Card>) : !reports.loading && <Empty description="暂无保存的研究报告" />}</div>
      <div className="projects-pagination"><span className="subtle">共 {rows.length} 份报告</span><Pagination current={current} total={rows.length} pageSize={pageSize} showSizeChanger pageSizeOptions={[10, 20, 50]} showLessItems disabled={reports.loading} onChange={(next, size) => { setPage(size === pageSize ? next : 1); setPageSize(size); }} /></div>
    </Card>
  </div>;
}
