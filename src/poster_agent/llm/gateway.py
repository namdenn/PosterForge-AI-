"""Provider-neutral language-model boundary."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from poster_agent.domain.brand import BrandProfile
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.strategy import CampaignStrategy


class GenerationMetadata(BaseModel):
    """Operational metadata kept separate from the business result."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    response_id: str | None = None
    operation: str = "strategy"
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class StrategyGenerationResult(BaseModel):
    """Typed strategy plus provider metadata."""

    model_config = ConfigDict(extra="forbid")

    strategy: CampaignStrategy
    metadata: GenerationMetadata


class StrategyGenerator(Protocol):
    """Contract implemented by OpenAI in production and fakes in tests."""

    async def generate_strategy(
        self,
        brief: CampaignBrief,
        *,
        brand_profile: BrandProfile | None = None,
        feedback: list[str] | None = None,
    ) -> StrategyGenerationResult:
        """Generate a typed campaign strategy."""

        ...
