"""Stable domain contracts shared across application boundaries."""

from poster_agent.domain.blueprint import (
    ContextBundle,
    CreativeBlueprint,
    MessagingProposal,
    ReviewReport,
    StrategyProposal,
    VisualProposal,
)
from poster_agent.domain.brand import BrandProfile, EvidenceReference
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.render import (
    AssetManifest,
    AssetRecord,
    BlueprintArtifact,
    ComposedCandidate,
    GeneratedCandidate,
    QualityReport,
    RenderConfig,
    RenderManifest,
    RenderPlan,
    RenderSelection,
    ResolvedAsset,
    ResolvedAssets,
)
from poster_agent.domain.strategy import CampaignStrategy, StrategyRisk, VisualDirection

__all__ = [
    "BrandProfile",
    "AssetManifest",
    "AssetRecord",
    "BlueprintArtifact",
    "CampaignBrief",
    "CampaignStrategy",
    "ContextBundle",
    "CreativeBlueprint",
    "ComposedCandidate",
    "EvidenceReference",
    "GeneratedCandidate",
    "MessagingProposal",
    "QualityReport",
    "RenderConfig",
    "RenderManifest",
    "RenderPlan",
    "RenderSelection",
    "ResolvedAsset",
    "ResolvedAssets",
    "ReviewReport",
    "StrategyProposal",
    "StrategyRisk",
    "VisualDirection",
    "VisualProposal",
]
