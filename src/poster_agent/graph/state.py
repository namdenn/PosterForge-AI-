"""Shared state passed between Sprint 1 LangGraph nodes."""

from pathlib import Path
from typing import Any, TypedDict

from poster_agent.domain.brand import BrandProfile
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import CampaignStatus
from poster_agent.domain.strategy import CampaignStrategy
from poster_agent.llm.gateway import GenerationMetadata


class CampaignState(TypedDict, total=False):
    """Checkpoint-safe state; each node returns only the keys it owns."""

    thread_id: str
    brief_path: str
    raw_brief: dict[str, Any]
    brief: CampaignBrief
    brand_profile: BrandProfile
    strategy: CampaignStrategy
    generation_metadata: GenerationMetadata
    status: CampaignStatus
    validation_errors: list[str]
    quality_errors: list[str]
    generation_attempt: int
    max_generation_attempts: int
    artifact_path: Path
