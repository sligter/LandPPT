#!/usr/bin/env python3
"""Run full LandPPT API workflow with a user API key.

Workflow:
1) Create project
2) Confirm requirements
3) Generate outline
4) Select free template
5) Generate and confirm free template
6) Generate slides via SSE stream
7) Verify final project completion and slide count
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error, parse, request


class WorkflowError(RuntimeError):
    """Raised when workflow execution fails."""


def safe_print(message: str) -> None:
    """Print text safely on terminals with limited encodings (e.g. Windows GBK)."""
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sanitized = message.encode(encoding, errors="replace").decode(
            encoding, errors="replace"
        )
        print(sanitized)


def _fmt_seconds(value: float) -> str:
    seconds = int(max(0, value))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {sec}s"
    if minutes > 0:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def print_markdown_summary(summary: Dict[str, Any], *, success: bool) -> None:
    title = "## LandPPT Workflow Result" if success else "## LandPPT Workflow Failed"
    safe_print(title)
    safe_print("")
    safe_print(f"- success: `{str(bool(success)).lower()}`")
    safe_print(f"- base_url: `{summary.get('base_url', '')}`")
    safe_print(f"- topic: `{summary.get('topic', '')}`")
    if summary.get("project_id"):
        safe_print(f"- project_id: `{summary.get('project_id')}`")
    if summary.get("final_project_status") is not None:
        safe_print(f"- final_project_status: `{summary.get('final_project_status')}`")
    if summary.get("final_slides_count") is not None:
        safe_print(f"- final_slides_count: `{summary.get('final_slides_count')}`")
    if summary.get("share_url"):
        safe_print(f"- share_url: [{summary.get('share_url')}]({summary.get('share_url')})")
    if summary.get("public_file_url"):
        safe_print(f"- file_url: [{summary.get('public_file_url')}]({summary.get('public_file_url')})")
    if summary.get("elapsed_sec") is not None:
        safe_print(f"- elapsed: `{_fmt_seconds(float(summary.get('elapsed_sec') or 0))}`")
    if summary.get("error"):
        safe_print(f"- error: `{summary.get('error')}`")
    safe_print("")
    safe_print("### Raw Summary")
    safe_print("```json")
    safe_print(json.dumps(summary, ensure_ascii=False, indent=2))
    safe_print("```")


def _headers(
    api_key: str,
    content_type: Optional[str] = None,
    *,
    auth_mode: str = "bearer",
) -> Dict[str, str]:
    """Build request headers.

    Some hosted deployments sit behind bot-protection/WAF rules (e.g. Cloudflare)
    that may block Python's default urllib User-Agent (HTTP 403 / 1010).
    Always send a browser-like User-Agent by default.
    """
    headers: Dict[str, str]
    if auth_mode == "x-api-key":
        headers = {"X-API-Key": api_key}
    else:
        headers = {"Authorization": f"Bearer {api_key}"}

    # WAF/bot protection compatibility
    headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    )
    headers.setdefault("Accept", "application/json, text/event-stream;q=0.9, */*;q=0.8")

    if content_type:
        headers["Content-Type"] = content_type
    return headers


def call_json(
    method: str,
    url: str,
    api_key: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    form: Optional[Dict[str, Any]] = None,
    timeout: int = 120,
    auth_mode: str = "bearer",
) -> Dict[str, Any]:
    data: Optional[bytes] = None
    headers = _headers(api_key, auth_mode=auth_mode)

    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif form is not None:
        encoded = parse.urlencode(form)
        data = encoded.encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = request.Request(url, data=data, headers=headers, method=method)

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "ignore")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise WorkflowError(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise WorkflowError(f"{method} {url} failed: {exc}") from exc

    if not raw:
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        snippet = raw[:500]
        raise WorkflowError(f"{method} {url} returned non-JSON payload: {snippet}") from exc


def call_binary(
    method: str,
    url: str,
    api_key: str,
    *,
    timeout: int = 1200,
    auth_mode: str = "bearer",
) -> tuple[bytes, Dict[str, str]]:
    req = request.Request(url, headers=_headers(api_key, auth_mode=auth_mode), method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), dict(resp.headers.items())
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise WorkflowError(f"{method} {url} failed: HTTP {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise WorkflowError(f"{method} {url} failed: {exc}") from exc


def parse_outline_count(outline_content: Any) -> int:
    if outline_content is None:
        return 0

    outline_obj: Optional[Dict[str, Any]] = None

    if isinstance(outline_content, str):
        try:
            outline_obj = json.loads(outline_content)
        except json.JSONDecodeError:
            return 0
    elif isinstance(outline_content, dict):
        outline_obj = outline_content

    if not isinstance(outline_obj, dict):
        return 0

    slides = outline_obj.get("slides")
    if isinstance(slides, list):
        return len(slides)

    return 0


def _filename_from_headers(headers_map: Dict[str, str], fallback: str) -> str:
    cd = headers_map.get("Content-Disposition", "") or headers_map.get("content-disposition", "")
    if cd:
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
        if m:
            return parse.unquote(m.group(1))
        m = re.search(r'filename="?([^";]+)"?', cd)
        if m:
            return m.group(1)
    return fallback


def resolve_public_static_dir(cli_value: str) -> Path:
    from_env = (os.environ.get("LANDPPT_PUBLIC_STATIC_DIR") or "").strip()
    if from_env:
        return Path(from_env).resolve()
    if (cli_value or "").strip():
        return Path(cli_value).resolve()
    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[3]
    return (repo_root / "src" / "landppt" / "web" / "static").resolve()


def save_export_file(
    *,
    data: bytes,
    headers_map: Dict[str, str],
    output_dir: str,
    out: str,
    fallback_name: str,
) -> str:
    target = Path(out).resolve() if out else (Path(output_dir).resolve() / _filename_from_headers(headers_map, fallback_name))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(target)


def publish_to_static(
    *,
    saved_file: str,
    base_url: str,
    public_static_dir: Path,
    public_static_subdir: str,
) -> Dict[str, str]:
    source = Path(saved_file).resolve()
    if not source.exists():
        raise WorkflowError(f"Saved file does not exist: {source}")

    subdir = (public_static_subdir or "downloads").strip().strip("/\\")
    publish_dir = public_static_dir / subdir if subdir else public_static_dir
    publish_dir.mkdir(parents=True, exist_ok=True)

    target = publish_dir / source.name
    if target.exists():
        target = publish_dir / f"{source.stem}_{int(time.time())}{source.suffix}"

    shutil.copy2(source, target)
    if subdir:
        public_path = f"/static/{subdir}/{parse.quote(target.name)}"
    else:
        public_path = f"/static/{parse.quote(target.name)}"

    return {
        "saved_file": str(source),
        "public_file_path": public_path,
        "public_file_url": f"{base_url.rstrip('/')}{public_path}",
    }


def stream_slides(
    base_url: str,
    project_id: str,
    api_key: str,
    *,
    timeout_sec: int,
    disconnect_after_sec: int = 0,
    auth_mode: str = "bearer",
    verbose: bool = True,
) -> Dict[str, Any]:
    url = f"{base_url}/api/projects/{project_id}/slides/stream"
    req = request.Request(
        url, headers=_headers(api_key, auth_mode=auth_mode), method="GET"
    )

    slide_events = 0
    progress_events = 0
    complete_events = 0
    error_events = 0

    start = time.time()
    last_progress = None

    open_timeout = timeout_sec + 60 if timeout_sec > 0 else 3600

    try:
        with request.urlopen(req, timeout=open_timeout) as resp:
            while True:
                elapsed = time.time() - start

                if timeout_sec > 0 and elapsed > timeout_sec:
                    raise WorkflowError(
                        f"Slides stream timed out after {timeout_sec}s for project {project_id}"
                    )

                if disconnect_after_sec > 0 and elapsed >= disconnect_after_sec:
                    if verbose:
                        safe_print(
                            f"- [INFO] Intentionally disconnecting stream after {disconnect_after_sec}s"
                        )
                    return {
                        "slide_events": slide_events,
                        "progress_events": progress_events,
                        "complete_events": complete_events,
                        "error_events": error_events,
                        "completed": False,
                        "disconnected": True,
                    }

                raw_line = resp.readline()
                if raw_line == b"":
                    break

                line = raw_line.decode("utf-8", "ignore").strip()
                if not line.startswith("data: "):
                    continue

                payload_raw = line[6:]
                try:
                    event = json.loads(payload_raw)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "progress":
                    progress_events += 1
                    current = event.get("current")
                    total = event.get("total")
                    progress_key = (current, total)
                    if verbose and progress_key != last_progress:
                        elapsed = _fmt_seconds(time.time() - start)
                        safe_print(
                            f"- [STREAM] progress current={current} total={total} elapsed={elapsed} message={event.get('message')}"
                        )
                        last_progress = progress_key
                elif event_type == "slide":
                    slide_events += 1
                    if verbose:
                        slide_data = event.get("slide_data") or {}
                        elapsed = _fmt_seconds(time.time() - start)
                        safe_print(
                            f"- [STREAM] slide #{slide_events} elapsed={elapsed} title={slide_data.get('title', '<unknown>')}"
                        )
                elif event_type == "complete":
                    complete_events += 1
                    if verbose:
                        safe_print(f"- [STREAM] complete message={event.get('message')}")
                    return {
                        "slide_events": slide_events,
                        "progress_events": progress_events,
                        "complete_events": complete_events,
                        "error_events": error_events,
                        "completed": True,
                        "disconnected": False,
                    }
                elif event_type == "error":
                    error_events += 1
                    raise WorkflowError(f"Slides stream error event: {event}")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        raise WorkflowError(f"GET {url} failed: HTTP {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise WorkflowError(f"GET {url} failed: {exc}") from exc

    return {
        "slide_events": slide_events,
        "progress_events": progress_events,
        "complete_events": complete_events,
        "error_events": error_events,
        "completed": complete_events > 0,
        "disconnected": False,
    }


def wait_for_completion(
    base_url: str,
    project_id: str,
    api_key: str,
    *,
    expected_pages: int,
    poll_interval_sec: int,
    timeout_sec: int,
    heartbeat_sec: int = 20,
    auth_mode: str = "bearer",
    verbose: bool = True,
) -> Dict[str, Any]:
    start = time.time()
    last_state = None
    last_heartbeat = -1

    while True:
        project = call_json(
            "GET",
            f"{base_url}/api/projects/{project_id}",
            api_key,
            timeout=600,
            auth_mode=auth_mode,
        )

        status = project.get("status")
        slides_count = int(project.get("slides_count") or 0)
        state = (status, slides_count)
        elapsed_sec = int(time.time() - start)

        if verbose and state != last_state:
            safe_print(
                f"- [POLL] status={status} slides_count={slides_count} elapsed={_fmt_seconds(elapsed_sec)}"
            )
            last_state = state
            last_heartbeat = elapsed_sec
        elif (
            verbose
            and heartbeat_sec > 0
            and elapsed_sec - last_heartbeat >= heartbeat_sec
        ):
            safe_print(
                f"- [WAIT] still running status={status} slides_count={slides_count} elapsed={_fmt_seconds(elapsed_sec)}"
            )
            last_heartbeat = elapsed_sec

        if status == "completed" and slides_count >= expected_pages:
            return project

        if timeout_sec > 0 and (time.time() - start) > timeout_sec:
            raise WorkflowError(
                f"Project {project_id} did not complete within {timeout_sec}s"
            )

        time.sleep(max(1, poll_interval_sec))


def wait_for_task_completion(
    base_url: str,
    task_id: str,
    api_key: str,
    *,
    poll_interval_sec: int,
    timeout_sec: int,
    heartbeat_sec: int,
    auth_mode: str = "bearer",
    verbose: bool = True,
) -> Dict[str, Any]:
    start = time.time()
    last_state = None
    last_heartbeat = -1

    while True:
        task = call_json(
            "GET",
            f"{base_url}/api/landppt/tasks/{task_id}",
            api_key,
            timeout=600,
            auth_mode=auth_mode,
        )
        status = task.get("status")
        progress = task.get("progress")
        if isinstance(progress, dict):
            progress_value = progress.get("percentage")
        else:
            progress_value = progress

        elapsed_sec = int(time.time() - start)
        state = (status, progress_value)

        if verbose and state != last_state:
            safe_print(
                f"- [TASK] status={status} progress={progress_value} elapsed={_fmt_seconds(elapsed_sec)}"
            )
            last_state = state
            last_heartbeat = elapsed_sec
        elif (
            verbose
            and heartbeat_sec > 0
            and elapsed_sec - last_heartbeat >= heartbeat_sec
        ):
            safe_print(
                f"- [TASK] waiting status={status} progress={progress_value} elapsed={_fmt_seconds(elapsed_sec)}"
            )
            last_heartbeat = elapsed_sec

        if status in {"completed", "failed", "cancelled"}:
            return task

        if timeout_sec > 0 and (time.time() - start) > timeout_sec:
            raise WorkflowError(
                f"Task {task_id} did not complete within {timeout_sec}s"
            )

        time.sleep(max(1, poll_interval_sec))


def export_pdf_and_publish(
    *,
    base_url: str,
    project_id: str,
    api_key: str,
    output_dir: str,
    out: str,
    public_static_dir: Path,
    public_static_subdir: str,
    poll_interval_sec: int,
    timeout_sec: int,
    heartbeat_sec: int,
    auth_mode: str = "bearer",
    verbose: bool = True,
) -> Dict[str, Any]:
    start = call_json(
        "POST",
        f"{base_url}/api/projects/{project_id}/export/pdf/async",
        api_key,
        timeout=600,
        auth_mode=auth_mode,
    )
    task_id = start.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise WorkflowError(f"Export PDF did not return task_id: {start}")

    if verbose:
        safe_print(f"- [STEP] Wait export task {task_id}")
    task = wait_for_task_completion(
        base_url,
        task_id,
        api_key,
        poll_interval_sec=poll_interval_sec,
        timeout_sec=timeout_sec,
        heartbeat_sec=heartbeat_sec,
        auth_mode=auth_mode,
        verbose=verbose,
    )
    if task.get("status") != "completed":
        raise WorkflowError(f"Export PDF task failed: {task}")

    if verbose:
        safe_print("- [STEP] Download exported PDF")
    data, hdrs = call_binary(
        "GET",
        f"{base_url}/api/landppt/tasks/{task_id}/download",
        api_key,
        timeout=1200,
        auth_mode=auth_mode,
    )
    saved_file = save_export_file(
        data=data,
        headers_map=hdrs,
        output_dir=output_dir,
        out=out,
        fallback_name=f"{project_id}.pdf",
    )
    published = publish_to_static(
        saved_file=saved_file,
        base_url=base_url,
        public_static_dir=public_static_dir,
        public_static_subdir=public_static_subdir,
    )
    return {
        "task_id": task_id,
        "task_status": task.get("status"),
        **published,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run and verify full LandPPT API workflow with user API key."
    )
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--scenario", default="general")
    parser.add_argument("--topic", required=True)
    parser.add_argument(
        "--requirements",
        default="Management report with strategy, implementation path, risk, and ROI.",
    )
    parser.add_argument("--language", default="zh")
    parser.add_argument("--network-mode", action="store_true")
    parser.add_argument("--audience-type", default="management")
    parser.add_argument("--page-count", type=int, default=12)
    parser.add_argument("--ppt-style", default="general")
    parser.add_argument(
        "--description",
        default="End-to-end automated PPT generation test",
    )
    parser.add_argument("--stream-timeout-sec", type=int, default=3600)
    parser.add_argument("--disconnect-after-sec", type=int, default=0)
    parser.add_argument("--poll-interval-sec", type=int, default=10)
    parser.add_argument("--completion-timeout-sec", type=int, default=3600)
    parser.add_argument("--heartbeat-sec", type=int, default=20)
    parser.add_argument("--auth-mode", choices=["bearer", "x-api-key"], default="bearer")
    parser.add_argument("--strict-outline-pages", action="store_true")
    parser.add_argument(
        "--skip-share-link",
        action="store_true",
        help="Do not generate project share link after successful PPT generation.",
    )
    parser.add_argument(
        "--default-export-format",
        choices=["pdf", "none"],
        default="pdf",
        help="Default post-generation export type. Use 'none' to skip.",
    )
    parser.add_argument(
        "--export-timeout-sec",
        type=int,
        default=3600,
        help="Timeout for default export task.",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Local directory for downloaded export files.",
    )
    parser.add_argument(
        "--export-out",
        default="",
        help="Optional explicit output file path for default export.",
    )
    parser.add_argument(
        "--public-static-dir",
        default="",
        help="Static root for published public files. Defaults to <repo>/src/landppt/web/static or LANDPPT_PUBLIC_STATIC_DIR.",
    )
    parser.add_argument(
        "--public-static-subdir",
        default="downloads",
        help="Subdirectory under /static used for published files.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    api_key = args.api_key.strip() or os.environ.get("LANDPPT_USER_API_KEY", "").strip()
    if not api_key:
        api_key = os.environ.get("LANDPPT_API_KEY", "").strip()
    if not api_key:
        print(
            "[ERROR] Missing API key. Pass --api-key or set LANDPPT_USER_API_KEY/LANDPPT_API_KEY."
        )
        return 2

    base_url = args.base_url.rstrip("/")
    auth_mode = args.auth_mode
    verbose = not args.quiet
    public_static_dir = resolve_public_static_dir(args.public_static_dir)

    summary: Dict[str, Any] = {
        "base_url": base_url,
        "topic": args.topic,
        "scenario": args.scenario,
        "target_pages": args.page_count,
    }
    workflow_start = time.time()

    try:
        if verbose:
            safe_print("- [STEP] Verify API key")
        me = call_json(
            "GET",
            f"{base_url}/api/auth/me",
            api_key,
            timeout=60,
            auth_mode=auth_mode,
        )
        summary["user"] = (me.get("user") or {}).get("username")

        if verbose:
            safe_print("- [STEP] Create project")
        create_payload = {
            "scenario": args.scenario,
            "topic": args.topic,
            "requirements": args.requirements,
            "language": args.language,
            "network_mode": bool(args.network_mode),
        }
        project = call_json(
            "POST",
            f"{base_url}/api/projects",
            api_key,
            payload=create_payload,
            timeout=120,
            auth_mode=auth_mode,
        )
        project_id = project.get("project_id")
        if not project_id:
            raise WorkflowError(f"Create project response missing project_id: {project}")
        summary["project_id"] = project_id

        if verbose:
            safe_print("- [STEP] Confirm requirements")
        confirm_form = {
            "topic": args.topic,
            "audience_type": args.audience_type,
            "page_count_mode": "fixed",
            "fixed_pages": args.page_count,
            "ppt_style": args.ppt_style,
            "description": args.description,
            "content_source": "manual",
        }
        confirm_resp = call_json(
            "POST",
            f"{base_url}/projects/{project_id}/confirm-requirements",
            api_key,
            form=confirm_form,
            timeout=120,
            auth_mode=auth_mode,
        )
        if confirm_resp.get("status") != "success":
            raise WorkflowError(f"Confirm requirements failed: {confirm_resp}")

        if verbose:
            safe_print("- [STEP] Generate outline")
        outline_resp = call_json(
            "POST",
            f"{base_url}/projects/{project_id}/generate-outline",
            api_key,
            timeout=300,
            auth_mode=auth_mode,
        )
        if outline_resp.get("status") != "success":
            raise WorkflowError(f"Generate outline failed: {outline_resp}")

        outline_count = parse_outline_count(outline_resp.get("outline_content"))
        summary["outline_slides"] = outline_count

        if args.strict_outline_pages and outline_count != args.page_count:
            raise WorkflowError(
                f"Outline slide count mismatch: expected {args.page_count}, got {outline_count}"
            )

        if verbose:
            safe_print("- [STEP] Select free template mode")
        select_payload = {"project_id": project_id, "template_mode": "free"}
        select_resp = call_json(
            "POST",
            f"{base_url}/api/projects/{project_id}/select-template",
            api_key,
            payload=select_payload,
            timeout=120,
            auth_mode=auth_mode,
        )
        if not select_resp.get("success"):
            raise WorkflowError(f"Select template failed: {select_resp}")

        if verbose:
            safe_print("- [STEP] Generate free template")
        free_gen_resp = call_json(
            "POST",
            f"{base_url}/api/projects/{project_id}/free-template/generate",
            api_key,
            payload={},
            timeout=600,
            auth_mode=auth_mode,
        )
        if not free_gen_resp.get("success"):
            raise WorkflowError(f"Free template generation failed: {free_gen_resp}")

        if verbose:
            safe_print("- [STEP] Confirm free template")
        free_confirm_resp = call_json(
            "POST",
            f"{base_url}/api/projects/{project_id}/free-template/confirm",
            api_key,
            payload={"save_to_library": False},
            timeout=120,
            auth_mode=auth_mode,
        )
        if not free_confirm_resp.get("success"):
            raise WorkflowError(f"Free template confirm failed: {free_confirm_resp}")

        if verbose:
            safe_print("- [STEP] Stream slides generation")
        stream_result = stream_slides(
            base_url,
            project_id,
            api_key,
            timeout_sec=args.stream_timeout_sec,
            disconnect_after_sec=max(0, args.disconnect_after_sec),
            auth_mode=auth_mode,
            verbose=verbose,
        )
        summary["stream"] = stream_result

        if verbose:
            safe_print("- [STEP] Verify final completion")
        final_project = wait_for_completion(
            base_url,
            project_id,
            api_key,
            expected_pages=args.page_count,
            poll_interval_sec=args.poll_interval_sec,
            timeout_sec=args.completion_timeout_sec,
            heartbeat_sec=max(0, args.heartbeat_sec),
            auth_mode=auth_mode,
            verbose=verbose,
        )
        final_status = final_project.get("status")
        final_slides_count = int(final_project.get("slides_count") or 0)
        summary["final_project_status"] = final_status
        summary["final_slides_count"] = final_slides_count

        slides_data_resp = call_json(
            "GET",
            f"{base_url}/api/projects/{project_id}/slides-data",
            api_key,
            timeout=120,
            auth_mode=auth_mode,
        )
        summary["slides_data_total"] = int(slides_data_resp.get("total_slides") or 0)

        summary["success"] = (
            final_status == "completed"
            and final_slides_count >= args.page_count
            and summary["slides_data_total"] >= args.page_count
        )

        if summary["success"] and not args.skip_share_link:
            if verbose:
                safe_print("- [STEP] Generate share link")
            share_resp = call_json(
                "POST",
                f"{base_url}/api/projects/{project_id}/share/generate",
                api_key,
                timeout=120,
                auth_mode=auth_mode,
            )
            summary["share_link_success"] = bool(share_resp.get("success"))
            summary["share_token"] = share_resp.get("share_token")
            share_path = share_resp.get("share_url")
            summary["share_url_path"] = share_path
            if isinstance(share_path, str) and share_path.strip():
                if share_path.startswith("http://") or share_path.startswith("https://"):
                    summary["share_url"] = share_path
                else:
                    summary["share_url"] = f"{base_url}{share_path}"
            else:
                summary["share_url"] = None

        if summary["success"] and args.default_export_format == "pdf":
            if verbose:
                safe_print("- [STEP] Export default PDF")
            export_result = export_pdf_and_publish(
                base_url=base_url,
                project_id=project_id,
                api_key=api_key,
                output_dir=args.output_dir,
                out=args.export_out,
                public_static_dir=public_static_dir,
                public_static_subdir=args.public_static_subdir,
                poll_interval_sec=args.poll_interval_sec,
                timeout_sec=args.export_timeout_sec,
                heartbeat_sec=max(0, args.heartbeat_sec),
                auth_mode=auth_mode,
                verbose=verbose,
            )
            summary["default_export_format"] = "pdf"
            summary["default_export"] = export_result
            summary["public_file_url"] = export_result.get("public_file_url")
            summary["public_file_path"] = export_result.get("public_file_path")
            summary["saved_file"] = export_result.get("saved_file")

        summary["elapsed_sec"] = round(time.time() - workflow_start, 2)
        print_markdown_summary(summary, success=bool(summary["success"]))

        if not summary["success"]:
            return 3

        return 0

    except WorkflowError as exc:
        summary["success"] = False
        summary["error"] = str(exc)
        summary["elapsed_sec"] = round(time.time() - workflow_start, 2)
        print_markdown_summary(summary, success=False)
        return 4


if __name__ == "__main__":
    sys.exit(main())
