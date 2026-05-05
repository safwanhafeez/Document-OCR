from __future__ import annotations

import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _lib.gemini_client import analyze_document_image
from _lib.docx_builder import build_docx_bytes
from _lib.guardrails import (
    assert_request,
    read_json_body,
    sanitize_unknown,
    write_error,
    write_internal_error,
    write_response,
)
from _lib.image_validator import validate_image
from _lib.rate_limiter import check_rate_limit, rate_limit_headers

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

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

        if not isinstance(body, dict):
            write_error(self, 400, "Request body must be a JSON object.", rate_headers)
            return

        image_data_url = body.get("imageDataUrl")
        if not isinstance(image_data_url, str) or not image_data_url.strip():
            write_error(self, 400, "imageDataUrl is required.", rate_headers)
            return

        validation = validate_image(image_data_url)
        if not validation.get("valid"):
            write_error(
                self,
                400,
                str(validation.get("error", "Invalid image.")),
                rate_headers,
            )
            return

        try:
            text = analyze_document_image(
                base64_image=str(validation["base64"]),
                mime_type=str(validation["mime_type"]),
            )
            filename = sanitized.get("filename", "converted_document")
            import re
            filename = re.sub(r"[^A-Za-z0-9_]", "", filename)[:100] or "converted_document"

            docx_bytes = build_docx_bytes(text)
            extra_headers = {
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
        except Exception:
            sys.stderr.write("scriptorium.analyze_failed\n")
            traceback.print_exc()
            write_internal_error(self, rate_headers)

    def do_GET(self) -> None:
        write_error(self, 405, "Method not allowed.", {"Allow": "POST"})

    def do_OPTIONS(self) -> None:
        write_error(self, 405, "Method not allowed.", {"Allow": "POST"})

    def log_message(self, format: str, *args: object) -> None:
        return
