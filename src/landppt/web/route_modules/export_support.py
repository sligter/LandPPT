"""
Export helpers extracted from the legacy web router.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Request
from pydantic import BaseModel

from ...core.config import ai_config
from ...services.pyppeteer_pdf_converter import get_pdf_converter
from ...utils.thread_pool import run_blocking_io
from .support import logger


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


async def _is_standard_pptx_export_enabled() -> bool:
    """Return whether Apryse-based standard PPTX export is enabled system-wide."""
    feature_enabled = _coerce_bool(getattr(ai_config, "enable_apryse_pptx_export", False))
    license_key = str(getattr(ai_config, "apryse_license_key", "") or "").strip()

    try:
        from ...services.db_config_service import get_db_config_service

        config_service = get_db_config_service()
        system_config = await config_service.get_all_config(user_id=None)
        feature_enabled = _coerce_bool(system_config.get("enable_apryse_pptx_export", feature_enabled))
        license_key = str(system_config.get("apryse_license_key") or license_key or "").strip()
    except Exception as exc:
        logger.warning("Failed to resolve Apryse PPTX export state from DB config: %s", exc)

    return feature_enabled and bool(license_key)


def _strip_default_port(host: str, scheme: str) -> str:
    """Strip default port from a host string."""
    host = (host or "").strip()
    scheme = (scheme or "").strip().lower()
    if not host:
        return host

    try:
        parsed = urllib.parse.urlsplit(f"{scheme or 'http'}://{host}")
        hostname = parsed.hostname or host
        port = parsed.port
        if port is None:
            return host
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            if ":" in hostname and not hostname.startswith("["):
                return f"[{hostname}]"
            return hostname
    except Exception:
        return host

    return host


def _normalize_base_url_candidate(raw_url: Optional[str], default_scheme: str = "https") -> Optional[str]:
    """Normalize a base-URL candidate to scheme://host[:port]."""
    value = (str(raw_url).strip() if raw_url is not None else "")
    if not value:
        return None

    if value.startswith("//"):
        value = f"{default_scheme}:{value}"
    elif "://" not in value:
        value = f"{default_scheme}://{value.lstrip('/')}"

    parsed = urllib.parse.urlsplit(value)
    scheme = (parsed.scheme or default_scheme or "https").strip().lower()
    host = (parsed.netloc or "").strip()
    if not host:
        return None

    if "," in host:
        host = host.split(",", 1)[0].strip()
    host = _strip_default_port(host, scheme)
    if not host:
        return None
    return f"{scheme}://{host}"


def _is_loopback_base_url(base_url: Optional[str]) -> bool:
    """Return True when the URL points at a loopback/local host."""
    if not base_url:
        return True
    try:
        parsed = urllib.parse.urlsplit(base_url)
        hostname = (parsed.hostname or "").strip().lower()
        return hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
    except Exception:
        return False


def _resolve_export_base_url(http_request: Optional[Request] = None) -> str:
    """Resolve the public base URL used by file-based export renderers."""
    request_candidates: List[str] = []
    config_candidates: List[str] = []

    def add_candidate(target: List[str], raw_url: Optional[str], *, default_scheme: str = "https") -> None:
        normalized = _normalize_base_url_candidate(raw_url, default_scheme=default_scheme)
        if normalized and normalized not in target:
            target.append(normalized)

    try:
        if http_request is not None:
            headers = http_request.headers
            request_scheme = (http_request.url.scheme or "https").strip().lower()

            add_candidate(request_candidates, headers.get("origin"), default_scheme=request_scheme)

            referer = headers.get("referer")
            if referer:
                try:
                    referer_parts = urllib.parse.urlsplit(referer)
                    add_candidate(request_candidates, f"{referer_parts.scheme}://{referer_parts.netloc}", default_scheme=request_scheme)
                except Exception:
                    pass

            forwarded_host = (headers.get("x-forwarded-host") or "").strip()
            forwarded_proto = (headers.get("x-forwarded-proto") or request_scheme).strip().lower()
            forwarded_port = (headers.get("x-forwarded-port") or "").strip()
            if "," in forwarded_host:
                forwarded_host = forwarded_host.split(",", 1)[0].strip()
            if "," in forwarded_proto:
                forwarded_proto = forwarded_proto.split(",", 1)[0].strip()
            if forwarded_host and forwarded_port and ":" not in forwarded_host:
                forwarded_host = f"{forwarded_host}:{forwarded_port}"
            add_candidate(request_candidates, forwarded_host, default_scheme=forwarded_proto or request_scheme)

            host = (headers.get("host") or http_request.url.netloc or "").strip()
            if host:
                add_candidate(request_candidates, host, default_scheme=request_scheme)

            if getattr(http_request, "base_url", None):
                add_candidate(request_candidates, str(http_request.base_url), default_scheme=request_scheme)
    except Exception:
        pass

    try:
        from ...services.url_service import get_current_base_url

        add_candidate(config_candidates, get_current_base_url())
    except Exception:
        pass

    for candidate in request_candidates:
        if not _is_loopback_base_url(candidate):
            return candidate

    for candidate in config_candidates:
        if not _is_loopback_base_url(candidate):
            return candidate

    if request_candidates:
        return request_candidates[0]

    raise ValueError("Unable to resolve export base URL from request headers or app configuration")


