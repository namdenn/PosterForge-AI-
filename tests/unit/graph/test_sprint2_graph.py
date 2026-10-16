"""End-to-end Sprint 2 graph tests using fake RAG and fake model agents."""

import asyncio
import json
from pathlib import Path
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from poster_agent.domain.blueprint import (
    ContextBundle,
    MessagingProposal,
    ReviewReport,
    StrategyProposal,
    VisualProposal,
)
from poster_agent.domain.brand import BrandProfile, EvidenceReference
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import (
    ApprovalStatus,
    CampaignObjective,
    CampaignStatus,
    RiskSeverity,
)
from poster_agent.graph.sprint2_builder import build_sprint2_graph
from poster_agent.graph.sprint2_state import Sprint2State
from poster_agent.llm.gateway import GenerationMetadata
from poster_agent.persistence.artifact_store import LocalArtifactStore
from poster_agent.rag.store import IndexedChunk


def brief_payload() -> dict[str, object]:
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


def evidence() -> EvidenceReference:
    return EvidenceReference(
        tenant_id="tenant-1",
        brand_id="brand-1",
        document_id="brand-doc",
        chunk_id="brand-doc:chunk-0001",
        source_version="v1",
        source_path="brand.md",
        excerpt="The brand is confident, modern, and clear.",
        relevance_score=0.95,
    )


class FakeKnowledgeStore:
    def __init__(self) -> None:
        self.profile = BrandProfile(
            tenant_id="tenant-1",
            brand_id="brand-1",
            brand_name="Brand One",
            personality_traits=["modern"],
            tone_of_voice=["confident", "clear"],
            evidence=[evidence()],
        )

    async def setup(self) -> None: ...

    async def replace_document(self, chunks: list[IndexedChunk]) -> None:
        del chunks

    async def search(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        query_embedding: list[float],
        limit: int,
    ) -> list[EvidenceReference]:
        del tenant_id, brand_id, query_embedding, limit
        return [evidence()]

    async def save_profile(self, profile: BrandProfile) -> None:
        self.profile = profile

    async def get_profile(self, *, tenant_id: str, brand_id: str) -> BrandProfile | None:
        if tenant_id == self.profile.tenant_id and brand_id == self.profile.brand_id:
            return self.profile
        return None

    async def count_chunks(self, *, tenant_id: str, brand_id: str) -> int:
        del tenant_id, brand_id
        return 1


class FakeRetriever:
    async def retrieve(
        self,
        *,
        tenant_id: str,
        brand_id: str,
        query: str,
        limit: int = 8,
    ) -> list[EvidenceReference]:
        del tenant_id, brand_id, query, limit
        return [evidence()]


