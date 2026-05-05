from __future__ import annotations

import base64 as _b64
import os
from typing import Optional

from google import genai
from google.genai import types as genai_types

DEFAULT_MODEL = "gemini-2.5-pro"

_client: Optional[genai.Client] = None

def _get_client() -> genai.Client:
    global _client
    if _client is not None:
        return _client
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    _client = genai.Client(api_key=api_key)
    return _client

def _get_model_name() -> str:
    override = os.environ.get("GEMINI_MODEL", "").strip()
    return override if override else DEFAULT_MODEL

def analyze_document_image(base64_image: str, mime_type: str) -> str:
    client = _get_client()
    image_bytes = _b64.b64decode(base64_image, validate=False)

    response = client.models.generate_content(
        model=_get_model_name(),
        contents=[
            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            "Extract all the text from this document.",
        ]
    )

    raw_text = getattr(response, "text", None)
    if not raw_text or not raw_text.strip():
        raise RuntimeError("empty_model_response")

    return raw_text.strip()
