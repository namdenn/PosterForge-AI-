"""OpenAI Structured Output adapters for Sprint 2 specialist agents."""

from importlib.resources import files
from typing import TypeVar

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from poster_agent.domain.blueprint import (
    ContextBundle,
    MessagingProposal,
    StrategyProposal,
    VisualProposal,
)
from poster_agent.domain.brand import BrandProfile, EvidenceReference
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.errors import ModelOutputError, StrategyGenerationError
from poster_agent.llm.gateway import GenerationMetadata
from poster_agent.llm.retry import openai_retrying

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class BrandProfileDraft(BaseModel):
    """LLM-owned profile fields; evidence is attached by trusted application code."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    personality_traits: list[str] = Field(min_length=1, max_length=8)
    tone_of_voice: list[str] = Field(min_length=1, max_length=8)
    visual_keywords: list[str] = Field(min_length=1, max_length=12)
    preferred_colors: list[str] = Field(default_factory=list, max_length=12)
    forbidden_claims: list[str] = Field(default_factory=list, max_length=20)


class OpenAICreativeGenerator:
    """Generate brand profiles and parallel campaign proposals via Responses API."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._model = model
        prompt_root = files("poster_agent.prompts")
        self._prompts = {
            "brand_profile": prompt_root.joinpath("brand_profile_v1.md").read_text(
                encoding="utf-8"
            ),
            "messaging": prompt_root.joinpath("messaging_v1.md").read_text(encoding="utf-8"),
            "visual": prompt_root.joinpath("visual_v1.md").read_text(encoding="utf-8"),
            "campaign_strategy": prompt_root.joinpath("campaign_strategy_v2.md").read_text(
                encoding="utf-8"
            ),
        }

    async def build(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        brand_name: str,
        evidence: list[EvidenceReference],
    ) -> BrandProfile:
        """Synthesize a brand profile while application code retains source evidence."""

        self._validate_evidence_scope(evidence, tenant_id=tenant_id, brand_id=brand_id)
        evidence_text = "\n\n".join(f"[{item.chunk_id}] {item.excerpt}" for item in evidence)
        draft, _ = await self._parse(
            operation="brand_profile",
            output_type=BrandProfileDraft,
            instructions=self._prompts["brand_profile"],
            input_text=f"BRAND NAME: {brand_name}\n\nEVIDENCE:\n{evidence_text}",
        )
        return BrandProfile(
            tenant_id=tenant_id,
            brand_id=brand_id,
            brand_name=brand_name,
            personality_traits=draft.personality_traits,
            tone_of_voice=draft.tone_of_voice,
            visual_keywords=draft.visual_keywords,
            preferred_colors=draft.preferred_colors,
            forbidden_claims=draft.forbidden_claims,
            evidence=evidence,
        )

    async def generate_messaging(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[MessagingProposal, GenerationMetadata]:
        return await self._parse(
            operation="messaging",
            output_type=MessagingProposal,
            instructions=self._prompts["messaging"],
            input_text=self._campaign_input(brief, context, feedback),
        )

    async def generate_visual(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[VisualProposal, GenerationMetadata]:
        return await self._parse(
            operation="visual",
            output_type=VisualProposal,
            instructions=self._prompts["visual"],
            input_text=self._campaign_input(brief, context, feedback),
        )

    async def generate_strategy(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[StrategyProposal, GenerationMetadata]:
        return await self._parse(
            operation="campaign_strategy",
            output_type=StrategyProposal,
            instructions=self._prompts["campaign_strategy"],
            input_text=self._campaign_input(brief, context, feedback),
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
            raise StrategyGenerationError(
                f"OpenAI operation '{operation}' failed. Check model access and network."
            ) from exc

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
    def _campaign_input(
        brief: CampaignBrief,
        context: ContextBundle,
        feedback: list[str] | None,
    ) -> str:
        sections = [
            "CAMPAIGN BRIEF",
            brief.model_dump_json(indent=2),
            "VERIFIED CONTEXT",
            context.model_dump_json(indent=2),
        ]
        if feedback:
            sections.extend(["REVIEW FEEDBACK TO FIX", "\n".join(f"- {item}" for item in feedback)])
        return "\n\n".join(sections)

    @staticmethod
    def _validate_evidence_scope(
        evidence: list[EvidenceReference], *, tenant_id: str, brand_id: str
    ) -> None:
        if not evidence:
            raise ValueError("Brand profile requires at least one evidence chunk.")
        if any(item.tenant_id != tenant_id or item.brand_id != brand_id for item in evidence):
            raise ValueError("Brand profile evidence crossed a tenant or brand boundary.")
