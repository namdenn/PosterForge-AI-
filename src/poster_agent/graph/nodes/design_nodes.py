"""Dynamic creative-director and parallel concept-agent nodes for Sprint 3.5."""

import re
from collections.abc import Callable, Coroutine
from typing import Any

from poster_agent.domain.enums import RenderStatus
from poster_agent.domain.errors import RenderError
from poster_agent.domain.render import (
    DesignConcept,
    DiversityReport,
    RenderPlan,
    SceneLayer,
)
from poster_agent.graph.render_state import renderState
from poster_agent.llm.design_gateway import DesignGenerator

GraphNode = Callable[[renderState], Coroutine[Any, Any, renderState]]


def begin_design_attempt(state: renderState) -> renderState:
    return {
        "design_attempt": state.get("design_attempt", 0) + 1,
        "render_attempt": 0,
        "status": RenderStatus.RENDERING,
    }


def make_territory_director(generator: DesignGenerator) -> GraphNode:
    async def territory_director(state: renderState) -> renderState:
        metadata_items = []
        feedback: list[str] | None = None
        for _ in range(2):
            portfolio, metadata = await generator.generate_territories(
                brief=state["brief"],
                blueprint=state["blueprint"],
                brand_tokens=state["resolved_assets"].brand_tokens,
                approved_product_available=state["resolved_assets"].product is not None,
                feedback=feedback,
            )
            metadata_items.append(metadata)
            identifiers = [item.territory_id for item in portfolio.territories]
            if len(set(identifiers)) == len(identifiers):
                break
            feedback = ["Every territory_id must be unique."]
        else:
            raise RenderError("Creative director returned duplicate territory IDs twice.")
        return {
            "territory_portfolio": portfolio,
            "design_territories": portfolio.territories,
            "design_generation_metadata": metadata_items,
        }

    return territory_director


def make_concept_agent(*, index: int, generator: DesignGenerator) -> GraphNode:
    async def concept_agent(state: renderState) -> renderState:
        if index >= state["render_config"].variant_count:
            if index == 0:
                return {"concept_a": None}
            if index == 1:
                return {"concept_b": None}
            return {"concept_c": None}
        territory = state["territory_portfolio"].territories[index]
        metadata_items = []
        feedback: list[str] | None = None
        last_error: RenderError | None = None
        for _ in range(2):
            concept, metadata = await generator.generate_concept(
                brief=state["brief"],
                blueprint=state["blueprint"],
                brand_tokens=state["resolved_assets"].brand_tokens,
                territory=territory,
                concept_index=index,
                approved_product_available=state["resolved_assets"].product is not None,
                feedback=feedback,
            )
            metadata_items.append(metadata)
            concept = concept.model_copy(
                update={
                    "concept_id": f"concept-{'abc'[index]}",
                    "territory_id": territory.territory_id,
                }
            )
            try:
                validate_concept(concept, state=state)
                last_error = None
                break
            except RenderError as exc:
                last_error = exc
                feedback = [str(exc)]
        if last_error is not None:
            raise last_error
        result: renderState = {"design_generation_metadata": metadata_items}
        if index == 0:
            result["concept_a"] = concept
        elif index == 1:
            result["concept_b"] = concept
        else:
            result["concept_c"] = concept
        return result

    return concept_agent


