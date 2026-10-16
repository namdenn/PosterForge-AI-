"""Tenant-scoped semantic retrieval boundary and SQLite adapter."""

from typing import Protocol

from poster_agent.domain.brand import EvidenceReference
from poster_agent.llm.embedding_gateway import EmbeddingGateway
from poster_agent.rag.store import BrandKnowledgeStore


class BrandRetriever(Protocol):
    """Retrieve auditable evidence scoped to one tenant and brand."""

    async def retrieve(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        query: str,
        limit: int = 8,
    ) -> list[EvidenceReference]: ...


class SemanticBrandRetriever:
    """Embed a query and rank only chunks inside the requested scope."""

    def __init__(self, *, store: BrandKnowledgeStore, embedder: EmbeddingGateway) -> None:
        self._store = store
        self._embedder = embedder

    async def retrieve(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        query: str,
        limit: int = 8,
    ) -> list[EvidenceReference]:
        if limit < 1:
            return []
        vectors = await self._embedder.embed([query])
        return await self._store.search(
            tenant_id=tenant_id,
            brand_id=brand_id,
            query_embedding=vectors[0],
            limit=limit,
        )
