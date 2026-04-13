"""
PPT修复和验证相关提示词
包含所有用于修复和验证PPT数据的提示词模板
"""

from typing import Dict, Any, List


class RepairPrompts:
    """PPT修复和验证相关的提示词集合"""
    
    @staticmethod
    def get_repair_prompt(outline_data: Dict[str, Any], validation_errors: List[str], 
                         confirmed_requirements: Dict[str, Any]) -> str:
        """获取大纲修复提示词"""
        # 获取页数要求
        page_count_settings = confirmed_requirements.get('page_count_settings', {})
        page_count_mode = page_count_settings.get('mode', 'ai_decide')

        page_count_instruction = ""
        if page_count_mode == 'custom_range':
            min_pages = page_count_settings.get('min_pages', 8)
            max_pages = page_count_settings.get('max_pages', 15)
            page_count_instruction = f"- 页数要求：必须严格生成{min_pages}-{max_pages}页的PPT"
        elif page_count_mode == 'fixed':
            fixed_pages = page_count_settings.get('fixed_pages', 10)
            page_count_instruction = f"- 页数要求：必须生成恰好{fixed_pages}页的PPT"
        else:
            page_count_instruction = "- 页数要求：保持现有页数和内容，仅修复错误"

        errors_text = '\n'.join(["- " + str(error) for error in validation_errors])

        return f"""作为专业的PPT大纲修复助手，请修复以下PPT大纲JSON数据中的错误。

项目信息：
- 主题：{confirmed_requirements.get('topic', '未知')}
- 类型：{confirmed_requirements.get('type', '未知')}
- 重点内容：{', '.join(confirmed_requirements.get('focus_content', []))}
- 技术亮点：{', '.join(confirmed_requirements.get('tech_highlights', []))}
- 目标受众：{confirmed_requirements.get('target_audience', '通用受众')}
{page_count_instruction}

发现的错误：
{errors_text}

原始JSON数据：
```json
{outline_data}
```

修复要求：
1. 修复所有发现的错误
2. 确保JSON格式正确且完整
3. 保持原有内容
4. 严格遵守页数要求
5. 确保所有必需字段都存在且格式正确
6. 首尾页保持精简和聚焦，不要把普通内容页的要点密度直接套到这些页面

请输出修复后的完整JSON数据，使用```json```代码块包裹："""

    @staticmethod
    def get_json_validation_prompt(json_data: str, expected_structure: Dict[str, Any]) -> str:
        """获取JSON验证提示词"""
        return f"""作为数据验证专家，请验证以下JSON数据是否符合预期结构：

**待验证的JSON数据：**
```json
{json_data}
```

**预期结构：**
```json
{expected_structure}
```

请检查以下方面：
1. **JSON格式正确性**：语法是否正确，是否可以正常解析
2. **必需字段完整性**：所有必需字段是否存在
3. **数据类型匹配**：字段值类型是否符合预期
4. **数据有效性**：字段值是否在有效范围内
5. **结构一致性**：嵌套结构是否符合预期

如果发现问题，请提供：
- 具体的错误描述
- 错误位置定位
- 修复建议

如果数据正确，请确认验证通过。"""

    @staticmethod
    def get_content_validation_prompt(content: str, requirements: Dict[str, Any]) -> str:
        """获取内容验证提示词"""
        return f"""作为内容质量专家，请验证以下内容是否符合要求：

**待验证内容：**
{content}

**质量要求：**
{requirements}

请从以下维度进行验证：

1. **内容完整性**：
   - 是否包含所有必需的信息点
   - 内容是否完整表达了主题
   - 是否遗漏重要信息

2. **逻辑一致性**：
   - 内容逻辑是否清晰
   - 信息流是否连贯
   - 是否存在矛盾或冲突

3. **语言质量**：
   - 语言表达是否准确
   - 是否符合目标受众水平
   - 语言风格是否一致

4. **格式规范**：
   - 格式是否符合要求
   - 结构是否清晰
   - 标记是否正确

请提供详细的验证结果和改进建议。"""

    @staticmethod
    def get_structure_repair_prompt(data: Dict[str, Any], target_structure: Dict[str, Any]) -> str:
        """获取结构修复提示词"""
        return f"""作为数据结构专家，请将以下数据修复为目标结构：

**原始数据：**
```json
{data}
```

**目标结构：**
```json
{target_structure}
```

修复要求：
1. **保持数据完整性**：不丢失原有的有效信息
2. **结构标准化**：严格按照目标结构组织数据
3. **类型转换**：确保数据类型符合要求
4. **字段映射**：正确映射相似字段
5. **默认值填充**：为缺失的必需字段提供合理默认值

请输出修复后的完整数据结构。"""

    @staticmethod
    def get_quality_check_prompt(ppt_data: Dict[str, Any], quality_standards: Dict[str, Any]) -> str:
        """获取质量检查提示词"""
        return f"""作为PPT质量检查专家，请对以下PPT数据进行全面质量检查：

**PPT数据：**
```json
{ppt_data}
```

**质量标准：**
```json
{quality_standards}
```

请从以下维度进行检查：

1. **内容质量**：
   - 信息准确性和完整性
   - 逻辑结构和连贯性
   - 语言表达和专业性

2. **结构规范**：
   - 页面结构的合理性
   - 信息层级的清晰性
   - 导航逻辑的顺畅性

3. **设计一致性**：
   - 视觉风格的统一性
   - 色彩搭配的协调性
   - 字体使用的规范性

4. **用户体验**：
   - 信息传达的有效性
   - 交互体验的流畅性
   - 可访问性的考虑

5. **技术实现**：
   - 代码质量和规范性
   - 性能优化和兼容性
   - 错误处理和容错性

请提供详细的质量评估报告和改进建议。"""

    @staticmethod
    def get_error_recovery_prompt(error_info: str, context: Dict[str, Any]) -> str:
        """获取错误恢复提示词"""
        return f"""作为错误处理专家，请分析以下错误并提供恢复方案：

**错误信息：**
{error_info}

**上下文信息：**
```json
{context}
```

请提供：

1. **错误分析**：
   - 错误的根本原因
   - 错误的影响范围
   - 错误的严重程度

2. **恢复策略**：
   - 立即修复方案
   - 预防措施建议
   - 备用方案选择

3. **实施步骤**：
   - 具体的修复步骤
   - 验证方法
   - 回滚计划

请确保提供的方案安全可靠，不会造成数据丢失或系统不稳定。"""
