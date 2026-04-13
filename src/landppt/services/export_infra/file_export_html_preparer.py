"""
HTML 资源预处理工具。

用于将 file:// 渲染场景中的相对资源地址重写为可访问的绝对地址，
避免截图/录屏导出时图片、背景图、样式资源丢失。
"""

from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from ..url_service import get_current_base_url


_APP_EXPORTABLE_PATH_PREFIXES = (
    "/api/image/view/",
    "/api/image/thumbnail/",
    "/static/",
    "/temp/",
)


def _normalize_background_export_base_url(base_url: str) -> str:
    """将宿主机访问地址转换为后台导出进程可达的地址。"""
    candidate = str(base_url or "").strip().rstrip("/")
    if not candidate:
        return ""

    parsed = urllib.parse.urlsplit(candidate)
    hostname = (parsed.hostname or "").strip().lower()
    if hostname not in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return candidate

    port_value = str(os.environ.get("PORT") or "8000").strip()
    if not port_value.isdigit():
        port_value = "8000"

    auth_prefix = ""
    if parsed.username:
        auth_prefix = urllib.parse.quote(parsed.username, safe="")
        if parsed.password is not None:
            auth_prefix += ":" + urllib.parse.quote(parsed.password, safe="")
        auth_prefix += "@"

    normalized = urllib.parse.urlunsplit(
        (
            parsed.scheme or "http",
            f"{auth_prefix}127.0.0.1:{port_value}",
            parsed.path or "",
            parsed.query or "",
            parsed.fragment or "",
        )
    )
    return normalized.rstrip("/")


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


def resolve_background_export_base_url() -> str:
    """为后台导出任务解析公共 base_url。"""
    override = str(os.environ.get("LANDPPT_BACKGROUND_EXPORT_BASE_URL") or "").strip()
    if override:
        return _normalize_background_export_base_url(override)

    base_url = str(get_current_base_url() or "").strip()
    if not base_url:
        raise ValueError("Public base URL is unavailable for background export")
    return _normalize_background_export_base_url(base_url)


def _build_export_app_url(base_url: str, relative_path: str) -> str:
    normalized_path = "/" + (relative_path or "").lstrip("/")
    return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", normalized_path.lstrip("/"))


def _file_url_to_path(raw_url: str) -> Path | None:
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
    local_path = _file_url_to_path(raw_url)
    if local_path is None:
        return raw_url

    try:
        static_root = (Path(__file__).resolve().parents[2] / "web" / "static").resolve()
        if local_path.is_relative_to(static_root):
            relative_path = local_path.relative_to(static_root).as_posix()
            quoted = urllib.parse.quote(relative_path, safe="/")
            return _build_export_app_url(base_url, f"/static/{quoted}")
    except Exception:
        pass

    try:
        from ..image.image_service import get_image_service

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


def resolve_export_resource_url(raw_url: str, base_url: str) -> str:
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

        absolute_url = resolve_export_resource_url(inner, base_url)
        return f"{prefix}{quote}{absolute_url}{quote}{suffix}"

    return re.sub(r"(url\(\s*)([^)]+?)(\s*\))", replace_match, css_text, flags=re.IGNORECASE)


def _rewrite_export_srcset(srcset_value: str, base_url: str) -> str:
    if not isinstance(srcset_value, str) or not srcset_value.strip():
        return srcset_value

    rewritten_candidates: list[str] = []
    for candidate in srcset_value.split(","):
        item = candidate.strip()
        if not item:
            continue
        parts = item.split()
        if not parts:
            continue
        parts[0] = resolve_export_resource_url(parts[0], base_url)
        rewritten_candidates.append(" ".join(parts))
    return ", ".join(rewritten_candidates)


def _html_uses_tailwind_utilities(html_content: str) -> bool:
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


def prepare_html_for_file_based_export(html_content: str, base_url: str) -> str:
    """为 file:// 导出预处理 HTML 资源地址。"""
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
        rewrite_attr(attr, resolve_export_resource_url)

    rewrite_attr("srcset", _rewrite_export_srcset)
    rewrite_attr("style", _rewrite_export_css_urls)

    prepared = re.sub(
        r"(<style\b[^>]*>)(.*?)(</style>)",
        lambda match: f"{match.group(1)}{_rewrite_export_css_urls(match.group(2), normalized_base_url)}{match.group(3)}",
        prepared,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return prepared
