#!/usr/bin/env python3
"""Authenticated JSON, form, multipart, SSE and download client (stdlib only)."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
import shutil
import sys
from urllib import error, parse, request
from uuid import uuid4


def _origin(url):
    parts = parse.urlsplit(url)
    return (
        parts.scheme.lower(),
        parts.hostname,
        parts.port or (443 if parts.scheme == "https" else 80),
    )


class SameOriginRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(req.full_url) != _origin(newurl):
            raise error.HTTPError(
                req.full_url,
                code,
                "Refusing cross-origin credential redirect",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_authenticated(req, *, timeout=600):
    """Never forward a user's credential to a redirect on another origin."""
    return request.build_opener(SameOriginRedirect()).open(req, timeout=timeout)


def make_url(base_url, path):
    parts = parse.urlsplit(base_url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "base-url must be an HTTP(S) service URL without credentials, query or fragment"
        )
    if (
        not path.startswith("/")
        or path.startswith("//")
        or "\\" in path
        or parse.urlsplit(path).fragment
    ):
        raise ValueError(
            "path must start with a single / and stay on the configured service"
        )
    return base_url.rstrip("/") + path


def safe_filename(value):
    """Treat a server-supplied filename as a name, never as a path."""
    name = value.replace("\\", "/").rsplit("/", 1)[-1].replace("\x00", "").strip()
    if name in {"", ".", ".."} or ":" in name:
        return "download.bin"
    return name


def resolve_public_static_dir(cli_value, *, publish=False):
    if not publish:
        return None
    value = (cli_value or os.environ.get("LANDPPT_PUBLIC_STATIC_DIR") or "").strip()
    if not value:
        raise ValueError(
            "--publish-static requires the actual server --public-static-dir (or LANDPPT_PUBLIC_STATIC_DIR)"
        )
    root = Path(value).resolve()
    if not root.is_dir():
        raise ValueError("The server static directory must already exist")
    return root


def publish_to_static(*, saved_file, base_url, public_static_dir, public_static_subdir):
    source = Path(saved_file).resolve()
    if public_static_dir is None:
        return {"saved_file": str(source)}
    root = Path(public_static_dir).resolve()
    subdir = public_static_subdir or "downloads"
    destination = (root / subdir).resolve()
    if not destination.is_relative_to(root):
        raise ValueError(
            "Public subdirectory must stay inside the server static directory"
        )
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{uuid4().hex}_{source.name}"
    shutil.copy2(source, target)
    public_path = "/static/" + parse.quote(target.relative_to(root).as_posix())
    return {
        "saved_file": str(source),
        "public_file_path": public_path,
        "public_file_url": base_url.rstrip("/") + public_path,
    }


def pairs(values):
    result = []
    for value in values:
        key, sep, item = value.partition("=")
        if not sep or not key or any(c in key for c in '\r\n"'):
            raise ValueError("Expected FIELD=VALUE with a valid field name")
        result.append((key, item))
    return result


def multipart(fields, files):
    boundary = "landppt-" + uuid4().hex
    chunks = []
    for key, value in fields:
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
        )
        chunks.append(value.encode("utf-8") + b"\r\n")
    for key, value in files:
        path = Path(value)
        filename = (
            safe_filename(path.name)
            .replace('"', "_")
            .replace("\r", "_")
            .replace("\n", "_")
        )
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
        )
        chunks.append(path.read_bytes() + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def sse_events(response):
    """Yield complete SSE data frames, including multiline data and final EOF."""
    data = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if data:
                yield "\n".join(data)
                data = []
        elif line.startswith("data:"):
            value = line[5:]
            data.append(value[1:] if value.startswith(" ") else value)
    if data:
        yield "\n".join(data)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("LANDPPT_BASE_URL", "http://localhost:8000"),
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Prefer LANDPPT_USER_API_KEY to avoid shell history",
    )
    parser.add_argument(
        "--auth-mode", choices=["bearer", "x-api-key"], default="bearer"
    )
    parser.add_argument(
        "--method", choices=["GET", "POST", "PUT", "PATCH", "DELETE"], default="GET"
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Service-relative route, including any encoded query",
    )
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--json", dest="json_text")
    body.add_argument("--json-file")
    parser.add_argument("--form", action="append", default=[], metavar="FIELD=VALUE")
    parser.add_argument("--file", action="append", default=[], metavar="FIELD=PATH")
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--stream", action="store_true", help="Print complete SSE frames as they arrive"
    )
    output.add_argument("--out", help="Save response privately at this local path")
    parser.add_argument("--timeout", type=int, default=600)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        key = (
            args.api_key
            or os.environ.get("LANDPPT_USER_API_KEY")
            or os.environ.get("LANDPPT_API_KEY")
        )
        if not key:
            raise ValueError("Set LANDPPT_USER_API_KEY to the personal LandPPT key")
        url = make_url(args.base_url, args.path)
        headers = (
            {"X-API-Key": key}
            if args.auth_mode == "x-api-key"
            else {"Authorization": "Bearer " + key}
        )
        headers.update(
            {
                "User-Agent": "LandPPT-Skill/2",
                "Accept": "text/event-stream" if args.stream else "application/json",
            }
        )
        data = None
        if args.json_file or args.json_text is not None:
            if args.form or args.file:
                raise ValueError("JSON cannot be combined with form fields or files")
            content = (
                Path(args.json_file).read_text(encoding="utf-8-sig")
                if args.json_file
                else args.json_text
            )
            data = json.dumps(json.loads(content), ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif args.file:
            data, headers["Content-Type"] = multipart(
                pairs(args.form), pairs(args.file)
            )
        elif args.form:
            data = parse.urlencode(pairs(args.form)).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = request.Request(url, data=data, headers=headers, method=args.method)
        with open_authenticated(req, timeout=args.timeout) as response:
            if args.stream:
                if "text/event-stream" not in response.headers.get("Content-Type", ""):
                    raise ValueError(
                        "Expected SSE; server returned a different response type"
                    )
                failed = False
                for event in sse_events(response):
                    print(event, flush=True)
                    try:
                        obj = json.loads(event)
                        if isinstance(obj, dict) and (
                            obj.get("type") == "error" or obj.get("success") is False
                        ):
                            failed = True
                    except json.JSONDecodeError:
                        pass
                return 3 if failed else 0
            if args.out:
                target = Path(args.out)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as output:
                    shutil.copyfileobj(response, output)
                print(json.dumps({"saved_file": str(target.resolve())}))
                return 0
            raw = response.read().decode("utf-8")
            obj = json.loads(raw) if raw else {}
            print(json.dumps(obj, ensure_ascii=False, indent=2))
            return 3 if isinstance(obj, dict) and obj.get("success") is False else 0
    except error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.reason}", file=sys.stderr)
        return 3
    except (ValueError, OSError, error.URLError) as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
