"""Pure routing functions for the Sprint 2 graph."""

from typing import Literal

from poster_agent.domain.enums import RiskSeverity
from poster_agent.graph.rag_state import ragState

ReviewRoute = Literal["save", "retry"]


def route_after_reviews(state: ragState) -> ReviewRoute:
    if not state.get("review_errors"):
        return "save"
    reports = [
        state["brand_review"],
        state["compliance_review"],
        state["feasibility_review"],
    ]
    if any(report.severity == RiskSeverity.BLOCKING for report in reports):
        return "save"
    if state.get("concept_attempt", 0) < state.get("max_concept_attempts", 2):
        return "retry"
    return "save"
