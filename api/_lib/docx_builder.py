from __future__ import annotations

from io import BytesIO
from docx import Document

def build_docx_bytes(text: str) -> bytes:
    document = Document()

    for line in text.split('\n'):
        document.add_paragraph(line)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
