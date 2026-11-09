import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Dropdown, Modal, Select, Space, Spin, Typography, type MenuProps } from 'antd';
import { LeftOutlined, MoreOutlined, RightOutlined } from '@ant-design/icons';
import { request, errorText, type ApiData } from '../api';
import { modalFocus } from './modal-focus';

export const templateAPI = '/api/global-master-templates';
export const packageAPI = templateAPI + '/packages';
export const families: Record<string, string> = { cover: '封面', section: '章节', points: '要点', comparison: '对比', process: '流程', image: '图文', metrics: '指标', summary: '总结' };
export const packageStatuses: Record<string, string> = { draft: '草稿', validated: '已校验', published: '已发布', retired: '已停用' };

// Conditional dialog islands unmount immediately, before Ant's after-close restore.
export function useTemplateModalFocus() {
  const origin = useRef(document.activeElement as HTMLElement | null);
  useEffect(() => () => { if (origin.current?.isConnected) origin.current.focus({ preventScroll: true }); }, []);
}

export function TemplateMore({ name, items, disabled }: { name: string; items: MenuProps['items']; disabled?: boolean }) {
  const trigger = useRef<HTMLButtonElement>(null);
  return <Dropdown trigger={['click']} menu={{ items }} popupRender={menu => <div onKeyDownCapture={event => {
    if (event.key === 'Escape') queueMicrotask(() => trigger.current?.focus());
  }}>{menu}</div>}><Button ref={trigger} aria-label={name + '更多操作'} icon={<MoreOutlined aria-hidden />} disabled={disabled} /></Dropdown>;
}

// Keep the slide document at its original size; only scale its outer frame.
export function TemplateFrame({ html, src, title }: { html?: string; src?: string; title: string }) {
  const holder = useRef<HTMLDivElement>(null); const [scale, setScale] = useState(0);
  useEffect(() => {
    const element = holder.current!;
    const observer = new ResizeObserver(() => setScale(element.clientWidth / 1280));
    observer.observe(element); return () => observer.disconnect();
  }, []);
  return <div ref={holder} className="template-frame"><iframe className="template-preview-iframe" title={title} src={src} srcDoc={html} sandbox={html ? 'allow-scripts' : ''} tabIndex={-1} loading="lazy" style={{ transform: `scale(${scale})` }} /></div>;
}

export function sampleHTML(html: string, title: string) {
  const sample = html.replace(/\{\{\s*title\s*\}\}/g, () => title).replace(/\{\{\s*content\s*\}\}/g, '预览内容').replace(/\{\{\s*(slide_number|total_slides)\s*\}\}/g, '1');
  return /<html[\s>]/i.test(sample) ? sample : `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>body{width:1280px;height:720px;margin:0;padding:0}</style></head><body>${sample}</body></html>`;
}

