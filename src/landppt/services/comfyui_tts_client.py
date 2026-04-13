"""
ComfyUI API client helpers for TTS workflows.

This module focuses on:
- Building a Qwen3-TD-TTS workflow from a JSON template (tests/Qwen3-TD-TTS.json)
- Uploading reference audio to ComfyUI (input folder)
- Submitting prompts, polling history, and downloading output audio
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import aiohttp


def load_workflow_template(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"ComfyUI workflow template not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def build_qwen3_td_tts_workflow(
    template: Dict[str, Any],
    *,
    text: str,
    ref_audio_filename: str,
    language: str = "zh",
    ref_text: str = "",
    model_precision: Optional[str] = None,
    model_device: Optional[str] = None,
    attn_implementation: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Patch the provided workflow template for TD Qwen3 TTS Voice Clone.

    Expected node ids in the provided template:
    - "19": LoadAudio (inputs.audio)
    - "31": TDQwen3TTSVoiceClone (inputs.text, inputs.language, inputs.ref_text, inputs.ref_audio)
    """
    workflow: Dict[str, Any] = copy.deepcopy(template)

    if "19" not in workflow or "31" not in workflow:
        raise ValueError("Unexpected workflow template: missing node '19' or '31'")

    n19 = workflow.get("19") or {}
    n31 = workflow.get("31") or {}
    n24 = workflow.get("24") or {}
    n19_inputs = (n19.get("inputs") or {})
    n31_inputs = (n31.get("inputs") or {})
    n24_inputs = (n24.get("inputs") or {})

    n19_inputs["audio"] = ref_audio_filename
    n31_inputs["text"] = (text or "").strip()
    n31_inputs["ref_text"] = (ref_text or "").strip()

    lang = (language or "zh").strip().lower()
    if lang.startswith("zh"):
        n31_inputs["language"] = "Chinese"
    elif lang.startswith("en"):
        n31_inputs["language"] = "English"
    else:
        # Keep whatever the template expects (or default to Chinese).
        n31_inputs["language"] = n31_inputs.get("language") or "Chinese"

    n19["inputs"] = n19_inputs
    n31["inputs"] = n31_inputs
    workflow["19"] = n19
    workflow["31"] = n31

    # Optional model tuning for memory/perf.
    if isinstance(n24_inputs, dict) and ("24" in workflow):
        if model_precision:
            n24_inputs["precision"] = str(model_precision).strip()
        if model_device:
            n24_inputs["device"] = str(model_device).strip()
        if attn_implementation:
            n24_inputs["attn_implementation"] = str(attn_implementation).strip()
        n24["inputs"] = n24_inputs
        workflow["24"] = n24

    return workflow


