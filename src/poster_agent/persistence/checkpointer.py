"""LangGraph checkpoint providers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

# Checkpoints contain these trusted, code-owned Pydantic models and enums.
# An explicit allowlist avoids LangGraph's permissive deserialization warnings
# without allowing arbitrary third-party constructors during deserialization.
_ALLOWED_MSGPACK_TYPES = [
    ("poster_agent.domain.blueprint", "ContextBundle"),
    ("poster_agent.domain.blueprint", "CreativeBlueprint"),
    ("poster_agent.domain.blueprint", "MessagingProposal"),
    ("poster_agent.domain.blueprint", "ReviewReport"),
    ("poster_agent.domain.blueprint", "StrategyProposal"),
    ("poster_agent.domain.blueprint", "VisualProposal"),
    ("poster_agent.domain.brand", "BrandProfile"),
    ("poster_agent.domain.brand", "EvidenceReference"),
    ("poster_agent.domain.brief", "CampaignBrief"),
    ("poster_agent.domain.brief", "SupportCopyPolicy"),
    ("poster_agent.domain.enums", "ApprovalStatus"),
    ("poster_agent.domain.enums", "AssetType"),
    ("poster_agent.domain.enums", "CampaignObjective"),
    ("poster_agent.domain.enums", "CampaignStatus"),
    ("poster_agent.domain.enums", "Language"),
    ("poster_agent.domain.enums", "MarketingChannel"),
    ("poster_agent.domain.enums", "RenderStatus"),
    ("poster_agent.domain.enums", "RiskSeverity"),
    ("poster_agent.domain.render", "AssetManifest"),
    ("poster_agent.domain.render", "AssetRecord"),
    ("poster_agent.domain.render", "ArtworkLayoutDecision"),
    ("poster_agent.domain.render", "BlueprintArtifact"),
    ("poster_agent.domain.render", "BrandTokens"),
    ("poster_agent.domain.render", "ComposedCandidate"),
    ("poster_agent.domain.render", "CreativeTerritory"),
    ("poster_agent.domain.render", "DesignConcept"),
    ("poster_agent.domain.render", "DiversityReport"),
    ("poster_agent.domain.render", "GeneratedCandidate"),
    ("poster_agent.domain.render", "NormalizedBox"),
    ("poster_agent.domain.render", "QualityReport"),
    ("poster_agent.domain.render", "RenderConfig"),
    ("poster_agent.domain.render", "RenderManifest"),
    ("poster_agent.domain.render", "RenderPlan"),
    ("poster_agent.domain.render", "RenderSelection"),
    ("poster_agent.domain.render", "ResolvedAsset"),
    ("poster_agent.domain.render", "ResolvedAssets"),
    ("poster_agent.domain.render", "SceneLayer"),
    ("poster_agent.domain.render", "TerritoryPortfolio"),
    ("poster_agent.domain.strategy", "CampaignStrategy"),
    ("poster_agent.domain.strategy", "StrategyRisk"),
    ("poster_agent.domain.strategy", "VisualDirection"),
    ("poster_agent.llm.gateway", "GenerationMetadata"),
]


@asynccontextmanager
async def sqlite_checkpointer(path: Path) -> AsyncIterator[AsyncSqliteSaver]:
    """Open and initialize a local persistent checkpoint database."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serializer = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_TYPES)
    async with aiosqlite.connect(str(path)) as connection:
        saver = AsyncSqliteSaver(connection, serde=serializer)
        await saver.setup()
        yield saver
