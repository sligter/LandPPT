from pathlib import Path

import pytest

from landppt.services import file_processor as mod


def _write_deck(path: Path, *, picture_only: bool = False) -> Path:
    pptx = pytest.importorskip("pptx")
    from pptx.util import Inches

    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    if picture_only:
        from PIL import Image

        image_path = path.with_name(f"{path.stem}.png")
        Image.new("RGB", (60, 40), (12, 34, 56)).save(image_path)
        slide.shapes.add_picture(str(image_path), Inches(0), Inches(0), width=Inches(2))
    else:
        slide.shapes.add_textbox(Inches(0), Inches(0), Inches(6), Inches(1)).text_frame.text = (
            "季度复盘与下一步计划"
        )
    presentation.save(str(path))
    return path


def _write_sheet(path: Path) -> Path:
    openpyxl = pytest.importorskip("openpyxl")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "销量"
    sheet.append(["季度", "销量"])
    sheet.append(["Q1", 120])
    workbook.save(str(path))
    return path


def test_validate_file_accepts_office_formats_when_markitdown_available(monkeypatch):
    monkeypatch.setattr(mod, "MARKITDOWN_AVAILABLE", True, raising=True)

    fp = mod.FileProcessor()
    for name in ("demo.pptx", "demo.xlsx"):
        ok, message = fp.validate_file(name, file_size=1024)
        assert ok is True, message


def test_validate_file_rejects_office_formats_without_markitdown(monkeypatch):
    monkeypatch.setattr(mod, "MARKITDOWN_AVAILABLE", False, raising=True)

    fp = mod.FileProcessor()
    ok, message = fp.validate_file("demo.pptx", file_size=1024)
    assert ok is False
    assert "markitdown" in message


def test_slide_marker_comments_are_not_topics():
    fp = mod.FileProcessor()
    topics = fp._extract_topics("<!-- Slide number: 1 -->\n\n# 季度复盘与下一步计划")

    assert topics == ["# 季度复盘与下一步计划"]


@pytest.mark.asyncio
async def test_pptx_upload_extracts_slide_text(tmp_path: Path):
    pytest.importorskip("markitdown")
    path = _write_deck(tmp_path / "deck.pptx")

    result = await mod.FileProcessor().process_file(str(path), "deck.pptx")

    assert result.type == ".pptx"
    assert "季度复盘与下一步计划" in result.processed_content


@pytest.mark.asyncio
async def test_pptx_with_picture_only_slides_reports_missing_text(tmp_path: Path):
    pytest.importorskip("markitdown")
    path = _write_deck(tmp_path / "scanned.pptx", picture_only=True)

    with pytest.raises(ValueError, match="未能提取到可编辑文字"):
        await mod.FileProcessor().process_file(str(path), "scanned.pptx")


@pytest.mark.asyncio
async def test_xlsx_upload_extracts_sheet_rows(tmp_path: Path):
    pytest.importorskip("markitdown")
    path = _write_sheet(tmp_path / "sales.xlsx")

    result = await mod.FileProcessor().process_file(str(path), "sales.xlsx")

    assert result.type == ".xlsx"
    assert "| Q1 | 120 |" in result.processed_content


def test_url_source_accepts_office_formats():
    from landppt.web.route_modules import outline_support

    assert outline_support._is_supported_file_source_url("https://example.com/deck.pptx")
    assert outline_support._is_supported_file_source_url("https://example.com/sales.xlsx")
    assert outline_support._is_supported_file_source_url(
        "https://example.com/download",
        content_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
    )