"""Pure routing decisions for Sprint 3."""

from typing import Literal

from poster_agent.domain.enums import ApprovalStatus
from poster_agent.graph.sprint3_state import Sprint3State


def route_after_load(state: Sprint3State) -> Literal["continue", "stop"]:
    return "stop" if state.get("review_errors") else "continue"


def route_after_diversity(state: Sprint3State) -> Literal["render", "retry"]:
    if state["diversity_report"].passed:
        return "render"
    if state.get("design_attempt", 0) < state.get("max_design_attempts", 2):
        return "retry"
    return "render"


def route_after_background_reviews(state: Sprint3State) -> Literal["compose", "retry"]:
    if not state.get("review_errors"):
        return "compose"
    if state.get("render_attempt", 0) < state["render_config"].max_render_attempts:
        return "retry"
    return "compose"


def route_after_render_reviews(
    state: Sprint3State,
) -> Literal["save", "retry_layout", "retry_render", "retry_design"]:
    selection = state["selection"]
    if selection.approval_status == ApprovalStatus.APPROVED:
        return "save"
    layout_related = any(
        marker in error
        for error in state.get("review_errors", [])
        for marker in ("/layout_qa:", "/visual_qa:")
    )
    if (
        layout_related
        and state.get("layout_attempt", 0) < state["render_config"].max_layout_attempts
    ):
        return "retry_layout"
    structural = any(
        marker in error
        for error in state.get("review_errors", [])
        for marker in ("/brand_qa:", "/content_qa:")
    )
    if structural and state.get("design_attempt", 0) < state.get("max_design_attempts", 2):
        return "retry_design"
    if state.get("render_attempt", 0) < state["render_config"].max_render_attempts:
        return "retry_render"
    return "save"