def _build_export_app_url(base_url: str, relative_path: str) -> str:
    """Build an absolute app URL using the resolved export base URL."""
    normalized_path = "/" + (relative_path or "").lstrip("/")
    return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", normalized_path.lstrip("/"))


_APP_EXPORTABLE_PATH_PREFIXES = (
    "/api/image/view/",
    "/api/image/thumbnail/",
    "/static/",
    "/temp/",
)


def _is_app_exportable_path(path: str) -> bool:
    normalized_path = "/" + str(path or "").lstrip("/")
    return any(normalized_path.startswith(prefix) for prefix in _APP_EXPORTABLE_PATH_PREFIXES)


def _resolve_export_absolute_resource_url(raw_url: str, base_url: str) -> str:
    """将误写成宿主机 localhost 的应用资源地址改写为导出进程可达地址。"""
    try:
        parsed = urllib.parse.urlsplit(raw_url)
    except Exception:
        return raw_url

    if (parsed.scheme or "").lower() not in {"http", "https"}:
        return raw_url

    hostname = (parsed.hostname or "").strip().lower()
    if hostname not in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return raw_url

    if not _is_app_exportable_path(parsed.path):
        return raw_url

    relative_path = parsed.path or "/"
    if parsed.query:
        relative_path = f"{relative_path}?{parsed.query}"
    if parsed.fragment:
        relative_path = f"{relative_path}#{parsed.fragment}"
    return _build_export_app_url(base_url, relative_path)


def _file_url_to_path(raw_url: str) -> Optional[Path]:
    """Convert a file:// URL to a local filesystem path."""
    try:
        parsed = urllib.parse.urlsplit(raw_url)
        if (parsed.scheme or "").lower() != "file":
            return None

        pathname = urllib.request.url2pathname(parsed.path or "")
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            pathname = f"//{parsed.netloc}{pathname}"

        if os.name == "nt" and pathname.startswith("/") and re.match(r"^/[A-Za-z]:[/\\\\]", pathname):
            pathname = pathname[1:]

        return Path(pathname).resolve(strict=False)
    except Exception:
        return None


def _resolve_export_file_resource_url(raw_url: str, base_url: str) -> str:
    """Rewrite app-owned local file URLs to public URLs usable from export renderers."""
    local_path = _file_url_to_path(raw_url)
    if local_path is None:
        return raw_url

    try:
        static_root = (Path(__file__).resolve().parent.parent / "static").resolve()
        if local_path.is_relative_to(static_root):
            relative_path = local_path.relative_to(static_root).as_posix()
            quoted = urllib.parse.quote(relative_path, safe="/")
            return _build_export_app_url(base_url, f"/static/{quoted}")
    except Exception:
        pass

    try:
        from ...services.image.image_service import get_image_service

        image_service = get_image_service()
        cache_index = getattr(getattr(image_service, "cache_manager", None), "_cache_index", {}) or {}
        for cache_key, cache_info in cache_index.items():
            file_path = getattr(cache_info, "file_path", None)
            if not file_path:
                continue
            try:
                if Path(file_path).resolve(strict=False) == local_path:
                    quoted_key = urllib.parse.quote(str(cache_key), safe="")
                    return _build_export_app_url(base_url, f"/api/image/view/{quoted_key}")
            except Exception:
                continue
    except Exception:
        pass

    return raw_url


def _resolve_export_resource_url(raw_url: str, base_url: str) -> str:
    """Convert export-time relative resource URLs into absolute URLs."""
    if not isinstance(raw_url, str):
        return raw_url

    candidate = raw_url.strip()
    if not candidate:
        return raw_url

    lowered = candidate.lower()
    if lowered.startswith(("#", "data:", "blob:", "javascript:", "mailto:", "tel:", "about:")):
        return raw_url
    if lowered.startswith(("http://", "https://")):
        return _resolve_export_absolute_resource_url(candidate, base_url)
    if lowered.startswith("file://"):
        return _resolve_export_file_resource_url(candidate, base_url)
    if candidate.startswith("//"):
        base_scheme = urllib.parse.urlparse(base_url).scheme or "http"
        return f"{base_scheme}:{candidate}"

    joined = urllib.parse.urljoin(f"{base_url.rstrip('/')}/", candidate)
    return joined or candidate


def _rewrite_export_css_urls(css_text: str, base_url: str) -> str:
    """Rewrite url(...) references in CSS so file:// exports can still fetch assets."""
    if not isinstance(css_text, str) or "url(" not in css_text.lower():
        return css_text

    def replace_match(match: re.Match) -> str:
        prefix = match.group(1)
        raw_value = (match.group(2) or "").strip()
        suffix = match.group(3)

        quote = ""
        inner = raw_value
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in ("'", '"'):
            quote = raw_value[0]
            inner = raw_value[1:-1]

        absolute_url = _resolve_export_resource_url(inner, base_url)
        return f"{prefix}{quote}{absolute_url}{quote}{suffix}"

    return re.sub(r"(url\(\s*)([^)]+?)(\s*\))", replace_match, css_text, flags=re.IGNORECASE)


