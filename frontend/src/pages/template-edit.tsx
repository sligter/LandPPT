import { useEffect, useRef, useState } from 'react';
import { Alert, App, Button, Checkbox, Collapse, Form, Input, Modal, Radio, Space, Spin, Upload, type UploadFile } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import { request, type ApiData } from '../api';
import { copyText } from '../forms';
import { modalFocus } from '../components/modal-focus';
import { postStream, sampleHTML, TemplateFrame, TemplatePreview, templateAPI, useTemplateModalFocus } from '../components/templates';

export function TemplateEdit({ id, onClose, onSaved }: { id?: number; onClose: () => void; onSaved: () => void }) {
  useTemplateModalFocus();
  const [form] = Form.useForm(); const [loading, setLoading] = useState(!!id); const [ready, setReady] = useState(!id); const [pending, setPending] = useState(false); const [error, setError] = useState(''); const [retry, setRetry] = useState(0); const [preview, setPreview] = useState<ApiData>();
  const locked = useRef(false); const { message } = App.useApp();
  useEffect(() => {
    if (!id) return; const controller = new AbortController(); setLoading(true); setReady(false); setError('');
    request(`${templateAPI}/${id}`, 'GET', undefined, controller.signal).then(data => { if (!controller.signal.aborted) { form.setFieldsValue({ ...data, tags: (data.tags || []).join(', ') }); setReady(true); } }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [id, retry]);
  return <><Modal open className="template-editor-modal" centered width={800} title={id ? '编辑母版' : '新建母版'} onCancel={onClose} closable={!pending} keyboard={!pending} mask={{ closable: !pending }} modalRender={modalFocus} footer={<Space wrap><Button disabled={!ready || pending} onClick={() => { const values = form.getFieldsValue(); if (!values.html_template?.trim()) { message.warning('请先输入 HTML 模板内容'); return; } setPreview(values); }}>预览</Button><Button onClick={onClose} disabled={pending}>取消</Button><Button type="primary" aria-label="保存模板" disabled={!ready} loading={pending} onClick={() => form.submit()}>保存</Button></Space>}>
    {loading && <p role="status"><Spin size="small" /> 正在加载模板…</p>}
    {error && <Alert type="error" title={error} action={!ready ? <Button onClick={() => setRetry(value => value + 1)}>重试</Button> : undefined} className="page-error" />}
    <Form form={form} layout="vertical" disabled={!ready || pending} initialValues={{ is_default: false }} onFinish={async values => {
      if (!ready || locked.current) return; locked.current = true; setPending(true); setError('');
      try { await request(id ? `${templateAPI}/${id}` : templateAPI + '/', id ? 'PUT' : 'POST', { template_name: values.template_name, description: values.description || '', html_template: values.html_template, tags: (values.tags || '').split(',').map((tag: string) => tag.trim()).filter(Boolean), is_default: !!values.is_default }); message.success('模板已保存'); onSaved(); onClose(); }
      catch (reason) { setError((reason as Error).message); } finally { locked.current = false; setPending(false); }
    }}>
      <Form.Item label="模板名称" name="template_name" rules={[{ required: true, whitespace: true, message: '请输入模板名称' }]}><Input aria-label="模板名称" /></Form.Item>
      <Form.Item label="描述" name="description"><Input.TextArea rows={2} /></Form.Item>
      <Form.Item label="标签" name="tags" extra="用英文逗号分隔"><Input /></Form.Item>
      <Form.Item name="is_default" valuePropName="checked"><Checkbox>设为默认模板</Checkbox></Form.Item>
      <Form.Item label="HTML 模板" name="html_template" rules={[{ required: true, whitespace: true, message: '请输入 HTML 模板内容' }]}><Input.TextArea aria-label="HTML 模板" rows={10} className="template-code" placeholder="支持 {{title}}、{{content}}、{{slide_number}}、{{total_slides}}" /></Form.Item>
    </Form>
  </Modal>{preview && <TemplatePreview template={preview} onClose={() => setPreview(undefined)} />}</>;
}

function readReference(file: File): Promise<ApiData> {
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve({ filename: file.name, size: file.size, type: file.type || 'application/vnd.openxmlformats-officedocument.presentationml.presentation', data: reader.result }); reader.onerror = () => reject(new Error(`读取 ${file.name} 失败，请重试`)); reader.readAsDataURL(file); });
}

