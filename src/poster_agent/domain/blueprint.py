"""Typed contracts exchanged by Sprint 2 parallel agents."""

from pydantic import BaseModel, ConfigDict, Field

from poster_agent.domain.brand import BrandProfile, EvidenceReference
from poster_agent.domain.enums import ApprovalStatus, CampaignObjective, RiskSeverity
from poster_agent.domain.strategy import StrategyRisk, VisualDirection


class ContextBundle(BaseModel):
    """Auditable context assembled before concept generation."""

    model_config = ConfigDict(extra="forbid")

    brand_profile: BrandProfile
    brand_evidence: list[EvidenceReference] = Field(min_length=1)
    product_evidence: list[EvidenceReference] = Field(default_factory=list)
    audience_evidence: list[EvidenceReference] = Field(default_factory=list)
    channel_guidance: list[str] = Field(min_length=1)


class MessagingProposal(BaseModel):
    """Copy hierarchy proposed by the messaging agent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    headline: str = Field(min_length=1, max_length=180)
    primary_message: str = Field(min_length=1)
    supporting_messages: list[str] = Field(min_length=1, max_length=5)
    call_to_action: str = Field(min_length=1, max_length=200)
    tone_of_voice: list[str] = Field(min_length=1, max_length=6)
    rationale: str = Field(min_length=1)
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class VisualProposal(BaseModel):
    """Poster-ready visual system proposed by the visual agent."""

    model_config = ConfigDict(extra="forbid")

    direction: VisualDirection
    layout_notes: list[str] = Field(min_length=1, max_length=8)
    negative_constraints: list[str] = Field(default_factory=list, max_length=12)
    mandatory_elements: list[str] = Field(default_factory=list, max_length=20)
    rationale: str = Field(min_length=1)
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class StrategyProposal(BaseModel):
    """Strategic idea proposed independently of copy and visual execution."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: CampaignObjective
    audience_insight: str = Field(min_length=1)
    big_idea: str = Field(min_length=1)
    strategic_rationale: str = Field(min_length=1)
    risks: list[StrategyRisk] = Field(default_factory=list, max_length=8)
    evidence_chunk_ids: list[str] = Field(default_factory=list)


class ReviewReport(BaseModel):
    """Deterministic specialist review result."""

    model_config = ConfigDict(extra="forbid")

    reviewer: str
    passed: bool
    severity: RiskSeverity
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class CreativeBlueprint(BaseModel):
    """Approved hand-off contract for a later poster rendering sprint."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    campaign_id: str
    brand_id: str
    messaging: MessagingProposal
    visual: VisualProposal
    strategy: StrategyProposal
    brand_profile: BrandProfile
    evidence: list[EvidenceReference]
    channel_guidance: list[str]
    reviews: list[ReviewReport] = Field(default_factory=list)
    approval_status: ApprovalStatus = ApprovalStatus.DRAFT
