"""Strategy generation node with an injected provider-neutral gateway."""

from collections.abc import Callable, Coroutine
from typing import Any

from poster_agent.domain.enums import CampaignStatus
from poster_agent.graph.state import CampaignState
from poster_agent.llm.gateway import StrategyGenerator

GraphNode = Callable[[CampaignState], Coroutine[Any, Any, CampaignState]]


def make_generate_strategy_node(generator: StrategyGenerator) -> GraphNode:
    """Bind infrastructure once while leaving node state serializable."""

    async def generate_strategy(state: CampaignState) -> CampaignState:
        result = await generator.generate_strategy(
            state["brief"],
            brand_profile=state.get("brand_profile"),
            feedback=state.get("quality_errors"),
        )
        return {
            "strategy": result.strategy,
            "generation_metadata": result.metadata,
            "generation_attempt": state.get("generation_attempt", 0) + 1,
            "status": CampaignStatus.RUNNING,
        }

    return generate_strategy
