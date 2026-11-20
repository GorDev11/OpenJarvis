"""Upload / Paste router for ingesting documents into the knowledge store."""

from __future__ import annotations

import base64
import io
import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/connectors/upload", tags=["upload"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS = {".txt", ".md", ".csv", ".pdf", ".docx"}


def _chunk_text(text: str, max_chars: int = 1000) -> List[str]:
    """Split *text* into ~max_chars pieces at paragraph boundaries."""
    paragraphs = text.split("\n\n")
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current and len(current) + len(para) + 2 > max_chars:
            chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current.strip():
        chunks.append(current.strip())
    # Guard against very large paragraphs that exceed max_chars
    final: List[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            # Find last space within limit
            split_at = chunk.rfind(" ", 0, max_chars)
            if split_at == -1:
                split_at = max_chars
            final.append(chunk[:split_at].strip())
            chunk = chunk[split_at:].strip()
        if chunk:
            final.append(chunk)
    return final


def _extract_text_from_pdf(data: bytes) -> str:
    """Extract text from a PDF using pdfplumber or PyPDF2."""
    # Try pdfplumber first
    try:
        import pdfplumber  # type: ignore[import-untyped]

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n\n".join(pages)
    except ImportError:
        pass

    # Fall back to PyPDF2
    try:
        from PyPDF2 import PdfReader  # type: ignore[import-untyped]

        reader = PdfReader(io.BytesIO(data))
        pages = [p.extract_text() or "" for p in reader.pages]
        return "\n\n".join(pages)
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=(
                "PDF parsing requires pdfplumber or PyPDF2. "
                "Install one with: pip install pdfplumber"
            ),
        )


def _extract_text_from_docx(data: bytes) -> str:
    """Extract text from a .docx file using python-docx."""
    try:
        from docx import Document  # type: ignore[import-untyped]

        doc = Document(io.BytesIO(data))
        return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail=(
                "DOCX parsing requires python-docx. "
                "Install with: pip install python-docx"
            ),
        )


def _get_store() -> KnowledgeStore:
    """Return a KnowledgeStore pointing at the default knowledge DB."""
    db_path = DEFAULT_CONFIG_DIR / "knowledge.db"
    return KnowledgeStore(db_path=db_path)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PasteRequest(BaseModel):
    title: str = ""
    content: str


class IngestResponse(BaseModel):
    chunks_added: int
    source: str = "upload"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# Chat attachments are ephemeral by design: unlike /ingest/files, this route
# does not silently index a private attachment in the global knowledge DB.
# The client supplies the bounded extracted excerpt as chat context.
_CHAT_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".jsonl",
    ".log",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".html",
    ".htm",
    ".css",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".swift",
    ".rb",
    ".php",
}
_CHAT_DOCUMENT_EXTENSIONS = {".pdf", ".docx"}
_CHAT_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_CHAT_IMAGE_MAX_BYTES = 450 * 1024
_CHAT_MAX_FILES = 4
_CHAT_MAX_FILE_BYTES = 5 * 1024 * 1024
_CHAT_MAX_FILE_CHARS = 7_000
_CHAT_MAX_TOTAL_CHARS = 18_000


class ChatAttachment(BaseModel):
    name: str
    size: int
    text: str
    truncated: bool
    mime_type: str | None = None
    data_url: str | None = None


class ChatAttachmentsResponse(BaseModel):
    files: list[ChatAttachment]


