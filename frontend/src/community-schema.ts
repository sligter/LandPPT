import type { ApiData } from './api';

export const systemDefaults: ApiData = {
  default_ai_provider: 'landppt', landppt_model: 'MODEL1', landppt_base_url: '', landppt_api_key: '',
  max_tokens: 16384, temperature: .7, top_p: 1, llm_timeout_seconds: 600, parallel_slides_count: 3,
  research_provider: 'auto', enable_parallel_generation: true, enable_per_slide_creative_guidance: true,
  tavily_api_key: '', tavily_base_url: 'https://api.tavily.com', tavily_max_results: 10, tavily_search_depth: 'advanced',
  searxng_host: '', searxng_max_results: 10, searxng_language: 'auto', searxng_timeout: 30,
  research_max_content_length: 5000, research_extraction_timeout: 30, research_enable_content_extraction: true,
  tts_voice_zh: 'zh-CN-XiaoxiaoNeural', tts_voice_en: 'en-US-JennyNeural', comfyui_base_url: 'http://127.0.0.1:8188',
  comfyui_tts_workflow_path: 'tests/Qwen3-TD-TTS.json', comfyui_tts_timeout_seconds: 600, comfyui_tts_chunk_chars: 120,
  comfyui_tts_force_precision: '', mineru_base_url: 'https://mineru.net/api/v4', mineru_api_key: '',
  apryse_license_key: '', enable_apryse_pptx_export: false,
};
export const booleanValue = (value: unknown) => typeof value === 'boolean' ? value : ['true', '1', 'yes', 'on'].includes(String(value).toLowerCase().trim());
export function normalizeSystem(config: ApiData, fallback = systemDefaults) {
  return Object.fromEntries(Object.entries(systemDefaults).map(([key, original]) => {
    const saved = fallback[key] ?? original; let value = config[key] ?? saved;
    if (key === 'default_ai_provider' && value === 'gemini') value = 'google';
    if (typeof original === 'boolean') value = value === '' ? booleanValue(saved) : booleanValue(value);
    else if (typeof original === 'number') value = value === '' || value == null || !Number.isFinite(Number(value)) ? Number(saved) : Number(value);
    else value = String(value).trim();
    return [key, value];
  }));
}
export function systemPayload(values: ApiData, snapshot: ApiData) {
  const payload = normalizeSystem(values, snapshot);
  for (const key of ['default_ai_provider', 'research_provider', 'tavily_search_depth', 'tavily_base_url', 'landppt_model']) payload[key] ||= snapshot[key] || systemDefaults[key];
  return payload;
}
export function readSystemFields() {
  const source = document.querySelector<HTMLTemplateElement>('#communityBlueprint')!.content;
  return Array.from(source.querySelectorAll('.system-config-block')).map(block => ({
    title: block.querySelector('h3')!.textContent!.trim(),
    description: block.querySelector('.system-config-block__header p')?.textContent?.trim(),
    fields: Array.from(block.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input[name],select[name]')).map(input => {
      const group = input.closest('.form-group,.system-toggle-card')!;
      const numeric = (key: string) => input.hasAttribute(key) ? Number(input.getAttribute(key)) : undefined;
      return { name: input.name, id: input.id, label: group.querySelector('strong,label')?.textContent?.trim() || input.name,
        help: group.querySelector('span,.helper')?.textContent?.trim(), kind: input instanceof HTMLSelectElement ? 'select' : input.type,
        options: Array.from(input.querySelectorAll('option')).map(option => ({ value: option.value, label: option.textContent! })),
        min: numeric('min'), max: numeric('max'), step: numeric('step'), placeholder: input.getAttribute('placeholder') || '',
      };
    }),
  }));
}
