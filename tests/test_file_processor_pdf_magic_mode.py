from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_file_processor_pdf_magic_mode_uses_mineru_client(monkeypatch, tmp_path: Path):
    from landppt.services.file_processor import FileProcessor

    calls = []

    class FakeDBConfigService:
        async def get_config_value(self, key: str, user_id=None):
            if key == "mineru_api_key":
                return "abc"
            if key == "mineru_base_url":
                return "https://mineru.net/api/v4"
            return None

    import landppt.services.db_config_service as db_mod

    monkeypatch.setattr(db_mod, "get_db_config_service", lambda: FakeDBConfigService(), raising=True)

    class FakeMineruAPIClient:
        def __init__(self, api_key=None, base_url=None, timeout=60.0):
            calls.append(("init", api_key, base_url))
            self.api_key = api_key
            self.base_url = base_url

        @property
        def is_available(self):
            return True

        async def extract_markdown(self, file_path=None, pdf_url=None, **kwargs):
            calls.append(("extract_markdown", file_path, pdf_url))
            return "MAGIC_CONTENT", {}

        async def close(self):
            calls.append(("close", None, None))

    import summeryanyfile.core.mineru_api_client as mineru_mod

    monkeypatch.setattr(mineru_mod, "MineruAPIClient", FakeMineruAPIClient, raising=True)

    from landppt.auth.request_context import current_user_id

    token = current_user_id.set(1)
    try:
        pdf_path = tmp_path / "demo.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

        fp = FileProcessor()
        result = await fp.process_file(str(pdf_path), "demo.pdf", file_processing_mode="magic_pdf")
        assert result.processed_content == "MAGIC_CONTENT"
        assert any(c[0] == "extract_markdown" for c in calls)
    finally:
        current_user_id.reset(token)


def test_document_processor_passes_explicit_mineru_config(monkeypatch, tmp_path: Path):
    from summeryanyfile.core.document_processor import DocumentProcessor

    calls = []

    class FakeMarkItDownConverter:
        def __init__(self, **kwargs):
            calls.append(
                (
                    "init",
                    kwargs.get("mineru_api_key"),
                    kwargs.get("mineru_base_url"),
                    kwargs.get("use_magic_pdf"),
                )
            )

        def convert_file(self, file_path: str):
            calls.append(("convert_file", file_path))
            return "MAGIC_CONTENT", "utf-8"

        def clean_markdown_content(self, content: str):
            return content

    import summeryanyfile.core.document_processor as document_processor_mod

    monkeypatch.setattr(document_processor_mod, "MarkItDownConverter", FakeMarkItDownConverter, raising=True)

    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%fake\n")

    processor = DocumentProcessor(
        use_magic_pdf=True,
        enable_cache=False,
        mineru_api_key="abc",
        mineru_base_url="https://mineru.net/api/v4",
    )
    document = processor.load_document(str(pdf_path))

    assert document.content == "MAGIC_CONTENT"
    assert ("init", "abc", "https://mineru.net/api/v4", True) in calls
    assert any(call[0] == "convert_file" for call in calls)