def _rewrite_export_srcset(srcset_value: str, base_url: str) -> str:
    """Rewrite each candidate in srcset to an absolute URL."""
    if not isinstance(srcset_value, str) or not srcset_value.strip():
        return srcset_value

    rewritten_candidates: List[str] = []
    for candidate in srcset_value.split(","):
        item = candidate.strip()
        if not item:
            continue
        parts = item.split()
        if not parts:
            continue
        parts[0] = _resolve_export_resource_url(parts[0], base_url)
        rewritten_candidates.append(" ".join(parts))
    return ", ".join(rewritten_candidates)


def _html_uses_tailwind_utilities(html_content: str) -> bool:
    """Best-effort detection for Tailwind utility class usage."""
    if not isinstance(html_content, str) or "class" not in html_content.lower():
        return False

    utility_pattern = re.compile(
        r"^(?:"
        r"container|sr-only|not-sr-only|block|inline|inline-block|inline-flex|flex|inline-grid|grid|hidden|contents|"
        r"absolute|relative|fixed|sticky|static|"
        r"(?:top|right|bottom|left|inset|z)-[\w./\[\]-]+|"
        r"(?:m|mx|my|mt|mr|mb|ml|p|px|py|pt|pr|pb|pl|w|min-w|max-w|h|min-h|max-h|"
        r"gap|space-x|space-y|basis|grow|shrink|order|col|row|"
        r"text|font|leading|tracking|bg|from|via|to|border|rounded|shadow|opacity|"
        r"items|justify|content|self|place|object|overflow|overscroll|whitespace|break|"
        r"aspect|ring|fill|stroke|list|underline|line-clamp|animate|duration|delay|ease|"
        r"scale|rotate|translate|skew)-[\w./:%\[\]-]+|"
        r"(?:prose|antialiased|subpixel-antialiased|uppercase|lowercase|capitalize|truncate|underline|no-underline|italic|not-italic|"
        r"pointer-events-none|pointer-events-auto|select-none|select-text|align-middle|align-top|align-bottom)"
        r")$",
        re.IGNORECASE,
    )

    for match in re.finditer(r'class\s*=\s*["\']([^"\']+)["\']', html_content, flags=re.IGNORECASE):
        class_value = match.group(1) or ""
        for token in re.split(r"\s+", class_value.strip()):
            if token and utility_pattern.match(token):
                return True
    return False


