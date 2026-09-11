# SVG 页面模式对照实验

目的：在同一份大纲、同一份构图计划、同一套风格指导下，比较 HTML 页与 SVG 页的首轮构图质量与修复成本。判定规则在 `artifacts/composition-review/svg-page-mode-plan.md` 里预登记，跑之前不要改。

使用入口：`/create` 创建页底部工具栏 → **页面绘制 · HTML** → **SVG 页面（实验）**；项目的需求确认页也保留此选项。默认仍为 HTML。SVG 支持整页重生成，逐元素/代码编辑与 AI 编辑暂禁用。模式和逐页生成报告随项目保存；修改绘制方式后再次生成，会重新生成模式不符的旧页面。

Anthropic 输出上限可在 AI 配置页或 `ANTHROPIC_MAX_TOKENS` 设置，默认 16384；需与所选模型支持的上限匹配。测字字体可通过 `LANDPPT_SVG_MEASURE_FONT` 指定，不指定时优先使用本机雅黑或 Noto。字体替换仍需视觉复核。

## 步骤

1. **准备两个项目**：同一份资料，"页面绘制方式"分别选 HTML 与 SVG；其余选项一致，都不选全局母版。必须核对两组实际大纲、逐页 composition_brief 和创意指导内容一致；仅输入相同资料并不保证模型两次规划相同。运行时 `_render_mode` 不参与语义指导指纹，但缓存按项目存储，并不会自动跨项目复制。
2. **生成**：两组都用同一个模型、同一 temperature。SVG 组每页最多 3 轮（首轮 + 2 轮定点修复），日志写在 `cache/style_genes/<project_id>_svg_pages.jsonl`。
3. **导出页面**：

   ```bash
   uv run python -m scripts.svg_experiment.export_project_pages <html_project_id> --out results/pages/html
   uv run python -m scripts.svg_experiment.export_project_pages <svg_project_id> --out results/pages/svg
   ```

4. **度量**：

   ```bash
   uv run python -m scripts.svg_experiment.measure_html results/pages/html --out results/html
   uv run python -m scripts.svg_experiment.measure_svg results/pages/svg --out results/svg
   ```

   HTML 度量需要 Playwright 的 Chromium（`uv run playwright install chromium`）。SVG 度量默认不换行、不缩字、不移动元素；XML 清洗和符号注入仍会执行。加 `--repair` 才做确定性排版与越界修复。

   **数据库导出的是最终页面，不能当作模型首轮输出。** 每轮 SVG 报告的 `artifacts.raw` / `artifacts.repaired` 指向不可覆盖的候选文件，`before_repair` 记录修复前指标。测首轮时读取 attempt=1 的 raw 文件；测最终效果时使用项目导出的页面。文件中可能包含用户资料，沿用本地缓存的访问和清理规则，不应公开发布原始目录。

5. **聚合**：

   ```bash
   uv run python -m scripts.svg_experiment.aggregate \
       --group html=results/html --group svg=results/svg \
       --reports svg=cache/style_genes/<svg_project_id>_svg_pages.jsonl \
       --markdown results/compare.md
   ```

## 指标口径

两组共用 `landppt.services.slide.svg_page.inspect` 里的几何函数：

| 信号 | 含义 | 阻断 |
|---|---|---|
| out_of_canvas | 非背景元素超出 1280×720（容差 2px） | 是 |
| overlap | 文字与文字、文字与图片压叠，交叠面积 ≥ 较小者 4% | 是 |
| text_overflow | SVG：缩字到 14px 仍装不下文本框；HTML：scroll 尺寸超出 client 尺寸 | 是 |
| missing_text_box | SVG 特有：长文本没有 data-box-w | 否 |
| empty_band | stage 区域内连续空白 ≥ 区域高 25% 或宽 30% | 否 |
| equal_rect_group | ≥3 个同尺寸矩形 | 否 |
| stage_coverage | 非背景内容对 stage 区域的 16px 网格覆盖率（指标，不是门槛） | — |

HTML 组的标题/页脚角色靠 header/footer 元素与页面上下 15% 位置推断，压叠排除祖先-后代关系；这些是启发式，结果 JSON 里保留原始矩形（`metrics.rects`）供人工复核。

SVG 也是近似测量：字体替换、字距、复杂 tspan、旋转、曲线路径及滤镜会使包围盒与实际像素不同。自动信号不等同视觉判定；空白率和等大矩形数量不作为自动扩写条件。

## 修复预算与当前边界

首轮质量与修复收益必须分开报告。比较成本时，两组都给至多 3 次模型调用，并单独记录 SVG 本地排版耗时；不要用 HTML 首轮和 SVG 第三轮直接比较。目前工具提供 SVG 生成报告、候选留存，以及 HTML/SVG 文件测量与聚合；HTML 的多轮实验仍需运行者保存原始候选并按相同预算执行，脚本不会自动生成或重试 HTML 项目。

没有真实模型结果时不能宣称 SVG 已胜出，也不能从“矩形组减少”单独推断收益来自格式还是提示词。需增加 HTML 同画布契约组才能区分这两个因素。

## 无 API 凭据的离线验证

```bash
uv run python -m scripts.svg_experiment.smoke --out artifacts/svg-mode-verification/smoke
```

生成封面、正文、流程、对比、数据和总结六类合成夹具，验证 1280×720 渲染、文本和符号引用，保存截图及度量。它验证接入和排版功能，不评估模型构图能力。输出目录的 `index.html` 可直接打开。

## 人工盲评

除自动信号外，每页按 1–5 分评"主体是否足够大、构图是否服务内容、信息是否完整"，评审不看组别标签。自动信号只负责筛出可疑页与量化修复成本，好不好看最终还是人说了算。

## SVG 编辑与 PPTX 导出

SVG 页在幻灯片编辑器中支持快速编辑（拖动、Alt 选择分组、文字、字号、颜色、缩放和撤销）、源码编辑与 AI 编辑助手。保存复用现有按用户鉴权、版本哈希校验的单页接口，SVG 经过严格 XML 校验；脚本、foreignObject 和新增外部图片地址不放行。旧版 HTML 专用的原生对话和要点增强入口仍禁用。

PPT 菜单提供两种 SVG 导出：

- **原生对象 PPTX**：普通文本、矩形、圆、椭圆、直线、多边形和折线转换为可编辑 DrawingML 对象。渐变、滤镜、裁剪、复杂文字、路径和图标保留为 SVG 图层，并附 PNG 兼容图。它不是任意 SVG 到完整可编辑形状的转换器。
- **矢量保真 PPTX**：整页作为 SVG 嵌入，同样附 PNG 兼容图。字体不内嵌；接收设备的字体替换可能影响外观。此入口要求所选演示为 SVG 页面；HTML 演示继续用已有导出。

```bash
uv run --extra dev pytest tests/test_svg_page_edit.py tests/test_slide_edit_agent_service.py tests/test_slide_edit_agent_routes.py
uv run python -m scripts.svg_experiment.check_edit_export
```

浏览器夹具使用真实编辑和导出 JS，拦截保存 API 后调用实际 SVG 校验器。验证文字修改、拖动、撤销、保存、两种导出、多页、取消和图片读取失败，并检查 PPTX 的 XML、原生文本与几何、SVG 和 PNG 媒体。产物在 `artifacts/svg-mode-verification/edit-export/`。它不调用真实模型，也不代替在 PowerPoint/WPS 中打开文件进行保真验证。
