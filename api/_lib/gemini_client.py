from __future__ import annotations

import base64 as _b64
import json
import os
import re
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types as genai_types

DEFAULT_MODEL = "gemini-2.5-pro"

SYSTEM_INSTRUCTION = (
    "You are a document analysis expert. You extract structured content from document images with "
    "high accuracy. You always respond with valid JSON only. No markdown fences, no explanation, "
    "no preamble. Preserve all text exactly as written."
)

USER_PROMPT = """Analyze this document image carefully. Return ONLY a valid raw JSON object with this exact structure. No markdown, no backticks, no explanation before or after.

{
  "title": "main document title if visible, empty string if none",
  "layout": "single_column or two_column",
  "sections": [
    {
      "heading": "section heading text, empty string if no heading for this section",
      "headingLevel": 1,
      "headingColor": "red or black",
      "content": [
        {
          "type": "paragraph or bullet or numbered or equation or diagram",
          "text": "exact text content",
          "indentLevel": 0,
          "isBold": false,
          "isItalic": false
        }
      ]
    }
  ]
}

Rules:
- Red underlined text = headingLevel 1, headingColor red
- Red non-underlined text = headingLevel 2, headingColor red
- Black underlined large text = headingLevel 2, headingColor black
- Regular body text = type paragraph
- Items preceded by a bullet, dot, or dash = type bullet
- Chemical or mathematical expressions = type equation
- Hand-drawn illustrations or diagrams = type diagram, describe the illustration in the text field
- Numbered list items = type numbered
- For two_column layout: process entire left column first top to bottom, then entire right column top to bottom
- indentLevel 0 is baseline, 1 is one indent level, 2 is two indent levels
- Preserve all arrows (->), symbols, and special characters as unicode or plaintext approximation
- isBold true only for visibly heavier weight text
- isItalic true only for clearly slanted text
- Preserve exact spelling including errors"""

_FENCE_RE = re.compile(r"```json|```", re.IGNORECASE)

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


_ALLOWED_BLOCK_TYPES = {"paragraph", "bullet", "numbered", "equation", "diagram"}


def _coerce_block(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid_block")
    block_type = raw.get("type") if raw.get("type") in _ALLOWED_BLOCK_TYPES else "paragraph"
    text = raw.get("text") if isinstance(raw.get("text"), str) else ""
    indent_raw = raw.get("indentLevel")
    if isinstance(indent_raw, (int, float)) and indent_raw >= 0:
        indent_level = min(8, int(indent_raw))
    else:
        indent_level = 0
    return {
        "type": block_type,
        "text": text,
        "indentLevel": indent_level,
        "isBold": raw.get("isBold") is True,
        "isItalic": raw.get("isItalic") is True,
    }


def _coerce_section(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid_section")
    heading = raw.get("heading") if isinstance(raw.get("heading"), str) else ""
    level_raw = raw.get("headingLevel")
    if isinstance(level_raw, (int, float)) and level_raw >= 1:
        heading_level = min(6, int(level_raw))
    else:
        heading_level = 1
    heading_color = "red" if raw.get("headingColor") == "red" else "black"
    content_raw = raw.get("content")
    content_list: List[Dict[str, Any]] = []
    if isinstance(content_raw, list):
        for item in content_raw:
            content_list.append(_coerce_block(item))
    return {
        "heading": heading,
        "headingLevel": heading_level,
        "headingColor": heading_color,
        "content": content_list,
    }


def _coerce_analysis(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("invalid_analysis")
    title = raw.get("title") if isinstance(raw.get("title"), str) else ""
    layout = "two_column" if raw.get("layout") == "two_column" else "single_column"
    sections_raw = raw.get("sections")
    sections: List[Dict[str, Any]] = []
    if isinstance(sections_raw, list):
        for item in sections_raw:
            sections.append(_coerce_section(item))
    return {"title": title, "layout": layout, "sections": sections}


def analyze_document_image(base64_image: str, mime_type: str) -> Dict[str, Any]:
    client = _get_client()
    image_bytes = _b64.b64decode(base64_image, validate=False)

    response = client.models.generate_content(
        model=_get_model_name(),
        contents=[
            genai_types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            USER_PROMPT,
        ],
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )

    raw_text = getattr(response, "text", None)
    if not raw_text or not raw_text.strip():
        raise RuntimeError("empty_model_response")

    cleaned = _FENCE_RE.sub("", raw_text).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError("invalid_model_json") from exc

    return _coerce_analysis(parsed)
