from landppt.services.file_outline_utils import (
    extract_saved_file_outline,
    get_file_processing_mode,
    is_file_generated_outline,
    normalize_uploaded_files,
    prefer_uploaded_files_for_magic_pdf,
    should_force_file_outline_regeneration,
)


def test_get_file_processing_mode_defaults():
    assert get_file_processing_mode({}) == "markitdown"
    assert get_file_processing_mode({"file_processing_mode": ""}) == "markitdown"


def test_normalize_uploaded_files_filters_invalid_entries():
    assert normalize_uploaded_files(None) == []
    assert normalize_uploaded_files({}) == []
    assert normalize_uploaded_files([{"filename": "a.pdf"}]) == []
    assert normalize_uploaded_files([{"file_path": "/x/a.pdf", "filename": "a.pdf"}]) == [
        {"file_path": "/x/a.pdf", "filename": "a.pdf"}
    ]


def test_prefer_uploaded_files_for_magic_pdf_only_when_selected():
    ok, items = prefer_uploaded_files_for_magic_pdf(
        {"file_processing_mode": "markitdown", "uploaded_files": [{"file_path": "/x/a.pdf", "filename": "a.pdf"}]}
    )
    assert ok is False
    assert items == []

    ok, items = prefer_uploaded_files_for_magic_pdf(
        {"file_processing_mode": "magic_pdf", "uploaded_files": [{"file_path": "/x/a.pdf", "filename": "a.pdf"}]}
    )
    assert ok is True
    assert items == [{"file_path": "/x/a.pdf", "filename": "a.pdf"}]


def test_extract_saved_file_outline_prefers_project_outline():
    project_outline = {
        "slides": [{"title": "A"}],
        "metadata": {"generated_with_summeryfile": True},
    }
    confirmed_requirements = {
        "file_generated_outline": {
            "slides": [{"title": "B"}],
            "metadata": {},
        }
    }

    assert extract_saved_file_outline(project_outline, confirmed_requirements) == project_outline
    assert is_file_generated_outline(project_outline) is True


def test_extract_saved_file_outline_honors_force_regeneration():
    project_outline = {
        "slides": [{"title": "A"}],
        "metadata": {"generated_with_summeryfile": True},
    }
    confirmed_requirements = {
        "file_generated_outline": {
            "slides": [{"title": "B"}],
            "metadata": {},
        },
        "force_file_outline_regeneration": True,
    }

    assert should_force_file_outline_regeneration(confirmed_requirements) is True
    assert extract_saved_file_outline(project_outline, confirmed_requirements) is None
