"""SQLAlchemy records for durable business metadata (not graph checkpoints)."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative metadata root used by Alembic."""


class CampaignRecord(Base):
    """Latest validated campaign brief."""

    __tablename__ = "campaigns"

    campaign_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    brand_id: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), index=True)
    brief_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    runs: Mapped[list["WorkflowRunRecord"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan"
    )


class WorkflowRunRecord(Base):
    """One LangGraph thread associated with a campaign."""

    __tablename__ = "workflow_runs"

    thread_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(
        ForeignKey("campaigns.campaign_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    campaign: Mapped[CampaignRecord] = relationship(back_populates="runs")
