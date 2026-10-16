"""Campaign brief contract accepted by campaign workflows."""

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from poster_agent.domain.enums import CampaignObjective, Language, MarketingChannel


class SupportCopyPolicy(BaseModel):
    """Bounded freedom for evidence-grounded supporting poster copy."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    min_items: int = Field(default=1, ge=1, le=5)
    max_items: int = Field(default=3, ge=1, le=5)
    max_words_per_item: int = Field(default=12, ge=3, le=30)
    allowed_angles: list[str] = Field(default_factory=list, max_length=8)
    must_be_grounded_in_rag: bool = True

    @model_validator(mode="after")
    def valid_range(self) -> "SupportCopyPolicy":
        if self.max_items < self.min_items:
            raise ValueError("max_items must be greater than or equal to min_items")
        return self


class CampaignBrief(BaseModel):
    """Validated marketing input supplied by a user or upstream system."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tenant_id: str = Field(min_length=1, max_length=100)
    campaign_id: str = Field(min_length=1, max_length=100)
    brand_id: str = Field(min_length=1, max_length=100)
    campaign_name: str = Field(min_length=1, max_length=160)
    objective: CampaignObjective
    product_name: str = Field(min_length=1, max_length=160)
    product_description: str = Field(min_length=10, max_length=3000)
    target_audience: list[str] = Field(min_length=1, max_length=10)
    channel: MarketingChannel
    language: Language = Language.VIETNAMESE
    headline: str | None = Field(default=None, min_length=1, max_length=180)
    call_to_action: str = Field(min_length=1, max_length=200)
    support_copy_policy: SupportCopyPolicy = Field(default_factory=SupportCopyPolicy)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    mandatory_elements: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("target_audience", "constraints", "mandatory_elements")
    @classmethod
    def normalize_string_list(cls, values: list[str], info: ValidationInfo) -> list[str]:
        """Trim, discard empty entries, and preserve-order de-duplicate values."""

        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if info.field_name == "target_audience" and not normalized:
            raise ValueError("target_audience must contain at least one non-empty value")
        return normalized
