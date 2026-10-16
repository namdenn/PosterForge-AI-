"""Tests for tenant isolation and local ingestion without external API calls."""

import asyncio
from pathlib import Path

from poster_agent.domain.brand import BrandProfile
from poster_agent.llm.embedding_gateway import EmbeddingGateway
from poster_agent.rag.ingestion import BrandDocument, LocalBrandIngestor
from poster_agent.rag.retrieval import SemanticBrandRetriever
from poster_agent.rag.store import SQLiteBrandKnowledgeStore


class FakeEmbeddingGateway(EmbeddingGateway):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "coffee" in text.casefold() else [0.0, 1.0] for text in texts]


async def test_retrieval_is_strictly_tenant_scoped(tmp_path: Path) -> None:
    store = SQLiteBrandKnowledgeStore(tmp_path / "knowledge.db")
    await store.setup()
    embedder = FakeEmbeddingGateway()
    ingestor = LocalBrandIngestor(
        store=store,
        embedder=embedder,
        chunk_size=200,
        chunk_overlap=20,
    )
    tenant_a_file = tmp_path / "tenant-a.md"
    tenant_b_file = tmp_path / "tenant-b.md"
    await asyncio.to_thread(
        tenant_a_file.write_text,
        "Coffee brand tone is energetic and modern. " * 8,
        encoding="utf-8",
    )
    await asyncio.to_thread(
        tenant_b_file.write_text,
        "Coffee brand tone is formal and traditional. " * 8,
        encoding="utf-8",
    )
    await ingestor.ingest(
        BrandDocument(
            tenant_id="tenant-a",
            brand_id="brand-1",
            document_id="doc-a",
            source_version="v1",
            path=tenant_a_file,
        )
    )
    await ingestor.ingest(
        BrandDocument(
            tenant_id="tenant-b",
            brand_id="brand-1",
            document_id="doc-b",
            source_version="v1",
            path=tenant_b_file,
        )
    )

    retriever = SemanticBrandRetriever(store=store, embedder=embedder)
    results = await retriever.retrieve(
        tenant_id="tenant-a",
        brand_id="brand-1",
        query="coffee identity",
        limit=10,
    )

    assert results
    assert {item.tenant_id for item in results} == {"tenant-a"}
    assert {item.document_id for item in results} == {"doc-a"}


async def test_profile_round_trip_is_scoped(tmp_path: Path) -> None:
    store = SQLiteBrandKnowledgeStore(tmp_path / "knowledge.db")
    await store.setup()
    profile = BrandProfile(
        tenant_id="tenant-a",
        brand_id="brand-1",
        brand_name="Brand One",
        personality_traits=["modern"],
        tone_of_voice=["clear"],
    )
    await store.save_profile(profile)

    loaded = await store.get_profile(tenant_id="tenant-a", brand_id="brand-1")
    wrong_tenant = await store.get_profile(tenant_id="tenant-b", brand_id="brand-1")

    assert loaded == profile
    assert wrong_tenant is None
