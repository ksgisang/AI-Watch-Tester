"""Document text extraction for uploaded files.

Supports: .md, .txt, .pdf, .docx
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".md", ".txt", ".pdf", ".docx"}


def allowed_extension(filename: str) -> bool:
    """Check if file extension is supported."""
    return Path(filename).suffix.lower() in _ALLOWED_EXTENSIONS


def extract_text(file_path: Path) -> str:
    """Extract plain text from a document file.

    Raises ValueError for unsupported formats or extraction failures.
    """
    suffix = file_path.suffix.lower()

    if suffix in (".md", ".txt"):
        return _extract_plaintext(file_path)
    elif suffix == ".pdf":
        return _extract_pdf(file_path)
    elif suffix == ".docx":
        return _extract_docx(file_path)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def _extract_plaintext(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="replace")


def _extract_pdf(file_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError("pypdf is required for PDF extraction. Install with: pip install pypdf")

    reader = PdfReader(file_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    if not pages:
        raise ValueError("PDF contains no extractable text")
    return "\n\n".join(pages)


def _extract_docx(file_path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        raise ValueError(
            "python-docx is required for DOCX extraction. Install with: pip install python-docx"
        )

    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    if not paragraphs:
        raise ValueError("DOCX contains no extractable text")
    return "\n\n".join(paragraphs)
