import ast
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from landppt.services.outline.project_outline_normalization_service import (
    ProjectOutlineNormalizationService,
)


ROOT = Path(__file__).resolve().parents[1]


SAMPLE_OUTLINE = '''```json
{
  "title": "少样本过拟合：挑战与应对策略",
  "slides": [
    {
      "page_number": 1,
      "title": "少样本过拟合",
      "content_points": [
        "技术团队内部培训",
        "主讲人：[姓名]",
        "日期：2026-04-05"
      ],
      "slide_type": "title"
    },
    {
      "page_number": 2,
      "title": "目录",
      "content_points": [
        "过拟合问题定义与背景",
        " "少样本"场景的特殊性",
        "过拟合的根源分析",
        "核心缓解策略与实践",
        "案例分析与代码实现",
        "总结与讨论"
      ],
      "slide_type": "agenda"
    },
    {
      "page_number": 3,
      "title": "过拟合问题回顾",
      "content_points": [
        "定义：模型在训练集表现优异，但在测试集/新数据上泛化能力差",
        "本质：模型学习了数据中的噪声或特定样本特征，而非普遍规律",
        "表现：训练Loss持续下降，验证Loss先降后升（U型曲线）",
        "传统解决思路：增加数据量、正则化、Dropout、Early Stopping"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 4,
      "title": "少样本学习 (FSL) 的困境",
      "content_points": [
        "场景：类别样本极少（如每类仅1-5个样本），常见于医疗、工业缺陷检测",
        "矛盾：数据量不足以支撑复杂模型训练，极易陷入过拟合陷阱",
        "挑战：模型参数量远大于样本数量，缺乏统计显著性",
        "影响：微调阶段稍微不慎，模型性能即断崖式下跌"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 5,
      "title": "少样本过拟合的根源分析",
      "content_points": [
        "样本多样性不足：有限样本无法覆盖类内方差",
        "模型复杂度过高：参数空间大，模型倾向于“记忆”而非“理解”",
        "特征提取器偏差：基类训练得到的特征可能不适应新类",
        "任务定义偏差：Support Set与Query Set分布不一致"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 6,
      "title": "策略一：数据增强与合成",
      "content_points": [
        "传统增强：旋转、裁剪、颜色变换（效果有限）",
        "高级增强：Mixup、CutMix、CutOut（增加决策边界的平滑性）",
        "生成式方法：利用GAN或Diffusion模型生成逼真伪样本扩充Support Set",
        "特征空间增强：在特征层添加噪声或进行插值"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 7,
      "title": "策略二：模型架构与度量学习",
      "content_points": [
        "参数高效微调 (PEFT)：冻结Backbone，仅训练分类头或使用Adapter/LoRA",
        "度量学习：孪生网络、原型网络，将分类问题转化为距离度量问题",
        "图神经网络 (GNN)：利用样本间关系构建图结构进行传播",
        "注意力机制：引入自注意力机制增强特征表达"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 8,
      "title": "策略三：正则化与优化技巧",
      "content_points": [
        "强正则化：大幅提高Weight Decay系数，限制权重幅度",
        "Transductive Inference：利用未标注的Query Set信息辅助推理",
        "Meta-Regularization：在元学习阶段引入正则项，学习如何避免过拟合",
        "减少训练轮次：少样本场景下往往只需极少的Epoch即可收敛"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 9,
      "title": "技术实践：代码级建议",
      "content_points": [
        "冻结BatchNorm层：防止少量样本导致的统计量偏移",
        "使用更大的Batch Size（配合Gradient Accumulation）",
        "学习率调整：采用更小的学习率或Cosine Annealing",
        "交叉验证：使用Leave-One-Out策略最大化验证可靠性"
      ],
      "slide_type": "content"
    },
    {
      "page_number": 10,
      "title": "总结与下一步行动",
      "content_points": [
        "核心观点：少样本过拟合是数据稀缺与模型复杂度的博弈",
        "关键策略：数据增强 + 度量学习/PEFT + 强正则化",
        "建议：优先尝试冻结Backbone和原型网络，再考虑复杂微调",
        "后续计划：团队内部复现基准测试，建立少样本任务开发规范"
      ],
      "slide_type": "conclusion"
    },
    {
      "page_number": 11,
      "title": "Q&A",
      "content_points": [
        "感谢聆听",
        "欢迎提问与讨论"
      ],
      "slide_type": "thankyou"
    }
  ]
}
```'''


def _load_class_method(relative_path: str, class_name: str, method_name: str):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    method_node = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )
    module = ast.Module(body=[method_node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "time": time,
        "logger": logging.getLogger("test-outline-normalization"),
    }
    exec(compile(module, relative_path, "exec"), namespace)
    return namespace[method_name]


def test_parse_outline_content_supports_fenced_json_with_inner_quotes():
    service = ProjectOutlineNormalizationService(SimpleNamespace())
    project = SimpleNamespace(topic="少样本过拟合：挑战与应对策略")

    outline = service._parse_outline_content(SAMPLE_OUTLINE, project)

    assert outline["title"] == "少样本过拟合：挑战与应对策略"
    assert len(outline["slides"]) == 11
    assert outline["slides"][1]["slide_type"] == "agenda"
    assert outline["slides"][1]["content_points"][1] == '"少样本"场景的特殊性'
    assert outline["slides"][-1]["slide_type"] == "thankyou"


def test_parse_outline_content_no_longer_fabricates_default_slides():
    service = ProjectOutlineNormalizationService(SimpleNamespace())
    project = SimpleNamespace(topic="测试主题")

    with pytest.raises(ValueError):
        service._parse_outline_content("这是一段没有结构的大纲文本", project)


@pytest.mark.asyncio
async def test_update_project_outline_uses_normalized_parser():
    update_project_outline = _load_class_method(
        "src/landppt/services/project_workflow_stage_service.py",
        "ProjectWorkflowStageService",
        "update_project_outline",
    )

    project = SimpleNamespace(
        topic="少样本过拟合：挑战与应对策略",
        outline={},
        todo_board=None,
    )

    class _FakeProjectManager:
        async def get_project(self, project_id):
            assert project_id == "project-1"
            return project

    normalizer = ProjectOutlineNormalizationService(SimpleNamespace())
    service = SimpleNamespace(
        project_manager=_FakeProjectManager(),
        _parse_outline_content=normalizer._parse_outline_content,
    )

    success = await update_project_outline(service, "project-1", SAMPLE_OUTLINE)

    assert success is True
    assert project.outline["title"] == "少样本过拟合：挑战与应对策略"
    assert len(project.outline["slides"]) == 11
    assert project.outline["slides"][1]["slide_type"] == "agenda"
