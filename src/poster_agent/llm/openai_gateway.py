"""OpenAI Responses API adapter for structured campaign strategies."""

from importlib.resources import files

from openai import AsyncOpenAI, OpenAIError

from poster_agent.domain.brand import BrandProfile
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.errors import ModelOutputError, StrategyGenerationError
from poster_agent.domain.strategy import CampaignStrategy
from poster_agent.llm.gateway import GenerationMetadata, StrategyGenerationResult
from poster_agent.llm.retry import openai_retrying


class OpenAIStrategyGenerator:
    """Translate domain input to an OpenAI request and back to domain output."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 60.0) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,
        )
        self._model = model
        self._instructions = (
            files("poster_agent.prompts").joinpath("strategy_v1.md").read_text(encoding="utf-8")
        )

    async def generate_strategy(
        self,
        brief: CampaignBrief,
        *,
        brand_profile: BrandProfile | None = None,
        feedback: list[str] | None = None,
    ) -> StrategyGenerationResult:
        """Call Responses API with a Pydantic output schema and bounded retry."""

        request_text = self._build_request(brief, brand_profile, feedback)
        try:
            async for attempt in openai_retrying():
                with attempt:
                    response = await self._client.responses.parse(
                        model=self._model,
                        instructions=self._instructions,
                        input=request_text,
                        text_format=CampaignStrategy,
                        store=False,
                    )
        except OpenAIError as exc:
            raise StrategyGenerationError(
                "OpenAI strategy generation failed. Check credentials, model access, and network."
            ) from exc

        strategy = response.output_parsed
        if strategy is None:
            raise ModelOutputError(
                "OpenAI returned no CampaignStrategy (the response may have been refused)."
            )

        usage = response.usage
        return StrategyGenerationResult(
            strategy=strategy,
            metadata=GenerationMetadata(
                provider="openai",
                model=self._model,
                response_id=response.id,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
            ),
        )

    @staticmethod
    def _build_request(
        brief: CampaignBrief,
        brand_profile: BrandProfile | None,
        feedback: list[str] | None,
    ) -> str:
        sections = ["CAMPAIGN BRIEF", brief.model_dump_json(indent=2)]
        if brand_profile is not None:
            sections.extend(["BRAND PROFILE", brand_profile.model_dump_json(indent=2)])
        if feedback:
            feedback_text = "\n".join(f"- {item}" for item in feedback)
            sections.extend(["QUALITY FEEDBACK TO FIX", feedback_text])
        return "\n\n".join(sections)
