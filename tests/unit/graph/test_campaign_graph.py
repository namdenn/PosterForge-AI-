"""End-to-end graph tests with no external API calls."""

import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from poster_agent.domain.brand import BrandProfile
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import CampaignStatus
from poster_agent.domain.errors import StrategyGenerationError
from poster_agent.domain.strategy import CampaignStrategy
from poster_agent.graph.builder import build_campaign_graph
from poster_agent.graph.state import CampaignState
from poster_agent.llm.gateway import GenerationMetadata, StrategyGenerationResult
from poster_agent.persistence.artifact_store import LocalArtifactStore
from poster_agent.persistence.checkpointer import sqlite_checkpointer


def valid_brief_payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant-1",
        "campaign_id": "campaign-1",
        "brand_id": "brand-1",
        "campaign_name": "Product launch",
        "objective": "conversion",
        "product_name": "Product",
        "product_description": "A sufficiently detailed product description.",
        "target_audience": ["Busy professionals"],
        "channel": "linkedin",
        "language": "en",
        "call_to_action": "Learn more",
        "mandatory_elements": ["Brand logo"],
    }


def valid_strategy(*, call_to_action: str = "Learn more") -> CampaignStrategy:
    return CampaignStrategy.model_validate(
        {
            "campaign_id": "campaign-1",
            "objective": "conversion",
            "audience_insight": "Professionals need a simple solution.",
            "big_idea": "Make the next task effortless.",
            "headline": "Work smarter today",
            "primary_message": "The product removes friction from daily work.",
            "supporting_messages": ["Simple", "Reliable"],
            "tone_of_voice": ["Confident", "Clear"],
            "call_to_action": call_to_action,
            "visual_direction": {
                "art_style": "Editorial photography",
                "mood": "Focused",
                "color_palette": ["#101820", "#FEE715"],
                "composition": "Product on the right with clear copy space.",
                "typography": "Bold geometric sans serif",
                "image_subject": "Professional using the product",
            },
            "mandatory_elements": ["Brand logo"],
            "risks": [],
        }
    )


class FakeStrategyGenerator:
    def __init__(self, *, fail_first_quality_gate: bool = False) -> None:
        self.calls = 0
        self.fail_first_quality_gate = fail_first_quality_gate

    async def generate_strategy(
        self,
        brief: CampaignBrief,
        *,
        brand_profile: BrandProfile | None = None,
        feedback: list[str] | None = None,
    ) -> StrategyGenerationResult:
        del brief, brand_profile, feedback
        self.calls += 1
        should_fail = self.fail_first_quality_gate and self.calls == 1
        action = "Wrong action" if should_fail else "Learn more"
        return StrategyGenerationResult(
            strategy=valid_strategy(call_to_action=action),
            metadata=GenerationMetadata(provider="fake", model="fake-model"),
        )


class FailingStrategyGenerator:
    async def generate_strategy(
        self,
        brief: CampaignBrief,
        *,
        brand_profile: BrandProfile | None = None,
        feedback: list[str] | None = None,
    ) -> StrategyGenerationResult:
        del brief, brand_profile, feedback
        raise StrategyGenerationError("simulated transient failure")


async def test_graph_completes_and_saves_artifact(tmp_path: Path) -> None:
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(valid_brief_payload()), encoding="utf-8")
    generator = FakeStrategyGenerator()
    graph = build_campaign_graph(
        generator=generator,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        checkpointer=InMemorySaver(),
    )
    initial: CampaignState = {
        "thread_id": "thread-1",
        "brief_path": str(brief_path),
        "max_generation_attempts": 2,
    }

    result = await graph.ainvoke(
        initial,
        config={"configurable": {"thread_id": "thread-1"}},
    )

    assert result["status"] == CampaignStatus.COMPLETED
    artifact_path = Path(result["artifact_path"])
    assert await asyncio.to_thread(artifact_path.exists)
    assert generator.calls == 1


async def test_graph_retries_failed_quality_gate(tmp_path: Path) -> None:
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(valid_brief_payload()), encoding="utf-8")
    generator = FakeStrategyGenerator(fail_first_quality_gate=True)
    graph = build_campaign_graph(
        generator=generator,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        checkpointer=InMemorySaver(),
    )
    initial: CampaignState = {
        "thread_id": "thread-retry",
        "brief_path": str(brief_path),
        "max_generation_attempts": 2,
    }

    result = await graph.ainvoke(
        initial,
        config={"configurable": {"thread_id": "thread-retry"}},
    )

    assert result["status"] == CampaignStatus.COMPLETED
    assert result["generation_attempt"] == 2
    assert generator.calls == 2


async def test_invalid_brief_stops_before_generation(tmp_path: Path) -> None:
    brief_path = tmp_path / "invalid.json"
    brief_path.write_text("{}", encoding="utf-8")
    generator = FakeStrategyGenerator()
    graph = build_campaign_graph(
        generator=generator,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        checkpointer=InMemorySaver(),
    )

    result = await graph.ainvoke(
        {"thread_id": "thread-invalid", "brief_path": str(brief_path)},
        config={"configurable": {"thread_id": "thread-invalid"}},
    )

    assert result["status"] == CampaignStatus.FAILED
    assert result["validation_errors"]
    assert generator.calls == 0


async def test_sqlite_checkpoint_survives_reopen(tmp_path: Path) -> None:
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(valid_brief_payload()), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoints.db"
    generator = FakeStrategyGenerator()
    config: RunnableConfig = {"configurable": {"thread_id": "durable-thread"}}

    async with sqlite_checkpointer(checkpoint_path) as checkpointer:
        graph = build_campaign_graph(
            generator=generator,
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            checkpointer=checkpointer,
        )
        await graph.ainvoke(
            {"thread_id": "durable-thread", "brief_path": str(brief_path)},
            config=config,
        )

    async with sqlite_checkpointer(checkpoint_path) as reopened:
        checkpoint = await reopened.aget_tuple(config)

    assert checkpoint is not None
    assert checkpoint.checkpoint["channel_values"]["status"] == CampaignStatus.COMPLETED


async def test_interrupted_graph_resumes_from_sqlite_checkpoint(tmp_path: Path) -> None:
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps(valid_brief_payload()), encoding="utf-8")
    checkpoint_path = tmp_path / "resume.db"
    config: RunnableConfig = {"configurable": {"thread_id": "resume-thread"}}

    async with sqlite_checkpointer(checkpoint_path) as checkpointer:
        failing_graph = build_campaign_graph(
            generator=FailingStrategyGenerator(),
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            checkpointer=checkpointer,
        )
        with pytest.raises(StrategyGenerationError):
            await failing_graph.ainvoke(
                {"thread_id": "resume-thread", "brief_path": str(brief_path)},
                config=config,
            )

    successful_generator = FakeStrategyGenerator()
    async with sqlite_checkpointer(checkpoint_path) as reopened:
        resumed_graph = build_campaign_graph(
            generator=successful_generator,
            artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
            checkpointer=reopened,
        )
        result = await resumed_graph.ainvoke(None, config=config)

    assert result["status"] == CampaignStatus.COMPLETED
    assert successful_generator.calls == 1
