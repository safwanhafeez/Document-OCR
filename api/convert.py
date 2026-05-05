from __future__ import annotations

import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib.docx_builder import build_docx_bytes
from _lib.guardrails import (
    assert_request,
    read_json_body,
    sanitize_unknown,
    write_error,
    write_internal_error,
    write_response,
)
from _lib.rate_limiter import check_rate_limit, rate_limit_headers

DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
FILENAME_STRIP_RE = re.compile(r"[^A-Za-z0-9_]")
MAX_FILENAME_LENGTH = 100
ALLOWED_BLOCK_TYPES = {"paragraph", "bullet", "numbered", "equation", "diagram"}


def _sanitize_filename(raw: Any) -> str:
    if not isinstance(raw, str):
        return "converted_document"
    stripped = FILENAME_STRIP_RE.sub("", raw)[:MAX_FILENAME_LENGTH]
    return stripped if stripped else "converted_document"


def _is_block(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("type") not in ALLOWED_BLOCK_TYPES:
        return False
    if not isinstance(value.get("text"), str):
        return False
    if not isinstance(value.get("indentLevel"), (int, float)):
        return False
    if not isinstance(value.get("isBold"), bool):
        return False
    if not isinstance(value.get("isItalic"), bool):
        return False
    return True


def _is_section(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("heading"), str):
        return False
    if not isinstance(value.get("headingLevel"), (int, float)):
        return False
    if value.get("headingColor") not in ("red", "black"):
        return False
    content = value.get("content")
    if not isinstance(content, list):
        return False
    return all(_is_block(item) for item in content)


def _is_analysis(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("title"), str):
        return False
    if value.get("layout") not in ("single_column", "two_column"):
        return False
    sections = value.get("sections")
    if not isinstance(sections, list):
        return False
    return all(_is_section(item) for item in sections)


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        rejection = assert_request(self)
        if rejection is not None:
            status, message, extra = rejection
            write_error(self, status, message, extra)
            return

        rate = check_rate_limit(self)
        rate_headers = rate_limit_headers(rate)
        if not rate["allowed"]:
            message = (
                "Too many requests. Temporarily blocked."
                if rate["blocked"]
                else "Rate limit exceeded."
            )
            write_error(self, 429, message, rate_headers)
            return

        try:
            body = read_json_body(self)
        except ValueError as exc:
            code = str(exc)
            if code == "body_too_large":
                write_error(self, 413, "Request body too large.", rate_headers)
            else:
                write_error(self, 400, "Invalid JSON payload.", rate_headers)
            return

        sanitized = sanitize_unknown(body)
        if not isinstance(sanitized, dict):
            write_error(self, 400, "Request body must be a JSON object.", rate_headers)
            return

        analysis = sanitized.get("analysis")
        if not _is_analysis(analysis):
            write_error(self, 400, "analysis payload is malformed.", rate_headers)
            return

        filename = _sanitize_filename(sanitized.get("filename"))

        try:
            docx_bytes = build_docx_bytes(analysis)
        except Exception:
            sys.stderr.write("scriptorium.convert_failed\n")
            traceback.print_exc()
            write_internal_error(self, rate_headers)
            return

        extra_headers: Dict[str, str] = {
            **rate_headers,
            "Content-Disposition": f'attachment; filename="{filename}.docx"',
            "Cache-Control": "no-store",
        }
        write_response(
            self,
            200,
            docx_bytes,
            extra_headers=extra_headers,
            content_type=DOCX_MIME,
        )

    def do_GET(self) -> None:
        write_error(self, 405, "Method not allowed.", {"Allow": "POST"})

    def do_OPTIONS(self) -> None:
        write_error(self, 405, "Method not allowed.", {"Allow": "POST"})

    def log_message(self, format: str, *args: object) -> None:
        return
