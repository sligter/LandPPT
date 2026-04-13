from landppt.services.prompts import design_prompts as prompts_module


def test_project_design_guide_prompt_includes_layout_priority_context():
    prompt = prompts_module.DesignPrompts.get_project_design_guide_prompt(
        confirmed_requirements={"topic": "年度战略汇报"},
        slides_summary="- 第1页：封面\n- 第2页：业务总览",
        total_pages=2,
        first_slide_data={"title": "年度战略汇报", "slide_type": "cover"},
        template_html="<div class='page'><header></header><main></main><footer></footer></div>",
    )

    assert "**版面取舍顺序**" in prompt
    assert "**模板理解与使用方向**" in prompt
    assert "**E. 普通内容页与特殊页面的分工**" in prompt
    assert "**H. 给单页生成器的执行原则**" in prompt


def test_slide_design_guide_prompt_includes_page_type_guidance(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = prompts_module.DesignPrompts.get_slide_design_guide_prompt(
        slide_data={"title": "业务分析", "content_points": ["现状", "问题", "机会"]},
        confirmed_requirements={"topic": "年度战略汇报", "target_audience": "管理层"},
        slides_summary="- 第1页：封面\n- 第2页：业务分析\n- 第3页：行动方案",
        page_number=2,
        total_pages=3,
        template_html="<div class='page'><header></header><main></main><footer></footer></div>",
    )

    assert "**模板理解与使用方向**" in prompt
    assert "**A. 当前页角色判断**" in prompt
    assert "**B. 视觉焦点与布局方向**" in prompt
    assert "**F. 风险与避坑**" in prompt


def test_single_slide_html_prompt_includes_fixed_canvas_guidance(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = prompts_module.DesignPrompts.get_single_slide_html_prompt(
        slide_data={"title": "业务总览", "content_points": ["增长", "效率", "成本"]},
        confirmed_requirements={"topic": "年度战略汇报", "target_audience": "管理层"},
        page_number=2,
        total_pages=10,
        context_info="",
        style_genes="- 深色标题\n- 轻量卡片",
        template_html="<div class='page'><header></header><main></main><footer></footer></div>",
    )

    assert "**版面取舍顺序**" in prompt
    assert "**固定画布实现提醒**" in prompt
    assert "1280×720" in prompt
    assert "overflow:hidden" in prompt
    assert "flex/grid item" in prompt
    assert "页码锚点优先跟随模板原有位置关系" in prompt


def test_combined_style_prompt_includes_canvas_priority(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = prompts_module.DesignPrompts.get_combined_style_genes_and_guide_prompt(
        template_code="<div class='page'><header></header><main></main><footer></footer></div>",
        slide_data={"title": "封面", "subtitle": "项目启动"},
        page_number=1,
        total_pages=8,
    )

    assert "**版面取舍顺序**" in prompt
    assert "**内容与设计质量**" in prompt
    assert "**固定画布策略**" in prompt
    assert "===STYLE_GENES===" in prompt
    assert "===DESIGN_GUIDE===" in prompt
