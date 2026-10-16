"""Deterministic quality checks before an artifact can be saved."""

from poster_agent.domain.enums import CampaignStatus, RiskSeverity
from poster_agent.graph.state import CampaignState


def quality_gate(state: CampaignState) -> CampaignState:
    """Check cross-field invariants that the Pydantic schema cannot express."""

    brief = state["brief"]
    strategy = state["strategy"]
    errors: list[str] = []

    if strategy.campaign_id != brief.campaign_id:
        errors.append("campaign_id must exactly match the brief")
    if strategy.objective != brief.objective:
        errors.append("objective must exactly match the brief")
    if strategy.call_to_action.casefold() != brief.call_to_action.casefold():
        errors.append("call_to_action must preserve the brief")

    returned_elements = {item.casefold() for item in strategy.mandatory_elements}
    missing_elements = [
        item for item in brief.mandatory_elements if item.casefold() not in returned_elements
    ]
    if missing_elements:
        errors.append(f"missing mandatory elements: {', '.join(missing_elements)}")
    if any(risk.severity == RiskSeverity.BLOCKING for risk in strategy.risks):
        errors.append("strategy contains a blocking risk requiring human review")

    attempts = state.get("generation_attempt", 0)
    max_attempts = state.get("max_generation_attempts", 2)
    status = (
        CampaignStatus.RUNNING
        if errors and attempts < max_attempts
        else CampaignStatus.NEEDS_REVIEW
        if errors
        else CampaignStatus.RUNNING
    )
    return {"quality_errors": errors, "status": status}
