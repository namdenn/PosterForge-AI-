"""Composition root for the Sprint 1 LangGraph workflow."""

from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from poster_agent.graph.nodes.generate_strategy import make_generate_strategy_node
from poster_agent.graph.nodes.load_brief import load_brief
from poster_agent.graph.nodes.normalize_brief import normalize_brief
from poster_agent.graph.nodes.quality_gate import quality_gate
from poster_agent.graph.nodes.save_artifact import make_save_artifact_node
from poster_agent.graph.nodes.validate_brief import validate_brief
from poster_agent.graph.routing import route_after_quality, route_after_validation
from poster_agent.graph.state import CampaignState
from poster_agent.llm.gateway import StrategyGenerator
from poster_agent.persistence.artifact_store import ArtifactStore


def build_campaign_graph(
    *,
    generator: StrategyGenerator,
    artifact_store: ArtifactStore,
    checkpointer: Any,
) -> Any:
    """Build and compile the graph with injected infrastructure adapters."""

    builder: StateGraph[CampaignState, None, CampaignState, CampaignState] = StateGraph(
        CampaignState
    )
    builder.add_node("load_brief", load_brief)
    builder.add_node("validate_brief", validate_brief)
    builder.add_node("normalize_brief", normalize_brief)
    # LangGraph's current overloads do not recognize typed async closures; the
    # closures themselves remain fully checked in their modules.
    generate_node = cast(Any, make_generate_strategy_node(generator))
    save_node = cast(Any, make_save_artifact_node(artifact_store))
    builder.add_node(
        "generate_strategy",
        generate_node,
        input_schema=CampaignState,
    )
    builder.add_node("quality_gate", quality_gate)
    builder.add_node(
        "save_artifact",
        save_node,
        input_schema=CampaignState,
    )

    builder.add_edge(START, "load_brief")
    builder.add_edge("load_brief", "validate_brief")
    builder.add_conditional_edges(
        "validate_brief",
        route_after_validation,
        {"normalize": "normalize_brief", "stop": END},
    )
    builder.add_edge("normalize_brief", "generate_strategy")
    builder.add_edge("generate_strategy", "quality_gate")
    builder.add_conditional_edges(
        "quality_gate",
        route_after_quality,
        {"save": "save_artifact", "retry": "generate_strategy", "stop": END},
    )
    builder.add_edge("save_artifact", END)
    return builder.compile(checkpointer=checkpointer, name="poster-strategy-sprint-1")
