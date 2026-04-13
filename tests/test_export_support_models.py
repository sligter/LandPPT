import importlib.util
import logging
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPORT_SUPPORT_PATH = ROOT / "src" / "landppt" / "web" / "route_modules" / "export_support.py"
WEB_DIR = ROOT / "src" / "landppt" / "web"
ROUTE_MODULES_DIR = WEB_DIR / "route_modules"


def _load_export_support_module():
    import landppt

    web_pkg = types.ModuleType("landppt.web")
    web_pkg.__path__ = [str(WEB_DIR)]
    route_modules_pkg = types.ModuleType("landppt.web.route_modules")
    route_modules_pkg.__path__ = [str(ROUTE_MODULES_DIR)]
    support_module = types.ModuleType("landppt.web.route_modules.support")
    support_module.logger = logging.getLogger("test.export_support")

    original_web = sys.modules.get("landppt.web")
    original_route_modules = sys.modules.get("landppt.web.route_modules")
    original_support = sys.modules.get("landppt.web.route_modules.support")
    sys.modules["landppt.web"] = web_pkg
    sys.modules["landppt.web.route_modules"] = route_modules_pkg
    sys.modules["landppt.web.route_modules.support"] = support_module
    setattr(landppt, "web", web_pkg)

    module_name = "landppt.web.route_modules._export_support_test"
    spec = importlib.util.spec_from_file_location(module_name, EXPORT_SUPPORT_PATH)
    assert spec is not None and spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        if original_web is not None:
            sys.modules["landppt.web"] = original_web
            setattr(landppt, "web", original_web)
        else:
            sys.modules.pop("landppt.web", None)
            if hasattr(landppt, "web"):
                delattr(landppt, "web")

        if original_route_modules is not None:
            sys.modules["landppt.web.route_modules"] = original_route_modules
        else:
            sys.modules.pop("landppt.web.route_modules", None)

        if original_support is not None:
            sys.modules["landppt.web.route_modules.support"] = original_support
        else:
            sys.modules.pop("landppt.web.route_modules.support", None)


def test_image_pptx_export_request_validates_after_model_rebuild():
    module = _load_export_support_module()
    payload = module.ImagePPTXExportRequest.model_validate(
        {
            "slides": [
                {
                    "index": 1,
                    "html_content": "<div>slide</div>",
                    "title": "封面",
                }
            ],
            "images": [
                {
                    "index": 1,
                    "data": "base64-data",
                    "width": 1280,
                    "height": 720,
                }
            ],
        }
    )

    assert payload.slides is not None
    assert payload.slides[0]["index"] == 1
    assert payload.images is not None
    assert payload.images[0]["width"] == 1280
