"""
JSON解析工具 - 处理LLM返回的JSON响应
"""

import json
import re
import ast
from typing import Dict, Any, Optional, Iterable, Tuple
import logging

logger = logging.getLogger(__name__)


class JSONParser:
    """JSON解析器，用于处理LLM返回的各种格式的JSON响应"""
    
    @staticmethod
    def extract_json_from_response(response: Any) -> Dict[str, Any]:
        """
        从LLM响应中提取JSON
        
        Args:
            response: LLM的原始响应文本
            
        Returns:
            解析后的JSON字典，如果解析失败则返回默认结构
        """
        if response is None:
            logger.warning("收到空响应，返回默认JSON结构")
            return JSONParser._get_default_structure()

        if isinstance(response, dict):
            return response

        # 兼容部分LangChain消息对象
        if hasattr(response, "content") and isinstance(getattr(response, "content"), str):
            response = getattr(response, "content")

        if not isinstance(response, str):
            response = str(response)

        if not response.strip():
            logger.warning("收到空响应，返回默认JSON结构")
            return JSONParser._get_default_structure()

        response = response.strip()

        candidates: list[str] = [response]

        # 提取所有代码块内容（优先JSON代码块，但也兼容无语言标注）
        for code_block in JSONParser._extract_fenced_code_blocks(response):
            candidates.append(code_block)

        cleaned_response = JSONParser._clean_response(response)
        if cleaned_response:
            candidates.append(cleaned_response)

        # 从任意文本中提取可能的JSON片段（基于括号配对，避免正则贪婪匹配）
        candidates.extend(JSONParser._extract_json_candidates(response))

        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)

            parsed = JSONParser._loads_best_effort(candidate)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
                # 兼容部分模型只返回slides数组的情况
                return {
                    "title": "PPT大纲",
                    "total_pages": len(parsed),
                    "page_count_mode": "estimated",
                    "slides": parsed,
                }

        logger.warning(
            "所有JSON解析方法都失败，响应内容(截断): %s",
            JSONParser._truncate_for_log(response),
        )
        return JSONParser._get_default_structure()

    @staticmethod
    def _truncate_for_log(text: str, limit: int = 1200) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "…(truncated)"

    @staticmethod
    def _extract_fenced_code_blocks(text: str) -> Iterable[str]:
        # ```json ... ``` 或 ``` ... ```，可能存在多个块
        for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE):
            block = match.group(1).strip()
            # 兼容 ```\njson\n{...}\n``` 这种变体
            block = re.sub(r"^\s*json\s*\n", "", block, flags=re.IGNORECASE)
            if block:
                yield block

    @staticmethod
    def _extract_json_candidates(text: str, max_candidates: int = 20) -> list[str]:
        candidates: list[str] = []
        starts = [m.start() for m in re.finditer(r"[\{\[]", text)]
        for start in starts[:max_candidates]:
            extracted, missing_closers = JSONParser._extract_balanced_json(text, start)
            if extracted:
                candidates.append(extracted)
                if missing_closers:
                    candidates.append(extracted + missing_closers)
        return candidates

    @staticmethod
    def _extract_balanced_json(text: str, start: int) -> Tuple[Optional[str], str]:
        opener = text[start]
        if opener not in "{[":
            return None, ""

        stack = [opener]
        in_string = False
        string_quote = ""
        escape = False

        for idx in range(start + 1, len(text)):
            ch = text[idx]

            if escape:
                escape = False
                continue

            if in_string:
                if ch == "\\":
                    escape = True
                elif ch == string_quote:
                    in_string = False
                    string_quote = ""
                continue

            if ch in ("\"", "'"):
                in_string = True
                string_quote = ch
                continue

            if ch in "{[":
                stack.append(ch)
                continue

            if ch in "}]":
                if not stack:
                    return None, ""
                expected = "}" if stack[-1] == "{" else "]"
                if ch != expected:
                    return None, ""
                stack.pop()
                if not stack:
                    return text[start : idx + 1], ""

        # 未闭合：尝试补全闭合括号（仅当截断发生在结构尾部时有机会成功）
        missing = "".join("}" if s == "{" else "]" for s in reversed(stack))
        return text[start:], missing

    @staticmethod
    def _loads_best_effort(text: str) -> Any:
        # 1) 严格JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2) 常见清理/修复后再尝试
        normalized = JSONParser._normalize_json_text(text)
        if normalized and normalized != text:
            try:
                return json.loads(normalized)
            except json.JSONDecodeError:
                pass

        # 3) Python字面量兜底（处理单引号、尾逗号等），依然只解析字面量，避免执行
        py_literal = JSONParser._to_python_literal(normalized or text)
        if py_literal:
            try:
                return ast.literal_eval(py_literal)
            except (ValueError, SyntaxError):
                pass

        return None

    @staticmethod
    def _normalize_json_text(text: str) -> str:
        s = text.strip().lstrip("\ufeff")

        # 移除常见前缀
        s = re.sub(r"^\s*(?:Here's the JSON:|Here is the JSON:|JSON:|Result:|Output:|Response:)\s*", "", s, flags=re.IGNORECASE)

        # 去掉包裹整个文本的Markdown代码块（防止模型输出不规范导致提取失败）
        s = re.sub(r"^\s*```(?:json)?\s*\n", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\n\s*```\s*$", "", s)

        # 统一常见的智能引号
        s = s.replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")

        # 移除JSON里常见的注释（仅做简单处理，复杂情况交给括号提取候选）
        s = JSONParser._remove_json_comments(s)

        # 去掉结尾多余的分号
        s = re.sub(r";\s*$", "", s)

        # 移除尾逗号：{"a":1,} / [1,2,]
        s = re.sub(r",\s*([}\]])", r"\1", s)

        # 处理模型常见的省略号占位符（如数组中出现未加引号的 ...）
        s = re.sub(r"(?:(?<=\[)|(?<=,))\s*\.\.\.\s*(?=,|\])", " null ", s)

        return s.strip()

    @staticmethod
    def _remove_json_comments(text: str) -> str:
        result_chars: list[str] = []
        in_string = False
        string_quote = ""
        escape = False
        i = 0

        while i < len(text):
            ch = text[i]

            if escape:
                result_chars.append(ch)
                escape = False
                i += 1
                continue

            if in_string:
                result_chars.append(ch)
                if ch == "\\":
                    escape = True
                elif ch == string_quote:
                    in_string = False
                    string_quote = ""
                i += 1
                continue

            if ch in ("\"", "'"):
                in_string = True
                string_quote = ch
                result_chars.append(ch)
                i += 1
                continue

            # // line comment
            if ch == "/" and i + 1 < len(text) and text[i + 1] == "/":
                i += 2
                while i < len(text) and text[i] not in "\r\n":
                    i += 1
                continue

            # /* block comment */
            if ch == "/" and i + 1 < len(text) and text[i + 1] == "*":
                i += 2
                while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2 if i + 1 < len(text) else 0
                continue

            result_chars.append(ch)
            i += 1

        return "".join(result_chars)

    @staticmethod
    def _to_python_literal(text: str) -> str:
        """
        将可能的“类JSON”文本转换为更容易被ast.literal_eval处理的形式：
        - 将 true/false/null 转为 True/False/None（仅做简单的词边界替换）
        """
        s = text.strip()
        if not s:
            return s
        s = re.sub(r"\btrue\b", "True", s, flags=re.IGNORECASE)
        s = re.sub(r"\bfalse\b", "False", s, flags=re.IGNORECASE)
        s = re.sub(r"\bnull\b", "None", s, flags=re.IGNORECASE)
        return s
    
    @staticmethod
    def _clean_response(response: str) -> Optional[str]:
        """
        清理响应文本，尝试提取可能的JSON内容
        
        Args:
            response: 原始响应文本
            
        Returns:
            清理后的文本，如果无法清理则返回None
        """
        # 移除常见的非JSON前缀和后缀
        prefixes_to_remove = [
            "Here's the JSON:",
            "Here is the JSON:",
            "JSON:",
            "Result:",
            "Output:",
            "Response:",
        ]
        
        cleaned = response.strip()
        
        for prefix in prefixes_to_remove:
            if cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix):].strip()
        
        # 移除可能的Markdown格式
        cleaned = re.sub(r'^```.*?\n', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\n```$', '', cleaned, flags=re.MULTILINE)
        
        # 查找第一个 { 和最后一个 }
        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')
        
        if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
            return cleaned[first_brace:last_brace + 1]
        
        return None
    
    @staticmethod
    def _get_default_structure() -> Dict[str, Any]:
        """
        返回默认的JSON结构
        
        Returns:
            默认的PPT大纲结构
        """
        return {
            "title": "PPT大纲",
            "total_pages": 10,
            "page_count_mode": "estimated",
            "slides": [
                {
                    "page_number": 1,
                    "title": "标题页",
                    "content_points": ["演示标题", "演示者信息", "日期"],
                    "slide_type": "title",
                    "description": "PPT的开场标题页"
                }
            ]
        }
    
    @staticmethod
    def validate_ppt_structure(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证并修复PPT结构
        
        Args:
            data: 待验证的PPT数据
            
        Returns:
            验证并修复后的PPT数据
        """
        # 确保必需字段存在
        if "title" not in data:
            data["title"] = "PPT大纲"
        
        if "slides" not in data or not isinstance(data["slides"], list):
            data["slides"] = []
        
        if "total_pages" not in data:
            data["total_pages"] = len(data["slides"])
        
        if "page_count_mode" not in data:
            data["page_count_mode"] = "final"
        
        # 验证和修复每个幻灯片
        valid_slides = []
        for i, slide in enumerate(data["slides"]):
            if not isinstance(slide, dict):
                continue
            
            # 确保幻灯片必需字段
            slide.setdefault("page_number", i + 1)
            slide.setdefault("title", f"幻灯片 {i + 1}")
            slide.setdefault("content_points", [])
            slide.setdefault("slide_type", "content")
            slide.setdefault("description", "")
            
            # 验证slide_type
            if slide["slide_type"] not in ["title", "content", "conclusion"]:
                slide["slide_type"] = "content"
            
            # 确保content_points是列表
            if not isinstance(slide["content_points"], list):
                slide["content_points"] = []
            
            valid_slides.append(slide)
        
        data["slides"] = valid_slides
        data["total_pages"] = len(valid_slides)
        
        return data
