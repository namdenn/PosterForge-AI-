"""Typed contracts for Sprint 3 visual assets, rendering, and quality review."""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from poster_agent.domain.blueprint import CreativeBlueprint
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import (
    ApprovalStatus,
    AssetType,
    MarketingChannel,
    RenderStatus,
    RiskSeverity,
)

SceneLayerType = Literal[
    "shape",
    "headline",
    "primary_message",
    "support_message",
    "call_to_action",
    "locked_logo",
    "approved_product",
]
ShapeKind = Literal["rectangle", "rounded_rectangle", "ellipse", "line"]
TextAlign = Literal["left", "center", "right"]
VerticalAlign = Literal["top", "center", "bottom"]
FontFamily = Literal[
    "brand",
    "segoe_ui",
    "arial",
    "calibri",
    "bahnschrift",
    "georgia",
    "cambria",
    "constantia",
    "corbel",
    "times_new_roman",
    "trebuchet_ms",
    "verdana",
]
FontWeight = Literal["auto", "regular", "semibold", "bold", "black"]
FontStyle = Literal["normal", "italic"]
TextTransform = Literal["preserve", "uppercase", "lowercase", "titlecase"]


class BlueprintArtifact(BaseModel):
    """Validated Sprint 2 artifact consumed by the rendering workflow."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    thread_id: str = Field(min_length=1)
    brief: CampaignBrief
    creative_blueprint: CreativeBlueprint
    generation: list[dict[str, Any]] = Field(default_factory=list)
    status: str


class AssetRecord(BaseModel):
    """One versioned, explicitly approved local visual asset."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    asset_id: str = Field(min_length=1)
    asset_type: AssetType
    path: Path
    version: str = Field(min_length=1)
    approval_status: ApprovalStatus = ApprovalStatus.APPROVED
    allowed_channels: list[MarketingChannel] = Field(default_factory=list)
    description: str = ""


class BrandTokens(BaseModel):
    """Human-approved identity tokens that agents may select but never mutate."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    colors: dict[str, str] = Field(default_factory=dict)
    gradients: list[list[str]] = Field(default_factory=list, max_length=8)
    heading_font_asset_id: str | None = None
    body_font_asset_id: str | None = None
    minimum_logo_width_ratio: float = Field(default=0.12, ge=0.05, le=0.5)
    logo_clear_space_ratio: float = Field(default=0.025, ge=0.0, le=0.15)


class AssetManifest(BaseModel):
    """Tenant- and brand-scoped inventory used instead of fuzzy asset selection."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"] = "1.0"
    tenant_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    brand_tokens: BrandTokens = Field(default_factory=BrandTokens)
    assets: list[AssetRecord] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_asset_ids(self) -> "AssetManifest":
        identifiers = [item.asset_id for item in self.assets]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("asset_id values must be unique inside one manifest")
        return self


class ResolvedAsset(BaseModel):
    """Approved asset with an absolute path and verified content hash."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    asset_type: AssetType
    path: Path
    version: str
    sha256: str
    description: str = ""


class ResolvedAssets(BaseModel):
    """Exact assets selected for one render run."""

    model_config = ConfigDict(extra="forbid")

    logo: ResolvedAsset
    product: ResolvedAsset | None = None
    fonts: list[ResolvedAsset] = Field(default_factory=list)
    references: list[ResolvedAsset] = Field(default_factory=list)
    brand_tokens: BrandTokens = Field(default_factory=BrandTokens)


class NormalizedBox(BaseModel):
    """Agent-selected position represented independently from output resolution."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    width: float = Field(gt=0.0, le=1.0)
    height: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def inside_canvas(self) -> "NormalizedBox":
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("scene layer bounds must stay inside the normalized canvas")
        return self


class SceneLayer(BaseModel):
    """One renderer-agnostic layer chosen by a concept agent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    layer_id: str = Field(min_length=1, max_length=80)
    layer_type: SceneLayerType
    bounds: NormalizedBox
    z_index: int = Field(default=10, ge=0, le=1000)
    support_index: int | None = Field(default=None, ge=0, le=4)
    shape: ShapeKind = "rounded_rectangle"
    fill_token: str | None = None
    stroke_token: str | None = None
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    corner_radius: float = Field(default=0.04, ge=0.0, le=0.5)
    font_role: Literal["heading", "body"] = "body"
    font_family: FontFamily = "brand"
    font_weight: FontWeight = "auto"
    font_style: FontStyle = "normal"
    font_size_ratio: float = Field(default=0.035, ge=0.012, le=0.16)
    accent_words: list[str] = Field(default_factory=list, max_length=8)
    accent_fill_token: str | None = None
    text_align: TextAlign = "left"
    vertical_align: VerticalAlign = "center"
    text_transform: TextTransform = "preserve"
    line_spacing_ratio: float = Field(default=0.18, ge=0.05, le=0.6)
    max_lines: int = Field(default=4, ge=1, le=10)
    padding_ratio: float = Field(default=0.02, ge=0.0, le=0.1)

    @model_validator(mode="after")
    def complete_accent_style(self) -> "SceneLayer":
        if bool(self.accent_words) != bool(self.accent_fill_token):
            raise ValueError("accent_words and accent_fill_token must be supplied together")
        return self


class CreativeTerritory(BaseModel):
    """A campaign-specific creative territory, never a reusable fixed template."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    territory_id: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    narrative: str = Field(min_length=1)
    visual_metaphor: str = Field(min_length=1)
    storytelling_mode: str = Field(min_length=1)
    composition_logic: str = Field(min_length=1)
    hero_subject: str = Field(min_length=1)
    must_avoid: list[str] = Field(default_factory=list, max_length=12)


