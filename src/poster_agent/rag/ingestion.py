"""Tenant-scoped local document ingestion for Sprint 2."""

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader

from poster_agent.domain.errors import BrandKnowledgeError
from poster_agent.llm.embedding_gateway import EmbeddingGateway
from poster_agent.rag.store import BrandKnowledgeStore, IndexedChunk

SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".pdf"}


class BrandDocument(BaseModel):
    """A source document ready for parsing and chunking."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    path: Path


class IngestionReport(BaseModel):
    """Observable outcome of one ingestion operation."""

    tenant_id: str
    brand_id: str
    document_id: str
    source_path: str
    chunks_indexed: int = Field(ge=0)


class BrandIngestor(Protocol):
    """Port for document parsing, chunking, embedding, and indexing."""

    async def ingest(self, document: BrandDocument) -> IngestionReport: ...


class LocalBrandIngestor:
    """Ingest Markdown, text, JSON, and PDF files into the knowledge store."""

    def __init__(
        self,
        *,
        store: BrandKnowledgeStore,
        embedder: EmbeddingGateway,
        chunk_size: int = 1200,
        chunk_overlap: int = 200,
    ) -> None:
        if chunk_size < 200:
            raise ValueError("chunk_size must be at least 200 characters")
        if chunk_overlap < 0 or chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be between 0 and chunk_size - 1")
        self._store = store
        self._embedder = embedder
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def ingest(self, document: BrandDocument) -> IngestionReport:
        text = await asyncio.to_thread(self._read_document, document.path)
        chunks = self._chunk_text(text)
        if not chunks:
            raise BrandKnowledgeError(f"Document contains no usable text: {document.path}")
        vectors = await self._embedder.embed(chunks)
        if len(vectors) != len(chunks):
            raise BrandKnowledgeError("Embedding count does not match document chunk count.")

        records = [
            IndexedChunk(
                tenant_id=document.tenant_id,
                brand_id=document.brand_id,
                document_id=document.document_id,
                chunk_id=f"{document.document_id}:chunk-{index:04d}",
                source_version=document.source_version,
                source_path=str(document.path),
                text=chunk,
                embedding=vector,
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True), start=1)
        ]
        await self._store.replace_document(records)
        return IngestionReport(
            tenant_id=document.tenant_id,
            brand_id=document.brand_id,
            document_id=document.document_id,
            source_path=str(document.path),
            chunks_indexed=len(records),
        )

    def _chunk_text(self, text: str) -> list[str]:
        normalized = re.sub(r"[ \t]+", " ", text.replace("\r\n", "\n"))
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(normalized):
            tentative_end = min(start + self._chunk_size, len(normalized))
            end = tentative_end
            if tentative_end < len(normalized):
                paragraph_break = normalized.rfind("\n\n", start, tentative_end)
                sentence_break = normalized.rfind(". ", start, tentative_end)
                candidate = max(paragraph_break, sentence_break)
                if candidate > start + self._chunk_size // 2:
                    end = candidate + (2 if candidate == paragraph_break else 1)
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(normalized):
                break
            start = max(end - self._chunk_overlap, start + 1)
        return chunks

    @staticmethod
    def _read_document(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise BrandKnowledgeError(f"Unsupported document type: {suffix}")
        if suffix == ".pdf":
            reader = PdfReader(path)
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        raw = path.read_text(encoding="utf-8")
        if suffix == ".json":
            parsed = json.loads(raw)
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        return raw


async def discover_brand_documents(
    source: Path, *, tenant_id: str, brand_id: str
) -> list[BrandDocument]:
    """Discover supported files and assign stable document/version identifiers."""

    return await asyncio.to_thread(
        _discover_brand_documents_sync,
        source,
        tenant_id,
        brand_id,
    )


def _discover_brand_documents_sync(
    source: Path, tenant_id: str, brand_id: str
) -> list[BrandDocument]:
    files = (
        [source]
        if source.is_file()
        else sorted(path for path in source.rglob("*") if path.is_file())
    )
    root = source.parent if source.is_file() else source
    documents: list[BrandDocument] = []
    for path in files:
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        relative = path.relative_to(root).as_posix()
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", relative).strip(".-").lower()
        document_id = f"{slug[:80]}-{hashlib.sha256(relative.encode()).hexdigest()[:8]}"
        documents.append(
            BrandDocument(
                tenant_id=tenant_id,
                brand_id=brand_id,
                document_id=document_id,
                source_version=content_hash[:16],
                path=path.resolve(),
            )
        )
    if not documents:
        raise BrandKnowledgeError(
            f"No supported documents found under '{source}'. Use .md, .txt, .json, or .pdf."
        )
    return documents
