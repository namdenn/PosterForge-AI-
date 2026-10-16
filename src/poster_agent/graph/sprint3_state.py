"""Checkpointed state for Sprint 3 parallel poster rendering."""

import operator
from pathlib import Path
from typing import Annotated, TypedDict

from poster_agent.domain.blueprint import CreativeBlueprint
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import RenderStatus
from poster_agent.domain.render import (
    ArtworkLayoutDecision,
    AssetManifest,
    BlueprintArtifact,
    ComposedCandidate,
    CreativeTerritory,
    DesignConcept,
    DiversityReport,
    GeneratedCandidate,
    QualityReport,
    RenderConfig,
    RenderPlan,
    RenderSelection,
    ResolvedAssets,
    TerritoryPortfolio,
)
from poster_agent.llm.gateway import GenerationMetadata


class renderState(TypedDict, total=False):
    """Parallel render branches own unique candidate and review keys."""

    workflow_version: str
    render_id: str
    blueprint_path: str
    asset_manifest_path: str
    render_work_dir: str
    blueprint_artifact: BlueprintArtifact
    source_thread_id: str
    brief: CampaignBrief
    blueprint: CreativeBlueprint
    asset_manifest: AssetManifest
    resolved_assets: ResolvedAssets
    render_config: RenderConfig
    design_attempt: int
    max_design_attempts: int
    territory_portfolio: TerritoryPortfolio
    concept_a: DesignConcept | None
    concept_b: DesignConcept | None
    concept_c: DesignConcept | None
    design_territories: list[CreativeTerritory]
    diversity_report: DiversityReport
    design_generation_metadata: Annotated[list[GenerationMetadata], operator.add]
    render_plan: RenderPlan
    render_attempt: int
    layout_attempt: int
    candidate_a: GeneratedCandidate | None
    candidate_b: GeneratedCandidate | None
    candidate_c: GeneratedCandidate | None
    generated_candidates: list[GeneratedCandidate]
    layout_decision_a: ArtworkLayoutDecision | None
    layout_decision_b: ArtworkLayoutDecision | None
    layout_decision_c: ArtworkLayoutDecision | None
    refined_concept_a: DesignConcept | None
    refined_concept_b: DesignConcept | None
    refined_concept_c: DesignConcept | None
    artwork_layout_report_a: QualityReport | None
    artwork_layout_report_b: QualityReport | None
    artwork_layout_report_c: QualityReport | None
    background_qa: list[QualityReport]
    composed_candidates: list[ComposedCandidate]
    brand_qa: list[QualityReport]
    content_qa: list[QualityReport]
    technical_qa: list[QualityReport]
    visual_qa: list[QualityReport]
    layout_qa: list[QualityReport]
    all_reviews: list[QualityReport]
    review_errors: list[str]
    selection: RenderSelection
    status: RenderStatus
    final_poster_path: Path
    render_manifest_path: Path