class TerritoryPortfolio(BaseModel):
    """Exactly three dynamically planned, mutually distinct directions."""

    model_config = ConfigDict(extra="forbid")

    territories: list[CreativeTerritory] = Field(min_length=3, max_length=3)


class DesignConcept(BaseModel):
    """Structured design authored by one parallel concept agent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    concept_id: str = Field(min_length=1, max_length=80)
    territory_id: str = Field(min_length=1, max_length=60)
    creative_thesis: str = Field(min_length=1)
    artwork_prompt: str = Field(min_length=1)
    selected_support_messages: list[str] = Field(default_factory=list, max_length=5)
    palette_tokens: list[str] = Field(default_factory=list, max_length=8)
    layers: list[SceneLayer] = Field(min_length=3, max_length=30)
    layout_signature: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1)


class ArtworkLayoutDecision(BaseModel):
    """Vision-authored overlay plan grounded in the actual generated artwork."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    passed: bool
    score: int = Field(ge=0, le=100)
    severity: RiskSeverity
    issues: list[str] = Field(default_factory=list, max_length=10)
    recommendations: list[str] = Field(default_factory=list, max_length=10)
    layers: list[SceneLayer] = Field(min_length=3, max_length=20)
    layout_signature: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1)


class DiversityReport(BaseModel):
    """Auditable structural diversity gate for the concept portfolio."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    score: int = Field(ge=0, le=100)
    issues: list[str] = Field(default_factory=list)


class RenderConfig(BaseModel):
    """Bounded runtime configuration for image generation and composition."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(default=1080, ge=512, le=4096)
    height: int = Field(default=1350, ge=512, le=4096)
    generation_size: str = "1088x1360"
    generation_quality: Literal["low", "medium", "high", "auto"] = "high"
    variant_count: int = Field(default=3, ge=1, le=3)
    max_render_attempts: int = Field(default=2, ge=1, le=3)
    max_layout_attempts: int = Field(default=2, ge=1, le=3)
    qa_threshold: int = Field(default=75, ge=0, le=100)


class RenderPlan(BaseModel):
    """Dynamic bridge between creative agents and the generic renderer."""

    model_config = ConfigDict(extra="forbid")

    width: int
    height: int
    safe_margin: int
    concepts: list[DesignConcept] = Field(min_length=1, max_length=3)
    diversity: DiversityReport
    headline: str
    primary_message: str
    supporting_messages: list[str] = Field(default_factory=list, max_length=5)
    call_to_action: str
    palette: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    brand_tokens: BrandTokens = Field(default_factory=BrandTokens)


class GeneratedCandidate(BaseModel):
    """Provider-generated key visual before trusted brand composition."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    concept_id: str = ""
    attempt: int = Field(ge=1)
    prompt: str
    generated_path: Path
    provider: str
    model: str
    response_id: str | None = None
    revised_prompt: str | None = None


class ComposedCandidate(BaseModel):
    """Poster candidate after exact text and approved assets are composited."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    concept_id: str = ""
    attempt: int = Field(ge=1)
    source_path: Path
    poster_path: Path
    width: int
    height: int
    rendered_text: list[str]
    asset_ids: list[str]
    locked_asset_hashes: dict[str, str] = Field(default_factory=dict)
    layout_signature: str = ""


class QualityReport(BaseModel):
    """One auditable review result for one poster candidate."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    reviewer: str
    passed: bool
    score: int = Field(ge=0, le=100)
    severity: RiskSeverity
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class RenderSelection(BaseModel):
    """Ranked result chosen by the QA join or a human approver."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    poster_path: Path
    score: float = Field(ge=0, le=100)
    approval_status: ApprovalStatus
    human_reason: str | None = None


class RenderManifest(BaseModel):
    """Final Sprint 3 hand-off with complete render and review provenance."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["3.0", "3.1", "3.2"] = "3.2"
    render_id: str
    source_thread_id: str
    tenant_id: str
    campaign_id: str
    brand_id: str
    status: RenderStatus
    selection: RenderSelection
    candidates: list[ComposedCandidate]
    reviews: list[QualityReport]
    render_plan: RenderPlan | None = None
    final_poster_path: Path
