"""Tests for header/footer extraction and locked zones context."""
from landppt.services.prompts.design_prompts import DesignPrompts


# --- Default template HTML with slide-header and slide-footer classes ---
DEFAULT_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<style>
.slide-header { padding: 40px 60px 20px 60px; border-bottom: 2px solid rgba(96,165,250,0.3); }
.slide-title { font-size: 3.5rem; font-weight: bold; color: #60a5fa; }
.slide-footer { position: absolute; bottom: 20px; right: 30px; font-size: 14px; color: #94a3b8; }
</style>
</head>
<body>
<div class="slide-container">
    <div class="slide-header"><h1 class="slide-title">{{ main_heading }}</h1></div>
    <div class="slide-content"><div class="content-main">{{ page_content }}</div></div>
    <div class="slide-footer">{{ current_page_number }} / {{ total_page_count }}</div>
</div>
</body>
</html>"""

# --- Template without semantic class names ---
NO_SEMANTIC_TEMPLATE = """<!DOCTYPE html>
<html><head><style>
.page { width: 1280px; height: 720px; }
</style></head>
<body>
<div class="page">
    <div class="top-bar"><h1>{{ main_heading }}</h1></div>
    <div class="body-area">{{ page_content }}</div>
    <div style="position: absolute; bottom: 10px; right: 20px;">{{ current_page_number }}</div>
</div>
</body>
</html>"""


def test_extract_header_footer_from_default_template():
    """Should extract slide-header and slide-footer from standard template."""
    result = DesignPrompts._extract_header_footer_html(DEFAULT_TEMPLATE)

    assert "slide-header" in result["header_html"]
    assert "slide-title" in result["header_html"]
    assert "slide-footer" in result["footer_html"]
    assert result["header_css"], "Header CSS should be extracted"
    assert result["footer_css"], "Footer CSS should be extracted"


def test_extract_header_footer_from_template_without_semantic_classes():
    """Should fallback to position-based heuristics when no semantic classes."""
    result = DesignPrompts._extract_header_footer_html(NO_SEMANTIC_TEMPLATE)

    # Header may not be found without semantic classes - that's OK
    # Footer should be found via absolute-positioned element with page number placeholder
    assert "current_page_number" in result["footer_html"] or result["footer_html"] == ""


def test_extract_returns_empty_for_empty_template():
    """Should return empty dict values for empty/None template."""
    result = DesignPrompts._extract_header_footer_html("")
    assert result["header_html"] == ""
    assert result["footer_html"] == ""

    result2 = DesignPrompts._extract_header_footer_html(None)
    assert result2["header_html"] == ""
    assert result2["footer_html"] == ""


def test_locked_zones_context_for_content_page():
    """Content pages (not first/last/catalog) should get locked zone context."""
    context = DesignPrompts._build_locked_zones_context(
        DEFAULT_TEMPLATE, page_number=3, total_pages=10, slide_type="content")

    assert "母板锁定区" in context
    assert "Header 锁定结构" in context
    assert "Footer 锁定结构" in context
    assert "slide-header" in context
    assert "slide-footer" in context


def test_locked_zones_context_empty_for_first_page():
    """First page should not get locked zone context."""
    context = DesignPrompts._build_locked_zones_context(
        DEFAULT_TEMPLATE, page_number=1, total_pages=10, slide_type="title")
    assert context == ""


def test_locked_zones_context_empty_for_last_page():
    """Last page should not get locked zone context."""
    context = DesignPrompts._build_locked_zones_context(
        DEFAULT_TEMPLATE, page_number=10, total_pages=10, slide_type="thankyou")
    assert context == ""


def test_locked_zones_context_empty_for_catalog_page():
    """Catalog page should not get locked zone context."""
    context = DesignPrompts._build_locked_zones_context(
        DEFAULT_TEMPLATE, page_number=2, total_pages=10, slide_type="catalog")
    assert context == ""

    # Also test title-based detection
    context2 = DesignPrompts._build_locked_zones_context(
        DEFAULT_TEMPLATE, page_number=2, total_pages=10, slide_type="content",
        slide_title="目录概览")
    assert context2 == ""


def test_locked_zones_fallback_for_unextractable_template():
    """When header/footer can't be extracted, should return fallback hint."""
    minimal_template = "<html><body><div>hello</div></body></html>"
    context = DesignPrompts._build_locked_zones_context(
        minimal_template, page_number=3, total_pages=10, slide_type="content")

    assert "母板锁定区提示" in context
    assert "未能从模板中精确提取" in context
