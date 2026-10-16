"""Brand knowledge contracts used by the future RAG workflow."""

from pydantic import BaseModel, ConfigDict, Field


class EvidenceReference(BaseModel):
    """Auditable reference to one retrieved brand-knowledge chunk."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    relevance_score: float = Field(ge=0.0, le=1.0)


class BrandProfile(BaseModel):
    """Evidence-backed brand personality consumed by strategy generation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    brand_name: str = Field(min_length=1)
    personality_traits: list[str] = Field(min_length=1)
    tone_of_voice: list[str] = Field(min_length=1)
    visual_keywords: list[str] = Field(default_factory=list)
    preferred_colors: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)
