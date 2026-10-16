"""Repository contracts and SQLAlchemy implementations."""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import CampaignStatus
from poster_agent.persistence.models import CampaignRecord


class CampaignRepository(Protocol):
    """Business persistence boundary."""

    async def save_brief(self, brief: CampaignBrief, *, status: CampaignStatus) -> CampaignRecord:
        """Insert or update a campaign."""

        ...

    async def get(self, campaign_id: str) -> CampaignRecord | None:
        """Return a campaign record by identifier."""

        ...


class SqlAlchemyCampaignRepository:
    """Async SQLAlchemy implementation usable with SQLite or PostgreSQL."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def save_brief(self, brief: CampaignBrief, *, status: CampaignStatus) -> CampaignRecord:
        async with self._sessions() as session:
            record = await session.get(CampaignRecord, brief.campaign_id)
            if record is None:
                record = CampaignRecord(
                    campaign_id=brief.campaign_id,
                    brand_id=brief.brand_id,
                    name=brief.campaign_name,
                    status=status.value,
                    brief_json=brief.model_dump(mode="json"),
                )
                session.add(record)
            else:
                record.brand_id = brief.brand_id
                record.name = brief.campaign_name
                record.status = status.value
                record.brief_json = brief.model_dump(mode="json")
            await session.commit()
            await session.refresh(record)
            return record

    async def get(self, campaign_id: str) -> CampaignRecord | None:
        async with self._sessions() as session:
            return await session.get(CampaignRecord, campaign_id)
