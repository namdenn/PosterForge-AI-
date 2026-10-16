"""Perform deterministic normalization after validation."""

from poster_agent.domain.enums import CampaignStatus
from poster_agent.graph.state import CampaignState


def normalize_brief(state: CampaignState) -> CampaignState:
    """Collapse repeated whitespace in human-entered headline-like fields."""

    brief = state["brief"]
    normalized = brief.model_copy(
        update={
            "campaign_name": " ".join(brief.campaign_name.split()),
            "product_name": " ".join(brief.product_name.split()),
            "call_to_action": " ".join(brief.call_to_action.split()),
        }
    )
    return {"brief": normalized, "status": CampaignStatus.READY}
