"""OpenAI Images and vision adapters used by the Sprint 3 graph."""

import asyncio
import base64
import os
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI, OpenAIError, RateLimitError
from pydantic import BaseModel, ConfigDict, Field

from poster_agent.domain.blueprint import CreativeBlueprint
from poster_agent.domain.enums import RiskSeverity
from poster_agent.domain.errors import ImageGenerationError, ModelOutputError
from poster_agent.domain.render import GeneratedCandidate, QualityReport, RenderPlan
from poster_agent.llm.image_gateway import ImageGenerationRequest
from poster_agent.llm.retry import openai_retrying


class VisualAssessment(BaseModel):
    """Model-owned fields for visual QA; trusted code adds candidate identity."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    score: int = Field(ge=0, le=100)
    severity: Literal["low", "medium", "high", "blocking"]
    issues: list[str] = Field(default_factory=list, max_length=10)
    recommendations: list[str] = Field(default_factory=list, max_length=10)


class OpenAIImageGenerator:
    """Generate concept-led, brand-safe artwork through the OpenAI Images API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 120.0,
        max_concurrency: int = 1,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._model = model
        self._capacity = asyncio.Semaphore(max_concurrency)

    async def generate(self, request: ImageGenerationRequest) -> GeneratedCandidate:
        try:
            # LangGraph still runs three creative branches concurrently. Only the
            # provider boundary is paced so an IPM burst cannot fan out threefold.
            async with self._capacity:
                async for attempt in openai_retrying():
                    with attempt:
                        if request.reference_paths:
                            with ExitStack() as stack:
                                references = [
                                    stack.enter_context(path.open("rb"))
                                    for path in request.reference_paths
                                ]
                                response = await self._client.images.edit(
                                    model=self._model,
                                    image=references,
                                    prompt=request.prompt,
                                    size=request.size,
                                    quality=request.quality,
                                    background="opaque",
                                    output_format="png",
                                    n=1,
                                )
                        else:
                            response = await self._client.images.generate(
                                model=self._model,
                                prompt=request.prompt,
                                size=request.size,
                                quality=request.quality,
                                output_format="png",
                                moderation="auto",
                                n=1,
                            )
        except RateLimitError as exc:
            raise ImageGenerationError(
                "OpenAI Images API reached a temporary rate limit or account quota while "
                f"generating '{request.candidate_id}'. Wait for the limit to reset, verify "
                "Limits/Billing, then resume the same render ID."
            ) from exc
        except OpenAIError as exc:
            raise ImageGenerationError(
                f"OpenAI image generation failed for '{request.candidate_id}'."
            ) from exc

        if not response.data or not response.data[0].b64_json:
            raise ImageGenerationError(
                f"OpenAI returned no image data for '{request.candidate_id}'."
            )
        try:
            image_bytes = base64.b64decode(response.data[0].b64_json, validate=True)
        except ValueError as exc:
            raise ImageGenerationError("OpenAI returned invalid base64 image data.") from exc
        await asyncio.to_thread(_atomic_write_bytes, request.output_path, image_bytes)
        return GeneratedCandidate(
            candidate_id=request.candidate_id,
            concept_id=request.concept_id,
            attempt=request.attempt,
            prompt=request.prompt,
            generated_path=request.output_path,
            provider="openai",
            model=self._model,
            revised_prompt=response.data[0].revised_prompt,
        )


