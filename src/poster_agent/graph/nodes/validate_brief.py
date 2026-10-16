"""Validate raw input against the domain contract."""

from pydantic import ValidationError

from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import CampaignStatus
from poster_agent.graph.state import CampaignState


def validate_brief(state: CampaignState) -> CampaignState:
    """Return a typed brief or CLI-friendly field errors."""

    if "raw_brief" not in state:
        return {
            "status": CampaignStatus.FAILED,
            "validation_errors": state.get("validation_errors", ["Brief data is missing."]),
        }

    try:
        brief = CampaignBrief.model_validate(state["raw_brief"])
    except ValidationError as exc:
        errors = []
        for issue in exc.errors(include_url=False):
            location = ".".join(str(part) for part in issue["loc"])
            errors.append(f"{location}: {issue['msg']}")
        return {"status": CampaignStatus.FAILED, "validation_errors": errors}

    return {
        "brief": brief,
        "status": CampaignStatus.READY,
        "validation_errors": [],
    }
