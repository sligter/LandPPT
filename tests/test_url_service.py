from landppt.services.url_service import URLService


def test_build_image_url_includes_dimensions(monkeypatch):
    service = URLService()
    monkeypatch.setattr(service, "_get_base_url", lambda: "http://localhost:8001")

    image_url = service.build_image_url("public_demo", width=320, height=180)

    assert image_url == "http://localhost:8001/api/image/view/public_demo?width=320px&height=180px"


def test_build_image_url_omits_empty_dimensions(monkeypatch):
    service = URLService()
    monkeypatch.setattr(service, "_get_base_url", lambda: "http://localhost:8001")

    image_url = service.build_image_url("public_demo", width=0, height=None)

    assert image_url == "http://localhost:8001/api/image/view/public_demo"
