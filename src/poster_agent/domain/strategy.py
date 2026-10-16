"""Structured strategy returned by the language model."""

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from poster_agent.domain.enums import CampaignObjective, RiskSeverity


class VisualDirection(BaseModel):
    """Creative direction that a later design agent can consume."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    art_style: str = Field(min_length=1)
    mood: str = Field(min_length=1)
    color_palette: list[str] = Field(min_length=1, max_length=8)
    composition: str = Field(min_length=1)
    typography: str = Field(min_length=1)
    image_subject: str = Field(min_length=1)


class StrategyRisk(BaseModel):
    """A marketing, brand, or execution risk and its mitigation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    severity: RiskSeverity
    description: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)


class CampaignStrategy(BaseModel):
    """Provider-independent output of the strategy-generation block."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    campaign_id: str = Field(min_length=1)
    objective: CampaignObjective
    audience_insight: str = Field(min_length=1)
    big_idea: str = Field(min_length=1)
    headline: str = Field(min_length=1, max_length=180)
    primary_message: str = Field(min_length=1)
    supporting_messages: list[str] = Field(min_length=1, max_length=5)
    tone_of_voice: list[str] = Field(min_length=1, max_length=6)
    call_to_action: str = Field(min_length=1, max_length=200)
    visual_direction: VisualDirection
    mandatory_elements: list[str] = Field(default_factory=list)
    risks: list[StrategyRisk] = Field(default_factory=list, max_length=8)

    @field_validator("supporting_messages", "tone_of_voice", "mandatory_elements", mode="after")
    @classmethod
    def deduplicate_list(cls, values: list[str], info: ValidationInfo) -> list[str]:
        """Keep model output stable and easy for downstream nodes to compare."""

        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        required_lists = {"supporting_messages", "tone_of_voice"}
        if info.field_name in required_lists and not normalized:
            raise ValueError(f"{info.field_name} must contain at least one non-empty value")
        return normalized
