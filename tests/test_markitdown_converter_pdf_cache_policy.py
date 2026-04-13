from pathlib import Path

from summeryanyfile.core.markitdown_converter import MarkItDownConverter


class _FakeCache:
    def __init__(self, processing_method: str):
        self.processing_method = processing_method
        self.saved = []

    def is_cached(self, file_path: str):
        return True, "md5"

    def get_cached_content(self, md5_hash: str):
        return (
            "CACHED",
            {"processing_metadata": {"detected_encoding": "utf-8", "processing_method": self.processing_method}},
        )

    def save_to_cache(self, file_path: str, markdown_content: str, processing_metadata=None):
        self.saved.append((file_path, markdown_content, processing_metadata))
        return "md5"


class _FakeMagicPDF:
    def __init__(self):
        self.calls = 0

    def convert_pdf_file(self, file_path: str):
        self.calls += 1
        return "MAGIC", "utf-8"


def test_pdf_magic_pdf_available_ignores_non_magic_cache(tmp_path: Path):
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

    converter = MarkItDownConverter(use_magic_pdf=True, enable_cache=False)
    converter.enable_cache = True
    converter._cache_manager = _FakeCache(processing_method="markitdown")

    magic = _FakeMagicPDF()
    converter._get_magic_pdf_converter = lambda: magic

    content, encoding = converter.convert_file(str(pdf_path))
    assert content == "MAGIC"
    assert encoding == "utf-8"
    assert magic.calls == 1


def test_pdf_magic_pdf_unavailable_uses_cached_result(tmp_path: Path):
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

    converter = MarkItDownConverter(use_magic_pdf=True, enable_cache=False)
    converter.enable_cache = True
    converter._cache_manager = _FakeCache(processing_method="markitdown")
    converter._get_magic_pdf_converter = lambda: None

    content, encoding = converter.convert_file(str(pdf_path))
    assert content == "CACHED"
    assert encoding == "utf-8"