@router.post("/chat-files", response_model=ChatAttachmentsResponse)
async def parse_chat_attachments(
    files: List[UploadFile] = File(...),
) -> ChatAttachmentsResponse:
    """Parse small files for the current chat without persisting raw uploads.

    Supports source code/text natively and reuses existing PDF/DOCX parsers.
    Size and excerpt budgets keep an RTX 3060 hybrid-model prompt bounded.
    """
    import asyncio
    from pathlib import PurePosixPath

    if len(files) > _CHAT_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Attach at most {_CHAT_MAX_FILES} files per message.",
        )

    processed: list[ChatAttachment] = []
    total_chars = 0
    image_count = 0

    for uploaded in files:
        # Never trust client-provided paths or MIME headers.
        name = PurePosixPath((uploaded.filename or "untitled").replace("\\", "/")).name
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in (
            _CHAT_TEXT_EXTENSIONS | _CHAT_DOCUMENT_EXTENSIONS | _CHAT_IMAGE_EXTENSIONS
        ):
            raise HTTPException(
                status_code=415,
                detail=f"File type {ext or '(none)'} is not supported in Chat yet.",
            )

        data = await uploaded.read(_CHAT_MAX_FILE_BYTES + 1)
        await uploaded.close()
        if len(data) > _CHAT_MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{name} exceeds the 5 MB attachment limit.",
            )
        if not data:
            raise HTTPException(status_code=422, detail=f"{name} is empty.")

        if ext in _CHAT_IMAGE_EXTENSIONS:
            image_count += 1
            if image_count > 1:
                raise HTTPException(
                    status_code=400,
                    detail="Attach one image per message (vision model limitation).",
                )
            if len(data) > _CHAT_IMAGE_MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"{name} is too large after compression (450 KB maximum).",
                )
            is_png = ext == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n")
            is_jpeg = ext in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff")
            if not (is_png or is_jpeg):
                raise HTTPException(
                    status_code=415,
                    detail=f"{name} is not a valid PNG or JPEG file.",
                )
            mime = "image/png" if is_png else "image/jpeg"
            processed.append(
                ChatAttachment(
                    name=name,
                    size=len(data),
                    text="",
                    truncated=False,
                    mime_type=mime,
                    data_url=f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
                )
            )
            continue

        try:
            if ext == ".pdf":
                extracted = await asyncio.to_thread(_extract_text_from_pdf, data)
            elif ext == ".docx":
                extracted = await asyncio.to_thread(_extract_text_from_docx, data)
            else:
                # UTF-8 is the expected encoding for code and text attachments.
                # The BOM-aware decoder also accepts Windows-saved UTF-8 files.
                extracted = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"{name} is not UTF-8 text.",
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Chat attachment extraction failed (%s): %s", name, exc)
            raise HTTPException(
                status_code=422,
                detail=f"Could not extract text from {name}.",
            ) from exc

        extracted = extracted.strip()
        if not extracted:
            raise HTTPException(
                status_code=422,
                detail=f"No selectable text found in {name}; scanned PDFs require OCR.",
            )
        available = min(
            _CHAT_MAX_FILE_CHARS,
            _CHAT_MAX_TOTAL_CHARS - total_chars,
        )
        if available <= 0:
            raise HTTPException(
                status_code=413,
                detail="Combined attachment text is too large for one message.",
            )
        snippet = extracted[:available]
        processed.append(
            ChatAttachment(
                name=name,
                size=len(data),
                text=snippet,
                truncated=len(extracted) > len(snippet),
            )
        )
        total_chars += len(snippet)

    return ChatAttachmentsResponse(files=processed)


@router.post("/ingest", response_model=IngestResponse)
async def ingest_paste(body: PasteRequest) -> IngestResponse:
    """Ingest pasted text into the knowledge store."""
    text = body.content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Content is empty")

    store = _get_store()
    doc_id = str(uuid.uuid4())
    chunks = _chunk_text(text)

    for idx, chunk in enumerate(chunks):
        store.store(
            chunk,
            source="upload",
            doc_type="paste",
            doc_id=doc_id,
            title=body.title or "Pasted text",
            chunk_index=idx,
        )

    logger.info("Ingested %d chunks from pasted text (doc_id=%s)", len(chunks), doc_id)
    return IngestResponse(chunks_added=len(chunks))


@router.post("/ingest/files", response_model=IngestResponse)
async def ingest_files(
    files: List[UploadFile] = File(...),
    title: Optional[str] = Form(None),
) -> IngestResponse:
    """Ingest uploaded files into the knowledge store."""
    store = _get_store()
    total_chunks = 0

    for upload in files:
        filename = upload.filename or "untitled"
        ext = ""
        if "." in filename:
            ext = "." + filename.rsplit(".", 1)[-1].lower()

        if ext not in _ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(_ALLOWED_EXTENSIONS))
            raise HTTPException(
                status_code=400,
                detail=(f"Unsupported file type: {ext}. Allowed: {allowed}"),
            )

        data = await upload.read()

        # Parse content based on extension
        if ext in (".txt", ".md", ".csv"):
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("latin-1")
        elif ext == ".pdf":
            text = _extract_text_from_pdf(data)
        elif ext == ".docx":
            text = _extract_text_from_docx(data)
        else:
            continue

        text = text.strip()
        if not text:
            continue

        doc_id = str(uuid.uuid4())
        doc_title = title or filename
        chunks = _chunk_text(text)

        for idx, chunk in enumerate(chunks):
            store.store(
                chunk,
                source="upload",
                doc_type=ext.lstrip("."),
                doc_id=doc_id,
                title=doc_title,
                chunk_index=idx,
            )

        total_chunks += len(chunks)
        logger.info(
            "Ingested %d chunks from file %s (doc_id=%s)",
            len(chunks),
            filename,
            doc_id,
        )

    return IngestResponse(chunks_added=total_chunks)
