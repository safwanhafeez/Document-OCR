from __future__ import annotations

import math
import os
import re
from typing import Dict, Set, TypedDict


class ImageValidationSuccess(TypedDict):
    valid: bool
    base64: str
    mime_type: str
    size_bytes: int


class ImageValidationFailure(TypedDict):
    valid: bool
    error: str


_DATA_URL_RE = re.compile(r"^data:([a-zA-Z0-9]+/[a-zA-Z0-9\-.+]+);base64,(.+)$", re.DOTALL)
_BASE64_STRIP_RE = re.compile(r"[^A-Za-z0-9+/=]")


def _allowed_mime_types() -> Set[str]:
    raw = os.environ.get("ALLOWED_MIME_TYPES", "image/jpeg,image/png,image/webp")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _max_bytes() -> int:
    raw = os.environ.get("MAX_IMAGE_SIZE_BYTES", "")
    if not raw:
        return 10 * 1024 * 1024
    try:
        parsed = int(raw)
    except ValueError:
        return 10 * 1024 * 1024
    return parsed if parsed > 0 else 10 * 1024 * 1024


def validate_image(data_url: object) -> Dict[str, object]:
    if not isinstance(data_url, str) or len(data_url) == 0:
        return {"valid": False, "error": "imageDataUrl must be a non-empty string."}

    match = _DATA_URL_RE.match(data_url)
    if not match:
        return {"valid": False, "error": "imageDataUrl is not a valid base64 data URL."}

    raw_mime = match.group(1)
    raw_base64 = match.group(2)
    if not raw_mime or not raw_base64:
        return {"valid": False, "error": "imageDataUrl is missing mime type or payload."}

    mime_type = raw_mime.lower()
    if mime_type not in _allowed_mime_types():
        return {"valid": False, "error": f"Unsupported image type: {mime_type}."}

    base64_clean = _BASE64_STRIP_RE.sub("", raw_base64)
    if len(base64_clean) == 0:
        return {"valid": False, "error": "imageDataUrl has an empty base64 payload."}

    remainder = len(base64_clean) % 4
    if remainder != 0:
        base64_clean = base64_clean + ("=" * (4 - remainder))

    size_bytes = math.ceil((len(base64_clean) * 3) / 4)
    if size_bytes > _max_bytes():
        return {"valid": False, "error": "Image exceeds the maximum allowed size."}

    return {
        "valid": True,
        "base64": base64_clean,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
    }