def _strip_unused_tailwind_cdn(html_content: str) -> str:
    """Remove Tailwind Play CDN when the document does not appear to use Tailwind utilities."""
    if not isinstance(html_content, str) or "cdn.tailwindcss.com" not in html_content.lower():
        return html_content
    if _html_uses_tailwind_utilities(html_content):
        return html_content

    cleaned = re.sub(
        r'<script\b[^>]*src=["\']https://cdn\.tailwindcss\.com(?:/)?[^"\']*["\'][^>]*>\s*</script>',
        '',
        html_content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if cleaned != html_content:
        cleaned = re.sub(
            r'<script\b(?![^>]*\bsrc=)[^>]*>\s*tailwind\.config\s*=.*?</script>',
            '',
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return cleaned


def _prepare_html_for_file_based_export(html_content: str, base_url: str) -> str:
    """Normalize resource URLs before rendering HTML from a local temp file."""
    if not isinstance(html_content, str) or not html_content.strip():
        return html_content

    prepared = _strip_unused_tailwind_cdn(html_content)
    normalized_base_url = base_url.rstrip("/")
    base_href = f"{normalized_base_url}/"

    if re.search(r"<base\b", prepared, flags=re.IGNORECASE):
        prepared = re.sub(
            r"(<base\b[^>]*\bhref\s*=\s*)(['\"])(.*?)(\2)",
            lambda match: f"{match.group(1)}{match.group(2)}{base_href}{match.group(2)}",
            prepared,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    elif re.search(r"<head\b[^>]*>", prepared, flags=re.IGNORECASE):
        prepared = re.sub(
            r"(<head\b[^>]*>)",
            lambda match: f'{match.group(1)}<base href="{base_href}">',
            prepared,
            count=1,
            flags=re.IGNORECASE,
        )

    def rewrite_attr(attr_name: str, transform) -> None:
        nonlocal prepared
        attr_token = re.escape(attr_name)
        quoted_pattern = rf"((?<![\w:-]){attr_token}\s*=\s*)([\"'])(.*?)(\2)"
        unquoted_pattern = rf"((?<![\w:-]){attr_token}\s*=\s*)(?![\"'])([^\s>]+)"

        prepared = re.sub(
            quoted_pattern,
            lambda match: f"{match.group(1)}{match.group(2)}{transform(match.group(3), normalized_base_url)}{match.group(2)}",
            prepared,
            flags=re.IGNORECASE | re.DOTALL,
        )
        prepared = re.sub(
            unquoted_pattern,
            lambda match: f"{match.group(1)}{transform(match.group(2), normalized_base_url)}",
            prepared,
            flags=re.IGNORECASE,
        )

    for attr in ("src", "href", "poster", "data-src", "data-href", "xlink:href"):
        rewrite_attr(attr, _resolve_export_resource_url)

    rewrite_attr("srcset", _rewrite_export_srcset)
    rewrite_attr("style", _rewrite_export_css_urls)

    prepared = re.sub(
        r"(<style\b[^>]*>)(.*?)(</style>)",
        lambda match: f"{match.group(1)}{_rewrite_export_css_urls(match.group(2), normalized_base_url)}{match.group(3)}",
        prepared,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return prepared


class ImagePPTXExportRequest(BaseModel):
    slides: Optional[List[Dict[str, Any]]] = None  # 包含index, html_content, title
    images: Optional[List[Dict[str, Any]]] = None  # 包含index, data(base64), width, height (向后兼容)


ImagePPTXExportRequest.model_rebuild()


def _generate_html_export_sync(project) -> bytes:
    """同步生成HTML导出文件（在线程池中运行）"""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Generate individual HTML files for each slide
        slide_files = []
        for i, slide in enumerate(project.slides_data):
            slide_filename = f"slide_{i+1}.html"
            slide_files.append(slide_filename)

            # Create complete HTML document for each slide
            slide_html = _generate_individual_slide_html_sync(slide, i+1, len(project.slides_data), project.topic)

            slide_path = temp_path / slide_filename
            with open(slide_path, 'w', encoding='utf-8') as f:
                f.write(slide_html)

        # Generate index.html slideshow page
        index_html = _generate_slideshow_index_sync(project, slide_files)
        index_path = temp_path / "index.html"
        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(index_html)

        # Create ZIP file
        zip_filename = f"{project.topic}_PPT.zip"
        zip_path = temp_path / zip_filename

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add index.html
            zipf.write(index_path, "index.html")

            # Add all slide files
            for slide_file in slide_files:
                slide_path = temp_path / slide_file
                zipf.write(slide_path, slide_file)

        # Read ZIP file content
        with open(zip_path, 'rb') as f:
            return f.read()


def _generate_individual_slide_html_sync(slide, slide_number: int, total_slides: int, topic: str) -> str:
    """同步生成单个幻灯片HTML（在线程池中运行）"""
    slide_html = slide.get('html_content', '')
    slide_title = slide.get('title', f'第{slide_number}页')

    # Check if it's already a complete HTML document
    import re
    if slide_html.strip().lower().startswith('<!doctype') or slide_html.strip().lower().startswith('<html'):
        # It's a complete HTML document, enhance it with navigation
        return _enhance_complete_html_with_navigation(slide_html, slide_number, total_slides, topic, slide_title)
    else:
        # It's just content, wrap it in a complete structure
        slide_content = slide_html

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{topic} - {slide_title}</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            background: #f5f5f5;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }}
        .slide-container {{
            width: 90vw;
            height: 90vh;
            background: white;
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            overflow: hidden;
            position: relative;
        }}
        .slide-content {{
            width: 100%;
            height: 100%;
            padding: 20px;
            box-sizing: border-box;
        }}
        .slide-number {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 5px 10px;
            border-radius: 5px;
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <div class="slide-container">
        <div class="slide-content">
            {slide_content}
        </div>
        <div class="slide-number">{slide_number} / {total_slides}</div>
    </div>
</body>
</html>"""


def _generate_slideshow_index_sync(project, slide_files: list) -> str:
    """同步生成幻灯片索引页面（在线程池中运行）"""
    slides_list = ""
    for i, slide_file in enumerate(slide_files):
        slide = project.slides_data[i]
        slide_title = slide.get('title', f'第{i+1}页')
        slides_list += f"""
        <div class="slide-item" onclick="openSlide('{slide_file}')">
            <div class="slide-preview">
                <div class="slide-number">{i+1}</div>
                <div class="slide-title">{slide_title}</div>
            </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project.topic} - PPT放映</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .header {{
            text-align: center;
            padding: 40px 20px;
            color: white;
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
            font-weight: 300;
        }}
        .slides-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            padding: 20px;
        }}
        .slide-item {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }}
        .slide-item:hover {{
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.2);
        }}
        .slide-number {{
            background: #007bff;
            color: white;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 15px auto;
            font-weight: bold;
        }}
        .slide-title {{
            font-size: 1.1em;
            color: #333;
            margin: 0;
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{project.topic}</h1>
        <p>PPT演示文稿 - 共{len(slide_files)}页</p>
    </div>
    <div class="slides-grid">
        {slides_list}
    </div>
    <script>
        function openSlide(slideFile) {{
            window.open(slideFile, '_blank');
        }}
    </script>
</body>
</html>"""


async def _generate_combined_html_for_export(project, export_type: str) -> str:
    """Generate combined HTML for export (PDF or HTML)"""
    try:
        if not project.slides_data:
            raise ValueError("No slides data available")

        # Create a combined HTML document with all slides
        html_parts = []

        # HTML document header
        html_parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project.topic} - PPT导出</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            background: #f5f5f5;
        }}
        .slide-container {{
            width: 100vw;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            page-break-after: always;
            background: white;
            position: relative;
        }}
        .slide-container:last-child {{
            page-break-after: avoid;
        }}
        .slide-frame {{
            width: 90vw;
            height: 90vh;
            border: none;
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }}
        .slide-number {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 5px 10px;
            border-radius: 5px;
            font-size: 14px;
        }}
        @media print {{
            .slide-container {{
                page-break-after: always;
                width: 100%;
                height: 100vh;
            }}
        }}
    </style>
</head>
<body>""")

        # Add each slide preserving original styles
        for i, slide in enumerate(project.slides_data):
            slide_html = slide.get('html_content', '')
            if slide_html:
                # Preserve complete HTML structure
                if slide_html.strip().lower().startswith('<!doctype') or slide_html.strip().lower().startswith('<html'):
                    # Extract styles from head and content from body
                    import re

                    # Extract CSS styles from head
                    style_matches = re.findall(r'<style[^>]*>(.*?)</style>', slide_html, re.DOTALL | re.IGNORECASE)
                    slide_styles = '\n'.join(style_matches)

                    # Extract body content
                    body_match = re.search(r'<body[^>]*>(.*?)</body>', slide_html, re.DOTALL | re.IGNORECASE)
                    if body_match:
                        slide_content = body_match.group(1)
                    else:
                        slide_content = slide_html
                else:
                    slide_styles = ""
                    slide_content = slide_html

                html_parts.append(f"""
    <div class="slide-container">
        <style>
            {slide_styles}
        </style>
        <div class="slide-frame">
            {slide_content}
        </div>
        <div class="slide-number">{i + 1} / {len(project.slides_data)}</div>
    </div>""")

        # Close HTML document
        html_parts.append("""
</body>
</html>""")

        return ''.join(html_parts)

    except Exception as e:
        # Fallback: return a simple error page
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>导出错误</title>
</head>
<body>
    <h1>导出失败</h1>
    <p>错误信息: {str(e)}</p>
    <p>请确保PPT已经生成完成后再尝试导出。</p>
</body>
</html>"""


async def _generate_individual_slide_html(slide, slide_number: int, total_slides: int, topic: str) -> str:
    """Generate complete HTML document for individual slide preserving original styles"""
    slide_html = slide.get('html_content', '')
    slide_title = slide.get('title', f'第{slide_number}页')

    # Check if it's already a complete HTML document
    import re
    if slide_html.strip().lower().startswith('<!doctype') or slide_html.strip().lower().startswith('<html'):
        # It's a complete HTML document, enhance it with navigation
        return _enhance_complete_html_with_navigation(slide_html, slide_number, total_slides, topic, slide_title)
    else:
        # It's just content, wrap it in a complete structure
        slide_content = slide_html

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{topic} - {slide_title}</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            background: #f5f5f5;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }}
        .slide-container {{
            width: 90vw;
            height: 90vh;
            background: white;
            border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            overflow: hidden;
            position: relative;
        }}
        .slide-content {{
            width: 100%;
            height: 100%;
            padding: 20px;
            box-sizing: border-box;
        }}
        .slide-number {{
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 5px 10px;
            border-radius: 5px;
            font-size: 14px;
        }}
        .navigation {{
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 10px;
            z-index: 1000;
        }}
        .nav-btn {{
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 15px;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }}
        .nav-btn:hover {{
            background: #0056b3;
        }}
        .nav-btn:disabled {{
            background: #ccc;
            cursor: not-allowed;
        }}
        .fullscreen-btn {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: #28a745;
            color: white;
            border: none;
            padding: 10px;
            border-radius: 5px;
            cursor: pointer;
            z-index: 1000;
        }}
        .fullscreen-btn:hover {{
            background: #1e7e34;
        }}
    </style>
</head>
<body>
    <div class="slide-container">
        <div class="slide-content">
            {slide_content}
        </div>
        <div class="slide-number">{slide_number} / {total_slides}</div>
    </div>

    <div class="navigation">
        <a href="index.html" class="nav-btn">🏠 返回目录</a>
        {"" if slide_number <= 1 else f'<a href="slide_{slide_number-1}.html" class="nav-btn">‹ 上一页</a>'}
        {"" if slide_number >= total_slides else f'<a href="slide_{slide_number+1}.html" class="nav-btn">下一页 ›</a>'}
    </div>

    <button class="fullscreen-btn" onclick="toggleFullscreen()" title="全屏显示">
        📺
    </button>

    <script>
        function toggleFullscreen() {{
            if (!document.fullscreenElement) {{
                document.documentElement.requestFullscreen();
            }} else {{
                if (document.exitFullscreen) {{
                    document.exitFullscreen();
                }}
            }}
        }}

        // Keyboard navigation
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'ArrowLeft' && {slide_number} > 1) {{
                window.location.href = 'slide_{slide_number-1}.html';
            }} else if (e.key === 'ArrowRight' && {slide_number} < {total_slides}) {{
                window.location.href = 'slide_{slide_number+1}.html';
            }} else if (e.key === 'Escape') {{
                window.location.href = 'index.html';
            }}
        }});
    </script>
</body>
</html>"""


def _enhance_complete_html_with_navigation(original_html: str, slide_number: int, total_slides: int, topic: str, slide_title: str) -> str:
    """Enhance complete HTML document with navigation controls"""
    import re

    # Add navigation CSS and JavaScript to the head section
    navigation_css = """
    <style>
        .slide-navigation {
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 10px;
            z-index: 10000;
            background: rgba(0,0,0,0.8);
            padding: 10px;
            border-radius: 25px;
        }
        .nav-btn {
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 15px;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            font-size: 14px;
        }
        .nav-btn:hover {
            background: #0056b3;
        }
        .fullscreen-btn {
            position: fixed;
            top: 20px;
            right: 20px;
            background: #28a745;
            color: white;
            border: none;
            padding: 10px;
            border-radius: 5px;
            cursor: pointer;
            z-index: 10000;
            font-size: 16px;
        }
        .fullscreen-btn:hover {
            background: #1e7e34;
        }
    </style>"""

    navigation_js = f"""
    <script>
        function toggleFullscreen() {{
            if (!document.fullscreenElement) {{
                document.documentElement.requestFullscreen();
            }} else {{
                if (document.exitFullscreen) {{
                    document.exitFullscreen();
                }}
            }}
        }}

        // Keyboard navigation
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'ArrowLeft' && {slide_number} > 1) {{
                window.location.href = 'slide_{slide_number-1}.html';
            }} else if (e.key === 'ArrowRight' && {slide_number} < {total_slides}) {{
                window.location.href = 'slide_{slide_number+1}.html';
            }} else if (e.key === 'Escape') {{
                window.location.href = 'index.html';
            }}
        }});
    </script>"""

    navigation_html = f"""
    <div class="slide-navigation">
        <a href="index.html" class="nav-btn">🏠 返回目录</a>
        {"" if slide_number <= 1 else f'<a href="slide_{slide_number-1}.html" class="nav-btn">‹ 上一页</a>'}
        {"" if slide_number >= total_slides else f'<a href="slide_{slide_number+1}.html" class="nav-btn">下一页 ›</a>'}
    </div>

    <button class="fullscreen-btn" onclick="toggleFullscreen()" title="全屏显示">
        📺
    </button>"""

    # Insert navigation CSS into head
    head_pattern = r'</head>'
    enhanced_html = re.sub(head_pattern, navigation_css + '\n</head>', original_html, flags=re.IGNORECASE)

    # Insert navigation HTML and JS before closing body tag
    body_pattern = r'</body>'
    enhanced_html = re.sub(body_pattern, navigation_html + '\n' + navigation_js + '\n</body>', enhanced_html, flags=re.IGNORECASE)

    return enhanced_html


async def _generate_pdf_slide_html(slide, slide_number: int, total_slides: int, topic: str) -> str:
    """Generate PDF-optimized HTML for individual slide without navigation elements"""
    slide_html = slide.get('html_content', '')
    slide_title = slide.get('title', f'第{slide_number}页')

    # Check if it's already a complete HTML document
    import re
    if slide_html.strip().lower().startswith('<!doctype') or slide_html.strip().lower().startswith('<html'):
        # It's a complete HTML document, clean it for PDF
        return _clean_html_for_pdf(slide_html, slide_number, total_slides)
    else:
        # It's just content, wrap it in a PDF-optimized structure
        slide_content = slide_html

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{topic} - {slide_title}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        html, body {{
            width: 100%;
            height: 100vh;
            margin: 0;
            padding: 0;
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            overflow: hidden;
        }}

        .slide-container {{
            width: 100vw;
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }}

        .slide-content {{
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
        }}

        /* Ensure all backgrounds and colors are preserved for PDF */
        * {{
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }}
    </style>
</head>
<body>
    <div class="slide-container">
        <div class="slide-content">
            {slide_content}
        </div>
    </div>
</body>
</html>"""


def _clean_html_for_pdf(original_html: str, slide_number: int, total_slides: int) -> str:
    """Clean complete HTML document for PDF generation by removing navigation elements"""
    import re

    # Remove navigation elements that might interfere with PDF generation
    cleaned_html = original_html

    # Remove navigation divs and buttons
    cleaned_html = re.sub(r'<div[^>]*class="[^"]*navigation[^"]*"[^>]*>.*?</div>', '', cleaned_html, flags=re.DOTALL | re.IGNORECASE)
    cleaned_html = re.sub(r'<button[^>]*class="[^"]*nav[^"]*"[^>]*>.*?</button>', '', cleaned_html, flags=re.DOTALL | re.IGNORECASE)
    cleaned_html = re.sub(r'<a[^>]*class="[^"]*nav[^"]*"[^>]*>.*?</a>', '', cleaned_html, flags=re.DOTALL | re.IGNORECASE)

    # Remove fullscreen buttons
    cleaned_html = re.sub(r'<button[^>]*fullscreen[^>]*>.*?</button>', '', cleaned_html, flags=re.DOTALL | re.IGNORECASE)

    # Add PDF-specific styles
    pdf_styles = """
    <style>
        /* PDF optimization styles */
        * {
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }

        html, body {
            width: 100% !important;
            height: 100vh !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }

        /* Hide any remaining navigation elements */
        .navigation, .nav-btn, .fullscreen-btn, .slide-navigation {
            display: none !important;
        }
    </style>
    """

    # Insert PDF styles before closing head tag
    head_pattern = r'</head>'
    cleaned_html = re.sub(head_pattern, pdf_styles + '\n</head>', cleaned_html, flags=re.IGNORECASE)

    return cleaned_html


async def _generate_pdf_with_pyppeteer(project, output_path: str, individual: bool = False) -> bool:
    """Generate PDF using Pyppeteer (Python)"""
    try:
        pdf_converter = get_pdf_converter()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Always generate individual HTML files for each slide for better page separation
            # This ensures each slide becomes a separate PDF page
            html_files = []
            for i, slide in enumerate(project.slides_data):
                # Use a specialized PDF-optimized HTML generator without navigation
                slide_html = await _generate_pdf_slide_html(
                    slide, i+1, len(project.slides_data), project.topic
                )

                html_file = temp_path / f"slide_{i+1}.html"
                # Write HTML file in thread pool to avoid blocking
                def write_html_file(content, path):
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(content)

                await run_blocking_io(write_html_file, slide_html, str(html_file))
                html_files.append(str(html_file))

            # Use Pyppeteer to convert multiple files and merge them
            pdf_dir = temp_path / "pdfs"
            await run_blocking_io(pdf_dir.mkdir)

            logging.info(f"Starting PDF generation for {len(html_files)} files")

            # Convert HTML files to PDFs and merge them
            pdf_files = await pdf_converter.convert_multiple_html_to_pdf(
                html_files, str(pdf_dir), output_path
            )

            if pdf_files and os.path.exists(output_path):
                logging.info("Pyppeteer PDF generation successful")
                return True
            else:
                logging.error("Pyppeteer PDF generation failed: No output file created")
                return False

    except Exception as e:
        logging.error(f"Pyppeteer PDF generation failed: {e}")
        return False


async def _generate_combined_html_for_pdf(project) -> str:
    """Generate combined HTML for PDF export with all slides preserving original styles"""
    slides_html = ""
    global_styles = ""

    for i, slide in enumerate(project.slides_data):
        slide_html = slide.get('html_content', '')
        slide_title = slide.get('title', f'第{i+1}页')

        # Enhanced style extraction to preserve all styling
        if slide_html.strip().lower().startswith('<!doctype') or slide_html.strip().lower().startswith('<html'):
            import re

            # Extract all CSS styles from head (including link tags and style tags)
            style_matches = re.findall(r'<style[^>]*>(.*?)</style>', slide_html, re.DOTALL | re.IGNORECASE)
            link_matches = re.findall(r'<link[^>]*rel=["\']stylesheet["\'][^>]*>', slide_html, re.IGNORECASE)

            slide_styles = '\n'.join(style_matches)
            slide_links = '\n'.join(link_matches)

            # Extract body content with preserved attributes
            body_match = re.search(r'<body([^>]*)>(.*?)</body>', slide_html, re.DOTALL | re.IGNORECASE)
            if body_match:
                body_attrs = body_match.group(1)
                slide_content = body_match.group(2)
                # Preserve body styles if any
                if 'style=' in body_attrs:
                    body_style_match = re.search(r'style=["\']([^"\']*)["\']', body_attrs)
                    if body_style_match:
                        slide_styles += f"\n.slide-content {{ {body_style_match.group(1)} }}"
            else:
                slide_content = slide_html
                slide_links = ""

            # Add to global styles to avoid duplication
            if slide_links and slide_links not in global_styles:
                global_styles += slide_links + "\n"
        else:
            slide_styles = ""
            slide_content = slide_html
            slide_links = ""

        # Create a separate page for each slide with proper page break
        slides_html += f"""
        <div class="slide-page" data-slide="{i+1}" style="page-break-before: always; page-break-after: always; page-break-inside: avoid;">
            <style>
                /* Slide {i+1} specific styles */
                .slide-page[data-slide="{i+1}"] .slide-content {{
                    /* Preserve original styling */
                }}
                {slide_styles}
            </style>
            <div class="slide-content">
                {slide_content}
            </div>
            <div class="slide-footer">
                <span class="slide-number">{i+1} / {len(project.slides_data)}</span>
                <span class="slide-title">{slide_title}</span>
            </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project.topic} - PDF导出</title>
    {global_styles}
    <style>
        /* Reset and base styles */
        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            padding: 0;
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            /* Don't force background color - let slides define their own */
        }}

        .slide-page {{
            width: 297mm;
            height: 167mm;
            margin: 0;
            padding: 0;
            page-break-before: always;
            page-break-after: always;
            page-break-inside: avoid;
            position: relative;
            aspect-ratio: 16/9;
            /* Don't force background - preserve original slide backgrounds */
            overflow: hidden;
            display: block;
            box-sizing: border-box;
        }}

        .slide-page:first-child {{
            page-break-before: avoid;
        }}

        .slide-page:last-child {{
            page-break-after: avoid;
        }}

        .slide-content {{
            width: 100%;
            height: calc(100% - 30px);
            position: relative;
            /* Preserve original content styling */
        }}

        .slide-footer {{
            position: absolute;
            bottom: 5mm;
            right: 10mm;
            font-size: 10px;
            color: rgba(255, 255, 255, 0.7);
            background: rgba(0, 0, 0, 0.3);
            padding: 2px 8px;
            border-radius: 3px;
            z-index: 1000;
        }}

        .slide-number {{
            font-weight: bold;
        }}

        .slide-title {{
            margin-left: 8px;
            opacity: 0.8;
        }}

        /* Print-specific styles */
        @media print {{
            @page {{
                size: 297mm 167mm;
                margin: 0;
            }}

            body {{
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
                margin: 0;
                padding: 0;
            }}

            .slide-page {{
                page-break-before: always;
                page-break-after: always;
                page-break-inside: avoid;
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
                width: 297mm;
                height: 167mm;
                margin: 0;
                padding: 0;
                display: block;
            }}

            .slide-page:first-child {{
                page-break-before: avoid;
            }}

            .slide-page:last-child {{
                page-break-after: avoid;
            }}
        }}

        /* Ensure all backgrounds and colors are preserved */
        * {{
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
        }}
    </style>
