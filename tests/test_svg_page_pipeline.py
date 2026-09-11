"""svg_page 包的单元测试：提取、清洗、测量、分行、检查、修复、外壳。"""

import pytest

from landppt.services.slide.svg_page import (
    SvgSanitizeError,
    TextMeasurer,
    build_placeholder_svg,
    build_slide_html,
    extract_svg_markup,
    is_svg_page_html,
    looks_truncated,
    process_svg_candidate,
    sanitize_svg,
    svg_from_shell,
)
from landppt.services.slide.svg_page.constants import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    FONT_FLOOR,
)
from landppt.services.slide.svg_page.defs_library import SYMBOL_IDS, library_defs_markup
from landppt.services.slide.svg_page.geometry import (
    BBox,
    apply_bbox,
    parse_transform,
    path_bbox,
)
from landppt.services.slide.svg_page.inspect import inspect_svg
from landppt.services.slide.svg_page.layout import layout_text_elements, wrap_text
from landppt.services.slide.svg_page.metrics import is_cjk_char, iter_break_units
from landppt.services.slide.svg_page.repair import repair_out_of_canvas
from landppt.services.slide.svg_page.sanitize import serialize

MEASURER = TextMeasurer()


def test_measure_only_preserves_lines_and_size_and_reports_raw_overflow():
    markup = '<svg><text id="t" x="100" y="200" font-size="24" data-box-w="100">这段文字需要多行显示</text></svg>'
    raw = process_svg_candidate(markup, apply_repair=False)
    fixed = process_svg_candidate(markup)
    assert "<tspan" not in raw.markup
    assert raw.layout_results[0].rewritten is False
    assert any(d["type"] == "text_overflow" for d in raw.blocking)
    assert "<tspan" in fixed.markup
    assert not any(d["type"] == "text_overflow" for d in fixed.blocking)
    assert fixed.before_repair["blocking"] >= 1


def test_long_latin_word_after_prefix_wraps_without_unnecessary_shrinking():
    text = "标题 Supercalifragilisticexpialidocious"
    lines = wrap_text(text, 100, 24, MEASURER)
    assert all(MEASURER.text_width(line, 24) <= 100.5 for line in lines)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")


def test_repair_uses_parent_coordinates_for_transformed_role_group():
    raw = '<svg><g data-role="stage" transform="translate(100 0) scale(2)"><rect id="r" x="550" y="100" width="150" height="50"/></g></svg>'
    result = process_svg_candidate(raw)
    assert result.repair_actions
    assert not any(d["type"] == "out_of_canvas" for d in result.blocking)


def test_blank_page_cannot_be_successful_after_cleaning():
    result = process_svg_candidate(
        "<svg><foreignObject><div>Lost content</div></foreignObject></svg>"
    )
    assert any(d["type"] == "empty_page" for d in result.blocking)


def test_inline_css_precedence_is_preserved_for_inspection():
    result = sanitize_svg(
        '<svg><text font-size="20" opacity="1" style="font-size:32px;opacity:0">Hi</text></svg>'
    )
    text = next(e for e in result.root.iter() if e.tag.endswith("text"))
    assert text.get("font-size") == "32" and text.get("opacity") == "0"
    assert "style" not in text.attrib


def test_extreme_font_size_is_rejected_before_layout_loop():
    with pytest.raises(SvgSanitizeError):
        process_svg_candidate(
            '<svg><text font-size="999999999" data-box-w="20">Hi</text></svg>'
        )


def wrap(body: str, roles: bool = True) -> str:
    inner = body
    if roles:
        inner = (
            '<g data-role="background"><rect width="1280" height="720" fill="#111"/></g>'
            '<g data-role="title"><text x="96" y="110" font-size="44" fill="#fff">标题</text></g>'
            f'<g data-role="stage">{body}</g>'
            '<g data-role="footer"><text id="pn" x="1200" y="690" font-size="16" fill="#aaa" text-anchor="end">2 / 5</text></g>'
        )
    return f'<svg viewBox="0 0 1280 720" width="1280" height="720">{inner}</svg>'


# ----------------------------------------------------------------------
# extract
# ----------------------------------------------------------------------
def test_extract_prefers_complete_fenced_svg_and_ignores_prose():
    raw = '说明文字 <svg>不完整\n```svg\n<svg viewBox="0 0 1280 720"><rect width="10" height="10"/></svg>\n```\n再来点解释'
    markup = extract_svg_markup(raw)
    assert markup.startswith("<svg") and markup.endswith("</svg>")
    assert "rect" in markup


def test_extract_strips_reasoning_and_detects_truncation():
    assert extract_svg_markup("<think>plan <svg></svg></think> nothing here") is None
    assert looks_truncated("```svg\n<svg viewBox='0 0 1280 720'><rect width='1'")
    assert not looks_truncated("<svg></svg>")