def join_design_concepts(state: renderState) -> renderState:
    concepts = [
        item
        for item in (state.get("concept_a"), state.get("concept_b"), state.get("concept_c"))
        if item is not None
    ]
    if not concepts:
        raise RenderError("No design concept was generated.")
    diversity = _measure_diversity(concepts, state=state)
    blueprint = state["blueprint"]
    brief = state["brief"]
    token_values = list(state["resolved_assets"].brand_tokens.colors.values())
    palette = token_values or blueprint.visual.direction.color_palette
    return {
        "diversity_report": diversity,
        "render_plan": RenderPlan(
            width=state["render_config"].width,
            height=state["render_config"].height,
            safe_margin=max(48, state["render_config"].width // 18),
            concepts=concepts,
            diversity=diversity,
            headline=brief.headline or blueprint.messaging.headline,
            primary_message=blueprint.messaging.primary_message,
            supporting_messages=blueprint.messaging.supporting_messages,
            call_to_action=brief.call_to_action,
            palette=palette,
            negative_constraints=blueprint.visual.negative_constraints,
            brand_tokens=state["resolved_assets"].brand_tokens,
        ),
        "review_errors": diversity.issues,
    }


def validate_concept(concept: DesignConcept, *, state: renderState) -> None:
    types = [layer.layer_type for layer in concept.layers]
    required = {"locked_logo", "headline", "call_to_action"}
    missing = sorted(required - set(types))
    if missing:
        raise RenderError(
            f"Concept '{concept.concept_id}' is missing required layers: {', '.join(missing)}."
        )
    if types.count("locked_logo") != 1:
        raise RenderError(f"Concept '{concept.concept_id}' must contain exactly one locked logo.")
    if "approved_product" in types and state["resolved_assets"].product is None:
        raise RenderError(
            f"Concept '{concept.concept_id}' requested an approved product asset that is absent."
        )
    shape_layers = [layer.layer_id for layer in concept.layers if layer.layer_type == "shape"]
    if shape_layers:
        raise RenderError(
            f"Concept '{concept.concept_id}' put visual artwork in compositor shape layers: "
            + ", ".join(shape_layers)
            + ". Move every illustration, UI surface, object, and decorative shape into "
            "artwork_prompt. The Scene Graph may contain only trusted copy, locked_logo, "
            "and an optional approved_product overlay."
        )
    approved = set(state["blueprint"].messaging.supporting_messages)
    unsupported = [item for item in concept.selected_support_messages if item not in approved]
    if unsupported:
        raise RenderError(
            f"Concept '{concept.concept_id}' invented unapproved support copy: "
            + "; ".join(unsupported)
        )
    support_layers = [item for item in concept.layers if item.layer_type == "support_message"]
    expected_indexes = set(range(len(concept.selected_support_messages)))
    actual_indexes = {item.support_index for item in support_layers}
    if actual_indexes != expected_indexes:
        raise RenderError(
            f"Concept '{concept.concept_id}' support layers do not match selected copy."
        )
    allowed_tokens = {
        *state["resolved_assets"].brand_tokens.colors.keys(),
        "black",
        "white",
        "transparent",
    }
    used_tokens = {
        token
        for layer in concept.layers
        for token in (layer.fill_token, layer.stroke_token, layer.accent_fill_token)
        if token is not None
    } | set(concept.palette_tokens)
    unknown = sorted(
        token
        for token in used_tokens - allowed_tokens
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", token)
    )
    if unknown:
        raise RenderError(
            f"Concept '{concept.concept_id}' used invalid color tokens: {', '.join(unknown)}. "
            "Use a brand token or a six-digit hexadecimal color."
        )
    _validate_accent_words(concept, state=state)
    protected = [
        layer
        for layer in concept.layers
        if layer.layer_type
        in {
            "locked_logo",
            "headline",
            "primary_message",
            "support_message",
            "call_to_action",
            "approved_product",
        }
    ]
    conflicts = []
    for position, first in enumerate(protected):
        for second in protected[position + 1 :]:
            if _intersection_ratio(first, second) > 0.03:
                conflicts.append(f"{first.layer_id} / {second.layer_id}")
    if conflicts:
        raise RenderError(
            f"Concept '{concept.concept_id}' has overlapping protected layers: "
            + "; ".join(conflicts)
            + ". Move or resize those layers before image generation."
        )


def _validate_accent_words(concept: DesignConcept, *, state: renderState) -> None:
    headline = state["brief"].headline or state["blueprint"].messaging.headline
    copy_by_type = {
        "headline": headline,
        "primary_message": state["blueprint"].messaging.primary_message,
        "call_to_action": state["brief"].call_to_action,
    }
    for layer in concept.layers:
        if not layer.accent_words:
            continue
        text = copy_by_type.get(layer.layer_type)
        if layer.layer_type == "support_message" and layer.support_index is not None:
            text = concept.selected_support_messages[layer.support_index]
        if text is None:
            raise RenderError(
                f"Layer '{layer.layer_id}' cannot apply accent words to non-text content."
            )
        available = {_normalize_word(word) for word in text.split()}
        unknown = [word for word in layer.accent_words if _normalize_word(word) not in available]
        if unknown:
            raise RenderError(
                f"Layer '{layer.layer_id}' accents words absent from its exact copy: "
                + ", ".join(unknown)
            )


def _normalize_word(value: str) -> str:
    return re.sub(r"^\W+|\W+$", "", value, flags=re.UNICODE).casefold()


def _measure_diversity(concepts: list[DesignConcept], *, state: renderState) -> DiversityReport:
    if len(concepts) == 1:
        return DiversityReport(passed=True, score=100)
    issues: list[str] = []
    signatures = [item.layout_signature.casefold() for item in concepts]
    if len(set(signatures)) != len(signatures):
        issues.append("Two or more concepts returned the same layout signature.")
    territory_by_id = {item.territory_id: item for item in state["territory_portfolio"].territories}
    modes = [territory_by_id[item.territory_id].storytelling_mode.casefold() for item in concepts]
    metaphors = [territory_by_id[item.territory_id].visual_metaphor.casefold() for item in concepts]
    if len(set(modes)) != len(modes):
        issues.append("Concepts do not use distinct storytelling modes.")
    if len(set(metaphors)) != len(metaphors):
        issues.append("Concepts do not use distinct visual metaphors.")
    fingerprints = [_layout_fingerprint(item.layers) for item in concepts]
    if len(set(fingerprints)) != len(fingerprints):
        issues.append("Concepts have materially identical foreground geometry.")
    score = max(0, 100 - 25 * len(issues))
    return DiversityReport(passed=not issues, score=score, issues=issues)


def _layout_fingerprint(layers: list[SceneLayer]) -> str:
    important = {
        "locked_logo",
        "headline",
        "primary_message",
        "support_message",
        "call_to_action",
        "approved_product",
    }
    parts: list[str] = []
    for layer in sorted(layers, key=lambda item: (item.layer_type, item.layer_id)):
        if layer.layer_type not in important:
            continue
        center_x = layer.bounds.x + layer.bounds.width / 2
        center_y = layer.bounds.y + layer.bounds.height / 2
        column = min(2, int(center_x * 3))
        row = min(2, int(center_y * 3))
        parts.append(f"{layer.layer_type}:{column}:{row}")
    return "|".join(parts)


def _intersection_ratio(first: SceneLayer, second: SceneLayer) -> float:
    left = max(first.bounds.x, second.bounds.x)
    top = max(first.bounds.y, second.bounds.y)
    right = min(first.bounds.x + first.bounds.width, second.bounds.x + second.bounds.width)
    bottom = min(first.bounds.y + first.bounds.height, second.bounds.y + second.bounds.height)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    smaller = min(
        first.bounds.width * first.bounds.height,
        second.bounds.width * second.bounds.height,
    )
    return intersection / smaller if smaller else 0.0