export function TemplateThumbnail({ template }: { template: ApiData }) {
  const [html, setHTML] = useState(''); const [error, setError] = useState(false); const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setError(false);
    request(`${templateAPI}/${template.id}`, 'GET', undefined, controller.signal).then(data => {
      if (!data.html_template) throw new Error('模板内容为空');
      if (!controller.signal.aborted) setHTML(sampleHTML(data.html_template, data.template_name || template.template_name));
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [template.id, retry]);
  return error ? <div className="template-preview-fallback"><span>预览加载失败</span><Button onClick={() => setRetry(value => value + 1)}>重试预览</Button></div> : html ? <TemplateFrame html={html} title={template.template_name + '预览'} /> : <div className="template-preview-fallback"><Spin /><span>正在加载预览…</span></div>;
}

export function TemplatePreview({ template, onClose, onSelect, selectLabel = '使用此模板', selectDisabled = false }: { template: ApiData; onClose: () => void; onSelect?: () => void; selectLabel?: string; selectDisabled?: boolean }) {
  useTemplateModalFocus();
  const components: ApiData[] = template.manifest?.components || [];
  const [component, setComponent] = useState(components[0]?.id); const [html, setHTML] = useState(template.html_template || ''); const [error, setError] = useState(''); const [retry, setRetry] = useState(0);
  const selectedIndex = Math.max(0, components.findIndex(item => item.id === component));
  const thumbnailStart = Math.floor(selectedIndex / 6) * 6;
  const previewURL = (id: string) => `${packageAPI}/${template.id}/preview/${encodeURIComponent(id)}?h=${(template.content_hash || '').slice(0, 12)}`;
  useEffect(() => {
    if (components.length || template.html_template) return;
    const controller = new AbortController(); setError('');
    request(`${templateAPI}/${template.id}/preview`, 'GET', undefined, controller.signal).then(data => { if (!data.html_template) throw new Error('模板预览内容为空'); if (!controller.signal.aborted) setHTML(data.html_template); }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [template.id, retry]);
  return <Modal open centered width={1000} title={template.template_name || '模板预览'} footer={<Space><Button onClick={onClose}>关闭预览</Button>{onSelect && <Button type="primary" disabled={selectDisabled} onClick={onSelect}>{selectLabel}</Button>}</Space>} onCancel={onClose} modalRender={modalFocus} className="template-detail-modal">
    {(template.description || template.manifest?.description) && <Typography.Paragraph type="secondary" ellipsis={{ rows: 3, expandable: true, symbol: '展开说明' }}>{template.description || template.manifest.description}</Typography.Paragraph>}
    {components.length > 0 && <Select aria-label="预览版式" className="template-preview-select" value={component} onChange={setComponent} options={components.map(item => ({ value: item.id, label: `${families[item.family] || item.family} · ${item.description}` }))} />}
    <div className={components.length ? 'template-detail-layout' : undefined}><div className="template-detail-main">
    {error ? <Alert type="error" title={error} action={<Button onClick={() => setRetry(value => value + 1)}>重试</Button>} /> : components.length ? <TemplateFrame src={previewURL(component)} title="模板包版式预览" /> : html ? <TemplateFrame html={sampleHTML(html, template.template_name || '模板预览')} title="完整模板预览" /> : <div className="page-loading" role="status"><Spin />正在加载预览…</div>}
    {components.length > 0 &&
      <div className="template-detail-pagination"><Button aria-label="上一个版式" icon={<LeftOutlined aria-hidden />} disabled={selectedIndex === 0} onClick={() => setComponent(components[selectedIndex - 1].id)} /><Typography.Text aria-live="polite">版式 {selectedIndex + 1} / {components.length} · {families[components[selectedIndex]?.family] || components[selectedIndex]?.family}</Typography.Text><Button aria-label="下一个版式" icon={<RightOutlined aria-hidden />} disabled={selectedIndex === components.length - 1} onClick={() => setComponent(components[selectedIndex + 1].id)} /></div>
    }</div>
    {components.length > 0 &&
      <div className="template-detail-thumbnails" role="group" aria-label="版式缩略图">{components.slice(thumbnailStart, thumbnailStart + 6).map((item, offset) => <Button key={item.id} className="template-detail-thumbnail" aria-label={`预览版式 ${thumbnailStart + offset + 1} ${families[item.family] || item.family}`} aria-pressed={component === item.id} type={component === item.id ? 'primary' : 'default'} onClick={() => setComponent(item.id)}><TemplateFrame src={previewURL(item.id)} title={`版式缩略图 ${thumbnailStart + offset + 1}`} /><span>{thumbnailStart + offset + 1} · {families[item.family] || item.family}</span></Button>)}</div>
    }</div>
    <p className="subtle">预览使用示例内容，按原始画布比例显示。</p>
  </Modal>;
}

export async function postStream(url: string, payload: ApiData, signal: AbortSignal, onEvent: (event: ApiData) => void): Promise<ApiData> {
  const response = await fetch(url, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' }, body: JSON.stringify(payload), signal });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(errorText(data.detail || data.message || `请求失败（${response.status}）`)); }
  if (!response.headers.get('Content-Type')?.includes('text/event-stream')) {
    const data = await response.json(); if (data.success === false || data.type === 'error' || data.status === 'error') throw new Error(errorText(data.detail || data.message)); return data.data || data;
  }
  if (!response.body) throw new Error('浏览器无法读取生成进度，请刷新后重试。');
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
  function event(block: string) {
    const text = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!text) return;
    const item = JSON.parse(text);
    if (item.type === 'error') throw new Error(errorText(item.message || item.detail));
    onEvent(item); return item;
  }
  try {
    while (true) {
      const { done, value } = await reader.read(); buffer += decoder.decode(value, { stream: !done });
      // Normalize after concatenation so a CR/LF pair split between reads is preserved.
      buffer = buffer.replace(/\r\n/g, '\n'); let split;
      while ((split = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, split); buffer = buffer.slice(split + 2); const item = event(block);
        if (item?.type === 'complete') return item.data || item;
      }
      if (done) { const last = event(buffer); if (last?.type === 'complete') return last.data || last; throw new Error('连接已中断，未收到完成确认。请检查草稿列表后再重试。'); }
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}

export function downloadTemplate(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = filename;
  document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let workspaceLoading: Promise<any> | undefined;
// Load the original request/stream controllers only when opened. Their dialogs
// and ordinary form controls are rendered by the shared Ant surface adapter.
export function packageWorkspace() {
  if (!workspaceLoading) workspaceLoading = (async () => {
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = '/static/css/template-packages.css?v=20261013-workspace-grid'; document.head.append(css);
    for (const name of ['template-packages', 'template-package-workspace', 'template-package-pptx']) {
      await new Promise<void>((resolve, reject) => {
        const script = document.createElement('script'); script.src = `/static/js/${name}.js?v=20261012`;
        const timer = setTimeout(() => { script.remove(); reject(new Error('模板包编辑器加载超时，请重试。')); }, 15000);
        script.onload = () => { clearTimeout(timer); resolve(); }; script.onerror = () => { clearTimeout(timer); script.remove(); reject(new Error('模板包编辑器加载失败，请重试。')); }; document.head.append(script);
      });
    }
    return window as any;
  })().catch(reason => { workspaceLoading = undefined; throw reason; });
  return workspaceLoading;
}