# ----------------------------------------------------------------------
# sanitize
# ----------------------------------------------------------------------
def test_sanitize_removes_active_content_and_normalizes_root():
    markup = (
        '<svg viewBox="0 0 800 600" onload="x()" transform="scale(2)">'
        "<script>alert(1)</script><style>text{fill:red}</style>"
        "<foreignObject><div>html</div></foreignObject>"
        '<a href="https://evil"><rect width="10" height="10" onclick="bad()"/></a>'
        '<image href="javascript:alert(1)" width="10" height="10"/>'
        '<text x="10" y="20" style="font-size: 24px; fill: url(http://evil/x); stroke: red">A</text>'
        '<linearGradient id="g" href="https://evil/grad"/>'
        "</svg>"
    )
    result = sanitize_svg(markup)
    out = result.markup
    assert 'viewBox="0 0 1280 720"' in out and 'width="1280"' in out
    for forbidden in (
        "<script",
        "<style",
        "foreignObject",
        "<a ",
        "onload",
        "onclick",
        "javascript:",
        "url(http",
        "https://evil",
    ):
        assert forbidden not in out
    assert 'font-size="24"' in out and 'stroke="red"' in out
    assert (
        "removed-element:script" in result.issues
        and "removed-element:style" in result.issues
    )
    assert any(issue.startswith("removed-image-href") for issue in result.issues)


def test_sanitize_rejects_doctype_and_malformed_xml():
    with pytest.raises(SvgSanitizeError):
        sanitize_svg('<!DOCTYPE svg [<!ENTITY x "y">]><svg viewBox="0 0 1 1"/>')
    with pytest.raises(SvgSanitizeError):
        sanitize_svg('<svg viewBox="0 0 1 1"><rect width=10></svg>')
    with pytest.raises(SvgSanitizeError):
        sanitize_svg("<div>not svg</div>")


def test_sanitize_assigns_ids_and_keeps_camel_case_attributes():
    result = sanitize_svg(
        '<svg viewBox="0 0 1280 720"><defs><linearGradient id="g" gradientUnits="userSpaceOnUse"/><clipPath id="c"/></defs>'
        '<rect width="10" height="10"/><rect id="dup" width="10" height="10"/><rect id="dup" width="10" height="10"/>'
        '<text x="1" y="2" font-size="1.5em">T</text></svg>'
    )
    out = result.markup
    assert (
        "linearGradient" in out
        and "gradientUnits" in out
        and "clipPath" in out
        and "viewBox" in out
    )
    ids = [el.get("id") for el in result.root.iter() if el.get("id")]
    assert len(ids) == len(set(ids)), ids
    assert all(el.get("id") for el in result.root.iter() if el.tag.endswith("rect"))
    assert 'font-size="24"' in out


def test_sanitize_use_references_only_library_or_local_ids():
    result = sanitize_svg(
        '<svg viewBox="0 0 1280 720"><defs><symbol id="mine" viewBox="0 0 24 24"><circle r="4"/></symbol></defs>'
        '<use href="#ic-check" width="24" height="24"/><use href="#mine" width="24" height="24"/>'
        '<use href="#ic-unknown" width="24" height="24"/><use xlink:href="#ic-star" width="24" height="24"/></svg>'
    )
    out = result.markup
    assert "#ic-check" in out and "#mine" in out and "#ic-star" in out
    assert "ic-unknown" not in out
    assert "xlink:href" not in out
    assert "unknown-symbol:#ic-unknown" in result.issues


def test_sanitize_image_allowlist_and_defaults():
    markup = '<svg viewBox="0 0 1280 720"><image href="https://cdn.example.com/a.png" width="10" height="10"/><image href="/local/b.png" width="10" height="10"/></svg>'
    default = sanitize_svg(markup)
    assert default.markup.count("<image") == 2
    restricted = sanitize_svg(markup, allowed_image_urls=["/local/b.png"])
    assert (
        restricted.markup.count("<image") == 1 and "/local/b.png" in restricted.markup
    )


# ----------------------------------------------------------------------
# metrics / wrap
# ----------------------------------------------------------------------
def test_cjk_width_is_exactly_one_em_and_latin_is_measured():
    assert is_cjk_char("中") and is_cjk_char("，") and not is_cjk_char("a")
    assert MEASURER.text_width("季度营收对比", 32) == pytest.approx(32 * 6)
    latin = MEASURER.text_width("Quarterly revenue", 32)
    assert 0.4 * 32 * 17 < latin < 0.75 * 32 * 17
    assert MEASURER.text_width("123456", 32) < MEASURER.text_width("中中中中中中", 32)
    assert MEASURER.text_width("Bold", 32, "bold") >= MEASURER.text_width(
        "Bold", 32, "normal"
    )


