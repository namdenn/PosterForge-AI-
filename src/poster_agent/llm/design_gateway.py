"""Provider-neutral contracts for autonomous creative direction and composition."""

from pathlib import Path
from typing import Protocol

from poster_agent.domain.blueprint import CreativeBlueprint
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.render import (
    ArtworkLayoutDecision,
    BrandTokens,
    CreativeTerritory,
    DesignConcept,
    RenderPlan,
    TerritoryPortfolio,
)
from poster_agent.llm.gateway import GenerationMetadata


class DesignGenerator(Protocol):
    """Plan distinct territories, then turn each territory into a free-form scene graph."""

    async def generate_territories(
        self,
        *,
        brief: CampaignBrief,
        blueprint: CreativeBlueprint,
        brand_tokens: BrandTokens,
        approved_product_available: bool,
        feedback: list[str] | None = None,
    ) -> tuple[TerritoryPortfolio, GenerationMetadata]: ...

    async def generate_concept(
        self,
        *,
        brief: CampaignBrief,
        blueprint: CreativeBlueprint,
        brand_tokens: BrandTokens,
        territory: CreativeTerritory,
        concept_index: int,
        approved_product_available: bool,
        feedback: list[str] | None = None,
    ) -> tuple[DesignConcept, GenerationMetadata]: ...


class VisualLayoutRefiner(Protocol):
    """Inspect generated artwork before placing exact copy and locked assets."""

    async def refine_overlay(
        self,
        *,
        artwork_path: Path,
        concept: DesignConcept,
        plan: RenderPlan,
        feedback: list[str] | None = None,
    ) -> tuple[ArtworkLayoutDecision, GenerationMetadata]: ...
