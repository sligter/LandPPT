import assert from 'node:assert/strict';
import test from 'node:test';
import { creationModeFields, pptStyleChanges, pptStyleSelection } from '../src/creation-content-mode.ts';

const draft = {
  topic: '运行时与共享文件',
  requirements: '先讲运行时，再讲文件协作',
  generation_mode: 'package',
  render_mode: 'svg',
  package_version_id: '7',
  content_urls: 'https://example.test/material',
  unattended_template_mode: 'global',
  unattended_template_id: '4',
  stop_at_stage: 'ppt',
};

test('技术图解使用 HTML 和自由模板，保留主题、需求与停止阶段', () => {
  const videoDraft = Object.freeze({ ...draft, content_mode: 'video_explainer' });
  assert.deepEqual(creationModeFields(videoDraft), {
    ...videoDraft,
    generation_mode: 'freeform',
    render_mode: 'html',
    package_version_id: '0',
    content_urls: '',
    unattended_template_mode: 'free',
    unattended_template_id: '',
  });
});

test('切回普通演示文稿时恢复草稿中的资料与模板', () => {
  const videoDraft = { ...draft, content_mode: 'video_explainer' };
  creationModeFields(videoDraft);
  const presentation = { ...videoDraft, content_mode: 'presentation' };
  assert.deepEqual(creationModeFields(presentation), { ...draft, content_mode: 'presentation' });
});

test('PPT 风格菜单将技术图解作为作品模式提交', () => {
  const fields = { ppt_style: 'keynote', content_mode: 'presentation' };
  const video = { ...fields, ...pptStyleChanges('video_explainer') };
  assert.equal(pptStyleSelection(video), 'video_explainer');
  assert.equal(creationModeFields(video).ppt_style, 'keynote');

  const custom = { ...video, ...pptStyleChanges('custom') };
  assert.equal(pptStyleSelection(custom), 'custom');
  assert.equal(custom.content_mode, 'presentation');
});
