"""制作备注与观众可读文案共用的字段约定。"""

import re
from html.parser import HTMLParser
from typing import Any, Mapping

OUTLINE_COPY_RULE = (
    "标题、content_points 和 description 直接给观众读。写主题相关的事实、机制、案例或结论，"
    "把‘本页要解释什么’直接写成解释。description 只放必要的正文补充，信息已在要点中时留空。"
    "制作步骤、调研或写作过程、排版和绘图指令只可放在可选的 production_notes，"
    "不得写进标题、要点或正文。保留对事实可靠性有实质影响的来源、限制及不确定性。"
)
OUTLINE_COPY_RULE_EN = (
    "Write titles, content_points and description as audience-facing copy: state the facts, "
    "mechanisms, examples or conclusions directly. Leave description empty if it adds nothing. "
    "Put research, writing and layout instructions only in optional production_notes. "
    "Keep source attribution and caveats that change the meaning of the content."
)

_PRODUCTION_PREFIX = re.compile(
    r"^(?:(?:制作|设计|分镜|画面|排版|构图|写作)(?:说明|要求|指令|计划|思路)\s*[:：]"
    r"|阅读(?:框架|约定)\s*[:：]"
    r"|(?:封面与背景页|目录导航页|标题页|内容页|结论页)\s*[,，:：]"
    r"|(?:本页|首屏|本镜头)\s*(?:将|应|可)?\s*(?:同时呈现|采用|展示|呈现|绘制)"
    r"|(?:上方|下方|左侧|右侧|底部)(?:突出|呈现|绘制|展示|摆放|留出|用一行)"
    r"|(?:采用|主图采用).{0,16}(?:机制图|流程图|构图|分栏|排版)"
    r"|架构页(?:应|要|建议)(?:按|用|画|突出)"
    r"|(?:production|layout|design|storyboard)\s+(?:notes?|instructions?|directions?)\s*:"
    r"|<think>)",
    re.IGNORECASE,
)


def is_production_direction(text: str) -> bool:
    return bool(_PRODUCTION_PREFIX.match(text.lstrip(" \t\r\n*#>-•")))


def audience_slide_copy(slide: Mapping[str, Any]) -> dict[str, Any]:
    copy = {}
    for field in ("title", "subtitle", "content", "description"):
        value = slide.get(field)
        if isinstance(value, str) and value.strip() and not is_production_direction(value):
            copy[field] = value
    points = slide.get("content_points") or slide.get("bullet_points")
    if isinstance(points, list):
        copy["content_points"] = [
            point for point in points
            if isinstance(point, str) and point.strip() and not is_production_direction(point)
        ]
    return copy


class _SlideTextParser(HTMLParser):
    _NON_VISIBLE = {"head", "script", "style", "template", "noscript", "title", "desc"}
    _BLOCKS = {"main", "section", "div", "p", "li", "br", "text", "td", "th", *(f"h{i}" for i in range(1, 7))}

    def __init__(self) -> None:
        super().__init__()
        self.hidden: list[str] = []
        self.fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._NON_VISIBLE:
            self.hidden.append(tag)
        elif not self.hidden and tag in self._BLOCKS:
            self.fragments.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
        elif tag in self._BLOCKS:
            self.fragments.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.fragments.append(data)


def slide_text_blocks(html: str) -> list[str]:
    parser = _SlideTextParser()
    parser.feed(html)
    parser.close()
    return [line.strip() for line in "".join(parser.fragments).splitlines() if line.strip()]