class OpenAIVisualReviewer:
    """Evaluate composed candidates using a vision-capable mainline model."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 120.0) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._model = model

    async def review_background(
        self,
        *,
        candidate_id: str,
        background_path: Path,
        plan: RenderPlan,
    ) -> QualityReport:
        concept = next(
            item for item in plan.concepts if item.concept_id == _concept_id(candidate_id)
        )
        requirements = {
            "forbidden": [
                "readable campaign copy, names, or numbers",
                "logos, brand marks, labels, or watermarks",
            ],
            "allowed": [
                "products and recognizable objects",
                "conceptual UI with abstract lines, dots, icons, and non-readable texture",
                "people, environments, symbols, diagrams, and expressive scenes",
            ],
            "creative_thesis": concept.creative_thesis,
            "artwork_prompt": concept.artwork_prompt,
            "canvas_requirement": "protected text and logo regions must remain usable",
            "palette": plan.palette,
        }
        assessment = await self._assess_image(
            candidate_id=candidate_id,
            image_path=background_path,
            instructions=(
                "You are a strict pre-composition artwork inspector. Products, conceptual UI, "
                "people, environments, diagrams, symbols, and recognizable objects are allowed. "
                "Fail the image for any logo, brand mark, watermark, readable unapproved text, "
                "personal data, or fake metric. Abstract UI marks and non-readable interface "
                "texture are allowed. Fail composition conflicts only when an important subject "
                "materially blocks the locked logo or makes the exact headline illegible; do not "
                "reject expressive detail merely because it approaches a support-copy or CTA "
                "region. Also fail artwork that contradicts the assigned creative thesis."
            ),
            context=f"Background requirements:\n{requirements}",
            operation="background review",
        )
        return _quality_report(
            candidate_id=candidate_id,
            reviewer="background_qa",
            assessment=assessment,
        )

    async def review(
        self,
        *,
        candidate_id: str,
        poster_path: Path,
        blueprint: CreativeBlueprint,
    ) -> QualityReport:
        context = {
            "messaging": blueprint.messaging.model_dump(mode="json"),
            "visual": blueprint.visual.model_dump(mode="json"),
            "brand_profile": blueprint.brand_profile.model_dump(mode="json"),
            "channel_guidance": blueprint.channel_guidance,
        }
        instructions = (
            "You are a strict senior art director. Review only visible visual quality, hierarchy, "
            "legibility, product prominence, brand fit, and production readiness. Fail when text "
            "or the logo covers a face, hero object, meaningful UI card, important icon, focal "
            "highlight, or the main visual path. Confirm that illustration and copy occupy "
            "complementary zones with deliberate breathing room. Reward varied but coherent font, "
            "weight, alignment, and color choices rather than a default black text stack. Treat "
            "exact text and asset provenance as separately verified. Return a conservative "
            "structured review."
        )
        assessment = await self._assess_image(
            candidate_id=candidate_id,
            image_path=poster_path,
            instructions=instructions,
            context=f"Candidate requirements:\n{context}",
            operation="visual review",
        )
        return _quality_report(
            candidate_id=candidate_id,
            reviewer="visual_qa",
            assessment=assessment,
        )

    async def _assess_image(
        self,
        *,
        candidate_id: str,
        image_path: Path,
        instructions: str,
        context: str,
        operation: str,
    ) -> VisualAssessment:
        encoded = await asyncio.to_thread(
            lambda: base64.b64encode(image_path.read_bytes()).decode("ascii")
        )
        try:
            async for attempt in openai_retrying():
                with attempt:
                    response = await self._client.responses.parse(
                        model=self._model,
                        instructions=instructions,
                        input=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": context,
                                    },
                                    {
                                        "type": "input_image",
                                        "image_url": f"data:image/png;base64,{encoded}",
                                        "detail": "high",
                                    },
                                ],
                            }
                        ],
                        text_format=VisualAssessment,
                        store=False,
                    )
        except OpenAIError as exc:
            raise ImageGenerationError(f"OpenAI {operation} failed for '{candidate_id}'.") from exc
        assessment = response.output_parsed
        if assessment is None:
            raise ModelOutputError(
                f"OpenAI returned no structured output for {operation} '{candidate_id}'."
            )
        return assessment


def _quality_report(
    *, candidate_id: str, reviewer: str, assessment: VisualAssessment
) -> QualityReport:
    return QualityReport(
        candidate_id=candidate_id,
        reviewer=reviewer,
        passed=assessment.passed,
        score=assessment.score,
        severity=RiskSeverity(assessment.severity),
        issues=assessment.issues,
        recommendations=assessment.recommendations,
    )


def _concept_id(candidate_id: str) -> str:
    suffix = candidate_id.rsplit("-", maxsplit=1)[-1].lower()
    return f"concept-{suffix}"


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
