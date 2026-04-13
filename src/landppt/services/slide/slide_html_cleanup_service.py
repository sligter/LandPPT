import logging
import re
from typing import TYPE_CHECKING


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from .slide_html_service import SlideHtmlService


class SlideHtmlCleanupService:
    """HTML response cleanup extracted from SlideHtmlService."""

    def __init__(self, service: "SlideHtmlService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _clean_html_response(self, raw_content: str) -> str:
        """Clean and extract HTML content from AI responses."""
        raw_content = self._strip_think_tags(raw_content)

        if not raw_content:
            logger.warning("Received empty response from AI")
            return ""

        content = raw_content.strip()
        logger.debug("Raw AI response length: %s, preview: %s...", len(content), content[:200])
        content_lower = content.lower()

        if len(content) < 100:
            logger.warning("AI response is very short (%s chars), might be incomplete", len(content))
        has_error_indicators = any(
            error_indicator in content_lower for error_indicator in ["error", "sorry", "cannot", "unable"]
        )

        html_match = re.search(r"```html\s*\n(.*?)\n```", content, re.DOTALL | re.IGNORECASE)
        if html_match:
            logger.debug("Found HTML in markdown code block")
            return html_match.group(1).strip()

        generic_match = re.search(r"```\s*\n(.*?)\n```", content, re.DOTALL)
        if generic_match:
            potential_html = generic_match.group(1).strip()
            if potential_html.lower().startswith("<!doctype html") or potential_html.lower().startswith("<html"):
                logger.debug("Found HTML in generic code block")
                return potential_html

        prefixes_to_remove = [
            "这是生成的HTML代码：",
            "以下是HTML代码：",
            "HTML代码如下：",
            "生成的完整HTML页面：",
            "Here's the HTML code:",
            "The HTML code is:",
            "```html",
            "```",
        ]
        for prefix in prefixes_to_remove:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()

        if content.endswith("```"):
            content = content[:-3].strip()

        doctype_match = re.search(r"<!DOCTYPE html.*?</html>", content, re.DOTALL | re.IGNORECASE)
        if doctype_match:
            logger.debug("Found HTML using DOCTYPE pattern")
            return doctype_match.group(0)

        html_tag_match = re.search(r"<html.*?</html>", content, re.DOTALL | re.IGNORECASE)
        if html_tag_match:
            logger.debug("Found HTML using html tag pattern")
            return html_tag_match.group(0)

        html_lines = []
        in_html = False
        for line in content.split("\n"):
            line_stripped = line.strip()
            line_lower = line_stripped.lower()

            if not line_stripped or line_stripped.startswith("#") or line_stripped.startswith("//"):
                continue

            if line_lower.startswith("<!doctype") or line_lower.startswith("<html"):
                in_html = True
                html_lines.append(line)
                continue

            if in_html:
                html_lines.append(line)
                if line_lower.endswith("</html>"):
                    break

        if html_lines:
            logger.debug("Found HTML using line-by-line extraction")
            return "\n".join(html_lines)

        if "<" in content and ">" in content:
            logger.warning("Could not extract HTML using strict patterns, returning cleaned content")
            return content

        if has_error_indicators:
            logger.warning("AI response appears to be an error message instead of HTML")

        logger.error("Failed to extract HTML from AI response")
        return ""
