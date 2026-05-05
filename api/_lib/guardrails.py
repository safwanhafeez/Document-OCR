from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

MAX_BODY_BYTES = 12 * 1024 * 1024

SECURITY_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'none'",
}

_HTML_TAG_RE = re.compile(r"<[^>]*>")
_NULL_BYTE_RE = re.compile("\x00")


def _extract_host(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = urlparse(value)
        if parsed.netloc:
            return parsed.netloc.lower()
        return None
    except Exception:
        return None


def _normalize_vercel_host(raw: str) -> str:
    trimmed = raw.strip()
    if not trimmed:
        return ""
    candidate = trimmed if "://" in trimmed else f"https://{trimmed}"
    try:
        parsed = urlparse(candidate)
        return (parsed.netloc or trimmed).lower()
    except Exception:
        return trimmed.lower()


def assert_request(
    handler: BaseHTTPRequestHandler,
) -> Optional[Tuple[int, str, Dict[str, str]]]:
    if handler.command != "POST":
        return (405, "Method not allowed.", {"Allow": "POST"})

    content_type = handler.headers.get("Content-Type", "") or ""
    if "application/json" not in content_type.lower():
        return (415, "Unsupported media type. Use application/json.", {})

    content_length_raw = handler.headers.get("Content-Length")
    if content_length_raw is not None:
        try:
            content_length = int(content_length_raw)
        except ValueError:
            return (400, "Invalid Content-Length header.", {})
        if content_length > MAX_BODY_BYTES:
            return (413, "Request body too large.", {})

    if os.environ.get("VERCEL_ENV") == "production" or os.environ.get("NODE_ENV") == "production":
        vercel_host = _normalize_vercel_host(os.environ.get("VERCEL_URL", ""))
        if vercel_host:
            origin_host = _extract_host(handler.headers.get("Origin"))
            referer_host = _extract_host(handler.headers.get("Referer"))
            presented = origin_host or referer_host
            if not presented or presented != vercel_host:
                return (403, "Forbidden origin.", {})

    return None


def read_json_body(handler: BaseHTTPRequestHandler) -> Any:
    length_raw = handler.headers.get("Content-Length")
    if length_raw is None:
        return {}
    try:
        length = int(length_raw)
    except ValueError:
        raise ValueError("invalid_content_length")
    if length <= 0:
        return {}
    if length > MAX_BODY_BYTES:
        raise ValueError("body_too_large")
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid_json")


def sanitize_string(value: str) -> str:
    stripped = _HTML_TAG_RE.sub("", value)
    return _NULL_BYTE_RE.sub("", stripped)


def sanitize_unknown(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_string(value)
    if isinstance(value, list):
        return [sanitize_unknown(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_unknown(inner) for key, inner in value.items()}
    return value


def write_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    body: bytes,
    extra_headers: Optional[Dict[str, str]] = None,
    content_type: str = "application/json; charset=utf-8",
) -> None:
    handler.send_response(status)
    for key, value in SECURITY_HEADERS.items():
        handler.send_header(key, value)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    if extra_headers:
        for key, value in extra_headers.items():
            if key.lower() in ("content-type", "content-length"):
                continue
            handler.send_header(key, value)
    handler.end_headers()
    if body:
        handler.wfile.write(body)


def write_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: Any,
    extra_headers: Optional[Dict[str, str]] = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    write_response(handler, status, body, extra_headers)


def write_error(
    handler: BaseHTTPRequestHandler,
    status: int,
    message: str,
    extra_headers: Optional[Dict[str, str]] = None,
) -> None:
    write_json(handler, status, {"error": message}, extra_headers)


def write_internal_error(
    handler: BaseHTTPRequestHandler,
    extra_headers: Optional[Dict[str, str]] = None,
) -> None:
    write_error(handler, 500, "An internal error occurred.", extra_headers)
