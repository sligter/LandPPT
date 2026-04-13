"""测试新版设计提示词的方向性结构。"""

from landppt.services.prompts import design_prompts as prompts_module
from landppt.services.prompts.design_prompts import DesignPrompts


SAMPLE_TEMPLATE = "<div class='slide-header'><h1>{{ main_heading }}</h1></div><main>{{ page_content }}</main><div class='slide-footer'>{{ current_page_number }}</div>"


def test_creative_template_prompt_includes_quality_and_intent(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = DesignPrompts.get_creative_template_context_prompt(
        slide_data={"title": "业务分析", "slide_type": "content", "content_points": ["增长", "效率"]},
        template_html=SAMPLE_TEMPLATE,
        slide_title="业务分析",
        slide_type="content",
        page_number=3,
        total_pages=8,
        context_info="",
        style_genes="- 深色主题",
        project_topic="年度报告",
        project_type="business",
        project_audience="管理层",
        project_style="professional",
    )

    assert "**内容与设计质量**" in prompt
    assert "**创意思考顺序**" in prompt


def test_content_quality_before_canvas_rules(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = DesignPrompts.get_creative_template_context_prompt(
        slide_data={"title": "测试", "slide_type": "content"},
        template_html=SAMPLE_TEMPLATE,
        slide_title="测试",
        slide_type="content",
        page_number=2,
        total_pages=5,
        context_info="",
        style_genes="",
        project_topic="",
        project_type="",
        project_audience="",
        project_style="",
    )

    quality_pos = prompt.find("**内容与设计质量**")
    creative_pos = prompt.find("**创意思考顺序**")
    canvas_pos = prompt.find("**固定画布实现提醒**")

    assert quality_pos > 0
    assert creative_pos > 0
    assert canvas_pos > 0
    assert quality_pos < canvas_pos
    assert creative_pos < canvas_pos


def test_slide_context_includes_directional_guidance():
    prompt = DesignPrompts.get_slide_context_prompt(
        slide_data={"title": "市场策略", "slide_type": "content"},
        page_number=4,
        total_pages=10,
    )

    assert "**普通内容页**" in prompt
    assert "吸收页面指导的方向建议" in prompt
    assert "完整信息单元" in prompt


def test_single_slide_prompt_includes_stable_zone_guidance(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    template = """<html><head><style>
    .slide-header { padding: 40px; border-bottom: 2px solid blue; }
    .slide-footer { position: absolute; bottom: 20px; right: 30px; }
    </style></head><body>
    <div class="slide-header"><h1>{{ main_heading }}</h1></div>
    <main>{{ page_content }}</main>
    <div class="slide-footer">{{ current_page_number }}</div>
    </body></html>"""

    prompt = DesignPrompts.get_single_slide_html_prompt(
        slide_data={"title": "技术架构", "slide_type": "content", "content_points": ["微服务", "容器化"]},
        confirmed_requirements={"topic": "技术方案", "target_audience": "技术团队"},
        page_number=3,
        total_pages=8,
        context_info="",
        style_genes="",
        template_html=template,
    )

    assert "**稳定区域理解方向**" in prompt
    assert "自行识别标题区、页码区和其他稳定锚点" in prompt


def test_single_slide_prompt_no_stable_zone_guidance_for_first_page(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = DesignPrompts.get_single_slide_html_prompt(
        slide_data={"title": "封面", "slide_type": "title"},
        confirmed_requirements={"topic": "年度报告"},
        page_number=1,
        total_pages=8,
        context_info="",
        style_genes="",
        template_html=SAMPLE_TEMPLATE,
    )

    assert "**稳定区域理解方向**" not in prompt


def test_content_quality_context_includes_qualitative_rules():
    context = DesignPrompts._build_content_quality_context()

    assert "信息密度与主题复杂度相称" in context
    assert "先补足事实、层次和结论" in context
    assert "留白服务于分组" in context
    assert "避免把信息平均切成四宫格这类均质化结构" in context
    assert "即使内容天然四等分，也应通过主次、轻重、大小、节奏或焦点转移建立层次差异" in context


def test_slide_design_guide_prompt_avoids_homogeneous_four_grid_layout(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = DesignPrompts.get_slide_design_guide_prompt(
        slide_data={"title": "核心举措", "content_points": ["举措一", "举措二", "举措三", "举措四"]},
        confirmed_requirements={"topic": "年度策略"},
        slides_summary="- 第1页：封面\n- 第2页：核心举措",
        page_number=2,
        total_pages=6,
        template_html="<div class='page'><main></main></div>",
    )

    assert "避免推荐四宫格等均质化布局" in prompt
    assert "即使当前页内容天然四等分且主次关系一致，也必须主动建立视觉层次" in prompt
    assert "不能做成均质排布" in prompt
