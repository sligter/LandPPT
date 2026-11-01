"""Exercise the distributable skill scripts without a model or real credential."""

import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from threading import Thread

import pytest


@pytest.fixture
def scripts(monkeypatch):
    root = Path(__file__).resolve().parents[1] / "skills/landppt-ppt-generation/scripts"
    loaded = {}
    for name in ("api_client", "run_flow", "project_ops"):
        spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded[name] = module
    monkeypatch.setenv("LANDPPT_USER_API_KEY", "test-only-generated-key")
    monkeypatch.delenv("LANDPPT_API_KEY", raising=False)
    monkeypatch.delenv("LANDPPT_PUBLIC_STATIC_DIR", raising=False)
    return loaded


@pytest.fixture
def server():
    servers = []

    def start(respond):
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                seen.append((self.command, self.path, dict(self.headers), body))
                status, headers, content = respond(self.command, self.path, body)
                if not isinstance(content, bytes):
                    content = json.dumps(content).encode()
                    headers = {"Content-Type": "application/json", **headers}
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        servers.append((httpd, thread))
        return f"http://127.0.0.1:{httpd.server_port}", seen

    yield start
    for httpd, thread in reversed(servers):
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize(
    "mode,header", [("bearer", "Authorization"), ("x-api-key", "X-Api-Key")]
)
def test_personal_key_headers_and_json(scripts, server, mode, header):
    base, seen = server(lambda *args: (200, {}, {"success": True}))
    result = scripts["api_client"].main(
        [
            "--base-url",
            base,
            "--auth-mode",
            mode,
            "--method",
            "PATCH",
            "--path",
            "/api/example",
            "--json",
            '{"title":"报告"}',
        ]
    )
    assert result == 0
    method, path, headers, body = seen[0]
    assert (method, path) == ("PATCH", "/api/example")
    assert headers[header].endswith("test-only-generated-key")
    assert "Cookie" not in headers
    assert json.loads(body) == {"title": "报告"}


def test_multipart_repeated_fields_and_file(scripts, server, tmp_path):
    source = tmp_path / "report.txt"
    source.write_text("source material", encoding="utf-8")
    base, seen = server(lambda *args: (200, {}, {"success": True}))
    assert (
        scripts["api_client"].main(
            [
                "--base-url",
                base,
                "--method",
                "POST",
                "--path",
                "/api/upload",
                "--form",
                "tag=first",
                "--form",
                "tag=second",
                "--file",
                f"file={source}",
            ]
        )
        == 0
    )
    headers, body = seen[0][2:]
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert body.count(b'name="tag"') == 2
    assert b'filename="report.txt"' in body
    assert b"source material" in body


