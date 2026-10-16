"""OpenAI Structured Output adapter for autonomous poster design agents."""

import asyncio
import base64
import json
from importlib.resources import files
from pathlib import Path
from typing import TypeVar

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel

from poster_agent.domain.blueprint import CreativeBlueprint
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.errors import ModelOutputError, StrategyGenerationError
from poster_agent.domain.render import (
    ArtworkLayoutDecision,
    BrandTokens,
    CreativeTerritory,
    DesignConcept,
    RenderPlan,
    TerritoryPortfolio,
)
from poster_agent.llm.gateway import GenerationMetadata
from poster_agent.llm.retry import openai_retrying

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class OpenAIDesignGenerator:
    """Use a director and parallel concept specialists without fixed layout templates."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 120.0) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._model = model
        prompt_root = files("poster_agent.prompts")
        self._director_prompt = prompt_root.joinpath("creative_director_v1.md").read_text(
            encoding="utf-8"
        )
        self._concept_prompt = prompt_root.joinpath("concept_designer_v1.md").read_text(
            encoding="utf-8"
        )
        self._visual_layout_prompt = prompt_root.joinpath("visual_layout_designer_v1.md").read_text(
            encoding="utf-8"
        )

    async def generate_territories(
        self,
        *,
        brief: CampaignBrief,
        blueprint: CreativeBlueprint,
        brand_tokens: BrandTokens,
        approved_product_available: bool,
        feedback: list[str] | None = None,
    ) -> tuple[TerritoryPortfolio, GenerationMetadata]:
        return await self._parse(
            operation="creative_territory_director",
            output_type=TerritoryPortfolio,
            instructions=self._director_prompt,
            input_text=self._input(
                brief, blueprint, brand_tokens, approved_product_available, feedback
            ),
        )

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
    ) -> tuple[DesignConcept, GenerationMetadata]:
        content = self._input(brief, blueprint, brand_tokens, approved_product_available, feedback)
        content += (
            "\n\nASSIGNED TERRITORY\n"
            + territory.model_dump_json(indent=2)
            + f"\n\nCONCEPT INDEX\n{concept_index}"
        )
        return await self._parse(
            operation=f"concept_designer_{concept_index + 1}",
            output_type=DesignConcept,
            instructions=self._concept_prompt,
            input_text=content,
        )

    async def refine_overlay(
        self,
        *,
        artwork_path: Path,
        concept: DesignConcept,
        plan: RenderPlan,
        feedback: list[str] | None = None,
    ) -> tuple[ArtworkLayoutDecision, GenerationMetadata]:
        """Place typography and locked assets after inspecting the real key visual."""

        context = {
            "canvas": {"width": plan.width, "height": plan.height},
            "headline": plan.headline,
            "primary_message": plan.primary_message,
            "selected_support_messages": concept.selected_support_messages,
            "call_to_action": plan.call_to_action,
            "brand_tokens": plan.brand_tokens.model_dump(mode="json"),
            "palette": plan.palette,
            "initial_concept": concept.model_dump(mode="json"),
            "feedback": feedback or [],
        }
        encoded = await asyncio.to_thread(
            lambda: base64.b64encode(artwork_path.read_bytes()).decode("ascii")
        )
        try:
            async for attempt in openai_retrying():
                with attempt:
                    response = await self._client.responses.parse(
                        model=self._model,
                        instructions=self._visual_layout_prompt,
                        input=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": json.dumps(context, ensure_ascii=False, indent=2),
                                    },
                                    {
                                        "type": "input_image",
                                        "image_url": f"data:image/png;base64,{encoded}",
                                        "detail": "high",
                                    },
                                ],
                            }
                        ],
                        text_format=ArtworkLayoutDecision,
                        store=False,
                    )
        except OpenAIError as exc:
            raise StrategyGenerationError("OpenAI visual layout refinement failed.") from exc
        parsed = response.output_parsed
        if parsed is None:
            raise ModelOutputError("OpenAI returned no structured visual layout plan.")
        usage = response.usage
        return parsed, GenerationMetadata(
            provider="openai",
            model=self._model,
            response_id=response.id,
            operation="visual_layout_refiner",
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        )

    async def _parse(
        self,
        *,
        operation: str,
        output_type: type[StructuredModel],
        instructions: str,
        input_text: str,
    ) -> tuple[StructuredModel, GenerationMetadata]:
        try:
            async for attempt in openai_retrying():
                with attempt:
                    response = await self._client.responses.parse(
                        model=self._model,
                        instructions=instructions,
                        input=input_text,
                        text_format=output_type,
                        store=False,
                    )
        except OpenAIError as exc:
            raise StrategyGenerationError(f"OpenAI design operation '{operation}' failed.") from exc
        parsed = response.output_parsed
        if parsed is None:
            raise ModelOutputError(f"OpenAI returned no structured output for '{operation}'.")
        usage = response.usage
        return parsed, GenerationMetadata(
            provider="openai",
            model=self._model,
            response_id=response.id,
            operation=operation,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        )

    @staticmethod
    def _input(
        brief: CampaignBrief,
        blueprint: CreativeBlueprint,
        brand_tokens: BrandTokens,
        approved_product_available: bool,
        feedback: list[str] | None,
    ) -> str:
        sections = [
            "CAMPAIGN BRIEF",
            brief.model_dump_json(indent=2),
            "APPROVED CREATIVE BLUEPRINT",
            blueprint.model_dump_json(indent=2),
            "LOCKED BRAND TOKENS",
            brand_tokens.model_dump_json(indent=2),
            "APPROVED PRODUCT ASSET AVAILABLE",
            str(approved_product_available),
        ]
        if feedback:
            sections.extend(["STRUCTURAL VALIDATION FEEDBACK TO FIX", "\n".join(feedback)])
        return "\n\n".join(sections)
