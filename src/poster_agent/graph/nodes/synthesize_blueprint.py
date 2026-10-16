"""Deterministically combine independent proposals into a creative blueprint."""

from poster_agent.domain.blueprint import CreativeBlueprint
from poster_agent.graph.sprint2_state import Sprint2State


def synthesize_blueprint(state: Sprint2State) -> Sprint2State:
    context = state["context_bundle"]
    seen: set[str] = set()
    evidence = []
    for item in [
        *context.brand_evidence,
        *context.product_evidence,
        *context.audience_evidence,
    ]:
        if item.chunk_id not in seen:
            seen.add(item.chunk_id)
            evidence.append(item)
    brief = state["brief"]
    return {
        "blueprint": CreativeBlueprint(
            tenant_id=brief.tenant_id,
            campaign_id=brief.campaign_id,
            brand_id=brief.brand_id,
            messaging=state["messaging_proposal"],
            visual=state["visual_proposal"],
            strategy=state["strategy_proposal"],
            brand_profile=context.brand_profile,
            evidence=evidence,
            channel_guidance=context.channel_guidance,
        )
    }
