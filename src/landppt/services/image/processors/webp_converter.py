"""
WebP conversion utilities for image uploads/caching.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image


@dataclass(frozen=True)
class WebpConversionInfo:
    converted: bool
    width: int
    height: int
    color_mode: str
    has_transparency: bool
    skipped_reason: str | None = None


def convert_image_bytes_to_webp(
    image_data: bytes,
    *,
    quality: int = 80,
    method: int = 6,
    skip_if_webp: bool = True,
    skip_animated: bool = True,
) -> tuple[bytes, WebpConversionInfo]:
    """
    Convert arbitrary image bytes into WebP bytes using Pillow.

    If `skip_if_webp` is True, WebP inputs are returned as-is.
    If `skip_animated` is True, animated images are returned as-is.
    """
    with Image.open(io.BytesIO(image_data)) as img:
        width, height = img.size
        color_mode = img.mode
        has_transparency = (
            img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        )

        image_format = (img.format or "").upper()
        if skip_if_webp and image_format == "WEBP":
            return image_data, WebpConversionInfo(
                converted=False,
                width=width,
                height=height,
                color_mode=color_mode,
                has_transparency=has_transparency,
                skipped_reason="already_webp",
            )

        if skip_animated and getattr(img, "is_animated", False) and getattr(img, "n_frames", 1) > 1:
            return image_data, WebpConversionInfo(
                converted=False,
                width=width,
                height=height,
                color_mode=color_mode,
                has_transparency=has_transparency,
                skipped_reason="animated",
            )

        if has_transparency:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
        else:
            if img.mode != "RGB":
                img = img.convert("RGB")

        out = io.BytesIO()
        img.save(out, format="WEBP", quality=int(quality), method=int(method))
        converted = out.getvalue()
        return converted, WebpConversionInfo(
            converted=True,
            width=width,
            height=height,
            color_mode="RGBA" if has_transparency else "RGB",
            has_transparency=has_transparency,
            skipped_reason=None,
        )

