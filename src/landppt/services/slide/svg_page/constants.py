"""画布契约常量。提示词、清洗器与几何检查器共用同一份数字。"""

from __future__ import annotations

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 720

#: 安全区：x 48–1232，y 40–680。
SAFE_LEFT = 48
SAFE_TOP = 40
SAFE_RIGHT = 1232
SAFE_BOTTOM = 680

ROLE_ATTR = "data-role"
ROLE_BACKGROUND = "background"
ROLE_TITLE = "title"
ROLE_STAGE = "stage"
ROLE_FOOTER = "footer"
ROLES = (ROLE_BACKGROUND, ROLE_TITLE, ROLE_STAGE, ROLE_FOOTER)

#: 文本框约定：模型只声明可用宽高，服务端负责分行与缩字。
BOX_WIDTH_ATTR = "data-box-w"
BOX_HEIGHT_ATTR = "data-box-h"
MAX_LINES_ATTR = "data-max-lines"
LINES_ATTR = "data-lines"

LINE_HEIGHT = 1.4
DEFAULT_FONT_SIZE = 16.0
FONT_FLOOR = 14.0
FONT_SHRINK_STEP = 2.0
#: 中文超过 12 字、拉丁超过 24 字符的文本被视为长文本，必须带 data-box-w。
LONG_TEXT_CJK_CHARS = 12
LONG_TEXT_LATIN_CHARS = 24

MAX_HAND_PATHS = 12
MAX_PATH_DATA_LENGTH = 400

#: 画布内容允许超出的容差（px），超过就算越界。
CANVAS_TOLERANCE = 2.0
#: 两个文本框相交面积超过较小者的这个比例才算压叠。
OVERLAP_RATIO = 0.04
#: stage 内连续空白带超过区域高度的这个比例才报告。
EMPTY_BAND_RATIO = 0.25
EMPTY_COLUMN_RATIO = 0.30
#: 覆盖画布面积达到这个比例的矩形视为背景。
BACKGROUND_AREA_RATIO = 0.90
#: 透明度低于此值的元素视为装饰，不参与压叠与空白计算。
DECOR_OPACITY = 0.15

DEFAULT_FONT_STACK = (
    "'Microsoft YaHei','PingFang SC','Hiragino Sans GB','Noto Sans CJK SC',"
    "'Segoe UI',Arial,sans-serif"
)

ALLOWED_ELEMENTS = frozenset(
    {
        "svg",
        "g",
        "defs",
        "symbol",
        "use",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "path",
        "text",
        "tspan",
        "image",
        "linearGradient",
        "radialGradient",
        "stop",
        "pattern",
        "clipPath",
        "mask",
        "marker",
        "filter",
        "feGaussianBlur",
        "feDropShadow",
        "feOffset",
        "feFlood",
        "feComposite",
        "feMerge",
        "feMergeNode",
        "feBlend",
        "feColorMatrix",
        "title",
        "desc",
    }
)

#: 可绘制元素：几何检查与 id 分配的对象。
DRAWABLE_ELEMENTS = frozenset(
    {
        "g",
        "use",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "path",
        "text",
        "image",
    }
)

#: 这些容器里的内容不直接绘制，不参与几何检查。
NON_RENDERING_CONTAINERS = frozenset(
    {"defs", "symbol", "clipPath", "mask", "marker", "pattern", "filter"}
)

