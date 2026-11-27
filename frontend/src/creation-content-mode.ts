import type { ApiData } from './api';

export const videoExplainer = 'video_explainer';
export const pptStyleOptions = [
  { value: 'general', label: '通用场景' },
  { value: 'keynote', label: '发布会' },
  { value: videoExplainer, label: '技术图解视频' },
  { value: 'custom', label: '自定义风格' },
];

export function pptStyleSelection(fields: ApiData): string {
  return fields.content_mode === videoExplainer ? videoExplainer : fields.ppt_style || 'general';
}

export function pptStyleChanges(selection: string): ApiData {
  if (selection === videoExplainer) return { content_mode: videoExplainer };
  return { content_mode: 'presentation', ppt_style: selection };
}

export function creationModeFields(fields: ApiData): ApiData {
  if (fields.content_mode !== videoExplainer) return fields;
  return {
    ...fields,
    generation_mode: 'freeform',
    render_mode: 'html',
    package_version_id: '0',
    content_urls: '',
    unattended_template_mode: 'free',
    unattended_template_id: '',
  };
}
