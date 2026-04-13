from .chains import ChainManager

# 这里不导入 PPTOutlineGenerator，避免引入 langgraph 相关依赖问题。
# 需要时请直接使用：
# from summeryanyfile.generators.ppt_generator import PPTOutlineGenerator

__all__ = [
    "ChainManager",
]