export function TemplateGeneration({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  useTemplateModalFocus();
  const [form] = Form.useForm(); const mode = Form.useWatch('generation_mode', form) || 'text_only';
  const [images, setImages] = useState<UploadFile[]>([]); const [pptx, setPptx] = useState<UploadFile[]>([]); const [result, setResult] = useState<ApiData>(); const [preview, setPreview] = useState(false);
  const [pending, setPending] = useState(''); const [status, setStatus] = useState(''); const [error, setError] = useState(''); const [adjustment, setAdjustment] = useState('');
  const [streamedHTML, setStreamedHTML] = useState(''); const [streamedResponse, setStreamedResponse] = useState('');
  const controller = useRef<AbortController | null>(null); const locked = useRef(false); const { message, modal } = App.useApp();
  useEffect(() => () => controller.current?.abort(), []);
  async function perform(kind: string, task: () => Promise<void>) { if (locked.current) return; locked.current = true; setPending(kind); setError(''); try { await task(); } catch (reason) { if ((reason as Error).name !== 'AbortError') setError((reason as Error).message); } finally { locked.current = false; setPending(''); } }
  function normalize(data: ApiData) { const template = data.data || data; if (!template.html_template) throw new Error(template.message || '生成结果缺少 HTML 模板'); return template; }
  function close() {
    if (!result) { onClose(); return; }
    modal.confirm({ title: '关闭未保存的模板', content: '生成结果尚未保存，关闭后将丢弃。', okText: '关闭', cancelText: '继续编辑', modalRender: modalFocus, onOk: onClose });
  }
  const raw = result?.raw_response || result?.llm_response || result?.html_template;
  function resetResult() { setResult(undefined); setStreamedHTML(''); setStreamedResponse(''); setError(''); setStatus(''); }
  return <><Modal open centered width={900} title="AI 生成母版" onCancel={close} closable={!pending} keyboard={!pending} mask={{ closable: !pending }} modalRender={modalFocus} footer={<Space wrap><Button disabled={!!pending} onClick={close}>关闭</Button>{(pending === 'generate' || pending === 'adjust') && <Button onClick={() => { controller.current?.abort(); setStatus('已停止接收生成结果'); }}>停止接收</Button>}{result ? <><Button disabled={!!pending} onClick={resetResult}>重新生成</Button><Button type="primary" aria-label="保存生成模板" loading={pending === 'save'} disabled={!!pending && pending !== 'save'} onClick={() => perform('save', async () => { await request(templateAPI + '/save-generated', 'POST', result); message.success('模板已保存'); onSaved(); onClose(); })}>保存模板</Button></> : <Button type="primary" aria-label="开始生成模板" loading={pending === 'generate'} disabled={!!pending && pending !== 'generate'} onClick={() => form.submit()}>开始生成</Button>}</Space>}>
    {error && <Alert type="error" title={error} className="page-error" />}
    {!result && <Form form={form} layout="vertical" initialValues={{ generation_mode: 'text_only' }} disabled={!!pending} onFinish={values => perform('generate', async () => {
      setStreamedHTML(''); setStreamedResponse('');
      const generationController = new AbortController(); controller.current = generationController; setStatus('正在准备参考资料…');
      const payload: ApiData = { prompt: values.prompt, template_name: values.template_name, description: values.description || '', tags: (values.tags || '').split(',').map((tag: string) => tag.trim()).filter(Boolean), generation_mode: values.generation_mode };
      if (mode === 'pptx_extract') { if (!pptx[0]?.originFileObj) throw new Error('请上传 PPTX 文件后再生成'); payload.reference_pptx = await readReference(pptx[0].originFileObj); }
      else if (mode !== 'text_only') { if (!images.length) throw new Error('请上传参考图片后再生成'); payload.reference_images = await Promise.all(images.map(file => readReference(file.originFileObj!))); payload.reference_image = payload.reference_images[0]; }
      generationController.signal.throwIfAborted(); setStatus('正在请求 AI 生成…');
      setResult(normalize(await postStream(templateAPI + '/generate?stream=true', payload, generationController.signal, item => {
        if (item.type === 'thinking' && item.content) setStreamedResponse(value => value + item.content);
        if (item.type === 'preview' && item.html_template) setStreamedHTML(item.html_template);
        if (item.type !== 'heartbeat') setStatus(item.message || '正在生成模板…');
      })));
    })}>
      <Form.Item name="prompt" label="设计要求" rules={[{ required: true, whitespace: true, message: '请输入设计要求' }]}><Input.TextArea aria-label="设计要求" rows={3} /></Form.Item>
      <div className="template-form-row"><Form.Item name="template_name" label="模板名称" rules={[{ required: true, whitespace: true, message: '请输入模板名称' }]}><Input aria-label="AI 模板名称" /></Form.Item><Form.Item name="tags" label="标签" extra="用英文逗号分隔"><Input /></Form.Item></div>
      <Form.Item name="description" label="描述"><Input.TextArea rows={2} /></Form.Item>
      <Form.Item name="generation_mode" label="生成方式"><Radio.Group options={[{ value: 'text_only', label: '纯文本' }, { value: 'reference_style', label: '参考风格' }, { value: 'exact_replica', label: '精确复刻' }, { value: 'pptx_extract', label: '提取 PPTX' }]} /></Form.Item>
      {['reference_style', 'exact_replica'].includes(mode) && <Form.Item label="参考图片" extra="最多 15 张，每张不超过 10 MB"><Upload accept="image/*" multiple listType="picture" fileList={images} disabled={!!pending} beforeUpload={file => { if (!file.type.startsWith('image/') || file.size > 10 * 1024 * 1024) { message.error('请选择不超过 10 MB 的图片'); return Upload.LIST_IGNORE; } return false; }} onChange={({ fileList }) => setImages(fileList.slice(0, 15))}><Button icon={<UploadOutlined aria-hidden />}>选择参考图片</Button></Upload></Form.Item>}
      {mode === 'pptx_extract' && <Form.Item label="参考 PPTX" extra="文件不超过 50 MB"><Upload accept=".pptx" maxCount={1} fileList={pptx} beforeUpload={file => { if (!file.name.toLowerCase().endsWith('.pptx') || file.size > 50 * 1024 * 1024) { message.error('请选择不超过 50 MB 的 PPTX 文件'); return Upload.LIST_IGNORE; } return false; }} onChange={({ fileList }) => setPptx(fileList)}><Button icon={<UploadOutlined aria-hidden />}>选择 PPTX 文件</Button></Upload></Form.Item>}
    </Form>}
    {pending && <p role="status"><Spin size="small" /> {pending === 'save' ? '正在保存模板…' : status}</p>}
    {!result && (pending === 'generate' || streamedHTML || streamedResponse) && <section aria-label="模板生成进度">
      {streamedHTML ? <TemplateFrame html={sampleHTML(streamedHTML, form.getFieldValue('template_name') || 'AI 生成结果')} title="AI 生成模板实时预览" /> : <div className="template-preview-fallback" role="status">正在等待页面内容…</div>}
      <p className="subtle">{pending === 'generate' ? '页面随生成内容实时更新，完成后可保存。' : '此预览尚未完成，请重新生成后保存。'}</p>
      <Collapse size="small" items={[{ key: 'stream', label: '查看实时响应', children: <pre className="template-raw">{streamedResponse || '等待 AI 响应…'}</pre> }]} />
    </section>}
    {result && <><TemplateFrame html={sampleHTML(result.html_template, result.template_name || 'AI 生成结果')} title="AI 生成模板预览" /><Space wrap className="template-result-tools"><Button onClick={() => setPreview(true)}>放大预览</Button><Button onClick={async () => { try { await copyText(typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2)); message.success('已复制'); } catch (reason) { message.error((reason as Error).message); } }}>复制响应</Button><span className="subtle">尚未保存</span></Space>
      <Collapse size="small" items={[{ key: 'raw', label: '查看原始响应', children: <pre className="template-raw">{typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2)}</pre> }]} />
      <label htmlFor="template-adjustment" className="template-adjust-label">调整意见</label><Input.TextArea id="template-adjustment" rows={2} value={adjustment} disabled={!!pending} onChange={event => setAdjustment(event.target.value)} />
      <Button className="template-result-tools" aria-label="调整模板" loading={pending === 'adjust'} disabled={!adjustment.trim() || (!!pending && pending !== 'adjust')} onClick={() => perform('adjust', async () => { controller.current = new AbortController(); setStatus('正在调整模板…'); const next = await postStream(templateAPI + '/adjust-template', { adjustment: adjustment.trim(), template_data: result }, controller.current.signal, item => setStatus(item.message || '正在调整模板…')); setResult(normalize(next)); setAdjustment(''); })}>调整模板</Button>
    </>}
  </Modal>{preview && result && <TemplatePreview template={result} onClose={() => setPreview(false)} />}</>;
}
