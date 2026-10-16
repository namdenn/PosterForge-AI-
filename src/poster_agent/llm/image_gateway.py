"""Provider-neutral ports for Sprint 3 image generation and visual review."""

from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from poster_agent.domain.blueprint import CreativeBlueprint
from poster_agent.domain.render import GeneratedCandidate, QualityReport, RenderPlan


class ImageGenerationRequest(BaseModel):
    """One bounded concept-art generation request."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    concept_id: str
    attempt: int = Field(ge=1)
    prompt: str
    output_path: Path
    reference_paths: list[Path] = Field(default_factory=list, max_length=4)
    size: str
    quality: Literal["low", "medium", "high", "auto"]


class ImageGenerator(Protocol):
    """Generate a key visual and persist it before checkpointing state."""

    async def generate(self, request: ImageGenerationRequest) -> GeneratedCandidate: ...


class VisualReviewer(Protocol):
    """Review a composed poster using image understanding."""

    async def review_background(
        self,
        *,
        candidate_id: str,
        background_path: Path,
        plan: RenderPlan,
    ) -> QualityReport:
        """Reject generated artwork that violates protected brand/copy regions."""

        ...

    async def review(
        self,
        *,
        candidate_id: str,
        poster_path: Path,
        blueprint: CreativeBlueprint,
    ) -> QualityReport: ...
