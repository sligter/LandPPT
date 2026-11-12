import { lazy, Suspense, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { Alert, Button, Card, Checkbox, Divider, Empty, Flex, Form, Input, InputNumber, Modal, Segmented, Select, Space, Spin, Tabs, Tag, Tooltip, Typography, Upload, theme } from 'antd';
import { ArrowRightOutlined, DownOutlined, FontSizeOutlined, InboxOutlined, InfoCircleOutlined, LinkOutlined, MessageOutlined, PaperClipOutlined, ReloadOutlined, SlidersOutlined } from '@ant-design/icons';
import { errorText, request, type ApiData } from '../api';
import { useCreationDraft } from './creation-draft';
import CreationAssistant from './creation-assistant';
import { readCreationConfiguration } from '../creation-config';
import { modalFocus } from './modal-focus';
import { useTemplateModalFocus } from './templates';
import { contentSource, sourceExtensions as extensions } from './source-materials';

const TemplatePackages = lazy(() => import('../pages/template-packages'));

const audienceOptions = ['企业管理层', '技术团队', '销售团队', '学生群体', '学术研究者', '投资人', '客户群体', '培训学员', '项目团队', '行业专家', '普通大众', '自定义'];
const choices = (pairs: string[][]) => pairs.map(([value, label]) => ({ value, label }));
const stages = choices([['outline', '生成大纲'], ['template', '选择模板'], ['ppt', '生成 PPT'], ['speech_script', '生成演讲稿'], ['narration_audio', '生成配音'], ['video', '导出讲解视频']]);
const defaults = { topic: '', requirements: '', scenario: 'general', audience_type: '普通大众', custom_audience: '', page_count_mode: 'ai_decide', min_pages: 8, max_pages: 15, ppt_style: 'general', custom_style_prompt: '', language: 'zh', render_mode: 'html', generation_mode: 'freeform', package_version_id: '', network_mode: false, include_transition_pages: false, include_page_numbers: true, file_processing_mode: 'markitdown', content_analysis_depth: 'fast', content_urls: '', unattended_mode: false, unattended_template_mode: 'auto', unattended_template_id: '', stop_at_stage: 'ppt', unattended_notify_in_app: true, unattended_notify_email: false };
const urls = (value: string) => String(value || '').split(/[\n,;\t ]+/).map(item => item.trim()).filter(Boolean).slice(0, 50);
function projectURL(value: unknown) {
  if (typeof value !== 'string' || !value) return '';
  try { const url = new URL(value, location.origin); return url.origin === location.origin && url.pathname.startsWith('/projects/') ? url.pathname + url.search + url.hash : ''; } catch { return ''; }
}

function CreationTemplatePicker({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useTemplateModalFocus();
  return <Modal open title="选择模板包" width={1100} onCancel={onClose} footer={<Button onClick={onClose}>返回创建</Button>} modalRender={modalFocus}>{children}</Modal>;
}

function ComposerForm({ data, compact }: { data: ApiData; compact: boolean }) {
  const { draft, feedback, setFeedback } = useCreationDraft();
  const [form] = Form.useForm();
  const { token } = theme.useToken();
  const [initial] = useState(() => ({ ...defaults, scenario: data.selectedScenario || 'general', ...data.createDefaults, unattended_template_id: String(data.templateOptions?.[0]?.id || ''), ...draft.current.fields,
    ...(new URLSearchParams(location.search).has('scenario') ? { scenario: data.selectedScenario || 'general' } : {}) }));
  const [expanded, setExpanded] = useState(!compact);
  const [pickingTemplate, setPickingTemplate] = useState(false);
  const advancedTriggerRef = useRef<HTMLButtonElement>(null);
  const watched = Form.useWatch(values => values, form);
  const values = { ...initial, ...watched };
  const [sourceTab, setSourceTab] = useState(draft.current.sourceTab); const [files, setFiles] = useState<File[]>(draft.current.files);
  const [warning, setWarning] = useState('');
  const [chatOpen, setChatOpen] = useState(!!draft.current.chatOpen);
  const { pending, error, redirect } = feedback;
  const locked = draft;
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);
  const remember = () => { draft.current.fields = form.getFieldsValue(true); };
  const chooseSource = (value: string) => { draft.current.sourceTab = value; setSourceTab(value); };
  const changeFiles = (update: (current: File[]) => File[]) => setFiles(current => { const next = update(current); draft.current.files = next; return next; });
  const [packages, setPackages] = useState<ApiData[]>([]); const [packageError, setPackageError] = useState(''); const [packageLoading, setPackageLoading] = useState(false); const [refresh, setRefresh] = useState(0);
  const fast = values.generation_mode === 'package'; const links = urls(values.content_urls);
  const source = contentSource(files.length, links.length);
  const sourceSummary = [files.length ? `${files.length} 个附件` : '', links.length ? `${links.length} 个链接` : ''].filter(Boolean).join(' · ') || '未添加资料';
  const settingsSummary = [values.language === 'en' ? 'English' : '中文', values.page_count_mode === 'custom_range' ? `${values.min_pages || defaults.min_pages}–${values.max_pages || defaults.max_pages} 页` : 'AI 智能页数', values.ppt_style === 'keynote' ? '发布会风格' : values.ppt_style === 'custom' ? '自定义风格' : '通用风格', ...(values.network_mode ? ['联网研究'] : [])].join(' · ');
  useEffect(() => {
    if (!fast) return;
    const controller = new AbortController(); setPackageLoading(true); setPackageError('');
    request('/api/global-master-templates/packages', 'GET', undefined, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(result.packages)) throw new Error('模板包列表无效，请重试');
      const published = result.packages.filter(item => item.status === 'published'); setPackages(published);
      const current = form.getFieldValue('package_version_id');
      if (current && !published.some(item => String(item.id) === current)) form.setFieldValue('package_version_id', '');
    }).catch(reason => { if (!controller.signal.aborted) setPackageError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setPackageLoading(false); });
    return () => controller.abort();
  }, [fast, refresh, form]);
  function addFile(file: File) {
    if (!extensions.includes(file.name.split('.').pop()?.toLowerCase() || '')) setWarning(`不支持的文件类型：${file.name}`);
    else if (file.size > 100 * 1024 * 1024) setWarning(`文件超过 100MB：${file.name}`);
    else changeFiles(current => current.some(item => item.name === file.name && item.size === file.size) ? current : [...current, file]);
    return false;
  }
  async function submit(submitted: ApiData) {
    if (locked.current.locked) return;
    const input = { ...initial, ...form.getFieldsValue(true), ...submitted };
    setFeedback({ pending: false, error: '', redirect: '' });
    if (fast && (packageLoading || packageError || !packages.some(item => String(item.id) === input.package_version_id))) { setFeedback({ pending: false, redirect: '', error: '快速模式需要先选择一个已发布的模板包。' }); form.scrollToField('package_version_id', { focus: true }); return; }
    let min = Math.min(50, Math.max(5, Math.trunc(Number(input.min_pages) || 8)));
    let max = Math.min(50, Math.max(5, Math.trunc(Number(input.max_pages) || 15)));
    if (min > max) [min, max] = [max, min];
    form.setFieldsValue({ min_pages: min, max_pages: max });
    remember();
    Object.assign(input, { min_pages: min, max_pages: max, content_source: source, render_mode: fast ? 'svg' : input.render_mode, package_version_id: fast ? input.package_version_id : '0', unattended_mode: !!data.user?.is_admin && !!input.unattended_mode, unattended_template_id: input.unattended_template_mode === 'global' ? input.unattended_template_id : '' });
    const body = new FormData();
    for (const key of Object.keys(defaults).filter(key => key !== 'content_urls')) {
      const value = input[key]; body.append(key, typeof value === 'boolean' ? String(value) : String(value ?? '').trim());
    }
    body.append('content_source', source);
    if (links.length) body.append('content_urls', links.join('\n'));
    if (files.length) files.forEach(file => body.append('file_upload', file));
    locked.current.locked = true; setFeedback({ pending: true, error: '', redirect: '' }); let navigating = false;
    try {
      const response = await fetch('/projects/create-and-confirm', { method: 'POST', credentials: 'same-origin', headers: { Accept: 'application/json' }, body });
      const result = await response.json().catch(() => ({})); const target = projectURL(result.redirect_url);
      if (response.ok && result.status === 'success' && target) { navigating = true; draft.current.fields = undefined; draft.current.files = []; draft.current.sourceTab = 'manual'; location.assign(target); return; }
      setFeedback({ pending: false, redirect: target, error: errorText(result.detail || result.message || `创建失败（HTTP ${response.status}）`) });
    } catch (reason) { setFeedback({ pending: false, redirect: '', error: (reason as Error).message }); }
    finally { if (!navigating) { locked.current.locked = false; setFeedback(current => ({ ...current, pending: false })); } }
  }
  const select = (name: string, label: string, options: { value: string; label: string }[], disabled = false) => <Form.Item name={name} label={label}><Select aria-label={label} options={options} disabled={pending || disabled} /></Form.Item>;
  const check = (name: string, label: string) => <Form.Item name={name} valuePropName="checked" className="create-checkbox"><Checkbox>{label}</Checkbox></Form.Item>;
  const parsing = <div className="create-field-grid">
    {select('file_processing_mode', 'PDF 处理方式', choices([['markitdown', '标准处理 · MarkItDown'], ['magic_pdf', '高质量 · Mineru（提取图片）']]))}
    {select('content_analysis_depth', '解析深度', choices([['fast', '快速解析'], ['standard', '标准解析'], ['deep', '深度解析']]))}
  </div>;
  const modeOptions = choices([['freeform', '自由设计'], ['package', '快速模式（模板包）']]);
  const topicField = <Form.Item name="topic" label={compact ? undefined : 'PPT 主题'} rules={[{ required: true, whitespace: true, message: '请先填写 PPT 主题' }]}>
    <Input aria-label="PPT 主题" size={compact ? 'large' : undefined} variant={compact ? 'borderless' : undefined} className={compact ? 'composer-topic' : undefined} placeholder={compact ? '演示主题，例如：人工智能的未来结局' : '给这份演示起一个主题'} onPressEnter={event => { if (!event.nativeEvent.isComposing && !event.ctrlKey && !event.metaKey) { event.preventDefault(); form.getFieldInstance('requirements')?.focus(); } }} />
  </Form.Item>;
  const requirementsField = <Form.Item name="requirements" label={compact ? undefined : '具体需求（选填）'}><Input.TextArea aria-label="具体需求" variant={compact ? 'borderless' : undefined} autoSize={{ minRows: compact ? 2 : 4, maxRows: 10 }} placeholder={compact ? '补充重点内容、章节思路、数据或风格偏好（选填）' : '重点内容、章节思路、数据素材、风格偏好…'} /></Form.Item>;
  const fileSource = <Upload.Dragger multiple disabled={pending} accept={extensions.map(ext => '.' + ext).join(',')} beforeUpload={addFile} showUploadList={false}>
    <InboxOutlined aria-hidden className="create-upload-icon" /><p>点击选择或拖入文件</p><p className="subtle">PDF / DOCX / PPTX / XLSX / TXT / MD / 图片，单个最大 100MB</p>
  </Upload.Dragger>;
  const urlSource = <Form.Item name="content_urls" label={compact ? undefined : '内容链接'} extra="每行一个或逗号分隔，最多使用前 50 个链接。支持网页与文件 URL。"><Input.TextArea aria-label="内容链接" autoSize={{ minRows: compact ? 2 : 3, maxRows: 6 }} placeholder="https://example.com/article" /></Form.Item>;
  const sourceExtras = <>
    {(sourceTab !== 'manual' || source !== 'manual') && parsing}
    {source !== 'manual' && <Space wrap className="create-source-summary" role="status" aria-label="已添加资料">
      {!!files.length && <Tag icon={<PaperClipOutlined aria-hidden />}>{files.length} 个附件</Tag>}
      {!!links.length && <><Tag icon={<LinkOutlined aria-hidden />}>{links.length} 个链接</Tag><Button type="text" size="small" disabled={pending} onClick={() => { form.setFieldValue('content_urls', ''); remember(); }}>清空链接</Button></>}
    </Space>}
    {files.length > 0 && <div className="create-files" aria-label="已选附件">{files.map((file, index) => <div className="create-file" key={file.name + ':' + file.size}><span>{file.name}<small className="subtle">{(file.size / 1024).toFixed(1)} KB</small></span><Button size="small" disabled={pending} aria-label={`移除附件 ${file.name}`} onClick={() => changeFiles(current => current.filter((_, i) => i !== index))}>移除</Button></div>)}</div>}
    {source === 'mixed' && <Alert type="info" title="附件与网页链接将合并用于生成大纲。" />}
    {warning && <Alert className="page-error" type="warning" title={warning} closable onClose={() => setWarning('')} />}
  </>;
  const openChat = (open: boolean) => { draft.current.chatOpen = open; setChatOpen(open); };
  const chatToggle = <Button type="text" size="small" icon={<MessageOutlined aria-hidden />} aria-pressed={chatOpen} disabled={pending} onClick={() => openChat(!chatOpen)}>{chatOpen ? '收起 AI 对话' : 'AI 对话填写'}</Button>;
  const assistant = chatOpen && <CreationAssistant form={form} files={files} disabled={pending} draft={draft} addFile={addFile} onChange={remember} />;
  const summary = <Typography.Text id="creationAdvancedSummary" className="create-advanced-summary" type="secondary">{settingsSummary}</Typography.Text>;
  const advancedTrigger = <Button ref={advancedTriggerRef} className="create-advanced-trigger" icon={<SlidersOutlined aria-hidden />} aria-label={expanded ? '收起高级参数' : '高级参数'} aria-expanded={expanded} aria-controls="creationAdvanced" disabled={pending} onClick={() => setExpanded(value => !value)}>
    {compact ? <>高级参数<Divider orientation="vertical" />{summary}</> : expanded ? '收起高级参数' : '高级参数'}<DownOutlined aria-hidden className="create-advanced-chevron" />
  </Button>;
  async function selectPackage(pkg: ApiData) {
    if (pending || pkg.status !== 'published') return;
    setPackages(current => [pkg, ...current.filter(item => item.id !== pkg.id)]);
    form.setFieldsValue({ generation_mode: 'package', package_version_id: String(pkg.id), render_mode: 'svg' });
    remember(); setPickingTemplate(false);
  }
  const packageField = fast && <div className="create-package-field">
    <Form.Item name="package_version_id" label="已发布模板包"><Select aria-label="已发布模板包" disabled={pending || packageLoading || !!packageError} loading={packageLoading} placeholder="请选择模板包" options={packages.map(item => ({ value: String(item.id), label: `${item.template_name} · v${item.version}` }))} /></Form.Item>
    <Space wrap><Button disabled={pending || packageLoading} onClick={() => setPickingTemplate(true)}>浏览模板包</Button><Button size="small" icon={<ReloadOutlined aria-hidden />} loading={packageLoading} disabled={pending} onClick={() => setRefresh(value => value + 1)}>刷新模板包</Button><a href="/global-master-templates?tab=packages" target="_blank" rel="noopener">管理模板包</a></Space>
    {packageError ? <Alert className="page-error" type="error" title={packageError} /> : !packageLoading && !packages.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无已发布模板包" /> : <p className="subtle">参考模板包规划大纲，使用 SVG 绘制。</p>}
  </div>;
  const advanced = <div id="creationAdvanced" className={compact ? 'composer-advanced' : undefined} hidden={!expanded}
    onKeyDown={event => { if (event.key === 'Escape' && !event.defaultPrevented && !(event.target as HTMLElement).closest('.ant-select-open')) { event.preventDefault(); setExpanded(false); advancedTriggerRef.current?.focus({ preventScroll: true }); } }}>
    <div className="create-field-grid">
      {select('scenario', '场景', (data.scenarios?.length ? data.scenarios : [{ id: 'general', name: '通用' }]).map((item: ApiData) => ({ value: item.id, label: item.name })))}
      {select('audience_type', '目标受众', audienceOptions.map(value => ({ value, label: value })))}
    </div>
    {values.audience_type === '自定义' && <Form.Item name="custom_audience" label="自定义受众描述" rules={[{ required: true, whitespace: true, message: '请描述自定义受众' }]}><Input aria-label="自定义受众描述" placeholder="例如：初级程序员" /></Form.Item>}
    {select('page_count_mode', '页数', choices([['ai_decide', 'AI 智能决定'], ['custom_range', '自定义范围']]))}
    {values.page_count_mode === 'custom_range' && <div className="create-field-grid"><Form.Item name="min_pages" label="最少页数"><InputNumber aria-label="最少页数" min={5} max={50} precision={0} /></Form.Item><Form.Item name="max_pages" label="最多页数"><InputNumber aria-label="最多页数" min={5} max={50} precision={0} /></Form.Item></div>}
    {select('ppt_style', 'PPT 风格', choices([['general', '通用场景'], ['keynote', '发布会'], ['custom', '自定义风格']]))}
    {values.ppt_style === 'custom' && <Form.Item name="custom_style_prompt" label="自定义风格描述" rules={[{ required: true, whitespace: true, message: '请填写自定义风格描述' }]}><Input.TextArea aria-label="自定义风格描述" autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>}
    <div className="create-field-grid">{select('language', '语言', choices([['zh', '中文'], ['en', 'English']]))}
      {select('render_mode', '页面绘制方式', choices([['html', 'HTML（默认）'], ['svg', 'SVG（实验）']]), fast)}
    </div>
    <div className="create-extra-settings">
      <div className="create-option-row">
        {check('network_mode', '联网深度研究')}
        <Tooltip title={<>联网研究需先在系统配置填写 Tavily Key / SearXNG 地址。</>}><a className="create-research-help" href="/research" aria-label="查看研究状态"><InfoCircleOutlined aria-hidden /></a></Tooltip>
        {check('include_transition_pages', '章节过渡页')}{check('include_page_numbers', '页码 / Footer')}
        {data.user?.is_admin && check('unattended_mode', '无人值守')}
      </div>
      {data.user?.is_admin && values.unattended_mode && <div className="create-unattended">
        <p className="subtle">自动执行到所选阶段，无需人工确认。</p>
        <div className="create-field-grid">
          {select('stop_at_stage', '停止阶段', stages)}
          {select('unattended_template_mode', '无人值守模板', choices([['auto', '使用我的默认模板'], ['global', '指定已有模板'], ['free', '自由模板（AI 按大纲生成）']]))}
          {values.unattended_template_mode === 'global' && <Form.Item name="unattended_template_id" label="选择模板"><Select aria-label="选择模板" placeholder="暂无可用模板" options={(data.templateOptions || []).map((item: ApiData) => ({ value: String(item.id), label: item.name + (item.is_default ? '（默认）' : '') }))} /></Form.Item>}
        </div>
        <div className="create-option-row">{check('unattended_notify_in_app', '系统通知')}{check('unattended_notify_email', '邮件通知')}</div>
      </div>}
    </div>
  </div>;
  const errorAlert = error && <Alert className="page-error" type="error" title={error} description={redirect ? <span>项目已创建，可<a href={redirect}>前往看板</a>手动确认需求，避免重复创建。</span> : undefined} showIcon />;
  const submitButton = <Button type="primary" htmlType="submit" aria-label="开始生成" aria-busy={pending} icon={<ArrowRightOutlined aria-hidden />} loading={pending} disabled={pending || (fast && (packageLoading || !!packageError))}>开始生成</Button>;
  const sourceTabs: [string, string, ReactNode][] = [['manual', '主题', <FontSizeOutlined aria-hidden />], ['file', '文件资料', <PaperClipOutlined aria-hidden />], ['url', '网页链接', <LinkOutlined aria-hidden />]];
  const formProps = { name: 'create', form, layout: 'vertical' as const, initialValues: initial, disabled: pending, scrollToFirstError: { focus: true }, onFinish: submit,
    onValuesChange: (changed: ApiData) => { if (changed.generation_mode === 'package') form.setFieldValue('render_mode', 'svg'); remember(); },
    onKeyDown: (event: KeyboardEvent<HTMLFormElement>) => { if (!event.nativeEvent.isComposing && (event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); if (!locked.current.locked) form.submit(); } },
    onFinishFailed: ({ errorFields }: { errorFields: { name: (string | number)[] }[] }) => {
      const first = errorFields[0]; if (!first) return;
      if (!['topic', 'requirements', 'content_urls', 'package_version_id'].includes(String(first.name[0]))) {
        setExpanded(true);
      }
      requestAnimationFrame(() => { if (mounted.current) form.scrollToField(first.name, { focus: true }); });
    } };
  const picker = pickingTemplate && <CreationTemplatePicker onClose={() => setPickingTemplate(false)}>
    <Suspense fallback={<div role="status"><Spin />正在加载模板包…</div>}><TemplatePackages preferred={Number(values.package_version_id) || 0} selecting pickOnly onSelect={selectPackage} /></Suspense>
  </CreationTemplatePicker>;
  if (compact) return <Card className="creation-composer create-project-page creation-composer--compact" style={{ boxShadow: token.boxShadowTertiary }} styles={{ body: { padding: 0 } }}>
    <Form {...formProps}>
      <div className="composer-body">
        {assistant}
        {assistant && <div className="composer-draft-label"><Typography.Text type="secondary">需求草稿 · 由对话自动填写，可直接修改</Typography.Text></div>}
        {topicField}{requirementsField}
        {sourceTab === 'file' && <div className="composer-source">{fileSource}</div>}
        {sourceTab === 'url' && <div className="composer-source">{urlSource}</div>}
        {sourceExtras}
      </div>
      <Flex className="composer-toolbar" wrap gap={8} align="center">
        <Segmented aria-label="输入方式" value={chatOpen ? 'chat' : sourceTab} disabled={pending} onChange={value => { const next = String(value); openChat(next === 'chat'); chooseSource(next === 'chat' ? 'manual' : next); }}
          options={[{ value: 'chat', label: 'AI 对话', icon: <MessageOutlined aria-hidden /> }, ...sourceTabs.map(([value, label, icon]) => ({ value, label, icon }))]} />
        <Form.Item name="generation_mode" noStyle><Select aria-label="生成方式" className="composer-mode" variant="filled" options={modeOptions} disabled={pending} popupMatchSelectWidth={false} labelRender={({ value }) => value === 'package' ? '模板包模式' : '自由设计'} /></Form.Item>
        <Flex className="composer-actions" gap={8} align="center">{advancedTrigger}{submitButton}</Flex>
      </Flex>
      {packageField && <div className="composer-package">{packageField}</div>}
      {advanced}
      {picker}
      {errorAlert}
    </Form>
  </Card>;
  return <div className="creation-composer">
    <Form {...formProps}>
      <div className="create-project-grid">
        <div className="create-main">
          {assistant && <Card size="small" title="AI 对话填写" extra={chatToggle}>{assistant}</Card>}
          <Card size="small" title={assistant ? '需求草稿' : '演示内容'} extra={!assistant && chatToggle}>{topicField}{requirementsField}</Card>
          <Card size="small" title="参考资料（选填）" extra={<span className="subtle">{sourceSummary}</span>}>
            <Tabs activeKey={sourceTab} onChange={chooseSource} items={[
              { key: 'manual', label: '主题与需求', children: <p className="subtle create-manual-help">根据上方主题和需求生成内容，也可添加文件或网页链接作为参考。</p> },
              { key: 'file', label: '文件资料', children: fileSource },
              { key: 'url', label: '网页链接', children: urlSource },
            ]} />
            {sourceExtras}
          </Card>
        </div>
        <Card size="small" title="生成设置" className="create-settings">
          <div className="create-advanced-control">{advancedTrigger}{summary}</div>
          {select('generation_mode', '生成方式', modeOptions)}
          {packageField}
          {advanced}
        </Card>
      </div>
      {errorAlert}
      {picker}
      <div className="create-submit-bar"><span className="subtle">{pending ? '正在创建项目…' : 'Ctrl / ⌘ + Enter'}</span>{submitButton}</div>
    </Form>
  </div>;
}

export default function CreateComposer({ data, compact = false }: { data: ApiData; compact?: boolean }) {
  const [configuration, setConfiguration] = useState<ApiData | null>(data.page === 'create-project' ? data : null);
  const [error, setError] = useState(''); const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (data.page === 'create-project') return;
    const controller = new AbortController(); setError('');
    readCreationConfiguration(data, controller.signal)
      .then(value => {
        if (!controller.signal.aborted) setConfiguration(value);
      }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [data, retry]);
  if (!configuration) return error ? <Alert type="error" title={error} action={<Button onClick={() => setRetry(value => value + 1)}>重试</Button>} /> : <div className="creation-loading" role="status">正在准备创作空间…</div>;
  return <ComposerForm data={configuration} compact={compact} />;
}
