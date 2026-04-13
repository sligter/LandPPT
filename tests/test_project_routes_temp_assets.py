from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_temp_route_is_public_and_uses_real_file_content_type():
    route_text = (ROOT / "src/landppt/web/route_modules/project_workspace_routes.py").read_text(encoding="utf-8")
    temp_route_block = route_text.split('@router.get("/temp/{file_path:path}")', 1)[1]

    assert '@router.get("/temp/{file_path:path}")' in route_text
    assert "mimetypes.guess_type(str(full_path))" in temp_route_block
    assert 'media_type=media_type or "application/octet-stream"' in temp_route_block
    assert "user: User = Depends(get_current_user_required)" not in temp_route_block