def test_break_units_keep_closing_punctuation_attached():
    units = iter_break_units("增长 18.4%，主要来自（新能源）客户。")
    assert "，" not in [u for u in units if len(u) == 1]
    assert any(u.endswith("，") for u in units)
    assert any(u.startswith("（") for u in units)
    assert "18.4%" in units or "18.4%，" in units


def test_wrap_text_fills_lines_by_measured_width():
    lines = wrap_text(
        "华东区域营收同比增长十八点四个百分点，主要来自新能源客户的批量采购",
        32 * 10,
        32,
        MEASURER,
    )
    assert all(MEASURER.text_width(line, 32) <= 32 * 10 + 0.5 for line in lines)
    assert len(lines) >= 3
    assert (
        "".join(lines)
        == "华东区域营收同比增长十八点四个百分点，主要来自新能源客户的批量采购"
    )
    single = wrap_text("短", 200, 32, MEASURER)
    assert single == ["短"]


# ----------------------------------------------------------------------
# layout + inspect
# ----------------------------------------------------------------------
def test_layout_wraps_long_text_into_tspans_and_shrinks_to_box_height():
    svg = wrap(
        '<text id="t" x="100" y="240" font-size="24" fill="#fff" data-box-w="480" data-box-h="60">'
        "华东区域营收同比增长十八个百分点，主要来自新能源客户的批量采购以及渠道下沉带来的新增门店贡献，其中三季度单季创下历史新高。"
        "</text>"
    )
    result = process_svg_candidate(svg, measurer=MEASURER)
    layout = next(r for r in result.layout_results if r.element_id == "t")
    assert layout.rewritten and layout.line_count >= 2
    assert layout.shrunk and layout.font_size < 24
    assert result.markup.count("<tspan") == layout.line_count
    assert f'data-lines="{layout.line_count}"' in result.markup
    for line in layout.lines:
        assert MEASURER.text_width(line, layout.font_size) <= 480.5


def test_layout_reports_overflow_when_even_floor_font_does_not_fit():
    svg = wrap(
        '<text id="t" x="100" y="240" font-size="24" fill="#fff" data-box-w="120" data-box-h="30">'
        + "很长的文字" * 12
        + "</text>"
    )
    result = process_svg_candidate(svg, measurer=MEASURER)
    layout = next(r for r in result.layout_results if r.element_id == "t")
    assert layout.overflow and layout.font_size >= FONT_FLOOR
    assert any(d["type"] == "text_overflow" and d["id"] == "t" for d in result.blocking)


def test_inspect_flags_overlap_equal_rects_missing_box_and_empty_band():
    svg = wrap(
        '<text id="a" x="100" y="230" font-size="22" fill="#fff">三季度营收十二点四亿元</text>'
        '<text id="b" x="100" y="236" font-size="22" fill="#fff">同比增长十八点四个百分点</text>'
        '<text id="long" x="700" y="230" font-size="20" fill="#fff">这是一段没有声明文本框宽度却明显超过十二个汉字的说明文字</text>'
        '<rect id="r1" x="96" y="600" width="200" height="40" fill="#333"/>'
        '<rect id="r2" x="320" y="600" width="200" height="40" fill="#333"/>'
        '<rect id="r3" x="544" y="600" width="200" height="40" fill="#333"/>'
    )
    result = process_svg_candidate(svg, measurer=MEASURER)
    types = {d["type"] for d in result.inspection.defects}
    assert {"overlap", "equal_rect_group", "missing_text_box", "empty_band"} <= types
    overlap = next(d for d in result.blocking if d["type"] == "overlap")
    assert {overlap["a"], overlap["b"]} == {"a", "b"}
    # 页脚页码位于边距区，必须豁免；stage 里那段压到画布边的长文本则应被提醒。
    safe_area_ids = [
        d["id"] for d in result.advisory if d["type"] == "outside_safe_area"
    ]
    assert "pn" not in safe_area_ids and safe_area_ids == ["long"]
    metrics = result.metrics
    assert metrics["text_count"] == 5 and metrics["blocking_count"] == 1
    assert 0 < metrics["stage_coverage"] < 0.5
    assert set(metrics["has_roles"]) == {"background", "title", "stage", "footer"}


def test_clean_page_has_no_blocking_defects():
    svg = wrap(
        '<rect x="96" y="180" width="520" height="220" rx="16" fill="#1e293b"/>'
        '<text x="120" y="230" font-size="24" fill="#fff" data-box-w="470">华东区域营收同比增长十八点四个百分点，主要来自新能源客户的批量采购。</text>'
        '<use href="#ic-trending-up" x="700" y="200" width="48" height="48" color="#38bdf8"/>'
        '<text x="770" y="235" font-size="28" fill="#fff">增长动力</text>'
    )
    result = process_svg_candidate(svg, measurer=MEASURER)
    assert result.blocking == []
    assert result.injected_symbols == ["ic-trending-up"]
    assert '<symbol id="ic-trending-up"' in result.markup
    assert result.markup.count("xmlns=") == 1


