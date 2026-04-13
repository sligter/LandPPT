from __future__ import annotations

from typing import Any, Dict, List, Tuple


def should_force_file_outline_regeneration(confirmed_requirements: Dict[str, Any]) -> bool:
    return bool((confirmed_requirements or {}).get("force_file_outline_regeneration"))


def is_file_generated_outline(outline: Any) -> bool:
    if not isinstance(outline, dict) or not outline.get("slides"):
        return False
    metadata = outline.get("metadata", {})
    if not isinstance(metadata, dict):
        return False
    return bool(
        metadata.get("generated_with_summeryfile") or metadata.get("generated_with_file")
    )


def extract_saved_file_outline(
    project_outline: Any,
    confirmed_requirements: Dict[str, Any],
    *,
    ignore_saved_outline: bool = False,
) -> Dict[str, Any] | None:
    if ignore_saved_outline or should_force_file_outline_regeneration(confirmed_requirements):
        return None

    if is_file_generated_outline(project_outline):
        return project_outline

    saved_outline = (confirmed_requirements or {}).get("file_generated_outline")
    if isinstance(saved_outline, dict) and saved_outline.get("slides"):
        return saved_outline

    return None


def get_file_processing_mode(confirmed_requirements: Dict[str, Any]) -> str:
    mode = (confirmed_requirements or {}).get("file_processing_mode") or "markitdown"
    mode = str(mode).strip() if mode is not None else "markitdown"
    return mode or "markitdown"


def normalize_uploaded_files(uploaded_files: Any) -> List[Dict[str, str]]:
    if not uploaded_files:
        return []
    if not isinstance(uploaded_files, list):
        return []

    normalized: List[Dict[str, str]] = []
    for item in uploaded_files:
        if not isinstance(item, dict):
            continue
        file_path = item.get("file_path")
        if not file_path:
            continue
        filename = item.get("filename") or ""
        normalized.append({"file_path": str(file_path), "filename": str(filename)})
    return normalized


def prefer_uploaded_files_for_magic_pdf(confirmed_requirements: Dict[str, Any]) -> Tuple[bool, List[Dict[str, str]]]:
    """
    When the user selects magic_pdf (MinerU), prefer processing the original uploaded PDF(s)
    rather than feeding a pre-merged Markdown file back into the pipeline.
    """
    mode = get_file_processing_mode(confirmed_requirements)
    uploaded = normalize_uploaded_files((confirmed_requirements or {}).get("uploaded_files"))
    if mode != "magic_pdf" or not uploaded:
        return False, []
    return True, uploaded
