"""Parallel retrieval agents and their deterministic join."""

from collections.abc import Callable, Coroutine
from typing import Any

from poster_agent.domain.blueprint import ContextBundle
from poster_agent.domain.enums import CampaignStatus, MarketingChannel
from poster_agent.domain.errors import BrandKnowledgeNotFound
from poster_agent.graph.rag_state import ragState
from poster_agent.rag.retrieval import BrandRetriever
from poster_agent.rag.store import BrandKnowledgeStore

GraphNode = Callable[[ragState], Coroutine[Any, Any, ragState]]


def make_brand_context_node(
    *, store: BrandKnowledgeStore, retriever: BrandRetriever, top_k: int
) -> GraphNode:
    async def brand_context(state: ragState) -> ragState:
        brief = state["brief"]
        profile = await store.get_profile(tenant_id=brief.tenant_id, brand_id=brief.brand_id)
        if profile is None:
            raise BrandKnowledgeNotFound(
                "No brand profile found. Run 'poster-agent brand ingest' for this tenant and brand."
            )
        evidence = await retriever.retrieve(
            tenant_id=brief.tenant_id,
            brand_id=brief.brand_id,
            query="brand personality tone of voice visual identity colors logo usage",
            limit=top_k,
        )
        if not evidence:
            raise BrandKnowledgeNotFound("The brand index exists but returned no evidence.")
        return {"brand_profile": profile, "brand_evidence": evidence}

    return brand_context


def make_product_context_node(*, retriever: BrandRetriever, top_k: int) -> GraphNode:
    async def product_context(state: ragState) -> ragState:
        brief = state["brief"]
        evidence = await retriever.retrieve(
            tenant_id=brief.tenant_id,
            brand_id=brief.brand_id,
            query=(
                f"product facts claims features constraints for {brief.product_name}: "
                f"{brief.product_description}"
            ),
            limit=top_k,
        )
        return {"product_evidence": evidence}

    return product_context


def make_audience_context_node(*, retriever: BrandRetriever, top_k: int) -> GraphNode:
    async def audience_context(state: ragState) -> ragState:
        brief = state["brief"]
        audience = ", ".join(brief.target_audience)
        evidence = await retriever.retrieve(
            tenant_id=brief.tenant_id,
            brand_id=brief.brand_id,
            query=f"target audience needs motivations objections: {audience}",
            limit=top_k,
        )
        return {"audience_evidence": evidence}

    return audience_context


def channel_context(state: ragState) -> ragState:
    """Provide stable channel constraints without spending an LLM call."""

    channel = state["brief"].channel
    shared = [
        "Keep one dominant message and a clearly visible call to action.",
        "Respect all mandatory elements and leave safe margins around logos and text.",
    ]
    channel_rules: dict[MarketingChannel, list[str]] = {
        MarketingChannel.INSTAGRAM: [
            "Prioritize a 4:5 mobile-first composition.",
            "Keep critical copy readable without zooming.",
        ],
        MarketingChannel.FACEBOOK: [
            "Use a mobile-readable feed composition.",
            "Avoid dense paragraphs inside the visual.",
        ],
        MarketingChannel.LINKEDIN: [
            "Use a professional, information-led hierarchy.",
            "Make the business value legible at feed size.",
        ],
        MarketingChannel.TIKTOK: [
            "Use a 9:16 vertical composition with UI-safe zones.",
            "Design for an immediate first-screen hook.",
        ],
        MarketingChannel.EMAIL: [
            "Keep the hero message concise and responsive.",
            "Do not place essential information only inside imagery.",
        ],
        MarketingChannel.WEBSITE: [
            "Preserve responsive crop flexibility and text contrast.",
            "Keep the call to action visually distinct.",
        ],
        MarketingChannel.DISPLAY_AD: [
            "Minimize copy and prioritize instant recognition.",
            "Plan variants for multiple aspect ratios.",
        ],
        MarketingChannel.PRINT: [
            "Plan for print-safe margins, bleed, and high-resolution assets.",
            "Do not rely on animation or interactive context.",
        ],
    }
    return {"channel_guidance": [*shared, *channel_rules[channel]]}


def context_join(state: ragState) -> ragState:
    brief = state["brief"]
    evidence = [
        *state["brand_evidence"],
        *state.get("product_evidence", []),
        *state.get("audience_evidence", []),
    ]
    crossed_scope = any(
        item.tenant_id != brief.tenant_id or item.brand_id != brief.brand_id for item in evidence
    )
    if crossed_scope:
        raise ValueError("Retrieved evidence crossed a tenant or brand boundary.")
    return {
        "context_bundle": ContextBundle(
            brand_profile=state["brand_profile"],
            brand_evidence=state["brand_evidence"],
            product_evidence=state.get("product_evidence", []),
            audience_evidence=state.get("audience_evidence", []),
            channel_guidance=state["channel_guidance"],
        ),
        "status": CampaignStatus.RUNNING,
    }
