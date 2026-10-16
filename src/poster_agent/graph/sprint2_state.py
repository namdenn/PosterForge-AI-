"""Checkpointed state for the Sprint 2 RAG and parallel-agent graph."""

import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict

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
from poster_agent.domain.enums import CampaignStatus
from poster_agent.llm.gateway import GenerationMetadata


class Sprint2State(TypedDict, total=False):
    """Each parallel branch owns unique keys; metadata uses an explicit reducer."""

    workflow_version: str
    thread_id: str
    brief_path: str
    raw_brief: dict[str, Any]
    brief: CampaignBrief
    status: CampaignStatus
    validation_errors: list[str]
    brand_profile: BrandProfile
    brand_evidence: list[EvidenceReference]
    product_evidence: list[EvidenceReference]
    audience_evidence: list[EvidenceReference]
    channel_guidance: list[str]
    context_bundle: ContextBundle
    messaging_proposal: MessagingProposal
    visual_proposal: VisualProposal
    strategy_proposal: StrategyProposal
    blueprint: CreativeBlueprint
    brand_review: ReviewReport
    compliance_review: ReviewReport
    feasibility_review: ReviewReport
    review_errors: list[str]
    concept_attempt: int
    max_concept_attempts: int
    generation_metadata: Annotated[list[GenerationMetadata], operator.add]
    artifact_path: Path
