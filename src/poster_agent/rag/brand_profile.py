"""Sprint 2 brand-profile synthesis boundary."""

from typing import Protocol

from poster_agent.domain.brand import BrandProfile, EvidenceReference


class BrandProfileBuilder(Protocol):
    """Build an evidence-backed profile from retrieved chunks."""

    async def build(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        brand_name: str,
        evidence: list[EvidenceReference],
    ) -> BrandProfile:
        """Synthesize a profile without losing its source evidence."""

        ...
