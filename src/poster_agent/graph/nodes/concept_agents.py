"""Parallel OpenAI specialist nodes for messaging, visuals, and strategy."""

from collections.abc import Callable, Coroutine
from typing import Any

from poster_agent.domain.enums import CampaignStatus
from poster_agent.graph.rag_state import ragState
from poster_agent.llm.creative_gateway import CreativeGenerator

GraphNode = Callable[[ragState], Coroutine[Any, Any, ragState]]


def begin_concept_attempt(state: ragState) -> ragState:
    return {
        "concept_attempt": state.get("concept_attempt", 0) + 1,
        "status": CampaignStatus.RUNNING,
    }


def make_messaging_agent(generator: CreativeGenerator) -> GraphNode:
    async def messaging_agent(state: ragState) -> ragState:
        proposal, metadata = await generator.generate_messaging(
            state["brief"],
            state["context_bundle"],
            feedback=state.get("review_errors"),
        )
        return {"messaging_proposal": proposal, "generation_metadata": [metadata]}

    return messaging_agent


def make_visual_agent(generator: CreativeGenerator) -> GraphNode:
    async def visual_agent(state: ragState) -> ragState:
        proposal, metadata = await generator.generate_visual(
            state["brief"],
            state["context_bundle"],
            feedback=state.get("review_errors"),
        )
        return {"visual_proposal": proposal, "generation_metadata": [metadata]}

    return visual_agent


def make_strategy_agent(generator: CreativeGenerator) -> GraphNode:
    async def strategy_agent(state: ragState) -> ragState:
        proposal, metadata = await generator.generate_strategy(
            state["brief"],
            state["context_bundle"],
            feedback=state.get("review_errors"),
        )
        return {"strategy_proposal": proposal, "generation_metadata": [metadata]}

    return strategy_agent
