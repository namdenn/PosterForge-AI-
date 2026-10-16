"""Composition root for Sprint 3 parallel rendering and poster quality gates."""

from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from poster_agent.graph.nodes.design_nodes import (
    begin_design_attempt,
    join_design_concepts,
    make_concept_agent,
    make_territory_director,
)
from poster_agent.graph.nodes.render_nodes import (
    begin_layout_attempt,
    begin_render_attempt,
    brand_qa,
    content_qa,
    join_artwork_layouts,
    join_generated_candidates,
    join_quality_reviews,
    layout_qa,
    load_and_resolve_assets,
    load_blueprint,
    make_artwork_layout_node,
    make_compose_node,
    make_variant_node,
    make_visual_qa_node,
    technical_qa,
)
from poster_agent.graph.nodes.save_render import make_save_render_node
from poster_agent.graph.sprint3_routing import (
    route_after_background_reviews,
    route_after_diversity,
    route_after_load,
    route_after_render_reviews,
)
from poster_agent.graph.sprint3_state import Sprint3State
from poster_agent.llm.design_gateway import DesignGenerator, VisualLayoutRefiner
from poster_agent.llm.image_gateway import ImageGenerator, VisualReviewer
from poster_agent.persistence.render_store import RenderArtifactStore
from poster_agent.rendering.compositor import PosterCompositor


def build_sprint3_graph(
    *,
    image_generator: ImageGenerator,
    design_generator: DesignGenerator,
    layout_refiner: VisualLayoutRefiner,
    visual_reviewer: VisualReviewer,
    compositor: PosterCompositor,
    artifact_store: RenderArtifactStore,
    checkpointer: Any,
) -> Any:
    """Compile dynamic creative direction, three concepts, rendering, and quality gates."""

    builder: StateGraph[Sprint3State, None, Sprint3State, Sprint3State] = StateGraph(Sprint3State)
    builder.add_node("load_blueprint", cast(Any, load_blueprint), input_schema=Sprint3State)
    builder.add_node(
        "load_and_resolve_assets",
        cast(Any, load_and_resolve_assets),
        input_schema=Sprint3State,
    )
    builder.add_node("begin_design_attempt", begin_design_attempt)
    builder.add_node(
        "creative_territory_director",
        cast(Any, make_territory_director(design_generator)),
        input_schema=Sprint3State,
    )
    concept_nodes = ["concept_agent_a", "concept_agent_b", "concept_agent_c"]
    for index, name in enumerate(concept_nodes):
        builder.add_node(
            name,
            cast(Any, make_concept_agent(index=index, generator=design_generator)),
            input_schema=Sprint3State,
        )
    builder.add_node("join_design_concepts", join_design_concepts)
    builder.add_node("begin_render_attempt", begin_render_attempt)

    variant_nodes = ["render_variant_a", "render_variant_b", "render_variant_c"]
    for index, name in enumerate(variant_nodes):
        builder.add_node(
            name,
            cast(Any, make_variant_node(index=index, generator=image_generator)),
            input_schema=Sprint3State,
        )
    builder.add_node("join_generated_candidates", join_generated_candidates)
    builder.add_node("begin_layout_attempt", begin_layout_attempt)
    layout_nodes = ["artwork_layout_agent_a", "artwork_layout_agent_b", "artwork_layout_agent_c"]
    for index, name in enumerate(layout_nodes):
        builder.add_node(
            name,
            cast(Any, make_artwork_layout_node(index=index, refiner=layout_refiner)),
            input_schema=Sprint3State,
        )
    builder.add_node("join_artwork_layouts", join_artwork_layouts)
    builder.add_node(
        "compose_candidates",
        cast(Any, make_compose_node(compositor)),
        input_schema=Sprint3State,
    )

    builder.add_node("brand_qa", brand_qa)
    builder.add_node("content_qa", content_qa)
    builder.add_node("layout_qa", layout_qa)
    builder.add_node("technical_qa", cast(Any, technical_qa), input_schema=Sprint3State)
    builder.add_node(
        "visual_qa",
        cast(Any, make_visual_qa_node(visual_reviewer)),
        input_schema=Sprint3State,
    )
    builder.add_node("join_quality_reviews", join_quality_reviews)
    builder.add_node(
        "save_render",
        cast(Any, make_save_render_node(artifact_store)),
        input_schema=Sprint3State,
    )

    builder.add_edge(START, "load_blueprint")
    builder.add_conditional_edges(
        "load_blueprint",
        route_after_load,
        {"continue": "load_and_resolve_assets", "stop": END},
    )
    builder.add_edge("load_and_resolve_assets", "begin_design_attempt")
    builder.add_edge("begin_design_attempt", "creative_territory_director")
    for node in concept_nodes:
        builder.add_edge("creative_territory_director", node)
    builder.add_edge(concept_nodes, "join_design_concepts")
    builder.add_conditional_edges(
        "join_design_concepts",
        route_after_diversity,
        {"render": "begin_render_attempt", "retry": "begin_design_attempt"},
    )
    for node in variant_nodes:
        builder.add_edge("begin_render_attempt", node)
    builder.add_edge(variant_nodes, "join_generated_candidates")
    for node in layout_nodes:
        builder.add_edge("begin_layout_attempt", node)
    builder.add_edge("join_generated_candidates", "begin_layout_attempt")
    builder.add_edge(layout_nodes, "join_artwork_layouts")
    builder.add_conditional_edges(
        "join_artwork_layouts",
        route_after_background_reviews,
        {"compose": "compose_candidates", "retry": "begin_render_attempt"},
    )

    review_nodes = ["brand_qa", "content_qa", "layout_qa", "technical_qa", "visual_qa"]
    for node in review_nodes:
        builder.add_edge("compose_candidates", node)
    builder.add_edge(review_nodes, "join_quality_reviews")
    builder.add_conditional_edges(
        "join_quality_reviews",
        route_after_render_reviews,
        {
            "save": "save_render",
            "retry_layout": "begin_layout_attempt",
            "retry_render": "begin_render_attempt",
            "retry_design": "begin_design_attempt",
        },
    )
    builder.add_edge("save_render", END)
    return builder.compile(checkpointer=checkpointer, name="poster-render-sprint-3")
