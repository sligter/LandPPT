from landppt.services import file_processor as mod


def test_validate_file_accepts_pdf_when_supported(monkeypatch):
    monkeypatch.setattr(mod, "PDF_AVAILABLE", True, raising=True)

    fp = mod.FileProcessor()
    ok, msg = fp.validate_file("demo.pdf", file_size=1024)
    assert ok is True, msg

