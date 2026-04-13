"""
Thin wrapper around the Playwright-based HTML renderer.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..pyppeteer_pdf_converter import get_pdf_converter


class HtmlRenderService:
    def __init__(
        self,
        *,
        converter: Optional[Any] = None,
        converter_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._converter = converter
        self._converter_factory = converter_factory or get_pdf_converter

    @property
    def converter(self) -> Any:
        if self._converter is None:
            self._converter = self._converter_factory()
        return self._converter

    def is_available(self) -> bool:
        return self.converter.is_available()

    async def screenshot_html(self, html_file_path: str, screenshot_path: str, **kwargs: Any) -> bool:
        return await self.converter.screenshot_html(html_file_path, screenshot_path, **kwargs)

    async def record_html_video(self, html_file_path: str, output_path: str, **kwargs: Any) -> bool:
        return await self.converter.record_html_video(html_file_path, output_path, **kwargs)
