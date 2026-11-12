import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Drawer, Empty, Flex, Form, Input, Space, Spin, Tag, Typography, Upload } from 'antd';
import { FolderOpenOutlined, InboxOutlined, ReloadOutlined } from '@ant-design/icons';
import { errorText, request } from '../api';
import { sourceExtensions } from './source-materials';
import { modalFocus } from './modal-focus';

type Sources = { revision: string; files: { id: string; filename: string }[]; urls: string[]; editable: boolean };
export type SourceSummary = { files: string[]; urls: string[] };

export function ProjectSources({ projectId, disabled, onSaved, onOpenChange, onAfterClose }: {
  projectId: string; disabled: boolean; onSaved: (value: SourceSummary) => void; onOpenChange: (open: boolean) => void;
  onAfterClose?: () => void;
}) {
  const { modal, message } = App.useApp();
  const [open, setOpen] = useState(false), [loading, setLoading] = useState(false), [saving, setSaving] = useState(false);
  const [snapshot, setSnapshot] = useState<Sources | null>(null), [retained, setRetained] = useState<string[]>([]);
  const [uploads, setUploads] = useState<File[]>([]), [urls, setUrls] = useState('');
  const [error, setError] = useState(''), [warning, setWarning] = useState(''), [attempt, setAttempt] = useState(0);
  const trigger = useRef<HTMLButtonElement>(null), locked = useRef(false);
  const base = `/projects/${encodeURIComponent(projectId)}/sources`;
  const dirty = !!snapshot && (uploads.length > 0 || urls !== snapshot.urls.join('\n') || JSON.stringify(retained) !== JSON.stringify(snapshot.files.map(file => file.id)));
  const blocked = disabled || snapshot?.editable === false;
  function changeOpen(value: boolean) { setOpen(value); onOpenChange(value); }
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true); setError(''); setWarning(''); setSnapshot(null); setUploads([]);
    request(base, 'GET', undefined, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      const sources = result.sources as Sources;
      if (!sources || !Array.isArray(sources.files) || !Array.isArray(sources.urls) || typeof sources.revision !== 'string') throw new Error('资料列表无效，请重试');
      setSnapshot(sources); setRetained(sources.files.map(file => file.id)); setUrls(sources.urls.join('\n'));
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [open, attempt, base]);
  function close() {
    if (locked.current) return;
    if (!dirty) { changeOpen(false); return; }
    modal.confirm({ title: '放弃未保存的资料修改？', content: '项目现有资料会保留。', okText: '放弃修改', cancelText: '继续编辑', modalRender: modalFocus, onOk: () => changeOpen(false) });
  }
  function addFile(file: File) {
    if (!sourceExtensions.includes(file.name.split('.').pop()?.toLowerCase() || '')) setWarning(`不支持的文件类型：${file.name}`);
    else if (!file.size || file.size > 100 * 1024 * 1024) setWarning(`请选择非空且不超过 100MB 的文件：${file.name}`);
    else setUploads(current => current.some(item => item.name === file.name && item.size === file.size) ? current : [...current, file]);
    return false;
  }
  async function save() {
    if (!snapshot || locked.current || blocked) return;
    locked.current = true; setSaving(true); setError('');
    try {
      const body = new FormData();
      body.set('revision', snapshot.revision); body.set('retained_files', JSON.stringify(retained)); body.set('content_urls', urls);
      uploads.forEach(file => body.append('file_upload', file));
      const response = await fetch(base, { method: 'POST', credentials: 'same-origin', body });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.success !== true) throw new Error(errorText(result.detail || result.error || '资料保存失败，请重试'));
      const sources = result.sources as Sources;
      onSaved({ files: sources.files.map(file => file.filename), urls: sources.urls });
      changeOpen(false); void message.success('资料已保存，可重新生成大纲以应用修改');
    } catch (reason) { setError((reason as Error).message); }
    finally { locked.current = false; setSaving(false); }
  }
  return <>
    <Button ref={trigger} icon={<FolderOpenOutlined aria-hidden />} disabled={disabled} onClick={() => changeOpen(true)}>管理资料</Button>
    <Drawer title="管理参考资料" open={open} onClose={close} size={560} styles={{ wrapper: { maxWidth: '100vw' } }} drawerRender={node => modalFocus(node, { height: '100%' })}
      closable={!saving} maskClosable={!saving} keyboard={!saving} afterOpenChange={value => { if (!value) { trigger.current?.focus(); onAfterClose?.(); } }}
      footer={<Flex gap={8} justify="flex-end" wrap><Button disabled={saving} onClick={close}>取消</Button><Button type="primary" loading={saving} disabled={loading || !snapshot || blocked || !dirty} onClick={() => void save()}>保存资料</Button></Flex>}>
      <Space orientation="vertical" size="middle" className="project-sources-form">
        <Alert type="info" showIcon title="保存后，重新生成大纲以应用资料修改。" description="现有大纲与页面会保留，不会自动重新生成。" />
        {blocked && snapshot && <Alert type="warning" showIcon title="项目任务进行中，完成后可重新打开修改资料。" />}
        {loading && <Flex justify="center"><Spin aria-label="正在读取资料" /></Flex>}
        {error && <Alert type="error" showIcon title={snapshot ? '资料保存失败' : '资料读取失败'} description={error}
          action={!snapshot && <Button icon={<ReloadOutlined aria-hidden />} onClick={() => setAttempt(value => value + 1)}>重试读取</Button>} />}
        {snapshot && <Form layout="vertical" disabled={saving || blocked}>
          <Form.Item label="附件" extra="PDF、Word、演示文稿、表格、文本与图片，单个文件不超过 100MB；最多 50 个附件。">
            <Space orientation="vertical" className="project-sources-files">
              {snapshot.files.filter(file => retained.includes(file.id)).map(file => <Flex key={file.id} gap={8} justify="space-between" align="center"><Typography.Text className="project-source-name">{file.filename}</Typography.Text><Button size="small" aria-label={`移除已存附件 ${file.filename}`} onClick={() => setRetained(current => current.filter(id => id !== file.id))}>移除</Button></Flex>)}
              {uploads.map((file, index) => <Flex key={`${file.name}-${file.size}`} gap={8} justify="space-between" align="center"><Typography.Text className="project-source-name">{file.name} <Tag>待保存</Tag></Typography.Text><Button size="small" aria-label={`移除新增附件 ${file.name}`} onClick={() => setUploads(current => current.filter((_, i) => i !== index))}>移除</Button></Flex>)}
              {!retained.length && !uploads.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无附件" />}
              <Upload.Dragger multiple disabled={saving || blocked} accept={sourceExtensions.map(ext => '.' + ext).join(',')} beforeUpload={addFile} showUploadList={false}><p><InboxOutlined aria-hidden /></p><p>选择或拖入新附件</p></Upload.Dragger>
            </Space>
          </Form.Item>
          {warning && <Alert type="warning" title={warning} closable onClose={() => setWarning('')} />}
          <Form.Item label="网页链接" extra="每行一个或逗号分隔，最多 50 个链接；清空表示移除所有链接。"><Input.TextArea aria-label="参考资料链接" value={urls} onChange={event => setUrls(event.target.value)} autoSize={{ minRows: 4, maxRows: 8 }} placeholder="https://example.com/article" /></Form.Item>
          <Typography.Text type="secondary">移除所有资料后，将按主题和创作需求生成大纲。</Typography.Text>
        </Form>}
      </Space>
    </Drawer>
  </>;
}
