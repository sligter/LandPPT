import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTLINE_SUPPORT_PATH = ROOT / "src/landppt/web/route_modules/outline_support.py"


def test_outline_support_imports_re_when_using_regex_helpers():
    source = OUTLINE_SUPPORT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    uses_re = any(
        isinstance(node, ast.Name) and node.id == "re" and isinstance(node.ctx, ast.Load)
        for node in ast.walk(tree)
    )
    has_re_import = any(
        (
            isinstance(node, ast.Import)
            and any(alias.name == "re" for alias in node.names)
        )
        or (
            isinstance(node, ast.ImportFrom)
            and node.module == "re"
        )
        for node in ast.walk(tree)
    )

    assert uses_re
    assert has_re_import
