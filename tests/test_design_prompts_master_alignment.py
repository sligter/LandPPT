from landppt.services.prompts import design_prompts as prompts_module


def test_project_design_guide_prompt_includes_current_structure():
    prompt = prompts_module.DesignPrompts.get_project_design_guide_prompt(
        confirmed_requirements={"topic": "年度经营汇报"},
        slides_summary="- 第1页：封面\n- 第2页：业务概览\n- 第3页：行动计划",
        total_pages=3,
        first_slide_data={"title": "年度经营汇报", "slide_type": "cover"},
        template_html="<div class='page'><header></header><main></main><footer></footer></div>",
    )

    assert "**模板理解与使用方向**" in prompt
    assert "**内容与设计质量**" in prompt
    assert "**固定画布策略**" in prompt
    assert "**版面取舍顺序**" in prompt
    assert "**E. 普通内容页与特殊页面的分工**" in prompt
    assert "**H. 给单页生成器的执行原则**" in prompt


def test_single_slide_html_prompt_includes_template_guidance_and_self_check(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = prompts_module.DesignPrompts.get_single_slide_html_prompt(
        slide_data={"title": "业务概览", "content_points": ["增长", "效率", "成本"]},
        confirmed_requirements={"topic": "年度经营汇报", "target_audience": "管理层"},
        page_number=2,
        total_pages=10,
        context_info="",
        style_genes="- 深色标题\n- 轻量卡片",
        template_html="<div class='page'><header></header><main></main><footer></footer></div>",
    )

    assert "**模板 HTML 原文**" in prompt
    assert "**模板理解与使用方向**" in prompt
    assert "**稳定区域理解方向**" in prompt
    assert "**内容与设计质量**" in prompt
    assert "**固定画布实现提醒**" in prompt
    assert "**输出前问自己**" in prompt
    assert "**设计基因**" in prompt


def test_slide_context_prompt_for_regular_page_uses_directional_guidance():
    prompt = prompts_module.DesignPrompts.get_slide_context_prompt(
        slide_data={"title": "业务策略", "slide_type": "content"},
        page_number=2,
        total_pages=8,
    )

    assert "**普通内容页**" in prompt
    assert "标题区和页码区更适合作为母板锚定区" in prompt
    assert "吸收页面指导的方向建议" in prompt
    assert "完整信息单元" in prompt


def test_combined_style_prompt_includes_current_structure(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = prompts_module.DesignPrompts.get_combined_style_genes_and_guide_prompt(
        template_code="<div class='page'><header></header><main></main><footer></footer></div>",
        slide_data={"title": "封面", "subtitle": "项目启动"},
        page_number=1,
        total_pages=8,
    )

    assert "**模板理解与使用方向**" in prompt
    assert "**内容与设计质量**" in prompt
    assert "**固定画布策略**" in prompt
    assert "**版面取舍顺序**" in prompt
    assert "===STYLE_GENES===" in prompt
    assert "===DESIGN_GUIDE===" in prompt
