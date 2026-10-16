"""Provider-neutral generation contract for Sprint 2 specialist agents."""

from typing import Protocol

from poster_agent.domain.blueprint import (
    ContextBundle,
    MessagingProposal,
    StrategyProposal,
    VisualProposal,
)
from poster_agent.domain.brief import CampaignBrief
from poster_agent.llm.gateway import GenerationMetadata


class CreativeGenerator(Protocol):
    """Generate three independent typed proposals for parallel execution."""

    async def generate_messaging(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[MessagingProposal, GenerationMetadata]: ...

    async def generate_visual(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[VisualProposal, GenerationMetadata]: ...

    async def generate_strategy(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[StrategyProposal, GenerationMetadata]: ...
