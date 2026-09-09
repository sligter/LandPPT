from landppt.services.prompts import design_prompts as prompts_module


def test_project_design_guide_prompt_includes_layout_mastery_context():
    prompt = prompts_module.DesignPrompts.get_project_design_guide_prompt(
        confirmed_requirements={"topic": "AI 战略汇报"},
        slides_summary="- 第1页：封面\n- 第2页：策略总览",
        total_pages=2,
        first_slide_data={"title": "AI 战略汇报", "slide_type": "cover"},
        template_html="<div class='page'><header></header><main></main><footer></footer></div>",
    )

    assert "版式参考工具箱" in prompt
    assert "古腾堡图表" in prompt
    assert "黄金比例" in prompt
    assert "非对称平衡" in prompt


def test_slide_design_guide_prompt_includes_layout_mastery_context(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = prompts_module.DesignPrompts.get_slide_design_guide_prompt(
        slide_data={"title": "增长机会", "content_points": ["渠道扩张", "品牌升级"]},
        confirmed_requirements={"topic": "年度复盘"},
        slides_summary="- 第1页：封面\n- 第2页：增长机会",
        page_number=2,
        total_pages=8,
        template_html="<div class='page'><main class='content-grid'></main></div>",
    )

    assert "版式参考工具箱" in prompt
    assert "模块化栅格" in prompt
    assert "帮助推理，不做硬性要求" in prompt
    assert "时间线" in prompt


def test_combined_style_and_guide_prompt_includes_layout_mastery_context(monkeypatch):
    monkeypatch.setattr(prompts_module, "_is_image_service_enabled", lambda: False)

    prompt = prompts_module.DesignPrompts.get_combined_style_genes_and_guide_prompt(
        template_code="<div class='page'><header></header><main></main><footer></footer></div>",
        slide_data={"title": "封面", "subtitle": "项目启动"},
        page_number=1,
        total_pages=10,
    )

    assert "版式参考工具箱" in prompt
    assert "留白张力" in prompt
    assert "帮助推理，不做硬性要求" in prompt
    assert "满版全画幅" in prompt
