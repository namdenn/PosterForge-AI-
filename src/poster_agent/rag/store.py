"""Tenant-scoped SQLite knowledge store for local Sprint 2 execution."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import aiosqlite
from pydantic import BaseModel, ConfigDict, Field

from poster_agent.domain.brand import BrandProfile, EvidenceReference


class IndexedChunk(BaseModel):
    """One text chunk and its normalized embedding."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    brand_id: str
    document_id: str
    chunk_id: str
    source_version: str
    source_path: str
    text: str = Field(min_length=1)
    embedding: list[float] = Field(min_length=1)


class BrandKnowledgeStore(Protocol):
    """Persistence contract shared by ingestion and retrieval."""

    async def setup(self) -> None: ...

    async def replace_document(self, chunks: list[IndexedChunk]) -> None: ...

    async def search(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        query_embedding: list[float],
        limit: int,
    ) -> list[EvidenceReference]: ...

    async def save_profile(self, profile: BrandProfile) -> None: ...

    async def get_profile(self, *, tenant_id: str, brand_id: str) -> BrandProfile | None: ...

    async def count_chunks(self, *, tenant_id: str, brand_id: str) -> int: ...


class SQLiteBrandKnowledgeStore:
    """Small local vector store with mandatory tenant and brand filtering."""

    def __init__(self, path: Path) -> None:
        self._path = path

    async def setup(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._path) as database:
            await database.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS brand_chunks (
                    tenant_id TEXT NOT NULL,
                    brand_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    text TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, brand_id, chunk_id)
                );
                CREATE INDEX IF NOT EXISTS ix_brand_chunks_scope
                    ON brand_chunks (tenant_id, brand_id);
                CREATE TABLE IF NOT EXISTS brand_profiles (
                    tenant_id TEXT NOT NULL,
                    brand_id TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, brand_id)
                );
                """
            )
            await database.commit()

    async def replace_document(self, chunks: list[IndexedChunk]) -> None:
        if not chunks:
            return
        first = chunks[0]
        scope = (first.tenant_id, first.brand_id, first.document_id)
        if any((item.tenant_id, item.brand_id, item.document_id) != scope for item in chunks):
            raise ValueError("All replacement chunks must belong to one scoped document.")

        now = datetime.now(UTC).isoformat()
        async with aiosqlite.connect(self._path) as database:
            await database.execute("BEGIN IMMEDIATE")
            await database.execute(
                """
                DELETE FROM brand_chunks
                WHERE tenant_id = ? AND brand_id = ? AND document_id = ?
                """,
                scope,
            )
            await database.executemany(
                """
                INSERT INTO brand_chunks (
                    tenant_id, brand_id, document_id, chunk_id, source_version,
                    source_path, text, embedding_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.tenant_id,
                        item.brand_id,
                        item.document_id,
                        item.chunk_id,
                        item.source_version,
                        item.source_path,
                        item.text,
                        json.dumps(item.embedding),
                        now,
                    )
                    for item in chunks
                ],
            )
            await database.commit()

    async def search(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        query_embedding: list[float],
        limit: int,
    ) -> list[EvidenceReference]:
        async with aiosqlite.connect(self._path) as database:
            database.row_factory = aiosqlite.Row
            cursor = await database.execute(
                """
                SELECT document_id, chunk_id, source_version, source_path, text, embedding_json
                FROM brand_chunks
                WHERE tenant_id = ? AND brand_id = ?
                """,
                (tenant_id, brand_id),
            )
            rows = await cursor.fetchall()

        scored: list[tuple[float, aiosqlite.Row]] = []
        for row in rows:
            candidate = json.loads(row["embedding_json"])
            if not isinstance(candidate, list) or len(candidate) != len(query_embedding):
                continue
            score = sum(
                float(a) * float(b) for a, b in zip(candidate, query_embedding, strict=True)
            )
            scored.append((max(0.0, min(1.0, score)), row))
        scored.sort(key=lambda item: item[0], reverse=True)

        return [
            EvidenceReference(
                tenant_id=tenant_id,
                brand_id=brand_id,
                document_id=row["document_id"],
                chunk_id=row["chunk_id"],
                source_version=row["source_version"],
                source_path=row["source_path"],
                excerpt=row["text"],
                relevance_score=score,
            )
            for score, row in scored[:limit]
        ]

    async def save_profile(self, profile: BrandProfile) -> None:
        async with aiosqlite.connect(self._path) as database:
            await database.execute(
                """
                INSERT INTO brand_profiles (tenant_id, brand_id, profile_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (tenant_id, brand_id) DO UPDATE SET
                    profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (
                    profile.tenant_id,
                    profile.brand_id,
                    profile.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )
            await database.commit()

    async def get_profile(self, *, tenant_id: str, brand_id: str) -> BrandProfile | None:
        async with aiosqlite.connect(self._path) as database:
            cursor = await database.execute(
                """
                SELECT profile_json FROM brand_profiles
                WHERE tenant_id = ? AND brand_id = ?
                """,
                (tenant_id, brand_id),
            )
            row = await cursor.fetchone()
        return BrandProfile.model_validate_json(row[0]) if row else None

    async def count_chunks(self, *, tenant_id: str, brand_id: str) -> int:
        async with aiosqlite.connect(self._path) as database:
            cursor = await database.execute(
                """
                SELECT COUNT(*) FROM brand_chunks
                WHERE tenant_id = ? AND brand_id = ?
                """,
                (tenant_id, brand_id),
            )
            row = await cursor.fetchone()
        return int(row[0]) if row else 0
