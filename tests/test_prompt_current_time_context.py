from datetime import datetime

from landppt.services.prompts.outline_prompts import OutlinePrompts
from summeryanyfile.config.prompts import PromptTemplates


def test_landppt_outline_prompt_zh_includes_current_time_context():
    prompt = OutlinePrompts.get_outline_prompt_zh(
        topic="AI 战略规划",
        scenario_desc="年度汇报",
        target_audience="管理层",
        style_desc="专业商务",
        requirements="突出年度重点",
        description="聚焦战略与执行",
        research_section="",
        page_count_instruction="共 10 页",
        expected_page_count=10,
        language="中文",
    )

    assert "当前时间参考" in prompt
    assert str(datetime.now().year) in prompt
    assert "当前季度" in prompt


def test_landppt_outline_prompt_en_includes_current_time_context():
    prompt = OutlinePrompts.get_outline_prompt_en(
        topic="AI Strategy",
        scenario_desc="Annual review",
        target_audience="Executives",
        style_desc="Professional business",
        requirements="Highlight priorities",
        description="Focus on strategy and execution",
        research_section="",
        page_count_instruction="10 slides",
        expected_page_count=10,
        language="English",
    )

    assert "Current Time Reference" in prompt
    assert str(datetime.now().year) in prompt
    assert "Current quarter" in prompt


def test_summeryanyfile_initial_outline_prompt_includes_current_time_context():
    prompt = PromptTemplates.get_initial_outline_prompt()
    messages = prompt.format_messages(
        project_topic="AI 战略规划",
        project_scenario="年度汇报",
        project_requirements="突出年度重点",
        target_audience="管理层",
        custom_audience="高层决策者",
        ppt_style="专业商务",
        custom_style_prompt="简洁有力量",
        structure='{"title":"示例"}',
        content="这是示例文档内容。",
        slides_range="共 10 页",
        target_language="中文",
    )

    content = messages[0].content
    assert "当前时间参考" in content
    assert str(datetime.now().year) in content
    assert "当前季度" in content


def test_summeryanyfile_refine_outline_prompt_includes_current_time_context():
    prompt = PromptTemplates.get_refine_outline_prompt()
    messages = prompt.format_messages(
        project_topic="AI 战略规划",
        project_scenario="年度汇报",
        project_requirements="突出年度重点",
        target_audience="管理层",
        custom_audience="高层决策者",
        ppt_style="专业商务",
        custom_style_prompt="简洁有力量",
        existing_outline='{"title":"示例PPT"}',
        new_content="这是新增内容。",
        context="这是上下文。",
        slides_range="共 10 页",
        target_language="中文",
    )

    content = messages[0].content
    assert "当前时间参考" in content
    assert str(datetime.now().year) in content
    assert "当前季度" in content
