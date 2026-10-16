"""Composition root for the Sprint 2 RAG and multi-parallel workflow."""

from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph

from poster_agent.graph.nodes.concept_agents import (
    begin_concept_attempt,
    make_messaging_agent,
    make_strategy_agent,
    make_visual_agent,
)
from poster_agent.graph.nodes.context_agents import (
    channel_context,
    context_join,
    make_audience_context_node,
    make_brand_context_node,
    make_product_context_node,
)
from poster_agent.graph.nodes.load_brief import load_brief
from poster_agent.graph.nodes.normalize_brief import normalize_brief
from poster_agent.graph.nodes.review_agents import (
    brand_guard,
    compliance_critic,
    feasibility_critic,
    review_join,
)
from poster_agent.graph.nodes.save_blueprint import make_save_blueprint_node
from poster_agent.graph.nodes.synthesize_blueprint import synthesize_blueprint
from poster_agent.graph.nodes.validate_brief import validate_brief
from poster_agent.graph.rag_routing import route_after_reviews
from poster_agent.graph.rag_state import ragState
from poster_agent.llm.creative_gateway import CreativeGenerator
from poster_agent.persistence.artifact_store import BlueprintArtifactStore
from poster_agent.rag.retrieval import BrandRetriever
from poster_agent.rag.store import BrandKnowledgeStore


def _route_after_validation(state: ragState) -> Literal["context", "stop"]:
    return "stop" if state.get("validation_errors") else "context"


def build_rag_graph(
    *,
    generator: CreativeGenerator,
    retriever: BrandRetriever,
    knowledge_store: BrandKnowledgeStore,
    artifact_store: BlueprintArtifactStore,
    checkpointer: Any,
    top_k: int = 6,
) -> Any:
    """Compile a graph with three explicit fan-out/fan-in stages."""

    builder: StateGraph[ragState, None, ragState, ragState] = StateGraph(ragState)
    builder.add_node("load_brief", cast(Any, load_brief), input_schema=ragState)
    builder.add_node("validate_brief", cast(Any, validate_brief), input_schema=ragState)
    builder.add_node("normalize_brief", cast(Any, normalize_brief), input_schema=ragState)

    builder.add_node(
        "brand_context",
        cast(
            Any,
            make_brand_context_node(
                store=knowledge_store,
                retriever=retriever,
                top_k=top_k,
            ),
        ),
        input_schema=ragState,
    )
    builder.add_node(
        "product_context",
        cast(Any, make_product_context_node(retriever=retriever, top_k=top_k)),
        input_schema=ragState,
    )
    builder.add_node(
        "audience_context",
        cast(Any, make_audience_context_node(retriever=retriever, top_k=top_k)),
        input_schema=ragState,
    )
    builder.add_node("channel_context", channel_context)
    builder.add_node("context_join", context_join)

    builder.add_node("begin_concept_attempt", begin_concept_attempt)
    builder.add_node(
        "messaging_agent",
        cast(Any, make_messaging_agent(generator)),
        input_schema=ragState,
    )
    builder.add_node(
        "visual_agent",
        cast(Any, make_visual_agent(generator)),
        input_schema=ragState,
    )
    builder.add_node(
        "strategy_agent",
        cast(Any, make_strategy_agent(generator)),
        input_schema=ragState,
    )
    builder.add_node("synthesize_blueprint", synthesize_blueprint)

    builder.add_node("brand_guard", brand_guard)
    builder.add_node("compliance_critic", compliance_critic)
    builder.add_node("feasibility_critic", feasibility_critic)
    builder.add_node("review_join", review_join)
    builder.add_node(
        "save_blueprint",
        cast(Any, make_save_blueprint_node(artifact_store)),
        input_schema=ragState,
    )

    builder.add_edge(START, "load_brief")
    builder.add_edge("load_brief", "validate_brief")
    builder.add_conditional_edges(
        "validate_brief",
        _route_after_validation,
        {"context": "normalize_brief", "stop": END},
    )

    context_nodes = ["brand_context", "product_context", "audience_context", "channel_context"]
    for node in context_nodes:
        builder.add_edge("normalize_brief", node)
    builder.add_edge(context_nodes, "context_join")

    builder.add_edge("context_join", "begin_concept_attempt")
    concept_nodes = ["messaging_agent", "visual_agent", "strategy_agent"]
    for node in concept_nodes:
        builder.add_edge("begin_concept_attempt", node)
    builder.add_edge(concept_nodes, "synthesize_blueprint")

    review_nodes = ["brand_guard", "compliance_critic", "feasibility_critic"]
    for node in review_nodes:
        builder.add_edge("synthesize_blueprint", node)
    builder.add_edge(review_nodes, "review_join")
    builder.add_conditional_edges(
        "review_join",
        route_after_reviews,
        {"save": "save_blueprint", "retry": "begin_concept_attempt"},
    )
    builder.add_edge("save_blueprint", END)
    return builder.compile(checkpointer=checkpointer, name="poster-blueprint-sprint-2")
