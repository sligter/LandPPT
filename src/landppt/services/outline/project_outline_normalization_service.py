import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...api.models import PPTProject
from ...ai.providers import strip_think_content
from ..audience_content import is_production_direction


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .project_outline_validation_service import ProjectOutlineValidationService


class ProjectOutlineNormalizationService:
    """统一处理大纲文本解析与结构标准化。"""

    _VALID_SLIDE_TYPES = {"title", "content", "agenda", "transition", "thankyou", "conclusion"}
    _SLIDE_TYPE_ALIASES = {
        "title": "title",
        "cover": "title",
        "intro": "title",
        "introduction": "title",
        "agenda": "agenda",
        "outline": "agenda",
        "catalog": "agenda",
        "directory": "agenda",
        "section": "agenda",
        "transition": "transition",
        "section_transition": "transition",
        "section_divider": "transition",
        "chapter_divider": "transition",
        "content": "content",
        "body": "content",
        "main": "content",
        "thankyou": "thankyou",
        "thanks": "thankyou",
        "thank_you": "thankyou",
        "end": "thankyou",
        "ending": "thankyou",
        "q&a": "thankyou",
        "qa": "thankyou",
        "conclusion": "conclusion",
        "summary": "conclusion",
        "closing": "conclusion",
        "final": "conclusion",
    }
    _TITLE_KEYWORDS = {
        "title": ("标题", "封面", "title", "cover"),
        "agenda": ("目录", "大纲", "agenda", "catalog", "outline", "directory"),
        "transition": ("过渡", "转场", "transition", "section divider", "chapter divider"),
        "thankyou": ("谢谢", "感谢", "致谢", "thank", "q&a", "qa"),
        "conclusion": ("总结", "结论", "收尾", "summary", "conclusion"),
    }
    _JSON_VALUE_ENDINGS = {",", "}", "]", ":"}

    def __init__(self, service: "ProjectOutlineValidationService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    @staticmethod
    def _strip_markdown_code_fence(content: str) -> str:
        """去掉包裹最外层的 Markdown 代码块。"""
        text = (content or "").strip()
        fenced_match = re.fullmatch(r"```(?:json|JSON)?\s*([\s\S]*?)\s*```", text)
        if fenced_match:
            return fenced_match.group(1).strip()
        return text

    @classmethod
    def _extract_balanced_json_blocks(cls, content: str) -> List[str]:
        """收集文本中所有括号平衡的 JSON 对象/数组（跳过嵌套在内部的）。"""
        text = (content or "").strip()
        blocks: List[str] = []
        index = 0
        while index < len(text):
            if text[index] not in "{[":
                index += 1
                continue
            candidate = cls._consume_balanced_json_block(text, index)
            if candidate:
                blocks.append(candidate)
                index += len(candidate)
            else:
                index += 1
        return blocks

    @classmethod
    def _extract_first_balanced_json_block(cls, content: str) -> Optional[str]:
        """提取最可能是大纲的括号平衡 JSON 块。

        以前直接返回第一个平衡块，于是模型回复里的引用标记（如 ``[1]``）会劫持
        解析：``json.loads("[1]")`` 成功后整份大纲被替换成一页标题为 "1" 的大纲。
        现在优先选择含 ``slides``/``title`` 字段的对象，其次选择最长的块。
        """
        blocks = cls._extract_balanced_json_blocks(content)
        if not blocks:
            return None

        outline_like = [
            block for block in blocks
            if block.startswith("{") and ('"slides"' in block or "'slides'" in block)
        ]
        if outline_like:
            return max(outline_like, key=len)

        objects = [block for block in blocks if block.startswith("{")]
        if objects:
            return max(objects, key=len)

        return max(blocks, key=len)

    @staticmethod
    def _consume_balanced_json_block(content: str, start_index: int) -> Optional[str]:
        """在忽略字符串内部括号的前提下，截取平衡 JSON 片段。"""
        opening_char = content[start_index]
        closing_char = "}" if opening_char == "{" else "]"
        stack = [closing_char]
        in_string = False
        escaped = False

        for current_index in range(start_index + 1, len(content)):
            char = content[current_index]

            if escaped:
                escaped = False
                continue

            if in_string:
                if char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue

            if char in "{[":
                stack.append("}" if char == "{" else "]")
                continue

            if char in "}]":
                if not stack or char != stack[-1]:
                    return None
                stack.pop()
                if not stack:
                    return content[start_index:current_index + 1]

        return None

    @classmethod
    def _find_next_significant_char(cls, content: str, start_index: int) -> Optional[str]:
        for char in content[start_index:]:
            if not char.isspace():
                return char
        return None

    @classmethod
    def _escape_inner_quotes_in_json_strings(cls, content: str) -> str:
        """修复字符串值内部未转义的双引号，例如 `" "少样本"场景"`。"""
        if not content:
            return content

        result: List[str] = []
        in_string = False
        escaped = False
        pending_inner_quote = False

        for index, char in enumerate(content):
            if escaped:
                result.append(char)
                escaped = False
                continue

            if not in_string:
                result.append(char)
                if char == '"':
                    in_string = True
                    pending_inner_quote = False
                continue

            if char == "\\":
                result.append(char)
                escaped = True
                continue

            if char != '"':
                result.append(char)
                continue

            next_significant = cls._find_next_significant_char(content, index + 1)
            should_close_string = (
                not pending_inner_quote
                and (
                    next_significant is None
                    or next_significant in cls._JSON_VALUE_ENDINGS
                )
            )

            if should_close_string:
                result.append(char)
                in_string = False
                pending_inner_quote = False
                continue

            result.append('\\"')
            pending_inner_quote = not pending_inner_quote

        return "".join(result)

    @classmethod
    def _repair_json_candidate(cls, content: str) -> str:
        """修复常见的轻微 JSON 污损，避免直接退回兜底流程。"""
        text = (content or "").strip().lstrip("\ufeff")
        text = text.replace("“", '"').replace("”", '"')
        text = text.replace("‘", "'").replace("’", "'")
        text = re.sub(r",(?=\s*[}\]])", "", text)
        return cls._escape_inner_quotes_in_json_strings(text)

    @classmethod
    def _iter_json_candidates(cls, content: str) -> List[str]:
        """按可信度输出待解析候选串，优先复用原始结构。"""
        text = (content or "").strip()
        stripped_fence = cls._strip_markdown_code_fence(text)
        extracted_from_raw = cls._extract_first_balanced_json_block(text)
        extracted_from_stripped = cls._extract_first_balanced_json_block(stripped_fence)

        candidates: List[str] = []
        for candidate in [text, stripped_fence, extracted_from_raw, extracted_from_stripped]:
            candidate = (candidate or "").strip()
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        return candidates

    @classmethod
    def _parse_json_like_outline(cls, content: str) -> Optional[Any]:
        """尝试把文本解析成 JSON/JSON-like 结构。"""
        for candidate in cls._iter_json_candidates(content):
            for payload in [candidate, cls._repair_json_candidate(candidate)]:
                try:
                    return json.loads(payload)
                except json.JSONDecodeError:
                    continue
        return None

    @classmethod
    def _normalize_page_number(cls, raw_value: Any, fallback_value: int) -> int:
        try:
            parsed = int(str(raw_value).strip())
            return parsed if parsed > 0 else fallback_value
        except (TypeError, ValueError):
            return fallback_value

    @staticmethod
    def _flatten_text_values(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (list, tuple, set)):
            result: List[str] = []
            for item in value:
                result.extend(ProjectOutlineNormalizationService._flatten_text_values(item))
            return result
        return [str(value)]

    @classmethod
    def _coerce_content_points(cls, slide: Dict[str, Any]) -> List[str]:
        """兼容不同字段名并转成标准要点数组。"""
        raw_points = (
            slide.get("content_points")
            if slide.get("content_points") is not None
            else slide.get("bullet_points")
        )
        if raw_points is None:
            raw_points = slide.get("points")
        if raw_points is None:
            raw_points = slide.get("key_points")
        if raw_points is None:
            raw_points = slide.get("outline_points")
        if raw_points is None:
            raw_points = slide.get("content")
        if raw_points is None:
            raw_points = slide.get("description")

        points: List[str] = []
        for raw_text in cls._flatten_text_values(raw_points):
            for line in re.split(r"\r?\n+", raw_text):
                text = line.strip()
                if not text:
                    continue
                text = re.sub(r"^[\-\*\u2022]+\s*", "", text)
                text = re.sub(r"^\d+[\.\)]\s*", "", text)
                if text:
                    points.append(text)
        return points

    @classmethod
    def _normalize_content_points_for_slide(
        cls,
        content_points: List[str],
        slide_type: str,
        page_number: int,
        total_slides: int,
        slide_title: str,
        description: str = "",
    ) -> List[str]:
        """清洗并补齐最小可用要点，避免后续结构校验被空数组卡住。"""
        cleaned_points = []
        for point in content_points or []:
            text = str(point).strip()
            if text:
                cleaned_points.append(text)

        if cleaned_points:
            return cleaned_points

        if description.strip():
            return [description.strip()]

        if slide_type == "title":
            return [slide_title.strip() or "演示主题"]
        if slide_type == "agenda":
            return ["本页为章节导航"]
        if slide_type == "transition":
            return [slide_title.strip() or "章节过渡"]
        if slide_type in {"thankyou", "conclusion"} or page_number == total_slides:
            return [slide_title.strip() or "总结与结束"]
        return [slide_title.strip() or "内容要点"]

    @classmethod
    def _normalize_slide_type(
        cls,
        raw_slide_type: Any,
        title_text: str,
        page_number: int,
        total_slides: int,
    ) -> str:
        normalized_raw_type = str(raw_slide_type or "").strip().lower().replace(" ", "_")
        normalized_raw_type = cls._SLIDE_TYPE_ALIASES.get(normalized_raw_type, normalized_raw_type)
        if normalized_raw_type in cls._VALID_SLIDE_TYPES:
            return normalized_raw_type

        title_lower = (title_text or "").strip().lower()
        for slide_type, keywords in cls._TITLE_KEYWORDS.items():
            if not cls._title_matches_keywords(title_lower, keywords):
                continue
            # These types are structurally positional. Without the position check a
            # mid-deck content page titled "QA体系与测试流程" became a thankyou page
            # and "Test Coverage Report" became the cover.
            if not cls._position_allows_slide_type(slide_type, page_number, total_slides):
                continue
            return slide_type

        if page_number == 1:
            return "title"
        if page_number == total_slides and cls._title_matches_keywords(
            title_lower, ("thanks", "thank", "q&a", "qa")
        ):
            return "thankyou"
        return "content"

    @staticmethod
    def _title_matches_keywords(title_lower: str, keywords: tuple) -> bool:
        """Match keywords as whole words for Latin text, as substrings for CJK.

        Plain substring matching made "coverage" match "cover" and "qa体系" match
        "qa". CJK has no word boundaries, so those keywords stay substring matches.
        """
        if not title_lower:
            return False
        for keyword in keywords:
            if keyword.isascii():
                if re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", title_lower):
                    return True
            elif keyword in title_lower:
                return True
        return False

    @staticmethod
    def _position_allows_slide_type(slide_type: str, page_number: int, total_slides: int) -> bool:
        """Whether a positional slide type is plausible at this page number."""
        if slide_type == "title":
            return page_number == 1
        if slide_type == "agenda":
            return page_number <= 3
        if slide_type in ("thankyou", "conclusion"):
            # Allow the closing stretch, not an arbitrary mid-deck page.
            return total_slides <= 2 or page_number >= max(total_slides - 2, 2)
        # 'transition' can legitimately appear anywhere.
        return True

    @classmethod
    def _normalize_outline_root(cls, outline_data: Any) -> Dict[str, Any]:
        """兼容数组、嵌套 outline、pages 等多种根结构。"""
        if isinstance(outline_data, list):
            return {"slides": outline_data}

        if not isinstance(outline_data, dict):
            raise ValueError("大纲数据必须是对象或数组")

        root = dict(outline_data)
        nested_outline = root.get("outline")
        if isinstance(nested_outline, dict):
            merged = dict(nested_outline)
            for key, value in root.items():
                if key == "outline":
                    continue
                merged.setdefault(key, value)
            root = merged

        if "slides" not in root:
            if isinstance(root.get("pages"), list):
                root["slides"] = root["pages"]
            elif isinstance(root.get("sections"), list):
                root["slides"] = root["sections"]

        return root

    def _parse_text_outline_to_slides(self, content: str, project: PPTProject) -> List[Dict[str, Any]]:
        """仅在明确是文本大纲时才做按行解析，不再伪造默认页。"""
        lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
        if not lines:
            return []

        slides: List[Dict[str, Any]] = []
        current_slide: Optional[Dict[str, Any]] = None

        def flush_current_slide():
            if current_slide:
                slides.append(current_slide.copy())

        for raw_line in lines:
            is_slide_heading = (
                raw_line.startswith("#")
                or re.match(r"^第\s*\d+\s*[页章节]\s*[:：\-]?\s*", raw_line)
                or re.match(r"^page\s*\d+\s*[:：\-]?\s*", raw_line, flags=re.IGNORECASE)
                or re.match(r"^\d+[\.\)]\s+\S+", raw_line)
            )

            if is_slide_heading:
                flush_current_slide()
                title = re.sub(r"^#+\s*", "", raw_line)
                title = re.sub(r"^第\s*\d+\s*[页章节]\s*[:：\-]?\s*", "", title)
                title = re.sub(r"^page\s*\d+\s*[:：\-]?\s*", "", title, flags=re.IGNORECASE)
                title = re.sub(r"^\d+[\.\)]\s*", "", title)
                current_slide = {
                    "page_number": len(slides) + 1,
                    "title": title.strip() or f"第{len(slides) + 1}页",
                    "content_points": [],
                    "slide_type": "content",
                }
                continue

            if current_slide is None:
                continue

            point = re.sub(r"^[\-\*\u2022]+\s*", "", raw_line)
            point = re.sub(r"^\d+[\.\)]\s*", "", point)
            point = point.strip()
            if point:
                current_slide["content_points"].append(point)

        flush_current_slide()

        if not slides:
            return []

        return self._standardize_outline_format(
            {
                "title": getattr(project, "topic", "") or "PPT大纲",
                "slides": slides,
            }
        )["slides"]

    def _parse_outline_content(self, content: str, project: PPTProject) -> Dict[str, Any]:
        """从文本中解析大纲，不再退回默认三页兜底。"""
        content = strip_think_content(content)
        parsed_outline = self._parse_json_like_outline(content)
        if parsed_outline is not None:
            standardized_data = self._standardize_outline_format(parsed_outline)
            logger.info(
                "成功解析结构化大纲，共 %s 页",
                len(standardized_data.get("slides", [])),
            )
            return standardized_data

        slides = self._parse_text_outline_to_slides(content, project)
        if slides:
            logger.info("成功按文本大纲解析，共 %s 页", len(slides))
            return {
                "title": getattr(project, "topic", "") or "PPT大纲",
                "slides": slides,
                "metadata": {},
            }

        raise ValueError("无法从输入内容中解析出有效的大纲结构")

    def _standardize_outline_format(self, outline_data: Dict[str, Any]) -> Dict[str, Any]:
        """标准化大纲结构，统一字段名与幻灯片类型。"""
        root = self._normalize_outline_root(outline_data)

        title = str(
            root.get("title")
            or root.get("topic")
            or root.get("name")
            or root.get("project_title")
            or "PPT大纲"
        ).strip() or "PPT大纲"

        slides_data = root.get("slides", [])
        if not isinstance(slides_data, list):
            raise ValueError("slides 字段必须是数组")
        if not slides_data:
            raise ValueError("slides 不能为空")

        metadata = root.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        standardized_slides: List[Dict[str, Any]] = []
        total_slides = len(slides_data)

        for index, slide in enumerate(slides_data, start=1):
            if not isinstance(slide, dict):
                slide = {"title": str(slide)}

            title_text = str(
                slide.get("title")
                or slide.get("page_title")
                or slide.get("name")
                or slide.get("heading")
                or f"第{index}页"
            ).strip() or f"第{index}页"

            description = str(slide.get("description") or "").strip()
            production_notes = slide.get("production_notes")
            if not isinstance(production_notes, str):
                production_notes = ""
            source_points = self._coerce_content_points(slide)
            description_is_direction = is_production_direction(description)
            if description_is_direction:
                production_notes = "\n".join(dict.fromkeys(filter(None, (production_notes, description))))
                description = ""
            page_number = self._normalize_page_number(slide.get("page_number"), index)
            slide_type = self._normalize_slide_type(
                slide.get("slide_type", slide.get("type")),
                title_text,
                page_number,
                total_slides,
            )
            content_points = self._normalize_content_points_for_slide(
                content_points=source_points,
                slide_type=slide_type,
                page_number=page_number,
                total_slides=total_slides,
                slide_title=title_text,
                description=description,
            )

            standardized_slide = {
                "page_number": index,
                "title": title_text,
                "content_points": [] if description_is_direction and not source_points else content_points,
                "slide_type": slide_type,
                "type": slide_type,
                "description": description,
            }

            if production_notes.strip():
                standardized_slide["production_notes"] = production_notes.strip()
            if slide.get("chart_config"):
                standardized_slide["chart_config"] = slide["chart_config"]
            # Fast-mode outlines name the package layout chosen for the page.
            layout = slide.get("layout")
            if isinstance(layout, str) and layout.strip():
                standardized_slide["layout"] = layout.strip()[:100]

            standardized_slides.append(standardized_slide)

        standardized_outline = {
            "title": title,
            "slides": standardized_slides,
            "metadata": metadata,
        }
        logger.info("大纲标准化完成：%s，共 %s 页", title, len(standardized_slides))
        return standardized_outline

    def _create_default_slides_from_content(self, content: str, project: PPTProject) -> List[Dict[str, Any]]:
        """保留旧接口名，但不再伪造默认页，只解析显式文本大纲。"""
        return self._parse_text_outline_to_slides(content, project)