class FakeCreativeGenerator:
    def __init__(self, *, fail_first_message: bool = False) -> None:
        self.fail_first_message = fail_first_message
        self.messaging_calls = 0

    async def generate_messaging(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[MessagingProposal, GenerationMetadata]:
        del brief, context, feedback
        self.messaging_calls += 1
        should_fail = self.fail_first_message and self.messaging_calls == 1
        return (
            MessagingProposal(
                headline="Work smarter",
                primary_message="A clear product message.",
                supporting_messages=["Simple", "Reliable"],
                call_to_action="Wrong CTA" if should_fail else "Learn more",
                tone_of_voice=["confident", "clear"],
                rationale="Aligned with the verified brand tone.",
                evidence_chunk_ids=[evidence().chunk_id],
            ),
            GenerationMetadata(provider="fake", model="fake", operation="messaging"),
        )

    async def generate_visual(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[VisualProposal, GenerationMetadata]:
        del brief, context, feedback
        return (
            VisualProposal.model_validate(
                {
                    "direction": {
                        "art_style": "Editorial photography",
                        "mood": "Focused",
                        "color_palette": ["#101820"],
                        "composition": "Product right, copy left.",
                        "typography": "Geometric sans serif",
                        "image_subject": "Professional with product",
                    },
                    "layout_notes": ["Preserve clear hierarchy"],
                    "negative_constraints": [],
                    "mandatory_elements": ["Brand logo"],
                    "rationale": "Practical for the selected channel.",
                    "evidence_chunk_ids": [evidence().chunk_id],
                }
            ),
            GenerationMetadata(provider="fake", model="fake", operation="visual"),
        )

    async def generate_strategy(
        self,
        brief: CampaignBrief,
        context: ContextBundle,
        *,
        feedback: list[str] | None = None,
    ) -> tuple[StrategyProposal, GenerationMetadata]:
        del brief, context, feedback
        return (
            StrategyProposal(
                objective=CampaignObjective.CONVERSION,
                audience_insight="Professionals value clarity.",
                big_idea="Remove daily friction.",
                strategic_rationale="Matches the objective and audience.",
                risks=[],
                evidence_chunk_ids=[evidence().chunk_id],
            ),
            GenerationMetadata(provider="fake", model="fake", operation="campaign_strategy"),
        )


async def run_graph(tmp_path: Path, generator: FakeCreativeGenerator) -> Sprint2State:
    brief_path = tmp_path / "brief.json"
    await asyncio.to_thread(
        brief_path.write_text,
        json.dumps(brief_payload()),
        encoding="utf-8",
    )
    graph = build_sprint2_graph(
        generator=generator,
        retriever=FakeRetriever(),
        knowledge_store=FakeKnowledgeStore(),
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        checkpointer=InMemorySaver(),
        top_k=3,
    )
    initial: Sprint2State = {
        "thread_id": "sprint-2-thread",
        "brief_path": str(brief_path),
        "concept_attempt": 0,
        "max_concept_attempts": 2,
        "generation_metadata": [],
    }
    return cast(
        Sprint2State,
        await graph.ainvoke(
            initial,
            config={"configurable": {"thread_id": "sprint-2-thread"}},
        ),
    )


async def test_sprint2_graph_creates_approved_blueprint(tmp_path: Path) -> None:
    result = await run_graph(tmp_path, FakeCreativeGenerator())

    assert result["status"] == CampaignStatus.COMPLETED
    assert result["blueprint"].approval_status == ApprovalStatus.APPROVED
    assert {item.operation for item in result["generation_metadata"]} == {
        "messaging",
        "visual",
        "campaign_strategy",
    }
    artifact_path = Path(result["artifact_path"])
    assert artifact_path.name == "creative_blueprint.json"
    assert await asyncio.to_thread(artifact_path.exists)


async def test_sprint2_graph_retries_review_failure(tmp_path: Path) -> None:
    generator = FakeCreativeGenerator(fail_first_message=True)
    result = await run_graph(tmp_path, generator)

    assert result["status"] == CampaignStatus.COMPLETED
    assert result["concept_attempt"] == 2
    assert generator.messaging_calls == 2
    assert len(result["generation_metadata"]) == 6


async def test_human_approval_resumes_finished_review_thread(tmp_path: Path) -> None:
    brief_path = tmp_path / "brief.json"
    await asyncio.to_thread(
        brief_path.write_text,
        json.dumps(brief_payload()),
        encoding="utf-8",
    )
    graph = build_sprint2_graph(
        generator=FakeCreativeGenerator(fail_first_message=True),
        retriever=FakeRetriever(),
        knowledge_store=FakeKnowledgeStore(),
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        checkpointer=InMemorySaver(),
    )
    config: RunnableConfig = {"configurable": {"thread_id": "human-review"}}
    initial: Sprint2State = {
        "workflow_version": "2.0",
        "thread_id": "human-review",
        "brief_path": str(brief_path),
        "concept_attempt": 0,
        "max_concept_attempts": 1,
        "generation_metadata": [],
    }
    needs_review = cast(Sprint2State, await graph.ainvoke(initial, config=config))
    assert needs_review["status"] == CampaignStatus.NEEDS_REVIEW

    blueprint = needs_review["blueprint"]
    human_report = ReviewReport(
        reviewer="human_approver",
        passed=True,
        severity=RiskSeverity.LOW,
        recommendations=["Approved for this controlled campaign."],
    )
    approved = blueprint.model_copy(
        update={
            "approval_status": ApprovalStatus.APPROVED,
            "reviews": [*blueprint.reviews, human_report],
        }
    )
    await graph.aupdate_state(
        config,
        {
            "blueprint": approved,
            "review_errors": [],
            "status": CampaignStatus.RUNNING,
        },
        as_node="review_join",
    )
    completed = cast(Sprint2State, await graph.ainvoke(None, config=config))

    assert completed["status"] == CampaignStatus.COMPLETED
    assert completed["blueprint"].approval_status == ApprovalStatus.APPROVED
