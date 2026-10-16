"""Parallel deterministic reviewers and their join node."""

from poster_agent.domain.blueprint import ReviewReport
from poster_agent.domain.enums import ApprovalStatus, CampaignStatus, RiskSeverity
from poster_agent.graph.rag_state import ragState


def brand_guard(state: ragState) -> ragState:
    blueprint = state["blueprint"]
    profile = blueprint.brand_profile
    copy = " ".join(
        [
            blueprint.messaging.headline,
            blueprint.messaging.primary_message,
            *blueprint.messaging.supporting_messages,
        ]
    ).casefold()
    issues: list[str] = []
    recommendations: list[str] = []

    forbidden_hits = [claim for claim in profile.forbidden_claims if claim.casefold() in copy]
    if forbidden_hits:
        issues.append(f"Copy contains forbidden claims: {', '.join(forbidden_hits)}")
        recommendations.append("Remove every forbidden claim and use verified product facts only.")

    known_ids = {item.chunk_id for item in blueprint.evidence}
    citation_groups = {
        "messaging": blueprint.messaging.evidence_chunk_ids,
        "visual": blueprint.visual.evidence_chunk_ids,
        "strategy": blueprint.strategy.evidence_chunk_ids,
    }
    cited_ids = {item for group in citation_groups.values() for item in group}
    unknown_ids = sorted(cited_ids - known_ids)
    if unknown_ids:
        issues.append(f"Unknown evidence chunk IDs: {', '.join(unknown_ids)}")
        recommendations.append("Cite only chunk IDs present in verified context.")
    missing_citations = [name for name, identifiers in citation_groups.items() if not identifiers]
    if missing_citations:
        issues.append(f"Proposals without evidence citations: {', '.join(missing_citations)}")
        recommendations.append("Attach at least one verified evidence chunk ID to each proposal.")

    severity = (
        RiskSeverity.BLOCKING
        if forbidden_hits
        else RiskSeverity.MEDIUM
        if issues
        else RiskSeverity.LOW
    )
    return {
        "brand_review": ReviewReport(
            reviewer="brand_guard",
            passed=not issues,
            severity=severity,
            issues=issues,
            recommendations=recommendations,
        )
    }


def compliance_critic(state: ragState) -> ragState:
    brief = state["brief"]
    blueprint = state["blueprint"]
    issues: list[str] = []
    recommendations: list[str] = []
    if brief.headline and blueprint.messaging.headline.casefold() != brief.headline.casefold():
        issues.append("Headline does not preserve the locked campaign headline.")
        recommendations.append(f"Use the exact headline: {brief.headline}")
    if blueprint.messaging.call_to_action.casefold() != brief.call_to_action.casefold():
        issues.append("Call to action does not preserve the approved brief.")
        recommendations.append(f"Use the exact call to action: {brief.call_to_action}")
    if blueprint.strategy.objective != brief.objective:
        issues.append("Strategy objective does not match the approved brief.")
        recommendations.append(f"Use objective '{brief.objective.value}'.")
    policy = brief.support_copy_policy
    support_count = len(blueprint.messaging.supporting_messages)
    if not policy.min_items <= support_count <= policy.max_items:
        issues.append(
            f"Supporting copy count {support_count} is outside "
            f"{policy.min_items}..{policy.max_items}."
        )
        recommendations.append("Regenerate supporting copy within the approved content budget.")
    long_messages = [
        item
        for item in blueprint.messaging.supporting_messages
        if len(item.split()) > policy.max_words_per_item
    ]
    if long_messages:
        issues.append("One or more supporting messages exceed the approved word budget.")
        recommendations.append(
            f"Keep every supporting message within {policy.max_words_per_item} words."
        )
    blocking_risks = [
        risk.description
        for risk in blueprint.strategy.risks
        if risk.severity == RiskSeverity.BLOCKING
    ]
    if blocking_risks:
        issues.append(f"Blocking strategy risks: {', '.join(blocking_risks)}")
        recommendations.append("Resolve blocking risks or request explicit human approval.")
    severity = (
        RiskSeverity.BLOCKING
        if blocking_risks
        else RiskSeverity.HIGH
        if issues
        else RiskSeverity.LOW
    )
    return {
        "compliance_review": ReviewReport(
            reviewer="compliance_critic",
            passed=not issues,
            severity=severity,
            issues=issues,
            recommendations=recommendations,
        )
    }


def feasibility_critic(state: ragState) -> ragState:
    brief = state["brief"]
    blueprint = state["blueprint"]
    provided = {item.casefold() for item in blueprint.visual.mandatory_elements}
    missing = [item for item in brief.mandatory_elements if item.casefold() not in provided]
    issues = [f"Missing mandatory visual elements: {', '.join(missing)}"] if missing else []
    recommendations = (
        ["Add every mandatory element to the visual production specification."] if missing else []
    )
    return {
        "feasibility_review": ReviewReport(
            reviewer="feasibility_critic",
            passed=not issues,
            severity=RiskSeverity.HIGH if issues else RiskSeverity.LOW,
            issues=issues,
            recommendations=recommendations,
        )
    }


def review_join(state: ragState) -> ragState:
    reports = [
        state["brand_review"],
        state["compliance_review"],
        state["feasibility_review"],
    ]
    errors = [issue for report in reports for issue in report.issues]
    attempt = state.get("concept_attempt", 0)
    maximum = state.get("max_concept_attempts", 2)
    approved = not errors
    status = (
        CampaignStatus.RUNNING if approved or attempt < maximum else CampaignStatus.NEEDS_REVIEW
    )
    blueprint = state["blueprint"].model_copy(
        update={
            "reviews": reports,
            "approval_status": (
                ApprovalStatus.APPROVED if approved else ApprovalStatus.NEEDS_REVIEW
            ),
        }
    )
    return {"blueprint": blueprint, "review_errors": errors, "status": status}
