from typing import Dict, Any, List
from .outline_prompts import OutlinePrompts
from .content_prompts import ContentPrompts
from .design_prompts import DesignPrompts
from .system_prompts import SystemPrompts
from .template_prompts import TemplatePrompts
from .repair_prompts import RepairPrompts

__all__ = [
    'OutlinePrompts',
    'ContentPrompts', 
    'DesignPrompts',
    'SystemPrompts',
    'TemplatePrompts',
    'RepairPrompts'
]

# 为了向后兼容，提供一个统一的提示词管理器
class PPTPromptsManager:
    """PPT提示词统一管理器"""
    
    def __init__(self):
        self.outline = OutlinePrompts()
        self.content = ContentPrompts()
        self.design = DesignPrompts()
        self.system = SystemPrompts()
        self.template = TemplatePrompts()
        self.repair = RepairPrompts()
    
    # 大纲相关提示词
    def get_outline_prompt_zh(self, *args, **kwargs):
        return self.outline.get_outline_prompt_zh(*args, **kwargs)
    
    def get_outline_prompt_en(self, *args, **kwargs):
        return self.outline.get_outline_prompt_en(*args, **kwargs)
    
    def get_streaming_outline_prompt(self, *args, **kwargs):
        return self.outline.get_streaming_outline_prompt(*args, **kwargs)
    
    def get_outline_generation_context(self, *args, **kwargs):
        return self.outline.get_outline_generation_context(*args, **kwargs)
    
    # 内容相关提示词
    def get_slide_content_prompt_zh(self, *args, **kwargs):
        return self.content.get_slide_content_prompt_zh(*args, **kwargs)
    
    def get_slide_content_prompt_en(self, *args, **kwargs):
        return self.content.get_slide_content_prompt_en(*args, **kwargs)
    
    def get_enhancement_prompt_zh(self, *args, **kwargs):
        return self.content.get_enhancement_prompt_zh(*args, **kwargs)
    
    def get_enhancement_prompt_en(self, *args, **kwargs):
        return self.content.get_enhancement_prompt_en(*args, **kwargs)
    
    def get_ppt_creation_context(self, *args, **kwargs):
        return self.content.get_ppt_creation_context(*args, **kwargs)
    
    def get_general_stage_prompt(self, *args, **kwargs):
        return self.content.get_general_stage_prompt(*args, **kwargs)
    
    def get_general_subtask_context(self, *args, **kwargs):
        return self.content.get_general_subtask_context(*args, **kwargs)

    def get_general_subtask_prompt(self, *args, **kwargs):
        return self.content.get_general_subtask_prompt(*args, **kwargs)
    
    # 设计相关提示词
    def get_style_gene_extraction_prompt(self, *args, **kwargs):
        return self.design.get_style_gene_extraction_prompt(*args, **kwargs)

    def get_project_design_guide_prompt(self, *args, **kwargs):
        return self.design.get_project_design_guide_prompt(*args, **kwargs)

    def get_slide_design_guide_prompt(self, *args, **kwargs):
        return self.design.get_slide_design_guide_prompt(*args, **kwargs)
    
    def get_creative_variation_prompt(self, *args, **kwargs):
        return self.design.get_creative_variation_prompt(*args, **kwargs)
    
    def get_content_driven_design_prompt(self, *args, **kwargs):
        return self.design.get_content_driven_design_prompt(*args, **kwargs)

    def get_style_genes_extraction_prompt(self, *args, **kwargs):
        return self.design.get_style_genes_extraction_prompt(*args, **kwargs)

    def get_combined_style_genes_and_guide_prompt(self, *args, **kwargs):
        return self.design.get_combined_style_genes_and_guide_prompt(*args, **kwargs)

    def get_global_visual_constitution_prompt(self, *args, **kwargs):
        return self.design.get_global_visual_constitution_prompt(*args, **kwargs)

    def get_page_creative_briefs_prompt(self, *args, **kwargs):
        return self.design.get_page_creative_briefs_prompt(*args, **kwargs)

    def get_page_plan_prompt(self, *args, **kwargs):
        return self.design.get_page_plan_prompt(*args, **kwargs)

    def get_creative_template_context_prompt(self, *args, **kwargs):
        return self.design.get_creative_template_context_prompt(*args, **kwargs)
    
    # 系统相关提示词
    def get_default_ppt_system_prompt(self, *args, **kwargs):
        return self.system.get_default_ppt_system_prompt(*args, **kwargs)
    
    def get_keynote_style_prompt(self, *args, **kwargs):
        return self.system.get_keynote_style_prompt(*args, **kwargs)
    
    def load_prompts_md_system_prompt(self, *args, **kwargs):
        return self.system.load_prompts_md_system_prompt(*args, **kwargs)
    
    def get_ai_assistant_system_prompt(self, *args, **kwargs):
        return self.system.get_ai_assistant_system_prompt(*args, **kwargs)
    
    def get_html_generation_system_prompt(self, *args, **kwargs):
        return self.system.get_html_generation_system_prompt(*args, **kwargs)
    
    def get_content_analysis_system_prompt(self, *args, **kwargs):
        return self.system.get_content_analysis_system_prompt(*args, **kwargs)

    def get_custom_style_prompt(self, *args, **kwargs):
        return self.system.get_custom_style_prompt(*args, **kwargs)
    
    # 修复相关提示词
    def get_repair_prompt(self, *args, **kwargs):
        return self.repair.get_repair_prompt(*args, **kwargs)
    
    def get_json_validation_prompt(self, *args, **kwargs):
        return self.repair.get_json_validation_prompt(*args, **kwargs)
    
    def get_content_validation_prompt(self, *args, **kwargs):
        return self.repair.get_content_validation_prompt(*args, **kwargs)
    
    def get_structure_repair_prompt(self, *args, **kwargs):
        return self.repair.get_structure_repair_prompt(*args, **kwargs)
    
    def get_quality_check_prompt(self, *args, **kwargs):
        return self.repair.get_quality_check_prompt(*args, **kwargs)
    
    def get_error_recovery_prompt(self, *args, **kwargs):
        return self.repair.get_error_recovery_prompt(*args, **kwargs)

    def get_single_slide_html_prompt(self, *args, **kwargs) -> str:
        """获取单页HTML生成提示词"""
        return self.design.get_single_slide_html_prompt(*args, **kwargs)

    def get_slide_context_prompt(self, slide_data: Dict[str, Any], page_number: int, total_pages: int) -> str:
        """获取幻灯片上下文提示词（特殊页面设计要求）"""
        return self.design.get_slide_context_prompt(slide_data, page_number, total_pages)


# 创建默认实例
prompts_manager = PPTPromptsManager()
