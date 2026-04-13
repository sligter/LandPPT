#!/usr/bin/env python3
"""LandPPT project operations for outline/PPT/speech/narration/export."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib import error, parse, request


class ApiError(RuntimeError):
    pass


def safe_print(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(message.encode(enc, "replace").decode(enc, "replace"))


def fmt_seconds(value: float) -> str:
    seconds = int(max(0, value))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {sec}s"
    if minutes > 0:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def print_markdown_result(command: str, *, success: bool, result: Optional[Dict[str, Any]] = None, error: str = "") -> None:
    title = f"## LandPPT Operation: `{command}`"
    safe_print(title)
    safe_print("")
    safe_print(f"- success: `{str(bool(success)).lower()}`")
    if error:
        safe_print(f"- error: `{error}`")
    if isinstance(result, dict):
        share_url = result.get("share_url_full") or result.get("share_url")
        if isinstance(share_url, str) and share_url:
            if share_url.startswith("http://") or share_url.startswith("https://"):
                safe_print(f"- share_url: [{share_url}]({share_url})")
            else:
                safe_print(f"- share_url: `{share_url}`")
        file_url = result.get("public_file_url")
        if not isinstance(file_url, str) and isinstance(result.get("download"), dict):
            file_url = result["download"].get("public_file_url")
        if isinstance(file_url, str) and file_url:
            safe_print(f"- file_url: [{file_url}]({file_url})")
        task_id = (
            result.get("task_id")
            or (result.get("start") or {}).get("task_id")
            or (result.get("task") or {}).get("task_id")
        )
        if task_id:
            safe_print(f"- task_id: `{task_id}`")
    safe_print("")
    safe_print("### Raw Result")
    safe_print("```json")
    safe_print(json.dumps(result or {}, ensure_ascii=False, indent=2))
    safe_print("```")


def task_next_steps(
    *,
    base_url: str,
    auth_mode: str,
    task_id: str,
    output_dir: str,
    command_file: str,
) -> List[str]:
    auth_flag = f"--auth-mode {auth_mode}" if auth_mode != "bearer" else ""
    poll_cmd = (
        f"python {command_file} --base-url {base_url} {auth_flag} task-status --task-id {task_id}"
    ).strip()
    dl_cmd = (
        f"python {command_file} --base-url {base_url} {auth_flag} --output-dir {output_dir} task-download --task-id {task_id}"
    ).strip()
    return [poll_cmd, dl_cmd]


def resolve_api_key(cli_key: str) -> str:
    key = (cli_key or "").strip()
    if key:
        return key
    return (os.environ.get("LANDPPT_USER_API_KEY") or os.environ.get("LANDPPT_API_KEY") or "").strip()


def headers(api_key: str, auth_mode: str, content_type: Optional[str] = None) -> Dict[str, str]:
    """Build request headers.

    Some hosted deployments sit behind WAF/bot protection that may block the
    default Python urllib User-Agent (e.g. Cloudflare 1010).
    """
    result = {"X-API-Key": api_key} if auth_mode == "x-api-key" else {"Authorization": f"Bearer {api_key}"}

    # WAF/bot protection compatibility
    result.setdefault(
        "User-Agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    )
    result.setdefault("Accept", "application/json, text/event-stream;q=0.9, */*;q=0.8")

    if content_type:
        result["Content-Type"] = content_type
    return result


def make_url(base_url: str, path: str, query: Optional[Dict[str, Any]] = None) -> str:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        clean = {k: v for k, v in query.items() if v is not None}
        if clean:
            url = f"{url}?{parse.urlencode(clean, doseq=True)}"
    return url


def request_raw(
    method: str,
    base_url: str,
    path: str,
    api_key: str,
    auth_mode: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    form: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    timeout: int = 600,
) -> Tuple[bytes, Dict[str, str]]:
    data: Optional[bytes] = None
    req_headers = headers(api_key, auth_mode)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    elif form is not None:
        data = parse.urlencode(form, doseq=True).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    url = make_url(base_url, path, query=query)
    req = request.Request(url, method=method, headers=req_headers, data=data)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), dict(resp.headers.items())
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise ApiError(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise ApiError(f"{method} {url} failed: {exc}") from exc


def call_json(
    method: str,
    base_url: str,
    path: str,
    api_key: str,
    auth_mode: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    form: Optional[Dict[str, Any]] = None,
    query: Optional[Dict[str, Any]] = None,
    timeout: int = 600,
) -> Dict[str, Any]:
    body, _ = request_raw(
        method,
        base_url,
        path,
        api_key,
        auth_mode,
        payload=payload,
        form=form,
        query=query,
        timeout=timeout,
    )
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8", "ignore"))
    except json.JSONDecodeError as exc:
        raise ApiError(f"{method} {path} returned non-JSON payload") from exc


def parse_indices(raw: str) -> List[int]:
    if not (raw or "").strip():
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def read_json(path: str) -> Any:
    return json.loads(read_text(path))


def filename_from_headers(headers_map: Dict[str, str], fallback: str) -> str:
    cd = headers_map.get("Content-Disposition", "") or headers_map.get("content-disposition", "")
    if cd:
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
        if m:
            return parse.unquote(m.group(1))
        m = re.search(r'filename="?([^";]+)"?', cd)
        if m:
            return m.group(1)
    return fallback


def save_binary(
    data: bytes,
    headers_map: Dict[str, str],
    output_dir: str,
    out: Optional[str],
    fallback: str,
) -> str:
    target = Path(out) if out else Path(output_dir) / filename_from_headers(headers_map, fallback)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(target.resolve())


def resolve_public_static_dir(cli_value: str) -> Path:
    from_env = (os.environ.get("LANDPPT_PUBLIC_STATIC_DIR") or "").strip()
    if from_env:
        return Path(from_env).resolve()

    if (cli_value or "").strip():
        return Path(cli_value).resolve()

    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    return (repo_root / "src" / "landppt" / "web" / "static").resolve()


def _url_join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def publish_to_static(
    *,
    saved_file: str,
    base_url: str,
    public_static_dir: Path,
    public_static_subdir: str,
) -> Dict[str, str]:
    source = Path(saved_file).resolve()
    if not source.exists():
        raise ApiError(f"Saved file does not exist: {source}")

    subdir = (public_static_subdir or "downloads").strip().strip("/\\")
    publish_dir = public_static_dir / subdir if subdir else public_static_dir
    publish_dir.mkdir(parents=True, exist_ok=True)

    target = publish_dir / source.name
    if target.exists():
        suffix = source.suffix
        stem = source.stem
        target = publish_dir / f"{stem}_{int(time.time())}{suffix}"

    shutil.copy2(source, target)

    if subdir:
        public_path = f"/static/{subdir}/{parse.quote(target.name)}"
    else:
        public_path = f"/static/{parse.quote(target.name)}"

    return {
        "saved_file": str(source),
        "public_file_path": public_path,
        "public_file_url": _url_join(base_url, public_path),
    }


def wait_task(
    base_url: str,
    api_key: str,
    auth_mode: str,
    task_id: str,
    timeout_sec: int,
    interval_sec: int,
    heartbeat_sec: int,
    quiet: bool,
) -> Dict[str, Any]:
    start = time.time()
    last = None
    last_heartbeat = -1
    events: List[Dict[str, Any]] = []
    while True:
        task = call_json("GET", base_url, f"/api/landppt/tasks/{task_id}", api_key, auth_mode, timeout=600)
        status = task.get("status")
        progress = task.get("progress")
        if isinstance(progress, dict):
            pct = progress.get("percentage")
        else:
            pct = progress
        elapsed = int(time.time() - start)
        key = (status, pct)
        if not quiet and key != last:
            safe_print(
                f"- [TASK] `{task_id}` status=`{status}` progress=`{pct}` elapsed=`{fmt_seconds(elapsed)}`"
            )
            events.append({"elapsed_sec": elapsed, "status": status, "progress": pct})
            last = key
            last_heartbeat = elapsed
        elif not quiet and heartbeat_sec > 0 and elapsed - last_heartbeat >= heartbeat_sec:
            safe_print(
                f"- [TASK] `{task_id}` waiting status=`{status}` progress=`{pct}` elapsed=`{fmt_seconds(elapsed)}`"
            )
            last_heartbeat = elapsed
        if status in {"completed", "failed", "cancelled"}:
            if events:
                task["_progress_events"] = events
            return task
        if timeout_sec > 0 and time.time() - start > timeout_sec:
            raise ApiError(f"Task {task_id} timeout after {timeout_sec}s")
        time.sleep(max(1, interval_sec))


def download_task(
    base_url: str,
    api_key: str,
    auth_mode: str,
    task_id: str,
    output_dir: str,
    out: Optional[str],
    public_static_dir: Path,
    public_static_subdir: str,
) -> Dict[str, Any]:
    data, hdrs = request_raw("GET", base_url, f"/api/landppt/tasks/{task_id}/download", api_key, auth_mode, timeout=1200)
    saved = save_binary(data, hdrs, output_dir, out, f"task_{task_id}.bin")
    published = publish_to_static(
        saved_file=saved,
        base_url=base_url,
        public_static_dir=public_static_dir,
        public_static_subdir=public_static_subdir,
    )
    return {"task_id": task_id, **published}


def normalize_slides_payload(slides_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    slides: List[Dict[str, Any]] = []
    for i, slide in enumerate(slides_data):
        html = slide.get("html_content")
        if isinstance(html, str) and html.strip():
            slides.append({"index": i, "title": slide.get("title", f"Slide {i+1}"), "html_content": html})
    return slides


def run_command(args: argparse.Namespace) -> Dict[str, Any]:
    api_key = resolve_api_key(args.api_key)
    if not api_key:
        raise ApiError("Missing API key. Pass --api-key or set LANDPPT_USER_API_KEY/LANDPPT_API_KEY.")

    base_url = args.base_url.rstrip("/")
    auth_mode = args.auth_mode
    output_dir = args.output_dir
    public_static_dir = resolve_public_static_dir(args.public_static_dir)
    public_static_subdir = args.public_static_subdir

    if args.command == "share-generate":
        r = call_json("POST", base_url, f"/api/projects/{args.project_id}/share/generate", api_key, auth_mode, timeout=600)
        share_url = r.get("share_url")
        r["share_url_full"] = f"{base_url}{share_url}" if isinstance(share_url, str) and share_url.startswith("/") else share_url
        return r

    if args.command == "outline-update":
        content = read_text(args.outline_file) if args.outline_file else (args.outline_content or "")
        return call_json(
            "POST",
            base_url,
            f"/projects/{args.project_id}/update-outline",
            api_key,
            auth_mode,
            payload={"outline_content": content},
            timeout=600,
        )

    if args.command == "outline-confirm":
        return call_json("POST", base_url, f"/projects/{args.project_id}/confirm-outline", api_key, auth_mode, payload={}, timeout=120)

    if args.command == "ppt-update-html":
        html = read_text(args.html_file)
        return call_json(
            "POST",
            base_url,
            f"/api/projects/{args.project_id}/update-html",
            api_key,
            auth_mode,
            payload={"slides_html": html},
            timeout=600,
        )

    if args.command == "ppt-update-slides":
        source = read_json(args.slides_file)
        slides_data = source.get("slides_data") if isinstance(source, dict) else source
        if not isinstance(slides_data, list):
            raise ApiError("Slides JSON must be list or object with slides_data list")
        return call_json(
            "PUT",
            base_url,
            f"/api/projects/{args.project_id}/slides",
            api_key,
            auth_mode,
            payload={"slides_data": slides_data},
            timeout=600,
        )

    if args.command == "speech-generate":
        payload = {
            "generation_type": args.generation_type,
            "slide_indices": parse_indices(args.slide_indices) or None,
            "language": args.language,
            "customization": {"tone": args.tone, "target_audience": args.target_audience, "language_complexity": args.language_complexity},
        }
        start = call_json("POST", base_url, f"/api/projects/{args.project_id}/speech-script/generate", api_key, auth_mode, payload=payload, timeout=6000)
        if args.wait and start.get("task_id"):
            task_id = str(start["task_id"])
            task = wait_task(
                base_url,
                api_key,
                auth_mode,
                task_id,
                args.task_timeout_sec,
                args.poll_interval_sec,
                args.heartbeat_sec,
                args.quiet,
            )
            result = call_json(
                "GET",
                base_url,
                f"/api/projects/{args.project_id}/speech-scripts/result/{task_id}",
                api_key,
                auth_mode,
                query={"language": args.language},
                timeout=600,
            )
            return {"start": start, "task": task, "result": result}
        if start.get("task_id"):
            start["next_steps"] = task_next_steps(
                base_url=base_url,
                auth_mode=auth_mode,
                task_id=str(start["task_id"]),
                output_dir=output_dir,
                command_file="scripts/project_ops.py",
            )
        return start

    if args.command == "speech-list":
        return call_json(
            "GET",
            base_url,
            f"/api/projects/{args.project_id}/speech-scripts",
            api_key,
            auth_mode,
            query={"language": args.language},
            timeout=600,
        )

    if args.command == "speech-update":
        payload = {
            "script_content": args.script_content,
            "slide_title": args.slide_title,
            "estimated_duration": args.estimated_duration,
            "speaker_notes": args.speaker_notes,
        }
        return call_json(
            "PUT",
            base_url,
            f"/api/projects/{args.project_id}/speech-scripts/slide/{args.slide_index}",
            api_key,
            auth_mode,
            query={"language": args.language},
            payload=payload,
            timeout=600,
        )

    if args.command == "speech-delete":
        return call_json(
            "DELETE",
            base_url,
            f"/api/projects/{args.project_id}/speech-scripts/slide/{args.slide_index}",
            api_key,
            auth_mode,
            query={"language": args.language},
            timeout=600,
        )

    if args.command == "speech-export":
        scripts_resp = call_json(
            "GET",
            base_url,
            f"/api/projects/{args.project_id}/speech-scripts",
            api_key,
            auth_mode,
            query={"language": args.language},
            timeout=600,
        )
        scripts = scripts_resp.get("scripts")
        if not isinstance(scripts, list) or not scripts:
            raise ApiError("No speech scripts available to export")
        data, hdrs = request_raw(
            "POST",
            base_url,
            f"/api/projects/{args.project_id}/speech-script/export",
            api_key,
            auth_mode,
            payload={
                "export_format": args.format,
                "scripts_data": scripts,
                "include_metadata": True,
            },
            timeout=600,
        )
        ext = "md" if args.format == "markdown" else "docx"
        saved = save_binary(data, hdrs, output_dir, args.out, f"speech_scripts_{args.project_id}.{ext}")
        published = publish_to_static(
            saved_file=saved,
            base_url=base_url,
            public_static_dir=public_static_dir,
            public_static_subdir=public_static_subdir,
        )
        return {"project_id": args.project_id, "format": args.format, **published}

    if args.command == "narration-generate":
        payload = {
            "provider": args.provider,
            "language": args.language,
            "slide_indices": parse_indices(args.slide_indices) or None,
            "voice": args.voice or None,
            "rate": args.rate,
            "reference_audio_path": args.reference_audio_path or None,
            "reference_text": args.reference_text or "",
            "force_regenerate": bool(args.force_regenerate),
        }
        start = call_json("POST", base_url, f"/api/projects/{args.project_id}/narration/generate", api_key, auth_mode, payload=payload, timeout=600)
        if args.wait and start.get("task_id"):
            task = wait_task(
                base_url,
                api_key,
                auth_mode,
                str(start["task_id"]),
                args.task_timeout_sec,
                args.poll_interval_sec,
                args.heartbeat_sec,
                args.quiet,
            )
            return {"start": start, "task": task}
        if start.get("task_id"):
            start["next_steps"] = task_next_steps(
                base_url=base_url,
                auth_mode=auth_mode,
                task_id=str(start["task_id"]),
                output_dir=output_dir,
                command_file="scripts/project_ops.py",
            )
        return start

    if args.command == "narration-download":
        data, hdrs = request_raw(
            "GET",
            base_url,
            f"/api/projects/{args.project_id}/narration/audio/{args.slide_index}",
            api_key,
            auth_mode,
            query={"language": args.language, "autogen": str(not args.no_autogen).lower()},
            timeout=600,
        )
        saved = save_binary(data, hdrs, output_dir, args.out, f"narration_{args.project_id}_{args.slide_index}.bin")
        published = publish_to_static(
            saved_file=saved,
            base_url=base_url,
            public_static_dir=public_static_dir,
            public_static_subdir=public_static_subdir,
        )
        return {"project_id": args.project_id, "slide_index": args.slide_index, **published}

    if args.command == "export-html":
        data, hdrs = request_raw("GET", base_url, f"/api/projects/{args.project_id}/export/html", api_key, auth_mode, timeout=900)
        saved = save_binary(data, hdrs, output_dir, args.out, f"{args.project_id}.zip")
        published = publish_to_static(
            saved_file=saved,
            base_url=base_url,
            public_static_dir=public_static_dir,
            public_static_subdir=public_static_subdir,
        )
        return {"project_id": args.project_id, **published}

    if args.command == "export-pdf":
        if args.mode == "sync":
            data, hdrs = request_raw("GET", base_url, f"/api/projects/{args.project_id}/export/pdf", api_key, auth_mode, timeout=1800)
            saved = save_binary(data, hdrs, output_dir, args.out, f"{args.project_id}.pdf")
            published = publish_to_static(
                saved_file=saved,
                base_url=base_url,
                public_static_dir=public_static_dir,
                public_static_subdir=public_static_subdir,
            )
            return {"mode": "sync", "project_id": args.project_id, **published}
        start = call_json("POST", base_url, f"/api/projects/{args.project_id}/export/pdf/async", api_key, auth_mode, timeout=600)
        if args.wait and start.get("task_id"):
            task_id = str(start["task_id"])
            task = wait_task(
                base_url,
                api_key,
                auth_mode,
                task_id,
                args.task_timeout_sec,
                args.poll_interval_sec,
                args.heartbeat_sec,
                args.quiet,
            )
            return {
                "start": start,
                "task": task,
                "download": download_task(
                    base_url,
                    api_key,
                    auth_mode,
                    task_id,
                    output_dir,
                    args.out,
                    public_static_dir,
                    public_static_subdir,
                ),
            }
        if start.get("task_id"):
            start["next_steps"] = task_next_steps(
                base_url=base_url,
                auth_mode=auth_mode,
                task_id=str(start["task_id"]),
                output_dir=output_dir,
                command_file="scripts/project_ops.py",
            )
        return {"start": start}

    if args.command == "export-pptx-standard":
        start = call_json("GET", base_url, f"/api/projects/{args.project_id}/export/pptx", api_key, auth_mode, timeout=600)
        if args.wait and start.get("task_id"):
            task_id = str(start["task_id"])
            task = wait_task(
                base_url,
                api_key,
                auth_mode,
                task_id,
                args.task_timeout_sec,
                args.poll_interval_sec,
                args.heartbeat_sec,
                args.quiet,
            )
            return {
                "start": start,
                "task": task,
                "download": download_task(
                    base_url,
                    api_key,
                    auth_mode,
                    task_id,
                    output_dir,
                    args.out,
                    public_static_dir,
                    public_static_subdir,
                ),
            }
        if start.get("task_id"):
            start["next_steps"] = task_next_steps(
                base_url=base_url,
                auth_mode=auth_mode,
                task_id=str(start["task_id"]),
                output_dir=output_dir,
                command_file="scripts/project_ops.py",
            )
        return {"start": start}

    if args.command == "export-pptx-images":
        if args.slides_file:
            src = read_json(args.slides_file)
            slides = src.get("slides") if isinstance(src, dict) else src
            if not isinstance(slides, list):
                raise ApiError("slides-file must be list or object with slides list")
        else:
            slides_resp = call_json("GET", base_url, f"/api/projects/{args.project_id}/slides-data", api_key, auth_mode, timeout=600)
            slides_data = slides_resp.get("slides_data")
            if not isinstance(slides_data, list) or not slides_data:
                raise ApiError("No slides_data available for pptx-images export")
            slides = normalize_slides_payload(slides_data)
        if not slides:
            raise ApiError("No valid slides for pptx-images export")
        start = call_json(
            "POST",
            base_url,
            f"/api/projects/{args.project_id}/export/pptx-images",
            api_key,
            auth_mode,
            payload={"slides": slides},
            timeout=600,
        )
        if args.wait and start.get("task_id"):
            task_id = str(start["task_id"])
            task = wait_task(
                base_url,
                api_key,
                auth_mode,
                task_id,
                args.task_timeout_sec,
                args.poll_interval_sec,
                args.heartbeat_sec,
                args.quiet,
            )
            return {
                "start": start,
                "task": task,
                "download": download_task(
                    base_url,
                    api_key,
                    auth_mode,
                    task_id,
                    output_dir,
                    args.out,
                    public_static_dir,
                    public_static_subdir,
                ),
            }
        if start.get("task_id"):
            start["next_steps"] = task_next_steps(
                base_url=base_url,
                auth_mode=auth_mode,
                task_id=str(start["task_id"]),
                output_dir=output_dir,
                command_file="scripts/project_ops.py",
            )
        return {"start": start}

    if args.command == "task-status":
        return call_json(
            "GET",
            base_url,
            f"/api/landppt/tasks/{args.task_id}",
            api_key,
            auth_mode,
            timeout=600,
        )

    if args.command == "task-download":
        return download_task(
            base_url,
            api_key,
            auth_mode,
            args.task_id,
            output_dir,
            args.out,
            public_static_dir,
            public_static_subdir,
        )

    raise ApiError(f"Unsupported command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="LandPPT project operations script")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--api-key", default="")
    p.add_argument("--auth-mode", choices=["bearer", "x-api-key"], default="bearer")
    p.add_argument("--poll-interval-sec", type=int, default=5)
    p.add_argument("--heartbeat-sec", type=int, default=20)
    p.add_argument("--task-timeout-sec", type=int, default=3600)
    p.add_argument("--output-dir", default=".")
    p.add_argument(
        "--public-static-dir",
        default="",
        help="Static root directory used to publish downloadable files. Defaults to <repo>/src/landppt/web/static or LANDPPT_PUBLIC_STATIC_DIR.",
    )
    p.add_argument(
        "--public-static-subdir",
        default="downloads",
        help="Subdirectory under /static used for published files.",
    )
    p.add_argument("--quiet", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("share-generate")
    sp.add_argument("--project-id", required=True)

    sp = sub.add_parser("outline-update")
    sp.add_argument("--project-id", required=True)
    g = sp.add_mutually_exclusive_group(required=True)
    g.add_argument("--outline-content")
    g.add_argument("--outline-file")

    sp = sub.add_parser("outline-confirm")
    sp.add_argument("--project-id", required=True)

    sp = sub.add_parser("ppt-update-html")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--html-file", required=True)

    sp = sub.add_parser("ppt-update-slides")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--slides-file", required=True)

    sp = sub.add_parser("speech-generate")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--generation-type", choices=["single", "multi", "full"], default="full")
    sp.add_argument("--slide-indices", default="")
    sp.add_argument("--language", default="zh")
    sp.add_argument("--tone", default="conversational")
    sp.add_argument("--target-audience", default="general_public")
    sp.add_argument("--language-complexity", default="moderate")
    sp.add_argument("--wait", action=argparse.BooleanOptionalAction, default=False)

    sp = sub.add_parser("speech-list")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--language", default="zh")

    sp = sub.add_parser("speech-update")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--slide-index", required=True, type=int)
    sp.add_argument("--script-content", required=True)
    sp.add_argument("--slide-title", default="")
    sp.add_argument("--estimated-duration", default="")
    sp.add_argument("--speaker-notes", default="")
    sp.add_argument("--language", default="zh")

    sp = sub.add_parser("speech-delete")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--slide-index", required=True, type=int)
    sp.add_argument("--language", default="zh")

    sp = sub.add_parser("speech-export")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--format", choices=["docx", "markdown"], default="docx")
    sp.add_argument("--language", default="zh")
    sp.add_argument("--out", default=None)

    sp = sub.add_parser("narration-generate")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--provider", default="edge_tts")
    sp.add_argument("--language", default="zh")
    sp.add_argument("--slide-indices", default="")
    sp.add_argument("--voice", default="")
    sp.add_argument("--rate", default="+0%")
    sp.add_argument("--reference-audio-path", default="")
    sp.add_argument("--reference-text", default="")
    sp.add_argument("--force-regenerate", action="store_true")
    sp.add_argument("--wait", action=argparse.BooleanOptionalAction, default=False)

    sp = sub.add_parser("narration-download")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--slide-index", required=True, type=int)
    sp.add_argument("--language", default="zh")
    sp.add_argument("--no-autogen", action="store_true")
    sp.add_argument("--out", default=None)

    sp = sub.add_parser("export-html")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--out", default=None)

    sp = sub.add_parser("export-pdf")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--mode", choices=["sync", "async"], default="async")
    sp.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)
    sp.add_argument("--out", default=None)

    sp = sub.add_parser("export-pptx-standard")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)
    sp.add_argument("--out", default=None)

    sp = sub.add_parser("export-pptx-images")
    sp.add_argument("--project-id", required=True)
    sp.add_argument("--slides-file", default=None)
    sp.add_argument("--wait", action=argparse.BooleanOptionalAction, default=True)
    sp.add_argument("--out", default=None)

    sp = sub.add_parser("task-status")
    sp.add_argument("--task-id", required=True)

    sp = sub.add_parser("task-download")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--out", default=None)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    start = time.time()
    try:
        result = run_command(args)
        if isinstance(result, dict):
            result["elapsed_sec"] = round(time.time() - start, 2)
        print_markdown_result(args.command, success=True, result=result)
        return 0
    except ApiError as exc:
        payload = {"elapsed_sec": round(time.time() - start, 2)}
        print_markdown_result(args.command, success=False, result=payload, error=str(exc))
        return 3
    except Exception as exc:
        payload = {"elapsed_sec": round(time.time() - start, 2)}
        print_markdown_result(
            args.command,
            success=False,
            result=payload,
            error=f"Unexpected error: {exc}",
        )
        return 4


if __name__ == "__main__":
    sys.exit(main())