ALLOWED_ATTRIBUTES = frozenset(
    {
        "id",
        "class",
        "transform",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "width",
        "height",
        "points",
        "d",
        "href",
        "viewBox",
        "preserveAspectRatio",
        "fill",
        "fill-opacity",
        "fill-rule",
        "stroke",
        "stroke-width",
        "stroke-opacity",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-miterlimit",
        "opacity",
        "color",
        "font-family",
        "font-size",
        "font-weight",
        "font-style",
        "letter-spacing",
        "word-spacing",
        "text-anchor",
        "dominant-baseline",
        "alignment-baseline",
        "text-decoration",
        "dx",
        "dy",
        "rotate",
        "textLength",
        "lengthAdjust",
        "clip-path",
        "clip-rule",
        "mask",
        "filter",
        "marker-start",
        "marker-mid",
        "marker-end",
        "gradientUnits",
        "gradientTransform",
        "spreadMethod",
        "offset",
        "stop-color",
        "stop-opacity",
        "patternUnits",
        "patternContentUnits",
        "patternTransform",
        "clipPathUnits",
        "maskUnits",
        "maskContentUnits",
        "filterUnits",
        "primitiveUnits",
        "stdDeviation",
        "in",
        "in2",
        "result",
        "flood-color",
        "flood-opacity",
        "operator",
        "mode",
        "type",
        "values",
        "k1",
        "k2",
        "k3",
        "k4",
        "refX",
        "refY",
        "markerWidth",
        "markerHeight",
        "markerUnits",
        "orient",
        "style",
        "lang",
        "paint-order",
        "vector-effect",
        "shape-rendering",
        "text-rendering",
        "overflow",
        "visibility",
        "display",
        "xml:space",
    }
)

#: style 属性里允许保留的声明。
ALLOWED_STYLE_PROPERTIES = frozenset(
    {
        "fill",
        "fill-opacity",
        "stroke",
        "stroke-width",
        "stroke-opacity",
        "stroke-dasharray",
        "stroke-linecap",
        "stroke-linejoin",
        "opacity",
        "font-family",
        "font-size",
        "font-weight",
        "font-style",
        "letter-spacing",
        "text-anchor",
        "dominant-baseline",
        "stop-color",
        "stop-opacity",
        "flood-color",
        "flood-opacity",
        "color",
        "paint-order",
    }
)

#: 画布契约的提示词文本；清洗器与检查器执行的就是这几条。
CANVAS_CONTRACT_TEXT = """**SVG 画布契约（生成要求，服务端检查结构与基础几何）**
- 只输出一个根元素 `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720">`。坐标与尺寸一律是画布像素数字，不写 %、em、vw。
- 用四个分组承载页面：`<g data-role="background">`、`<g data-role="title">`、`<g data-role="stage">`、`<g data-role="footer">`。封面、结尾页、章节页可以省略 title 与 footer，普通内容页必须齐全。所有可见内容都放在这四个分组里。
- 安全区：x 48–1232，y 40–680。标题区通常在 y 40–140；页码放右下角（x≈1200，y≈690）。stage 是主舞台，要围绕本页意图组织它的空间，不要把内容缩在左上角，也不要靠一排等大卡片填满。
- 字号阶梯（px）：主标题 40–56，副标题 24–28，正文 20–24 且不低于 18，注释 16 且不低于 14，大数字 56–96。font-size 只写数字。
- 文本框约定：超过 12 个汉字或 24 个拉丁字符的 `<text>` 必须带 `data-box-w`（可用宽度 px），可选 `data-box-h`。不要自己拆行、不要写 tspan 换行；服务端按真实字宽自动换行，装不下时按阶梯缩字。行高 1.4，请为每段文字预留“行数 × 1.4 × 字号”的高度，避免与下方元素相撞。
- y 是文字基线；用 text-anchor 做水平对齐。
- 图标只能用 `<use href="#ic-…" x=".." y=".." width=".." height=".." color="…"/>` 引用下方列出的符号 id，不要自己画图标路径。
- `<path>` 只用于连接线、箭头和简单几何形状，最多 12 个，每个 d 不超过 400 字符。
- 允许：rect、circle、ellipse、line、polyline、polygon、path、text、image、g、use，以及 defs 中的 linearGradient、radialGradient、pattern、clipPath、mask、marker 和 feGaussianBlur、feDropShadow 等基础滤镜。
- 禁止：script、style 元素、foreignObject、a、动画元素、textPath、CSS 变量、事件属性、外部链接（href 必须以 # 开头；image 只能使用给定的图片地址）。样式写成属性（fill、stroke、font-size…）；可以用 style 属性，但不许出现 url(http…)。
- 文字与文字、文字与图片不得互相压叠；所有元素都在画布内。
- 背景可以铺满画布，但 stage 里的内容要与本页意图相称：内容少时先放大主体、改用焦点构图，而不是留一大片空白。
"""