def test_form_and_private_download(scripts, server, tmp_path):
    base, seen = server(
        lambda *args: (200, {"Content-Type": "application/pdf"}, b"%PDF-example")
    )
    output = tmp_path / "private" / "deck.pdf"
    assert (
        scripts["api_client"].main(
            [
                "--base-url",
                base,
                "--method",
                "POST",
                "--path",
                "/api/download",
                "--form",
                "topic=a & b",
                "--out",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_bytes() == b"%PDF-example"
    assert seen[0][3] == b"topic=a+%26+b"
    assert not (tmp_path / "static").exists()


def test_sse_multiline_and_error_are_observable(scripts, server, capsys):
    stream = b': heartbeat\n\ndata: {"type":\ndata: "error", "message":"denied"}\n\n'
    base, _ = server(lambda *args: (200, {"Content-Type": "text/event-stream"}, stream))
    assert (
        scripts["api_client"].main(
            ["--base-url", base, "--path", "/api/stream", "--stream"]
        )
        == 3
    )
    assert "denied" in capsys.readouterr().out
    assert list(scripts["api_client"].sse_events(io.BytesIO(b"data: last"))) == ["last"]


def test_cross_origin_redirect_never_receives_key(scripts, server):
    target, target_seen = server(lambda *args: (200, {}, {}))
    source, _ = server(lambda *args: (302, {"Location": target + "/capture"}, b""))
    assert (
        scripts["api_client"].main(["--base-url", source, "--path", "/redirect"]) == 3
    )
    assert target_seen == []
    with pytest.raises(scripts["project_ops"].ApiError):
        scripts["project_ops"].call_json(
            "GET", source, "/redirect", "fake-key", "bearer"
        )
    with pytest.raises(scripts["run_flow"].WorkflowError):
        scripts["run_flow"].call_json("GET", source + "/redirect", "fake-key")
    assert target_seen == []


@pytest.mark.parametrize(
    "path", ["https://other.example/api", "//other.example/api", "/\\other.example/api"]
)
def test_client_rejects_external_paths(scripts, path):
    with pytest.raises(ValueError):
        scripts["api_client"].make_url("https://landppt.example", path)


def test_exports_require_explicit_publish_and_bound_directory(
    scripts, tmp_path, monkeypatch
):
    root = tmp_path / "static"
    root.mkdir()
    monkeypatch.setenv("LANDPPT_PUBLIC_STATIC_DIR", str(root))
    source = tmp_path / "private.pdf"
    source.write_bytes(b"private")
    client = scripts["api_client"]
    assert client.resolve_public_static_dir(str(root)) is None
    result = client.publish_to_static(
        saved_file=str(source),
        base_url="https://example.test",
        public_static_dir=None,
        public_static_subdir="downloads",
    )
    assert result == {"saved_file": str(source.resolve())}
    assert list(root.iterdir()) == []
    with pytest.raises(ValueError):
        client.publish_to_static(
            saved_file=str(source),
            base_url="https://example.test",
            public_static_dir=root,
            public_static_subdir="../outside",
        )
    assert not (tmp_path / "outside").exists()
    published = client.publish_to_static(
        saved_file=str(source),
        base_url="https://example.test",
        public_static_dir=root,
        public_static_subdir="downloads",
    )
    assert published["public_file_url"].startswith(
        "https://example.test/static/downloads/"
    )
    assert len(list((root / "downloads").iterdir())) == 1


@pytest.mark.parametrize(
    "name", ["../../escape.pdf", r"C:\outside\escape.pdf", "../escape.pdf"]
)
def test_server_filename_cannot_escape_output_directory(scripts, tmp_path, name):
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    saved = scripts["project_ops"].save_binary(
        b"pdf", headers, str(tmp_path), None, "fallback.pdf"
    )
    assert Path(saved).parent == tmp_path
    saved = scripts["run_flow"].save_export_file(
        data=b"pdf",
        headers_map=headers,
        output_dir=str(tmp_path),
        out="",
        fallback_name="fallback.pdf",
    )
    assert Path(saved).parent == tmp_path


@pytest.mark.parametrize("persisted_pages,expected_exit", [(2, 0), (1, 3)])
def test_free_flow_uses_json_and_checks_persistence_without_sharing(
    scripts, server, monkeypatch, capsys, persisted_pages, expected_exit
):
    def respond(method, path, body):
        if path == "/api/auth/me":
            return 200, {}, {"user": {"username": "tester"}}
        if path == "/api/projects":
            return 200, {}, {"project_id": "test-project"}
        if path.endswith("/generate-outline"):
            return (
                200,
                {},
                {"status": "success", "outline_content": {"slides": [{}, {}]}},
            )
        if path.endswith("/slides/stream"):
            return (
                200,
                {"Content-Type": "text/event-stream"},
                b'data: {"type":"complete"}\n\n',
            )
        if path == "/api/projects/test-project":
            return 200, {}, {"status": "completed", "slides_count": 2}
        if path.endswith("/slides-data"):
            return 200, {}, {"total_slides": persisted_pages}
        if path.endswith("/free-template/generate"):
            assert json.loads(body)["stream"] is False
            return 200, {}, {"success": True}
        return 200, {}, {"success": True, "status": "success"}

    base, seen = server(respond)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_flow.py",
            "--base-url",
            base,
            "--topic",
            "test",
            "--page-count",
            "2",
            "--default-export-format",
            "none",
            "--quiet",
        ],
    )
    assert scripts["run_flow"].main() == expected_exit
    paths = [row[1] for row in seen]
    assert paths.index(
        "/api/projects/test-project/free-template/confirm"
    ) < paths.index("/api/projects/test-project/slides/stream")
    assert all("share" not in path for path in paths)
    assert "test-project" in capsys.readouterr().out


def test_failed_project_does_not_poll_for_an_hour(scripts, monkeypatch):
    flow = scripts["run_flow"]
    monkeypatch.setattr(
        flow,
        "call_json",
        lambda *args, **kwargs: {"status": "failed", "slides_count": 0},
    )
    with pytest.raises(flow.WorkflowError, match="failed"):
        flow.wait_for_completion(
            "https://example.test",
            "project",
            "fake-key",
            expected_pages=12,
            poll_interval_sec=10,
            timeout_sec=3600,
            verbose=False,
        )


def test_failed_followup_task_is_not_reported_as_success(
    scripts, server, monkeypatch, capsys
):
    def respond(method, path, body):
        if path.endswith("/speech-script/generate"):
            return 200, {}, {"success": True, "task_id": "failed-task"}
        return 200, {}, {"status": "failed", "error": "provider unavailable"}

    base, _ = server(respond)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "project_ops.py",
            "--base-url",
            base,
            "--quiet",
            "speech-generate",
            "--project-id",
            "project",
            "--wait",
        ],
    )
    assert scripts["project_ops"].main() == 3
    assert "success: `false`" in capsys.readouterr().out
