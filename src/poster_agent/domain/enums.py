"""Shared enumerations for the poster-agent domain."""

from enum import StrEnum


class CampaignObjective(StrEnum):
    """Business objective that the campaign is expected to achieve."""

    AWARENESS = "awareness"
    ENGAGEMENT = "engagement"
    LEAD_GENERATION = "lead_generation"
    CONVERSION = "conversion"
    RECRUITMENT = "recruitment"
    EVENT_PROMOTION = "event_promotion"


class MarketingChannel(StrEnum):
    """Primary publishing channel for a generated poster."""

    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    LINKEDIN = "linkedin"
    TIKTOK = "tiktok"
    EMAIL = "email"
    WEBSITE = "website"
    DISPLAY_AD = "display_ad"
    PRINT = "print"


class Language(StrEnum):
    """Language used for campaign copy and generated content."""

    VIETNAMESE = "vi"
    ENGLISH = "en"


class CampaignStatus(StrEnum):
    """Lifecycle status of a campaign workflow."""

    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RiskSeverity(StrEnum):
    """Severity assigned to a campaign or compliance risk."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKING = "blocking"


class ApprovalStatus(StrEnum):
    """Lifecycle of a synthesized creative blueprint."""

    DRAFT = "draft"
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class AssetType(StrEnum):
    """Approved visual asset roles used by the deterministic compositor."""

    LOGO = "logo"
    PRODUCT = "product"
    FONT = "font"
    REFERENCE = "reference"


class RenderStatus(StrEnum):
    """Lifecycle of a Sprint 3 poster-rendering workflow."""

    VALIDATING = "validating"
    RENDERING = "rendering"
    REVIEWING = "reviewing"
    NEEDS_REVIEW = "needs_review"
    COMPLETED = "completed"
    FAILED = "failed"
