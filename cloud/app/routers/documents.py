"""User-scoped reference document CRUD (base64 storage)."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.docparse import allowed_extension, extract_text_from_bytes
from app.models import Document, User
from app.schemas import DocumentListResponse, DocumentResponse

router = APIRouter(prefix="/api/documents", tags=["documents"])
logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
_MAX_DOCS_PER_USER = 3


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload a reference document (max 5 MB, 3 per user)."""
    filename = file.filename or "unknown"

    # Extension check
    if not allowed_extension(filename):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type. Allowed: .md, .txt, .pdf, .docx, .png, .jpg, .jpeg",
        )

    # Read content + size check
    content = await file.read()
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max {_MAX_FILE_BYTES // (1024 * 1024)}MB",
        )

    # Per-user count limit
    count_q = select(func.count()).select_from(Document).where(Document.user_id == user.id)
    current_count = (await db.execute(count_q)).scalar() or 0
    if current_count >= _MAX_DOCS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=f"Document limit reached ({_MAX_DOCS_PER_USER}). Delete an existing document first.",
        )

    # Extract text
    try:
        extracted = extract_text_from_bytes(content, filename)
    except ValueError as exc:
        extracted = f"[Extraction failed: {exc}]"

    # Save to DB as base64
    doc = Document(
        user_id=user.id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(content),
        content_base64=base64.b64encode(content).decode("ascii"),
        extracted_text=extracted,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    return {
        "id": doc.id,
        "filename": doc.filename,
        "content_type": doc.content_type,
        "size_bytes": doc.size_bytes,
        "extracted_chars": len(extracted),
        "created_at": doc.created_at,
    }


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List current user's reference documents."""
    query = (
        select(Document)
        .where(Document.user_id == user.id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(query)
    docs = list(result.scalars().all())

    return {
        "documents": [
            {
                "id": d.id,
                "filename": d.filename,
                "content_type": d.content_type,
                "size_bytes": d.size_bytes,
                "extracted_chars": len(d.extracted_text or ""),
                "created_at": d.created_at,
            }
            for d in docs
        ],
        "count": len(docs),
        "max_allowed": _MAX_DOCS_PER_USER,
    }


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a reference document."""
    query = select(Document).where(Document.id == doc_id, Document.user_id == user.id)
    doc = (await db.execute(query)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.commit()


async def get_user_doc_text(user_id: str, db: AsyncSession) -> str:
    """Combine all user document texts (for AI prompt injection)."""
    query = (
        select(Document.filename, Document.extracted_text)
        .where(Document.user_id == user_id)
        .order_by(Document.created_at)
    )
    result = await db.execute(query)
    rows = result.all()
    if not rows:
        return ""

    parts: list[str] = []
    for filename, text in rows:
        if text:
            parts.append(f"--- {filename} ---\n{text}")
    combined = "\n\n".join(parts)

    # Truncate to 16,000 chars (match executor.py pattern)
    if len(combined) > 16_000:
        combined = combined[:16_000] + "\n... (truncated)"
    return combined