</head>
<body>
    {slides_html}
</body>
</html>"""


async def _generate_slideshow_index(project, slide_files: list) -> str:
    """Generate slideshow index page"""
    slides_list = ""
    for i, slide_file in enumerate(slide_files):
        slide = project.slides_data[i]
        slide_title = slide.get('title', f'第{i+1}页')
        slides_list += f"""
        <div class="slide-item" onclick="openSlide('{slide_file}')">
            <div class="slide-preview">
                <div class="slide-number">{i+1}</div>
                <div class="slide-title">{slide_title}</div>
            </div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{project.topic} - PPT放映</title>
    <style>
        body {{
            margin: 0;
            padding: 0;
            font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .header {{
            text-align: center;
            padding: 40px 20px;
            color: white;
        }}
        .header h1 {{
            margin: 0;
            font-size: 2.5em;
            font-weight: 300;
        }}
        .header p {{
            margin: 10px 0 0 0;
            font-size: 1.2em;
            opacity: 0.9;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }}
        .slides-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            padding: 20px 0;
        }}
        .slide-item {{
            background: white;
            border-radius: 10px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }}
        .slide-item:hover {{
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.2);
        }}
        .slide-preview {{
            text-align: center;
        }}
        .slide-number {{
            background: #007bff;
            color: white;
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 15px auto;
            font-weight: bold;
        }}
        .slide-title {{
            font-size: 1.1em;
            color: #333;
            margin: 0;
        }}
        .controls {{
            text-align: center;
            padding: 40px 20px;
        }}
        .btn {{
            background: #28a745;
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            font-size: 1.1em;
            cursor: pointer;
            margin: 0 10px;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-block;
        }}
        .btn:hover {{
            background: #1e7e34;
            transform: translateY(-2px);
        }}
        .btn-secondary {{
            background: #6c757d;
        }}
        .btn-secondary:hover {{
            background: #545b62;
        }}
        @media (max-width: 768px) {{
            .slides-grid {{
                grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
                gap: 15px;
            }}
            .header h1 {{
                font-size: 2em;
            }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{project.topic}</h1>
        <p>PPT演示文稿 - 共{len(slide_files)}页</p>
    </div>

    <div class="container">
        <div class="controls">
            <button class="btn" onclick="startSlideshow()">🎬 开始放映</button>
            <button class="btn btn-secondary" onclick="downloadAll()">📦 下载所有文件</button>
        </div>

        <div class="slides-grid">
            {slides_list}
        </div>
    </div>

    <script>
        function openSlide(slideFile) {{
            window.open(slideFile, '_blank');
        }}

        function startSlideshow() {{
            window.open('slide_1.html', '_blank');
        }}

        function downloadAll() {{
            alert('所有文件已包含在此ZIP包中');
        }}

        // Keyboard shortcuts
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Enter' || e.key === ' ') {{
                startSlideshow();
            }}
        }});
    </script>
</body>
</html>"""
