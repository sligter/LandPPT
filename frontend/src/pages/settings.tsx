import { memo, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { Alert, App, AutoComplete, Button, Card, Collapse, Form, Input, InputNumber, Modal, Radio, Select, Slider, Space, Switch, Tabs, Tag, Tooltip } from 'antd';
import { ReloadOutlined, SaveOutlined, ApiOutlined, SettingOutlined, SlidersOutlined, BranchesOutlined, PictureOutlined, CheckCircleOutlined } from '@ant-design/icons';
import { request, type ApiData } from '../api';
import { readSettingsSchema, type Field } from '../settings-schema';
import JevSettings from './jev-settings';
import { modalFocus } from '../components/modal-focus';
import { ModelPicker } from '../components/model-picker';
import ManagedProviders, { useManagedProviders } from '../components/managed-providers';

const categories: Record<string, string> = { 'generation-params': 'generation_params', 'app-config': 'app_config', 'image-service': 'image_service' };
const saveLabels: Record<string, string> = { 'generation-params': '保存生成参数', 'app-config': '保存应用配置', 'image-service': '保存配置' };
const bool = (value: unknown) => value === true || value === 1 || value === 'true' || value === '1';
const labels: Record<string, string> = { landppt: 'LandPPT', openai: 'OpenAI', anthropic: 'Anthropic Claude', google: 'Google Gemini' };
const JevPanel = memo(JevSettings);
const tabIcons: Record<string, React.ReactNode> = { 'ai-providers': <ApiOutlined aria-hidden />, 'generation-params': <SlidersOutlined aria-hidden />, 'jev-config': <BranchesOutlined aria-hidden />, 'app-config': <SettingOutlined aria-hidden />, 'image-service': <PictureOutlined aria-hidden /> };
const providerMarks: Record<string, string> = { landppt: 'LP', openai: 'O', anthropic: 'A', google: 'G' };
type Drafts = { read: (name: string) => unknown; subscribe: (listener: () => void) => () => void };

const SettingsSection = memo(function SettingsSection({ fields, drafts, title, children, dependencies = [] }: {
  fields: Field[]; drafts: Drafts; title: React.ReactNode; children: React.ReactNode; dependencies?: string[];
}) {
  const visible = useSyncExternalStore(drafts.subscribe, () => dependencies.every(name => bool(drafts.read(name))) && fields.some(field => field.dependencies.every(name => bool(drafts.read(name)))));
  if (!visible) return null;
  return <Card size="small" className="config-section-card" title={title}>{children}</Card>;
});

const imageCredentialGroups = [
  { key: 'dalle', label: 'DALL-E', pattern: /^openai_api_key_image$/ },
  { key: 'siliconflow', label: 'SiliconFlow', pattern: /^siliconflow_/ },
  { key: 'gemini', label: 'Gemini 图片生成', pattern: /^gemini_image_/ },
  { key: 'openai_image', label: 'OpenAI 图片生成', pattern: /^openai_image_/ },
  { key: 'pollinations', label: 'Pollinations', pattern: /^pollinations_/ },
  { key: 'network', label: '网络搜索凭据', pattern: /^(unsplash_access_key|pixabay_api_key|searxng_host)$/ },
];

function ImageCredentials({ fields, drafts, children }: {
  fields: Field[]; drafts: Drafts; children: (fields: Field[]) => React.ReactNode;
}) {
  const provider = useSyncExternalStore(drafts.subscribe, () => String(drafts.read('default_ai_image_provider') || 'dalle'));
  const [expanded, setExpanded] = useState<string | string[]>(provider);
  useEffect(() => { setExpanded(provider); }, [provider]);
  const groups = imageCredentialGroups.map(group => ({ ...group, fields: fields.filter(field => group.pattern.test(field.name)) })).filter(group => group.fields.length);
  const remaining = fields.filter(field => !imageCredentialGroups.some(group => group.pattern.test(field.name)));
  return <Card size="small" className="image-credentials-card" title={<span className="config-card-title"><ApiOutlined aria-hidden />提供者与凭据</span>}>
    <p className="image-credentials-help subtle">展开需要使用的服务，填写密钥与模型；收起不会清除配置。</p>
    <Collapse className="image-credentials-collapse" accordion activeKey={expanded} onChange={setExpanded} items={groups.map(group => ({
      key: group.key, label: <span className="image-credential-heading"><strong>{group.label}</strong>{group.key === provider && <Tag>默认</Tag>}</span>, forceRender: true, children: children(group.fields),
    }))} />
    {remaining.length > 0 && children(remaining)}
  </Card>;
}

const SettingsField = memo(function SettingsField({ field, drafts, initialValue, pending, error, models, change, fetchModels }: {
  field: Field; drafts: Drafts; initialValue: unknown; pending: string; error?: string;
  models?: Field['options']; change: (name: string, value: unknown) => void; fetchModels: (field: Field) => Promise<void>;
}) {
  const raw = useSyncExternalStore(drafts.subscribe, () => drafts.read(field.name));
  const visible = useSyncExternalStore(drafts.subscribe, () => field.dependencies.every(name => bool(drafts.read(name))));
  const reasoningEnabled = useSyncExternalStore(drafts.subscribe, () => !field.name.endsWith('_reasoning_effort') || bool(drafts.read(field.name.replace('_reasoning_effort', '_enable_reasoning'))));
  const disabled = !!pending || !reasoningEnabled;
  const id = `field-${field.name}`;
  const value = String(raw ?? '');
  const modelField = field.name.endsWith('_model') || field.name.endsWith('_model_name');
  const options = useMemo(() => models || (field.kind === 'select' ? field.options : field.options.filter(option => option.value)), [models, field]);
  const common = { id, 'aria-label': field.label, placeholder: field.placeholder, disabled };
  if (!visible) return null;
  if (field.kind === 'checkbox') return <Form.Item className="switch-field"><label className="switch-row" htmlFor={id}><span className="switch-copy"><span>{field.label}</span>{field.help && <span className="subtle">{field.help}</span>}</span><Switch id={id} aria-label={field.label} disabled={disabled} checked={bool(raw)} onChange={checked => change(field.name, checked)} /></label></Form.Item>;
  let control;
  if (modelField) control = <ModelPicker field={field} value={value} options={options} fetched={models} disabled={disabled} change={change} />;
  else if (field.kind === 'select') control = <Select {...common} value={value} options={options} onChange={next => change(field.name, next)} showSearch optionFilterProp="label" />;
  else if (field.kind === 'number') control = <><InputNumber {...common} name={field.name} value={value ? Number(value) : null} min={field.min} max={field.max} step={field.step || 1} onChange={next => change(field.name, next === null ? '' : String(next))} />{field.slider && <Slider aria-label={`${field.label}滑块`} {...field.slider} value={value ? Number(value) : field.slider.min} onChange={next => change(field.name, String(next))} />}</>;
  else if (field.kind === 'textarea') control = <Input.TextArea {...common} name={field.name} value={value} autoSize={{ minRows: 3, maxRows: 8 }} onChange={event => change(field.name, event.target.value)} />;
  else if (field.kind === 'password') control = <Input.Password {...common} name={field.name} value={value} autoComplete="new-password" onChange={event => change(field.name, event.target.value)} />;
  else if (field.options.length) control = <AutoComplete {...common} value={value} options={options} onChange={next => change(field.name, next)} filterOption={(input, option) => String(option?.value).toLowerCase().includes(input.toLowerCase())}><Input name={field.name} /></AutoComplete>;
  else control = <Input {...common} name={field.name} value={value} onChange={event => change(field.name, event.target.value)} />;
  return <Form.Item label={field.label} htmlFor={id} extra={field.help || undefined} validateStatus={error ? 'error' : undefined} help={error} className={field.kind === 'textarea' ? 'field-full' : undefined}>
    {modelField ? <><div className="model-control">{control}<Tooltip title="获取可用模型列表"><Button aria-label={field.name === 'pollinations_model' ? '获取模型' : `获取${field.label}列表`} disabled={!!pending} loading={pending === `models-${field.name}`} icon={<ReloadOutlined aria-hidden />} onClick={() => fetchModels(field)} /></Tooltip></div>{models && <span className="model-list-status" role="status">{models.filter(option => option.value).length ? `${models.filter(option => option.value).length} 个可用模型` : '暂无可用模型'}{field.kind !== 'select' && ' · 可搜索或输入自定义名称'}</span>}</> : control}
    {field.name === 'ai_image_resolution_presets' && <Button type="text" className="field-action" onClick={() => change(field.name, String(initialValue))}>重置为默认</Button>}
  </Form.Item>;
});

export default function Settings({ data }: { data: ApiData }) {
  const managed = useManagedProviders();
  const panels = useMemo(readSettingsSchema, []);
  const allFields = useMemo(() => panels.flatMap(panel => panel.fields), [panels]);
  const initial = useMemo(() => Object.fromEntries(allFields.map(field => [field.name, data.config[field.name] ?? field.value])), [allFields, data.config]);
  const valuesRef = useRef<ApiData>(initial);
  const draftListeners = useRef(new Set<() => void>());
  const drafts = useMemo<Drafts>(() => ({
    read: name => valuesRef.current[name],
    subscribe: listener => { draftListeners.current.add(listener); return () => { draftListeners.current.delete(listener); }; },
  }), []);
  // Only fields whose snapshots change render; saving still reads the full draft.
  const setValues = useCallback((update: (previous: ApiData) => ApiData) => {
    const next = update(valuesRef.current);
    if (next === valuesRef.current) return;
    valuesRef.current = next;
    draftListeners.current.forEach(listener => listener());
  }, []);
  const dirty = useRef(new Set<string>());
  const [active, setActive] = useState('ai-providers');
  const [defaultProvider, setDefaultProvider] = useState(data.currentProvider);
  const [pending, setPending] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [models, setModels] = useState<Record<string, { label: string; value: string }[]>>({});
  const [imageStatus, setImageStatus] = useState<ApiData>({});
  const [testResult, setTestResult] = useState<ApiData | null>(null);
  const testTrigger = useRef<HTMLElement | null>(null);
  const { message } = App.useApp();
  const operations = useRef(new Map<string, AbortController>());
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    request('/api/config/all', 'GET', undefined, controller.signal).then(result => {
      setValues(previous => {
        const next = { ...previous };
        allFields.forEach(field => {
          if (!dirty.current.has(field.name) && Object.hasOwn(result.config || {}, field.name)) next[field.name] = result.config[field.name];
        });
        return next;
      });
    }).catch(reason => { if (!controller.signal.aborted) setError(`配置读取失败：${reason.message}`); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    request('/api/image/status', 'GET', undefined, controller.signal).then(setImageStatus).catch(() => {});
    return () => { mounted.current = false; controller.abort(); operations.current.forEach(operation => operation.abort()); operations.current.clear(); };
  }, [allFields, setValues]);
  const change = useCallback((name: string, value: unknown) => {
    if (name.endsWith('_model_provider') && !Object.is(valuesRef.current[name], value)) {
      const model = name.replace(/_provider$/, '_name');
      setModels(previous => { if (!Object.hasOwn(previous, model)) return previous; const next = { ...previous }; delete next[model]; return next; });
    }
    dirty.current.add(name);
    setValues(previous => Object.is(previous[name], value) ? previous : { ...previous, [name]: value });
    setFieldErrors(previous => { if (!Object.hasOwn(previous, name)) return previous; const next = { ...previous }; delete next[name]; return next; });
  }, [setValues]);
  const run = useCallback(async (key: string, operation: (signal: AbortSignal) => Promise<void>) => {
    if (operations.current.size) return;
    if (key.startsWith('test-')) testTrigger.current = document.activeElement as HTMLElement;
    const controller = new AbortController(); operations.current.set(key, controller);
    setPending(key); setError('');
    try { await operation(controller.signal); }
    catch (reason) { if (!controller.signal.aborted && mounted.current) setError((reason as Error).message); }
    finally { operations.current.delete(key); if (mounted.current) setPending(''); }
  }, []);
  function payload(fields: Field[], category: string): ApiData | null {
    const config: ApiData = {}; const errors: Record<string, string> = {};
    fields.forEach(field => {
      const value = valuesRef.current[field.name];
      if (field.kind === 'checkbox') { config[field.name] = bool(value); return; }
      let text = String(value ?? '');
      if (category !== 'generation_params') text = text.trim();
      if (field.name === 'tavily_base_url') text = text.trim() || 'https://api.tavily.com';
      if (field.name === 'deepseek_base_url') text = text.trim() || 'https://api.deepseek.com';
      if (field.required && !text.trim()) errors[field.name] = '请填写此项';
      if (field.kind === 'number' && text && (!Number.isFinite(Number(text)) || (field.min !== undefined && Number(text) < field.min) || (field.max !== undefined && Number(text) > field.max))) errors[field.name] = `请输入 ${field.min ?? '有效数值'} 至 ${field.max ?? '有效数值'} 之间的数值`;
      if (field.name === 'ai_image_resolution_presets' && text.trim()) {
        try { JSON.parse(text); } catch { errors[field.name] = '请输入有效的 JSON'; }
      }
      if (category === 'image_service' && field.kind === 'textarea') text = text.replace(/[\r\n]+/g, ' ');
      if (text || category === 'model_roles') config[field.name] = text;
    });
    setFieldErrors(errors);
    if (Object.keys(errors).length) { setError('请检查标记的配置项后保存。'); document.getElementById(`field-${Object.keys(errors)[0]}`)?.focus(); return null; }
    return config;
  }
  function save(fields: Field[], category: string, key: string) {
    const config = payload(fields, category); if (!config) return;
    run(key, async signal => {
      if (category === 'ai_providers' && fields.some(field => field.name === 'landppt_model') && !config.landppt_model) {
        try { const result = await request('/api/ai/providers/landppt/models', 'GET', undefined, signal); config.landppt_model = result.models?.includes('MODEL1') ? 'MODEL1' : result.models?.[0] || 'MODEL1'; }
        catch (reason) { if (signal.aborted) throw reason; config.landppt_model = 'MODEL1'; }
      }
      await request(`/api/config/${category}`, 'POST', { config }, signal);
      fields.forEach(field => dirty.current.delete(field.name));
      setValues(previous => ({ ...previous, ...config }));
      message.success('配置已保存，已实时生效');
      if (category === 'image_service') request('/api/image/status', 'GET', undefined, signal).then(setImageStatus).catch(() => {});
    });
  }
  function testProvider(provider: string) {
    const config = valuesRef.current;
    const body: ApiData = { provider };
    ['api_key', 'base_url', 'model'].forEach(key => { if (config[`${provider}_${key}`]) body[key] = String(config[`${provider}_${key}`]).trim(); });
    if (provider === 'openai') body.use_responses_api = bool(config.openai_use_responses_api);
    if (['openai', 'anthropic'].includes(provider)) { body.enable_reasoning = bool(config[`${provider}_enable_reasoning`]); body.reasoning_effort = config[`${provider}_reasoning_effort`] || 'medium'; }
    run(`test-${provider}`, async signal => { const result = await request('/api/ai/providers/test', 'POST', body, signal); setTestResult({ title: `${labels[provider]} 连接测试`, message: result.message || '连接成功' }); });
  }
  function chooseDefault(provider: string) {
    run(`default-${provider}`, async signal => {
      await request('/api/config/default-provider', 'POST', { provider }, signal);
      setDefaultProvider(provider);
      setModels(previous => {
        const next = { ...previous }; let changed = false;
        for (const name of Object.keys(next)) if (name.endsWith('_model_name') && !valuesRef.current[name.replace('_name', '_provider')]) { delete next[name]; changed = true; }
        return changed ? next : previous;
      });
      message.success('默认提供者已更新');
    });
  }
  const fetchModels = useCallback(async (field: Field) => {
    const provider = field.name === 'pollinations_model' ? 'pollinations' : field.name.endsWith('_model_name') ? String(valuesRef.current[field.name.replace('_name', '_provider')] || defaultProvider) : field.name.replace('_model', '');
    await run(`models-${field.name}`, async signal => {
      let list: string[] = [];
      const names = (records: unknown[]) => records
        .filter((model: any) => provider !== 'pollinations' || (typeof model === 'object' && Array.isArray(model?.output_modalities) && model.output_modalities.includes('image')))
        .map((model: any) => typeof model === 'string' ? model : model?.id || model?.name).filter((name: unknown): name is string => typeof name === 'string' && !!name.trim());
      if (provider.startsWith('custom:')) list = (await request(`/api/managed-providers/${provider.slice(7)}/models`, 'POST', undefined, signal)).models || [];
      else if (provider === 'landppt') list = (await request('/api/ai/providers/landppt/models', 'GET', undefined, signal)).models || [];
      else {
        let config = valuesRef.current;
        if (!config[`${provider}_api_key`]) {
          const saved = await request(`/api/config/${provider === 'pollinations' ? 'image_service' : 'ai_providers'}`, 'GET', undefined, signal);
          config = { ...saved.config, ...Object.fromEntries(Object.entries(config).filter(([, value]) => String(value ?? '').trim())) };
        }
        const base = String(config[`${provider}_${provider === 'pollinations' ? 'api_base' : 'base_url'}`] || (provider === 'openai' ? 'https://api.openai.com/v1' : provider === 'pollinations' ? 'https://gen.pollinations.ai' : '')).replace(/\/$/, '');
        if (!config[`${provider}_api_key`] && provider !== 'pollinations') throw new Error('请先配置 API Key');
        // OpenAI-compatible endpoints often lack CORS headers (e.g. LAN gateways); fetch through the backend proxy.
        if (provider === 'openai') list = names((await request('/api/ai/providers/openai/models', 'POST', { base_url: base, api_key: config.openai_api_key, llm_timeout_seconds: config.llm_timeout_seconds }, signal)).models || []);
        else try {
          const response = await fetch(`${base}/${provider === 'pollinations' ? 'image/models' : 'models'}`, { signal, headers: config[`${provider}_api_key`] ? { Authorization: `Bearer ${config[`${provider}_api_key`]}` } : {} });
          if (!response.ok) throw new Error(`模型列表读取失败（${response.status}）`);
          const result = await response.json();
          list = names(Array.isArray(result) ? result : result.data || []);
        } catch (reason) {
          if (signal.aborted || provider !== 'pollinations') throw reason;
          const result = await request('/api/image/pollinations/models', 'GET', undefined, signal);
          list = names(Array.isArray(result) ? result : result.models || []);
        }
      }
      list = [...new Set(list.filter(model => typeof model === 'string' && !!model.trim()))].sort((a, b) => a.localeCompare(b));
      if (list.includes('MODEL1')) list = ['MODEL1', ...list.filter(model => model !== 'MODEL1')];
      setModels(previous => ({ ...previous, [field.name]: [...(provider === 'pollinations' ? [{ label: '（留空/默认）', value: '' }] : []), ...list.map(model => ({ label: model, value: model }))] }));
      message.success(list.length ? `已获取 ${list.length} 个模型` : '暂无可用模型，可手动填写');
    });
  }, [defaultProvider, run, message]);
  function renderField(field: Field) {
    if (field.name.endsWith('_model_provider')) {
      const options = managed.providers.map(provider => ({ value: provider.provider, label: provider.name + (!provider.is_active ? '（已停用）' : !provider.configured ? '（请先配置）' : ''), disabled: !provider.configured }));
      const selected = String(valuesRef.current[field.name] || '');
      if (selected.startsWith('custom:') && !options.some(option => option.value === selected)) options.push({ value: selected, label: '不可用的 AI 提供商', disabled: true });
      field = { ...field, options: [...field.options, ...options] };
    }
    return <SettingsField key={field.name} field={field} drafts={drafts} initialValue={initial[field.name]} pending={pending} error={fieldErrors[field.name]} models={models[field.name]} change={change} fetchModels={fetchModels} />;
  }
  function fieldsGrid(fields: Field[]) { return <Form layout="vertical" className="settings-fields">{fields.map(renderField)}</Form>; }
  function renderPanel(key: string) {
    if (key === 'jev-config') return <JevPanel />;
    const fields = panels.find(panel => panel.key === key)!.fields;
    if (key === 'ai-providers') {
      const providers = Object.keys(labels);
      return <div id={key} className="settings-stack">
        {(managed.providers.length > 0 || managed.error) && <ManagedProviders catalogue={managed} current={defaultProvider} chooseDefault={chooseDefault} busy={!!pending || loading} />}
        <Card size="small" title={<span className="config-card-title"><ApiOutlined aria-hidden />AI 提供者</span>} extra={<Tag className="config-default-tag">默认：{labels[defaultProvider] || managed.providers.find(provider => provider.provider === defaultProvider)?.name || '待配置'}</Tag>}>
          <Collapse className="provider-collapse" defaultActiveKey={[defaultProvider]} items={providers.map(provider => ({
            key: provider, label: <div className="provider-heading"><span className={`provider-mark${defaultProvider === provider ? ' provider-mark--default' : ''}`}>{providerMarks[provider]}</span><strong>{labels[provider]}</strong><Tag className="provider-status" icon={provider === 'landppt' || data.providerStatus[provider] ? <CheckCircleOutlined aria-hidden /> : undefined}>{provider === 'landppt' || data.providerStatus[provider] ? '可用' : '未配置'}</Tag></div>,
            children: <>
              {fieldsGrid(fields.filter(field => field.section === provider))}
              <div className="settings-actions"><Radio aria-label="设为默认" checked={defaultProvider === provider} disabled={!!pending || loading} onChange={() => chooseDefault(provider)}>{defaultProvider === provider ? '当前默认' : '设为默认'}</Radio><Space wrap><Tooltip title={`测试 ${labels[provider]} 连接`}><Button aria-label="测试连接" disabled={!!pending || loading} loading={pending === `test-${provider}`} icon={<ApiOutlined aria-hidden />} onClick={() => testProvider(provider)} /></Tooltip><Button type="primary" aria-label={`保存 ${labels[provider]}`} icon={<SaveOutlined aria-hidden />} disabled={!!pending || loading} loading={pending === `save-${provider}`} onClick={() => save(fields.filter(field => field.section === provider), 'ai_providers', `save-${provider}`)}>保存</Button></Space></div>
            </>,
          }))} />
        </Card>
        <Collapse className="model-roles-collapse" items={[{ key: 'roles', label: <span className="config-card-title"><BranchesOutlined aria-hidden />模型任务配置</span>, children: <>{fieldsGrid(fields.filter(field => field.section === '模型任务配置'))}<Button type="primary" aria-label="保存模型任务配置" icon={<SaveOutlined aria-hidden />} disabled={!!pending || loading} loading={pending === 'roles'} onClick={() => save(fields.filter(field => field.section === '模型任务配置'), 'model_roles', 'roles')}>保存</Button></> }]} />
      </div>;
    }
    const sections = [...new Set(fields.map(field => field.section))];
    const sectionCard = (section: string, dependencies?: string[]) => {
      const sectionFields = fields.filter(field => field.section === section);
      return <SettingsSection key={section} fields={sectionFields} drafts={drafts} dependencies={dependencies} title={<span className="config-card-title">{tabIcons[key]}{key === 'image-service' ? section.replace(/^详细配置 · /, '') : section}</span>}>{fieldsGrid(sectionFields)}</SettingsSection>;
    };
    const imageBase = fields.filter(field => field.name === 'enable_image_service' || field.dependencies.includes('enable_image_service'));
    const imageCredentials = fields.filter(field => !field.dependencies.length && field.name !== 'enable_image_service');
    const imageDetails = sections.filter(section => fields.some(field => field.section === section && field.dependencies.length && !field.dependencies.includes('enable_image_service')));
    return <div id={key} className="settings-stack">
      <div className="settings-savebar"><span className="subtle">{loading ? '正在读取配置…' : '保存后应用当前配置'}</span><Space>{key === 'image-service' && <Button disabled={!!pending || loading} loading={pending === 'test-image'} onClick={() => run('test-image', async signal => {
        const config = valuesRef.current; const provider = config.default_ai_image_provider || 'dalle';
        let size = '1024x1024';
        try { size = JSON.parse(config.ai_image_resolution_presets || '{}')[provider]?.[0] || size; } catch { throw new Error('请先修正分辨率 JSON'); }
        const result = await request('/api/image/test-generate', 'POST', { provider, size, quality: config.ai_image_quality || 'standard', prompt: 'A clean modern presentation test image, abstract business technology background, high quality' }, signal);
        const imagePath = String(result.image_path || result.image_url || result.image?.url || '');
        const image = imagePath.startsWith('http') ? new URL(imagePath).pathname : imagePath.startsWith('/') ? imagePath : imagePath ? `/images/${imagePath}` : '';
        setTestResult({ title: '图片生成测试', message: result.message || '图片生成成功', image });
      })} icon={<PictureOutlined aria-hidden />}>测试生成</Button>}<Button type="primary" aria-label={saveLabels[key]} icon={<SaveOutlined aria-hidden />} disabled={!!pending || loading} loading={pending === key} onClick={() => save(fields, categories[key], key)}>保存</Button></Space></div>
      {key === 'image-service' && <Alert type={imageStatus.status === 'ok' ? 'success' : 'warning'} showIcon title={`服务状态：${imageStatus.status === 'ok' && imageStatus.available_providers?.length ? '正常运行' : '服务异常'}`} description={`可用提供者：${(imageStatus.available_providers || []).join('、') || '暂无'}`} />}
      {key === 'image-service' ? <>
        <div className="image-source-settings"><SettingsSection fields={imageBase} drafts={drafts} title={<span className="config-card-title"><PictureOutlined aria-hidden />图片来源</span>}>{fieldsGrid(imageBase)}</SettingsSection></div>
        <div className="image-settings-grid">
          <div className="settings-stack">
            {imageDetails.filter(section => fields.some(field => field.section === section && field.dependencies.includes('enable_ai_generation'))).map(section => sectionCard(section, ['enable_image_service']))}
          </div>
          <div className="settings-stack">
            {imageDetails.filter(section => fields.some(field => field.section === section && !field.dependencies.includes('enable_ai_generation'))).map(section => sectionCard(section, ['enable_image_service']))}
            <ImageCredentials fields={imageCredentials} drafts={drafts}>{fieldsGrid}</ImageCredentials>
          </div>
        </div>
      </> : sections.map(section => sectionCard(section))}
    </div>;
  }
  // Keep pane elements stable when only the selected tab or feedback changes.
  const tabItems = useMemo(() => panels.map(panel => ({ key: panel.key, label: panel.label, icon: tabIcons[panel.key], children: renderPanel(panel.key) })), [panels, drafts, fieldErrors, models, pending, loading, defaultProvider, imageStatus, initial, data, change, fetchModels, run, message, managed.providers, managed.error, managed.loading]);
  return <div className="settings-page configuration-page">
    <div className="page-heading config-heading"><div><span className="config-heading-icon"><SettingOutlined aria-hidden /></span><h1>系统配置管理</h1></div></div>
    {error && <Alert className="page-error" role="alert" type="error" showIcon title={error} closable onClose={() => setError('')} />}
    <Tabs aria-label="系统配置分类" animated={false} activeKey={active} onChange={setActive} items={tabItems} />
    <Modal title={testResult?.title} modalRender={modalFocus} open={!!testResult} onCancel={() => setTestResult(null)} afterClose={() => testTrigger.current?.focus()} footer={<Button onClick={() => setTestResult(null)}>关闭测试结果</Button>}>
      <p className="test-result-copy">{testResult?.message}</p>{testResult?.image && <img className="test-result-image" src={testResult.image} alt="图片生成测试结果" />}
    </Modal>
  </div>;
}