async def upload_input_file(
    *,
    session: aiohttp.ClientSession,
    base_url: str,
    file_path: str,
) -> str:
    """
    Upload a local file into ComfyUI's input folder and return the stored filename.

    ComfyUI versions/plugins vary; we try common endpoints.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Reference audio not found: {file_path}")

    endpoints = ["/upload/image", "/upload/audio", "/upload/file"]
    last_error: Optional[str] = None

    for ep in endpoints:
        url = (base_url.rstrip("/") + ep)
        try:
            with open(file_path, "rb") as f:
                form = aiohttp.FormData()
                # Common ComfyUI API expects a multipart field named "image" even for non-images.
                form.add_field(
                    "image",
                    f,
                    filename=os.path.basename(file_path),
                    content_type="application/octet-stream",
                )
                form.add_field("type", "input")
                async with session.post(url, data=form) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        last_error = f"{ep} -> HTTP {resp.status}: {text[:300]}"
                        continue
                    try:
                        payload = json.loads(text) if text else {}
                    except Exception:
                        payload = {}
                    # ComfyUI typically returns {"name":"<filename>"}.
                    name = (
                        (payload.get("name") if isinstance(payload, dict) else None)
                        or (payload.get("filename") if isinstance(payload, dict) else None)
                    )
                    if name:
                        return str(name)
                    # Some variants return raw filename as text.
                    if text and text.strip() and "." in text.strip():
                        return text.strip()
                    last_error = f"{ep} -> unexpected response: {text[:300]}"
        except Exception as e:
            last_error = f"{ep} -> {type(e).__name__}: {e}"
            continue

    raise RuntimeError(f"Failed to upload file to ComfyUI. Last error: {last_error or 'unknown'}")


async def submit_prompt(
    *,
    session: aiohttp.ClientSession,
    base_url: str,
    workflow: Dict[str, Any],
    client_id: Optional[str] = None,
) -> str:
    url = base_url.rstrip("/") + "/prompt"
    payload = {
        "prompt": workflow,
        "client_id": client_id or str(uuid.uuid4()),
    }
    async with session.post(url, json=payload) as resp:
        data = await resp.json(content_type=None)
        if resp.status >= 400:
            raise RuntimeError(f"ComfyUI /prompt failed: HTTP {resp.status}: {data}")
        prompt_id = (data or {}).get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI /prompt missing prompt_id: {data}")
        return str(prompt_id)


async def wait_for_history(
    *,
    session: aiohttp.ClientSession,
    base_url: str,
    prompt_id: str,
    timeout_s: int = 600,
    poll_interval_s: float = 0.8,
) -> Dict[str, Any]:
    """
    Poll ComfyUI history until the prompt has outputs.
    """
    deadline = asyncio.get_event_loop().time() + max(5, int(timeout_s))
    url_one = base_url.rstrip("/") + f"/history/{prompt_id}"
    url_all = base_url.rstrip("/") + "/history"

    last_payload: Optional[Dict[str, Any]] = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with session.get(url_one) as resp:
                data = await resp.json(content_type=None)
                if isinstance(data, dict) and data:
                    last_payload = data
                    # /history/{id} may return entry directly OR {id: entry}
                    entry = data.get(prompt_id) if prompt_id in data else data
                    # If execution completed with error, surface it early.
                    status = (entry or {}).get("status") if isinstance(entry, dict) else None
                    if isinstance(status, dict):
                        status_str = str(status.get("status_str") or status.get("status") or "").lower()
                        if status_str in {"error", "failed"}:
                            messages = status.get("messages")
                            raise RuntimeError(f"ComfyUI prompt failed: {messages or status}")
                        completed = status.get("completed")
                        if completed is True:
                            outputs = (entry or {}).get("outputs")
                            if isinstance(outputs, dict) and outputs:
                                return entry
                            messages = status.get("messages")
                            raise RuntimeError(f"ComfyUI prompt completed without outputs: {messages or status}")

                    outputs = (entry or {}).get("outputs")
                    if isinstance(outputs, dict) and outputs:
                        return entry
        except Exception:
            pass

        # Fallback: some deployments only support /history returning a dict of all prompts.
        try:
            async with session.get(url_all) as resp:
                data = await resp.json(content_type=None)
                if isinstance(data, dict) and data:
                    last_payload = data
                    entry = data.get(prompt_id)
                    if isinstance(entry, dict):
                        status = entry.get("status")
                        if isinstance(status, dict):
                            status_str = str(status.get("status_str") or status.get("status") or "").lower()
                            if status_str in {"error", "failed"}:
                                messages = status.get("messages")
                                raise RuntimeError(f"ComfyUI prompt failed: {messages or status}")
                            completed = status.get("completed")
                            if completed is True:
                                outputs = entry.get("outputs")
                                if isinstance(outputs, dict) and outputs:
                                    return entry
                                messages = status.get("messages")
                                raise RuntimeError(f"ComfyUI prompt completed without outputs: {messages or status}")

                        outputs = entry.get("outputs")
                        if isinstance(outputs, dict) and outputs:
                            return entry
        except Exception:
            pass

        await asyncio.sleep(poll_interval_s)

    raise TimeoutError(f"ComfyUI prompt timed out after {timeout_s}s (prompt_id={prompt_id}). Last={last_payload}")


def extract_first_audio_fileinfo(history_entry: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Extract (filename, subfolder, type) from a ComfyUI history entry.
    Returns the first audio-like output found.
    """
    outputs = (history_entry or {}).get("outputs") or {}
    if not isinstance(outputs, dict):
        raise RuntimeError("ComfyUI history entry missing outputs")

    # Search for common output keys used by audio nodes/plugins.
    audio_keys = ("audio", "audios", "sounds", "sound", "waveform", "files")
    for _, node_out in outputs.items():
        if not isinstance(node_out, dict):
            continue
        for k in audio_keys:
            v = node_out.get(k)
            if not v:
                continue
            items = v if isinstance(v, list) else [v]
            for it in items:
                if isinstance(it, dict) and it.get("filename"):
                    return (
                        str(it.get("filename")),
                        str(it.get("subfolder") or ""),
                        str(it.get("type") or "output"),
                    )

        # Some plugins may still emit "images" with a non-image extension; be permissive.
        imgs = node_out.get("images")
        if isinstance(imgs, list):
            for it in imgs:
                if isinstance(it, dict) and it.get("filename"):
                    fn = str(it.get("filename"))
                    if os.path.splitext(fn)[1].lower() in {".wav", ".flac", ".mp3", ".m4a", ".ogg"}:
                        return (fn, str(it.get("subfolder") or ""), str(it.get("type") or "output"))

    raise RuntimeError("No audio output found in ComfyUI history entry")


async def download_file_via_view(
    *,
    session: aiohttp.ClientSession,
    base_url: str,
    filename: str,
    subfolder: str = "",
    file_type: str = "output",
) -> bytes:
    from urllib.parse import urlencode

    qs = urlencode({"filename": filename, "subfolder": subfolder or "", "type": file_type or "output"})
    url = base_url.rstrip("/") + f"/view?{qs}"
    async with session.get(url) as resp:
        data = await resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"ComfyUI /view failed: HTTP {resp.status} ({len(data)} bytes)")
        return data