# ----------------------------------------------------------------------
# repair
# ----------------------------------------------------------------------
def test_repair_translates_out_of_canvas_card_with_its_label():
    svg = wrap(
        '<rect id="card" x="1100" y="500" width="300" height="160" rx="12" fill="#334155"/>'
        '<text id="label" x="1120" y="560" font-size="20" fill="#fff">越界卡片</text>'
    )
    result = process_svg_candidate(svg, measurer=MEASURER)
    assert result.repair_actions and result.repair_actions[0]["action"] == "translate"
    assert result.repair_actions[0]["moved_with"] == ["label"]
    assert not any(d["type"] == "out_of_canvas" for d in result.blocking)
    card = next(el for el in result.root.iter() if el.get("id") == "card")
    label = next(el for el in result.root.iter() if el.get("id") == "label")
    assert card.get("transform") == label.get("transform")
    assert parse_transform(card.get("transform")) == pytest.approx(
        (1, 0, 0, 1, -168, 0)
    )


def test_repair_scales_units_wider_than_the_canvas():
    # 面积达到画布九成的矩形会被当作背景；这里用一条比画布还宽、但面积不够背景的横幅。
    svg = wrap(
        '<rect id="banner" x="-60" y="200" width="1400" height="300" fill="#222"/>'
    )
    result = process_svg_candidate(svg, measurer=MEASURER)
    assert result.repair_actions and result.repair_actions[0]["action"] == "scale"
    assert result.repair_actions[0]["scale"] < 1.0
    assert not any(d["type"] == "out_of_canvas" for d in result.blocking)


def test_full_bleed_rect_is_background_not_a_defect():
    svg = wrap(
        '<rect id="bg2" x="-100" y="-50" width="1600" height="900" fill="#222"/>'
    )
    result = process_svg_candidate(svg, measurer=MEASURER)
    assert result.repair_actions == []
    assert not any(d["type"] == "out_of_canvas" for d in result.blocking)


def test_repair_is_skipped_when_disabled():
    svg = wrap(
        '<rect id="card" x="1200" y="100" width="300" height="100" fill="#333"/>'
    )
    result = process_svg_candidate(svg, measurer=MEASURER, apply_repair=False)
    assert result.repair_actions == []
    assert any(d["type"] == "out_of_canvas" for d in result.blocking)


# ----------------------------------------------------------------------
# geometry
# ----------------------------------------------------------------------
def test_transform_composition_and_bbox_projection():
    matrix = parse_transform("translate(100 50) scale(2)")
    box = apply_bbox(matrix, BBox(0, 0, 10, 10))
    assert (box.x0, box.y0, box.x1, box.y1) == (100, 50, 120, 70)
    rotated = apply_bbox(parse_transform("rotate(90 0 0)"), BBox(0, 0, 10, 20))
    assert rotated.width == pytest.approx(20) and rotated.height == pytest.approx(10)


def test_path_bbox_is_conservative_and_handles_relative_commands():
    box = path_bbox("M10 10 l 20 0 c 10 0 10 30 20 30 a 5 5 0 0 1 10 0 z")
    assert box.x0 <= 10 and box.y0 <= 10
    assert box.x1 >= 60 and box.y1 >= 40
    assert path_bbox("") is None


# ----------------------------------------------------------------------
# shell / placeholder / library
# ----------------------------------------------------------------------
def test_shell_round_trip_and_detection():
    svg = wrap('<text x="100" y="240" font-size="24" fill="#fff">A</text>')
    html = build_slide_html(svg, title='测试 "页"')
    assert html.startswith("<!DOCTYPE html>") and 'data-render-mode="svg"' in html
    assert (
        'class="landppt-svg-page"' in html
        and f"width:{CANVAS_WIDTH}px" in html
        and f"height:{CANVAS_HEIGHT}px" in html
    )
    assert is_svg_page_html(html) and not is_svg_page_html(
        "<html><body><div>x</div></body></html>"
    )
    assert svg_from_shell(html).startswith("<svg")


def test_placeholder_passes_its_own_validation():
    placeholder = build_placeholder_svg(
        "很长很长的标题" * 4, [f"要点{i}" for i in range(8)], 3, 9
    )
    result = process_svg_candidate(placeholder, measurer=MEASURER)
    assert result.blocking == []
    assert "3 / 9" in result.markup


def test_symbol_library_is_well_formed_and_prefixed():
    assert SYMBOL_IDS and all(sid.startswith("ic-") for sid in SYMBOL_IDS)
    from lxml import etree

    root = etree.fromstring(library_defs_markup())
    assert len(root) == len(SYMBOL_IDS)
    assert library_defs_markup(["ic-check", "not-a-symbol"]).count("<symbol") == 1
