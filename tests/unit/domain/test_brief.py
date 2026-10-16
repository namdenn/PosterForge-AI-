"""Unit tests for campaign-brief validation and normalization."""

import pytest
from pydantic import ValidationError

from poster_agent.domain.brief import CampaignBrief


def test_brief_normalizes_and_deduplicates_lists() -> None:
    brief = CampaignBrief.model_validate(
        {
            "tenant_id": "tenant-1",
            "campaign_id": "campaign-1",
            "brand_id": "brand-1",
            "campaign_name": "Launch",
            "objective": "conversion",
            "product_name": "Product",
            "product_description": "A sufficiently detailed product description.",
            "target_audience": ["Professionals", " Professionals ", ""],
            "channel": "linkedin",
            "call_to_action": "Learn more",
        }
    )

    assert brief.target_audience == ["Professionals"]
    assert brief.language.value == "vi"


def test_brief_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        CampaignBrief.model_validate(
            {
                "tenant_id": "tenant-1",
                "campaign_id": "campaign-1",
                "brand_id": "brand-1",
                "campaign_name": "Launch",
                "objective": "conversion",
                "product_name": "Product",
                "product_description": "A sufficiently detailed product description.",
                "target_audience": ["Professionals"],
                "channel": "linkedin",
                "call_to_action": "Learn more",
                "unexpected": True,
            }
        )


def test_brief_rejects_audience_with_only_whitespace() -> None:
    with pytest.raises(ValidationError):
        CampaignBrief.model_validate(
            {
                "tenant_id": "tenant-1",
                "campaign_id": "campaign-1",
                "brand_id": "brand-1",
                "campaign_name": "Launch",
                "objective": "conversion",
                "product_name": "Product",
                "product_description": "A sufficiently detailed product description.",
                "target_audience": ["   "],
                "channel": "linkedin",
                "call_to_action": "Learn more",
            }
        )


def test_brief_rejects_inverted_support_copy_budget() -> None:
    with pytest.raises(ValidationError):
        CampaignBrief.model_validate(
            {
                "tenant_id": "tenant-1",
                "campaign_id": "campaign-1",
                "brand_id": "brand-1",
                "campaign_name": "Launch",
                "objective": "conversion",
                "product_name": "Product",
                "product_description": "A sufficiently detailed product description.",
                "target_audience": ["Professionals"],
                "channel": "linkedin",
                "headline": "Stop searching. Start connecting.",
                "call_to_action": "Learn more",
                "support_copy_policy": {"min_items": 4, "max_items": 2},
            }
        )
