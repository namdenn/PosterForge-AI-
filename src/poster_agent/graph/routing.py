"""Pure routing decisions for the campaign graph."""

from typing import Literal

from poster_agent.graph.state import CampaignState

ValidationRoute = Literal["normalize", "stop"]
QualityRoute = Literal["save", "retry", "stop"]


def route_after_validation(state: CampaignState) -> ValidationRoute:
    """Invalid input is terminal and must never consume model tokens."""

    return "stop" if state.get("validation_errors") else "normalize"


def route_after_quality(state: CampaignState) -> QualityRoute:
    """Retry fixable structured output within a strict attempt budget."""

    if not state.get("quality_errors"):
        return "save"
    if state.get("generation_attempt", 0) < state.get("max_generation_attempts", 2):
        return "retry"
    return "stop"
