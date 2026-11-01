import { useEffect, useRef, useState, type MutableRefObject } from 'react';
import { Alert, Button, Input, Tooltip, Typography, Upload, type FormInstance } from 'antd';
import { ArrowRightOutlined, ArrowUpOutlined, CheckCircleOutlined, LoadingOutlined, PaperClipOutlined, RedoOutlined } from '@ant-design/icons';
import { request } from '../api';
import { BrandSymbol } from './brand-symbol';
import { sourceExtensions } from './source-materials';

export type ChatTurn = { role: 'user' | 'assistant'; content: string; applied?: string[]; ready?: boolean };

// Field → label shown under a reply so the user can see what the assistant filled in.
const labels: Record<string, string> = {
  topic: '标题', requirements: '需求', scenario: '场景', audience_type: '受众', custom_audience: '受众', page_count_mode: '页数', min_pages: '页数', max_pages: '页数',
  ppt_style: '风格', custom_style_prompt: '风格', language: '语言', network_mode: '联网研究', include_transition_pages: '过渡页', include_page_numbers: '页码',
};
const examples = ['给公司管理层汇报 2026 年 AI 落地计划，10 页左右，稳重商务风', '面向小学生讲讲太阳系，多用图片，轻松有趣', '把 https://example.com/article 这篇文章做成技术分享，受众是后端工程师'];
const urls = (value: unknown) => String(value || '').split(/[\n,;\t ]+/).map(item => item.trim()).filter(Boolean).slice(0, 50);

type Props = {
  form: FormInstance; files: File[]; disabled: boolean;
  draft: MutableRefObject<{ chat?: ChatTurn[] }>;
  addFile: (file: File) => boolean; onChange: () => void;
};

export default function CreationAssistant({ form, files, disabled, draft, addFile, onChange }: Props) {
  const [chat, setChat] = useState<ChatTurn[]>(() => draft.current.chat || []);
  const [input, setInput] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const controller = useRef<AbortController>(undefined); const log = useRef<HTMLDivElement>(null);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: 'smooth' }); }, [chat, busy]);
  const update = (next: ChatTurn[]) => { draft.current.chat = next; setChat(next); };
  async function send(value = input) {
    const text = value.trim(); if (!text || busy || disabled) return;
    const previous = chat, next: ChatTurn[] = [...chat, { role: 'user', content: text }];
    update(next); setInput(''); setBusy(true); setError('');
    const signal = (controller.current = new AbortController()).signal;
    try {
      const current = form.getFieldsValue(true);
      const fields = Object.fromEntries(Object.keys(labels).map(key => [key, current[key]]).filter(([, item]) => item !== undefined && item !== ''));
      const links = urls(current.content_urls);
      const messages = next.slice(-20).map(({ role, content }) => ({ role, content }));
      const result = await request('/api/ai/creation-assistant', 'POST', { messages, fields, attachments: files.map(file => file.name), links }, signal);
      const changes = result.fields && typeof result.fields === 'object' ? result.fields : {};
      // Links the user typed in chat are owned by the conversation; links added by hand stay untouched.
      const mentioned: string[] = Array.isArray(result.mentioned_urls) ? result.mentioned_urls : [];
      const nextLinks = [...new Set([...links.filter(link => !mentioned.includes(link)), ...(Array.isArray(result.content_urls) ? result.content_urls : [])])];
      const linksChanged = nextLinks.join('\n') !== links.join('\n');
      form.setFieldsValue({ ...changes, ...(linksChanged ? { content_urls: nextLinks.join('\n') } : {}) });
      onChange();
      const applied = [...new Set([...Object.keys(changes).map(key => labels[key]).filter(Boolean), ...(linksChanged ? ['网页链接'] : [])])];
      update([...next, { role: 'assistant', content: String(result.reply || ''), applied, ready: !!result.ready }]);
    } catch (reason) {
      if (signal.aborted) return;
      update(previous); setInput(text); setError((reason as Error).message);
    } finally { if (!signal.aborted) setBusy(false); }
  }
  function reset() { controller.current?.abort(); update([]); setBusy(false); setError(''); }
  const last = chat.length - 1;
  return <section className="creation-assistant" aria-label="AI 需求对话">
    <div className="creation-assistant-log" ref={log} role="log" aria-live="polite">
      {!chat.length && <div className="creation-assistant-welcome">
        <Typography.Text strong>说说你想做一份什么样的演示</Typography.Text>
        <Typography.Text type="secondary">我会追问关键信息，自动拟定标题、整理需求并设置参数。可以直接粘贴网页链接，或用回形针添加文件。</Typography.Text>
        <div className="creation-assistant-examples">{examples.map(example => <Button key={example} size="small" disabled={disabled} onClick={() => void send(example)}>{example}</Button>)}</div>
      </div>}
      {chat.map((turn, index) => turn.role === 'user'
        ? <div key={index} className="creation-assistant-turn is-user"><div className="creation-assistant-bubble">{turn.content}</div></div>
        : <div key={index} className="creation-assistant-turn is-assistant">
          <span className="creation-assistant-avatar"><BrandSymbol /></span>
          <div className="creation-assistant-message">
            <div className="creation-assistant-text">{turn.content}</div>
            {!!turn.applied?.length && <Typography.Text type="secondary" className="creation-assistant-applied"><CheckCircleOutlined aria-hidden /> 已填写：{turn.applied.join(' · ')}</Typography.Text>}
            {turn.ready && index === last && <div className="creation-assistant-ready">
              <Typography.Text>需求已确认，可检查下方草稿后开始生成。</Typography.Text>
              <Button size="small" type="primary" icon={<ArrowRightOutlined aria-hidden />} disabled={disabled} onClick={() => form.submit()}>开始生成</Button>
            </div>}
          </div>
        </div>)}
      {busy && <div className="creation-assistant-turn is-assistant" role="status">
        <span className="creation-assistant-avatar"><BrandSymbol /></span>
        <Typography.Text type="secondary" className="creation-assistant-text"><LoadingOutlined aria-hidden /> 正在整理需求…</Typography.Text>
      </div>}
    </div>
    {error && <Alert type="error" showIcon title={error} closable onClose={() => setError('')} />}
    <div className="creation-assistant-input">
      <Upload multiple showUploadList={false} disabled={disabled} accept={sourceExtensions.map(ext => '.' + ext).join(',')} beforeUpload={addFile}>
        <Tooltip title="添加文件资料"><Button type="text" shape="circle" icon={<PaperClipOutlined aria-hidden />} aria-label="添加文件资料" disabled={disabled} /></Tooltip>
      </Upload>
      <Input.TextArea aria-label="描述你的演示需求" variant="borderless" value={input} maxLength={4000} disabled={disabled} autoSize={{ minRows: 1, maxRows: 5 }}
        placeholder={chat.length ? '继续补充或回答问题，回复“你决定”也可以' : '描述你的演示需求，Enter 发送，Shift + Enter 换行'}
        onChange={event => setInput(event.target.value)}
        onPressEnter={event => { if (!event.shiftKey && !event.nativeEvent.isComposing && !event.ctrlKey && !event.metaKey) { event.preventDefault(); void send(); } }} />
      {!!chat.length && <Tooltip title="重新开始对话"><Button type="text" shape="circle" icon={<RedoOutlined aria-hidden />} aria-label="重新开始对话" disabled={disabled} onClick={reset} /></Tooltip>}
      <Button type="primary" shape="circle" icon={<ArrowUpOutlined aria-hidden />} aria-label="发送" loading={busy} disabled={disabled || !input.trim()} onClick={() => void send()} />
    </div>
  </section>;
}
