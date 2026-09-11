"""项目级 render_mode 的解析。

模式存在 ``project.project_metadata['render_mode']``，与 language 同级。运行时以
``confirmed_requirements['_render_mode']`` 传入生成链路：下划线键会被
``guidance_fingerprint`` 剔除，所以构图计划与创意指导的缓存在两种模式间共享，
这正是对照实验需要的控制变量。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

RENDER_MODE_HTML = "html"
RENDER_MODE_SVG = "svg"
RENDER_MODES = (RENDER_MODE_HTML, RENDER_MODE_SVG)
RENDER_MODE_METADATA_KEY = "render_mode"
RENDER_MODE_RUNTIME_KEY = "_render_mode"


def normalize_render_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in RENDER_MODES else RENDER_MODE_HTML


def resolve_project_render_mode(project: Any) -> str:
    metadata = getattr(project, "project_metadata", None)
    if isinstance(project, dict):
        metadata = project.get("project_metadata")
    if not isinstance(metadata, dict):
        return RENDER_MODE_HTML
    return normalize_render_mode(metadata.get(RENDER_MODE_METADATA_KEY))


def attach_render_mode(
    confirmed_requirements: Optional[Dict[str, Any]], project: Any
) -> str:
    mode = resolve_project_render_mode(project)
    if isinstance(confirmed_requirements, dict):
        confirmed_requirements[RENDER_MODE_RUNTIME_KEY] = mode
    return mode


def render_mode_from_requirements(
    confirmed_requirements: Optional[Dict[str, Any]],
) -> Optional[str]:
    """已注入则返回模式，否则 None，调用方再去项目元数据里取。"""
    if not isinstance(confirmed_requirements, dict):
        return None
    value = confirmed_requirements.get(RENDER_MODE_RUNTIME_KEY)
    return normalize_render_mode(value) if value is not None else None
