"""Sprint 3 load, planning, parallel generation, composition, and review nodes."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from PIL import Image
from pydantic import ValidationError

from poster_agent.assets.registry import load_asset_manifest, resolve_assets
from poster_agent.domain.enums import ApprovalStatus, RenderStatus, RiskSeverity
from poster_agent.domain.errors import RenderError
from poster_agent.domain.render import (
    ArtworkLayoutDecision,
    BlueprintArtifact,
    ComposedCandidate,
    DesignConcept,
    GeneratedCandidate,
    QualityReport,
    RenderSelection,
)
from poster_agent.graph.nodes.design_nodes import validate_concept
from poster_agent.graph.render_state import renderState
from poster_agent.llm.design_gateway import VisualLayoutRefiner
from poster_agent.llm.image_gateway import ImageGenerationRequest, ImageGenerator, VisualReviewer
from poster_agent.rendering.compositor import PosterCompositor

GraphNode = Callable[[renderState], Coroutine[Any, Any, renderState]]


async def load_blueprint(state: renderState) -> renderState:
    """Load the exact Sprint 2 wrapper and reject unapproved creative work."""

    path = Path(state["blueprint_path"])
    try:
        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        artifact = BlueprintArtifact.model_validate_json(raw)
    except (OSError, UnicodeError, ValidationError) as exc:
        return {
            "status": RenderStatus.FAILED,
            "review_errors": [f"Cannot load Sprint 2 blueprint artifact: {exc}"],
        }
    if artifact.schema_version != "2.0":
        return {
            "status": RenderStatus.FAILED,
            "review_errors": ["Sprint 3 requires a schema_version 2.0 blueprint artifact."],
        }
    if artifact.creative_blueprint.approval_status != ApprovalStatus.APPROVED:
        return {
            "status": RenderStatus.FAILED,
            "review_errors": ["Sprint 3 only renders an approved CreativeBlueprint."],
        }
    if (
        artifact.brief.tenant_id != artifact.creative_blueprint.tenant_id
        or artifact.brief.brand_id != artifact.creative_blueprint.brand_id
        or artifact.brief.campaign_id != artifact.creative_blueprint.campaign_id
    ):
        return {
            "status": RenderStatus.FAILED,
            "review_errors": ["Blueprint scope does not match the embedded campaign brief."],
        }
    return {
        "blueprint_artifact": artifact,
        "source_thread_id": artifact.thread_id,
        "brief": artifact.brief,
        "blueprint": artifact.creative_blueprint,
        "status": RenderStatus.VALIDATING,
        "review_errors": [],
    }


async def load_and_resolve_assets(state: renderState) -> renderState:
    manifest_path = Path(state["asset_manifest_path"])
    manifest = await load_asset_manifest(manifest_path)
    brief = state["brief"]
    assets = await resolve_assets(
        manifest,
        manifest_path=manifest_path,
        tenant_id=brief.tenant_id,
        brand_id=brief.brand_id,
        channel=brief.channel,
    )
    return {"asset_manifest": manifest, "resolved_assets": assets}


def begin_render_attempt(state: renderState) -> renderState:
    return {
        "render_attempt": state.get("render_attempt", 0) + 1,
        "layout_attempt": 0,
        "status": RenderStatus.RENDERING,
    }


def begin_layout_attempt(state: renderState) -> renderState:
    return {
        "layout_attempt": state.get("layout_attempt", 0) + 1,
        "status": RenderStatus.RENDERING,
    }


def make_variant_node(*, index: int, generator: ImageGenerator) -> GraphNode:
    async def render_variant(state: renderState) -> renderState:
        config = state["render_config"]
        if index >= config.variant_count:
            if index == 0:
                return {"candidate_a": None}
            if index == 1:
                return {"candidate_b": None}
            return {"candidate_c": None}
        plan = state["render_plan"]
        concept = plan.concepts[index]
        attempt = state["render_attempt"]
        feedback = state.get("review_errors", [])
        reserved = [
            {
                "role": layer.layer_type,
                "bounds": layer.bounds.model_dump(mode="json"),
            }
            for layer in concept.layers
            if layer.layer_type
            in {
                "headline",
                "primary_message",
                "support_message",
                "call_to_action",
                "locked_logo",
                "approved_product",
            }
        ]
        prompt_parts = [
            "Create the complete final key-visual artwork layer for a professional marketing "
            "poster. This generated image will be preserved as the visible illustration in the "
            "composed result; trusted code will only overlay exact text, the approved original "
            "logo, and an optional approved product asset. "
            "Products, expressive illustrations, conceptual user interfaces, people, "
            "environments, diagrams, symbols, and recognizable objects are allowed. Abstract UI "
            "lines, dots, iconography, and non-readable interface texture are allowed. Do not "
            "render readable campaign copy, names, numbers, logos, brand marks, or watermarks. "
            "Do not draw fake headline bars, faux paragraphs, placeholder copy, or fake CTA "
            "buttons. Keep the reserved copy and logo regions visually quiet enough for readable "
            "overlays, while integrating them naturally instead of drawing empty template boxes. "
            "Previous posters inform the "
            "upstream brand analysis only; do "
            "not recreate a previous composition, UI, text, logo, person, metric, testimonial, "
            "or campaign data.",
            f"Creative thesis: {concept.creative_thesis}",
            f"Artwork direction: {concept.artwork_prompt}",
            f"Brand anchor palette (expansion is allowed): {', '.join(plan.palette)}",
            "Concept-selected colors: "
            + ", ".join(
                plan.brand_tokens.colors.get(token, token) for token in concept.palette_tokens
            ),
            f"Reserved foreground regions: {reserved}",
        ]
        if feedback:
            prompt_parts.append(
                "Correct these review findings while preserving the approved direction: "
                + "; ".join(feedback)
            )
        candidate_id = f"variant-{'abc'[index]}"
        output = (
            Path(state["render_work_dir"])
            / "generated"
            / f"attempt-{attempt}"
            / f"{candidate_id}.png"
        )
        generated = await generator.generate(
            ImageGenerationRequest(
                candidate_id=candidate_id,
                concept_id=concept.concept_id,
                attempt=attempt,
                prompt="\n\n".join(prompt_parts),
                output_path=output,
                # Previous posters contain locked logos and campaign copy. Sending them to image
                # edit encourages layout copying and text contamination, so artwork generation
                # uses the agent-authored direction and verified brand tokens instead.
                reference_paths=[],
                size=config.generation_size,
                quality=config.generation_quality,
            )
        )
        if index == 0:
            return {"candidate_a": generated}
        if index == 1:
            return {"candidate_b": generated}
        return {"candidate_c": generated}

    return render_variant


def join_generated_candidates(state: renderState) -> renderState:
    candidates = [
        item
        for item in (state.get("candidate_a"), state.get("candidate_b"), state.get("candidate_c"))
        if item is not None
    ]
    if not candidates:
        raise RenderError("No image candidate was generated.")
    return {"generated_candidates": candidates}


def make_artwork_layout_node(*, index: int, refiner: VisualLayoutRefiner) -> GraphNode:
    """Inspect one generated variant and design its overlay against actual visible content."""

    async def artwork_layout(state: renderState) -> renderState:
        candidate = _candidate_at(state, index=index)
        active_candidate_ids = {item.candidate_id for item in state.get("generated_candidates", [])}
        if candidate is None or candidate.candidate_id not in active_candidate_ids:
            return _layout_branch_result(index=index)
        original = state["render_plan"].concepts[index]
        feedback: list[str] | None = state.get("review_errors") or None
        decision: ArtworkLayoutDecision | None = None
        refined: DesignConcept | None = None
        metadata_items = []
        validation_error: RenderError | None = None
        for _ in range(2):
            decision, metadata = await refiner.refine_overlay(
                artwork_path=candidate.generated_path,
                concept=original,
                plan=state["render_plan"],
                feedback=feedback,
            )
            metadata_items.append(metadata)
            refined = original.model_copy(
                update={
                    "layers": decision.layers,
                    "layout_signature": decision.layout_signature,
                    "rationale": decision.rationale,
                }
            )
            try:
                _validate_refined_overlay(original=original, refined=refined, state=state)
                validation_error = None
                break
            except RenderError as exc:
                validation_error = exc
                feedback = [str(exc)]
        if decision is None or refined is None:
            raise RenderError(f"No visual layout returned for '{candidate.candidate_id}'.")
        if validation_error is not None:
            decision = decision.model_copy(
                update={
                    "passed": False,
                    "score": 0,
                    "severity": RiskSeverity.BLOCKING,
                    "issues": [*decision.issues, str(validation_error)],
                }
            )
            refined = original
        report = QualityReport(
            candidate_id=candidate.candidate_id,
            reviewer="artwork_layout_qa",
            passed=decision.passed,
            score=decision.score,
            severity=decision.severity,
            issues=decision.issues,
            recommendations=decision.recommendations,
        )
        return _layout_branch_result(
            index=index,
            decision=decision,
            concept=refined,
            report=report,
            metadata=metadata_items,
        )

    return artwork_layout


def _candidate_at(state: renderState, *, index: int) -> GeneratedCandidate | None:
    if index == 0:
        return state.get("candidate_a")
    if index == 1:
        return state.get("candidate_b")
    return state.get("candidate_c")


def _layout_branch_result(
    *,
    index: int,
    decision: ArtworkLayoutDecision | None = None,
    concept: DesignConcept | None = None,
    report: QualityReport | None = None,
    metadata: list[Any] | None = None,
) -> renderState:
    shared: renderState = {"design_generation_metadata": metadata or []}
    if index == 0:
        shared.update(
            {
                "layout_decision_a": decision,
                "refined_concept_a": concept,
                "artwork_layout_report_a": report,
            }
        )
    elif index == 1:
        shared.update(
            {
                "layout_decision_b": decision,
                "refined_concept_b": concept,
                "artwork_layout_report_b": report,
            }
        )
    else:
        shared.update(
            {
                "layout_decision_c": decision,
                "refined_concept_c": concept,
                "artwork_layout_report_c": report,
            }
        )
    return shared


def join_artwork_layouts(state: renderState) -> renderState:
    """Keep valid artwork and replace guessed overlays with image-grounded layouts."""

    reports = [
        report
        for report in (
            state.get("artwork_layout_report_a"),
            state.get("artwork_layout_report_b"),
            state.get("artwork_layout_report_c"),
        )
        if report is not None
    ]
    refinements = {
        concept.concept_id: concept
        for concept in (
            state.get("refined_concept_a"),
            state.get("refined_concept_b"),
            state.get("refined_concept_c"),
        )
        if concept is not None
    }
    plan = state["render_plan"].model_copy(
        update={
            "concepts": [
                refinements.get(concept.concept_id, concept)
                for concept in state["render_plan"].concepts
            ]
        }
    )
    passed_ids = {report.candidate_id for report in reports if report.passed}
    clean_candidates = [
        candidate
        for candidate in state["generated_candidates"]
        if candidate.candidate_id in passed_ids
    ]
    if clean_candidates:
        return {
            "background_qa": reports,
            "generated_candidates": clean_candidates,
            "render_plan": plan,
            "review_errors": [],
        }
    errors = [
        f"{report.candidate_id}/artwork_layout_qa: {issue}"
        for report in reports
        for issue in report.issues
    ]
    if not errors:
        errors = ["No generated artwork supports a safe, professional text layout."]
    return {
        "background_qa": reports,
        "generated_candidates": state["generated_candidates"],
        "render_plan": plan,
        "review_errors": errors,
    }


def _validate_refined_overlay(
    *, original: DesignConcept, refined: DesignConcept, state: renderState
) -> None:
    original_has_product = any(layer.layer_type == "approved_product" for layer in original.layers)
    refined_has_product = any(layer.layer_type == "approved_product" for layer in refined.layers)
    if original_has_product != refined_has_product:
        raise RenderError(
            "Visual layout refinement must preserve the original approved_product decision."
        )
    validate_concept(refined, state=state)
    text_layers = [
        layer
        for layer in refined.layers
        if layer.layer_type in {"headline", "primary_message", "support_message", "call_to_action"}
    ]
    missing_colors = [
        layer.layer_id for layer in text_layers if layer.fill_token in {None, "transparent"}
    ]
    if missing_colors:
        raise RenderError(
            "Visual layout must choose an explicit readable color for every text layer: "
            + ", ".join(missing_colors)
        )
    font_families = {layer.font_family for layer in text_layers}
    if len(font_families) > 2:
        raise RenderError("Use at most two font families in one professional poster layout.")
    treatments = {
        (layer.font_family, layer.font_weight, layer.font_style, layer.fill_token)
        for layer in text_layers
    }
    if len(text_layers) > 1 and len(treatments) < 2:
        raise RenderError(
            "Headline, supporting copy, and CTA need at least two distinct typography treatments."
        )


def make_compose_node(compositor: PosterCompositor) -> GraphNode:
    async def compose_candidates(state: renderState) -> renderState:
        attempt = state["render_attempt"]
        work_dir = Path(state["render_work_dir"])
        composed = await asyncio.gather(
            *[
                compositor.compose(
                    generated=candidate,
                    plan=state["render_plan"],
                    assets=state["resolved_assets"],
                    output_path=(
                        work_dir
                        / "composed"
                        / f"attempt-{attempt}"
                        / f"{candidate.candidate_id}.png"
                    ),
                )
                for candidate in state["generated_candidates"]
            ]
        )
        return {
            "composed_candidates": list(composed),
            "status": RenderStatus.REVIEWING,
        }

    return compose_candidates


def brand_qa(state: renderState) -> renderState:
    reports = []
    for candidate in state["composed_candidates"]:
        concept = next(
            item
            for item in state["render_plan"].concepts
            if item.concept_id == candidate.concept_id
        )
        expected = {state["resolved_assets"].logo.asset_id}
        if any(layer.layer_type == "approved_product" for layer in concept.layers):
            product = state["resolved_assets"].product
            if product is not None:
                expected.add(product.asset_id)
            else:
                expected.add("missing approved product asset")
        missing = sorted(expected - set(candidate.asset_ids))
        logo_hash = candidate.locked_asset_hashes.get(state["resolved_assets"].logo.asset_id)
        if logo_hash != state["resolved_assets"].logo.sha256:
            missing.append("original logo checksum")
        reports.append(
            QualityReport(
                candidate_id=candidate.candidate_id,
                reviewer="brand_qa",
                passed=not missing,
                score=100 if not missing else 0,
                severity=RiskSeverity.LOW if not missing else RiskSeverity.BLOCKING,
                issues=[f"Missing approved assets: {', '.join(missing)}"] if missing else [],
                recommendations=["Recompose with the exact approved asset IDs."] if missing else [],
            )
        )
    return {"brand_qa": reports}


def content_qa(state: renderState) -> renderState:
    plan = state["render_plan"]
    forbidden = [item.casefold() for item in state["blueprint"].brand_profile.forbidden_claims]
    reports = []
    for candidate in state["composed_candidates"]:
        concept = next(item for item in plan.concepts if item.concept_id == candidate.concept_id)
        layer_types = {item.layer_type for item in concept.layers}
        expected_text = [plan.headline]
        if "primary_message" in layer_types:
            expected_text.append(plan.primary_message)
        expected_text.extend(concept.selected_support_messages)
        expected_text.append(plan.call_to_action)
        issues = []
        if candidate.rendered_text != expected_text:
            issues.append("Rendered copy does not exactly match the approved blueprint.")
        visible_copy = " ".join(candidate.rendered_text).casefold()
        hits = [claim for claim in forbidden if claim and claim in visible_copy]
        if hits:
            issues.append(f"Rendered copy contains forbidden claims: {', '.join(hits)}")
        reports.append(
            QualityReport(
                candidate_id=candidate.candidate_id,
                reviewer="content_qa",
                passed=not issues,
                score=100 if not issues else 0,
                severity=RiskSeverity.LOW if not issues else RiskSeverity.BLOCKING,
                issues=issues,
                recommendations=["Use only exact approved messaging fields."] if issues else [],
            )
        )
    return {"content_qa": reports}


def layout_qa(state: renderState) -> renderState:
    """Validate agent-authored geometry without imposing a reusable visual template."""

    reports = []
    tokens = state["resolved_assets"].brand_tokens
    for candidate in state["composed_candidates"]:
        concept = next(
            item
            for item in state["render_plan"].concepts
            if item.concept_id == candidate.concept_id
        )
        issues: list[str] = []
        if not state["render_plan"].diversity.passed:
            issues.extend(state["render_plan"].diversity.issues)
        logo = next(item for item in concept.layers if item.layer_type == "locked_logo")
        if logo.bounds.width < tokens.minimum_logo_width_ratio:
            issues.append("Locked logo is smaller than the approved minimum width.")
        foreground = [
            item
            for item in concept.layers
            if item.layer_type
            in {
                "headline",
                "primary_message",
                "support_message",
                "call_to_action",
                "locked_logo",
                "approved_product",
            }
        ]
        for position, first in enumerate(foreground):
            for second in foreground[position + 1 :]:
                overlap = _intersection_ratio(first.bounds, second.bounds)
                if overlap > 0.03:
                    issues.append(
                        f"Foreground layers overlap: {first.layer_id} / {second.layer_id}."
                    )
        reports.append(
            QualityReport(
                candidate_id=candidate.candidate_id,
                reviewer="layout_qa",
                passed=not issues,
                score=100 if not issues else max(0, 100 - len(issues) * 25),
                severity=RiskSeverity.LOW if not issues else RiskSeverity.HIGH,
                issues=issues,
                recommendations=(
                    ["Move or resize only the conflicting Scene Graph layers."] if issues else []
                ),
            )
        )
    return {"layout_qa": reports}


async def technical_qa(state: renderState) -> renderState:
    expected = (state["render_config"].width, state["render_config"].height)
    reports = await asyncio.gather(
        *[
            _inspect_candidate(candidate, expected=expected)
            for candidate in state["composed_candidates"]
        ]
    )
    return {"technical_qa": list(reports)}


def make_visual_qa_node(reviewer: VisualReviewer) -> GraphNode:
    async def visual_qa(state: renderState) -> renderState:
        reports = await asyncio.gather(
            *[
                reviewer.review(
                    candidate_id=candidate.candidate_id,
                    poster_path=candidate.poster_path,
                    blueprint=state["blueprint"],
                )
                for candidate in state["composed_candidates"]
            ]
        )
        return {"visual_qa": list(reports)}

    return visual_qa


def join_quality_reviews(state: renderState) -> renderState:
    reports = [
        *state["background_qa"],
        *state["brand_qa"],
        *state["content_qa"],
        *state["layout_qa"],
        *state["technical_qa"],
        *state["visual_qa"],
    ]
    by_candidate: dict[str, list[QualityReport]] = {}
    for report in reports:
        by_candidate.setdefault(report.candidate_id, []).append(report)

    ranked: list[tuple[bool, float, ComposedCandidate]] = []
    threshold = state["render_config"].qa_threshold
    for candidate in state["composed_candidates"]:
        candidate_reports = by_candidate[candidate.candidate_id]
        score = sum(item.score for item in candidate_reports) / len(candidate_reports)
        passed = score >= threshold and all(item.passed for item in candidate_reports)
        ranked.append((passed, score, candidate))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    passed, score, selected = ranked[0]
    errors = [
        f"{report.candidate_id}/{report.reviewer}: {issue}"
        for report in reports
        if report.candidate_id == selected.candidate_id
        for issue in report.issues
    ]
    if not passed and not errors:
        errors = [
            f"Selected candidate did not pass every QA gate "
            f"(aggregate score {score:.1f}, threshold {threshold})."
        ]
    return {
        "all_reviews": reports,
        "review_errors": errors,
        "selection": RenderSelection(
            candidate_id=selected.candidate_id,
            poster_path=selected.poster_path,
            score=score,
            approval_status=(ApprovalStatus.APPROVED if passed else ApprovalStatus.NEEDS_REVIEW),
        ),
    }


def _intersection_ratio(first: Any, second: Any) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    smaller = min(first.width * first.height, second.width * second.height)
    return intersection / smaller if smaller else 0.0


async def _inspect_candidate(
    candidate: ComposedCandidate, *, expected: tuple[int, int]
) -> QualityReport:
    return await asyncio.to_thread(_inspect_candidate_sync, candidate, expected)


def _inspect_candidate_sync(
    candidate: ComposedCandidate, expected: tuple[int, int]
) -> QualityReport:
    issues: list[str] = []
    try:
        with Image.open(candidate.poster_path) as image:
            image.verify()
        with Image.open(candidate.poster_path) as image:
            if image.size != expected:
                issues.append(f"Poster size is {image.size}, expected {expected}.")
            if image.format != "PNG":
                issues.append(f"Poster format is {image.format}, expected PNG.")
    except (OSError, SyntaxError) as exc:
        issues.append(f"Poster file cannot be decoded: {exc}")
    if candidate.poster_path.exists() and candidate.poster_path.stat().st_size < 10_000:
        issues.append("Poster file is unexpectedly small and may be incomplete.")
    return QualityReport(
        candidate_id=candidate.candidate_id,
        reviewer="technical_qa",
        passed=not issues,
        score=100 if not issues else 20,
        severity=RiskSeverity.LOW if not issues else RiskSeverity.HIGH,
        issues=issues,
        recommendations=["Regenerate or recompose a valid production PNG."] if issues else [],
    )


def serialize_state_summary(state: renderState) -> str:
    """Small helper used by CLI diagnostics without serializing image bytes."""

    selection = state.get("selection")
    return json.dumps(
        {
            "render_id": state.get("render_id"),
            "status": state.get("status"),
            "attempt": state.get("render_attempt", 0),
            "selection": selection.model_dump(mode="json") if selection else None,
            "errors": state.get("review_errors", []),
        },
        ensure_ascii=False,
        indent=2,
    )
