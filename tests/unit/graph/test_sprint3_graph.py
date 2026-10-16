"""Sprint 3 graph tests use local fake image and vision adapters only."""

import asyncio
from pathlib import Path
from typing import cast

from langgraph.checkpoint.memory import InMemorySaver
from PIL import Image

from poster_agent.domain.blueprint import (
    CreativeBlueprint,
    MessagingProposal,
    StrategyProposal,
    VisualProposal,
)
from poster_agent.domain.brand import BrandProfile, EvidenceReference
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import (
    ApprovalStatus,
    AssetType,
    CampaignObjective,
    RenderStatus,
    RiskSeverity,
)
from poster_agent.domain.render import (
    ArtworkLayoutDecision,
    BlueprintArtifact,
    BrandTokens,
    CreativeTerritory,
    DesignConcept,
    DiversityReport,
    FontFamily,
    GeneratedCandidate,
    NormalizedBox,
    QualityReport,
    RenderConfig,
    RenderPlan,
    ResolvedAsset,
    ResolvedAssets,
    SceneLayer,
    TerritoryPortfolio,
)
from poster_agent.domain.strategy import VisualDirection
from poster_agent.graph.render_builder import build_render_graph
from poster_agent.graph.render_state import renderState
from poster_agent.llm.gateway import GenerationMetadata
from poster_agent.llm.image_gateway import ImageGenerationRequest
from poster_agent.persistence.render_store import LocalRenderArtifactStore
from poster_agent.rendering.compositor import PillowPosterCompositor


def _brief() -> CampaignBrief:
    return CampaignBrief.model_validate(
        {
            "tenant_id": "tenant-1",
            "campaign_id": "campaign-1",
            "brand_id": "brand-1",
            "campaign_name": "Summer launch",
            "objective": "conversion",
            "product_name": "Cold Brew",
            "product_description": "A citrus cold brew for professionals.",
            "target_audience": ["Professionals"],
            "channel": "instagram",
            "language": "en",
            "call_to_action": "Order today",
            "mandatory_elements": ["Brand logo", "Product image"],
        }
    )


def _blueprint(*, approval: ApprovalStatus = ApprovalStatus.APPROVED) -> CreativeBlueprint:
    evidence = EvidenceReference(
        tenant_id="tenant-1",
        brand_id="brand-1",
        document_id="brand-doc",
        chunk_id="brand-doc:chunk-1",
        source_version="v1",
        source_path="brand.md",
        excerpt="Modern, clear, navy and orange.",
        relevance_score=0.9,
    )
    return CreativeBlueprint(
        tenant_id="tenant-1",
        campaign_id="campaign-1",
        brand_id="brand-1",
        messaging=MessagingProposal(
            headline="Refresh your afternoon",
            primary_message="Smooth citrus cold brew for a modern workday.",
            supporting_messages=["Light citrus taste"],
            call_to_action="Order today",
            tone_of_voice=["clear"],
            rationale="Matches the brief.",
            evidence_chunk_ids=[evidence.chunk_id],
        ),
        visual=VisualProposal(
            direction=VisualDirection(
                art_style="Editorial product photography",
                mood="Fresh and confident",
                color_palette=["Navy #101820", "Orange #F4A261"],
                composition="Copy left and product right",
                typography="Bold sans serif",
                image_subject="An accurate branded bottle and logo as the product hero",
            ),
            layout_notes=["Use a 4:5 canvas"],
            negative_constraints=["No text in generated background"],
            mandatory_elements=["Brand logo", "Product image"],
            rationale="Mobile first.",
            evidence_chunk_ids=[evidence.chunk_id],
        ),
        strategy=StrategyProposal(
            objective=CampaignObjective.CONVERSION,
            audience_insight="Professionals want a simple afternoon refreshment.",
            big_idea="Refresh the workday.",
            strategic_rationale="Direct product-led conversion.",
            evidence_chunk_ids=[evidence.chunk_id],
        ),
        brand_profile=BrandProfile(
            tenant_id="tenant-1",
            brand_id="brand-1",
            brand_name="Brand One",
            personality_traits=["modern"],
            tone_of_voice=["clear"],
            preferred_colors=["#101820", "#F4A261"],
            forbidden_claims=["medical benefit"],
            evidence=[evidence],
        ),
        evidence=[evidence],
        channel_guidance=["Use a 4:5 composition"],
        approval_status=approval,
    )


class FakeImageGenerator:
    def __init__(self) -> None:
        self.requests: list[ImageGenerationRequest] = []

    async def generate(self, request: ImageGenerationRequest) -> GeneratedCandidate:
        self.requests.append(request)
        await asyncio.to_thread(request.output_path.parent.mkdir, parents=True, exist_ok=True)
        image = Image.effect_noise((1024, 1536), 48).convert("RGB")
        await asyncio.to_thread(image.save, request.output_path, "PNG")
        return GeneratedCandidate(
            candidate_id=request.candidate_id,
            concept_id=request.concept_id,
            attempt=request.attempt,
            prompt=request.prompt,
            generated_path=request.output_path,
            provider="fake",
            model="fake-image",
        )


class FakeDesignGenerator:
    async def generate_territories(
        self,
        *,
        brief: CampaignBrief,
        blueprint: CreativeBlueprint,
        brand_tokens: BrandTokens,
        approved_product_available: bool,
        feedback: list[str] | None = None,
    ) -> tuple[TerritoryPortfolio, GenerationMetadata]:
        del brief, blueprint, brand_tokens, approved_product_available, feedback
        return (
            TerritoryPortfolio(
                territories=[
                    CreativeTerritory(
                        territory_id=f"territory-{index}",
                        name=f"Territory {index}",
                        narrative=f"Narrative {index}",
                        visual_metaphor=f"Metaphor {index}",
                        storytelling_mode=f"Mode {index}",
                        composition_logic=f"Composition {index}",
                        hero_subject=f"Hero {index}",
                    )
                    for index in range(3)
                ]
            ),
            GenerationMetadata(provider="fake", model="fake", operation="territories"),
        )

    async def generate_concept(
        self,
        *,
        brief: CampaignBrief,
        blueprint: CreativeBlueprint,
        brand_tokens: BrandTokens,
        territory: CreativeTerritory,
        concept_index: int,
        approved_product_available: bool,
        feedback: list[str] | None = None,
    ) -> tuple[DesignConcept, GenerationMetadata]:
        del brief, blueprint, brand_tokens, approved_product_available, feedback
        positions = [
            ((0.05, 0.04), (0.05, 0.15), (0.56, 0.28)),
            ((0.40, 0.04), (0.15, 0.16), (0.25, 0.43)),
            ((0.74, 0.04), (0.05, 0.18), (0.05, 0.42)),
        ]
        logo_xy, headline_xy, product_xy = positions[concept_index]
        font_families: list[FontFamily] = ["segoe_ui", "georgia", "bahnschrift"]
        layers = [
            SceneLayer(
                layer_id="logo",
                layer_type="locked_logo",
                bounds=NormalizedBox(x=logo_xy[0], y=logo_xy[1], width=0.2, height=0.07),
            ),
            SceneLayer(
                layer_id="headline",
                layer_type="headline",
                bounds=NormalizedBox(x=headline_xy[0], y=headline_xy[1], width=0.58, height=0.14),
                font_role="heading",
                font_family=font_families[concept_index],
                font_weight="black",
                fill_token="black",
            ),
            SceneLayer(
                layer_id="primary",
                layer_type="primary_message",
                bounds=NormalizedBox(x=0.05, y=0.68, width=0.42, height=0.1),
                fill_token="black",
            ),
            SceneLayer(
                layer_id="support",
                layer_type="support_message",
                support_index=0,
                bounds=NormalizedBox(x=0.53, y=0.68, width=0.42, height=0.1),
                fill_token="black",
            ),
            SceneLayer(
                layer_id="cta",
                layer_type="call_to_action",
                bounds=NormalizedBox(x=0.3, y=0.84, width=0.4, height=0.08),
                fill_token="black",
            ),
            SceneLayer(
                layer_id="product",
                layer_type="approved_product",
                bounds=NormalizedBox(x=product_xy[0], y=product_xy[1], width=0.35, height=0.25),
            ),
        ]
        return (
            DesignConcept(
                concept_id=f"concept-{concept_index}",
                territory_id=territory.territory_id,
                creative_thesis=f"Thesis {concept_index}",
                artwork_prompt=f"Artwork {concept_index}",
                selected_support_messages=["Light citrus taste"],
                palette_tokens=["black", "white"],
                layers=layers,
                layout_signature=f"signature-{concept_index}",
                rationale="A test concept.",
            ),
            GenerationMetadata(provider="fake", model="fake", operation=f"concept-{concept_index}"),
        )

    async def refine_overlay(
        self,
        *,
        artwork_path: Path,
        concept: DesignConcept,
        plan: RenderPlan,
        feedback: list[str] | None = None,
    ) -> tuple[ArtworkLayoutDecision, GenerationMetadata]:
        del artwork_path, plan, feedback
        return (
            ArtworkLayoutDecision(
                passed=True,
                score=96,
                severity=RiskSeverity.LOW,
                layers=concept.layers,
                layout_signature=concept.layout_signature,
                rationale="The overlay uses visible negative space.",
            ),
            GenerationMetadata(provider="fake", model="fake", operation="visual-layout"),
        )


class RetryLayoutRefiner(FakeDesignGenerator):
    async def refine_overlay(
        self,
        *,
        artwork_path: Path,
        concept: DesignConcept,
        plan: RenderPlan,
        feedback: list[str] | None = None,
    ) -> tuple[ArtworkLayoutDecision, GenerationMetadata]:
        del plan, feedback
        first_attempt = "attempt-1" in artwork_path.parts
        return (
            ArtworkLayoutDecision(
                passed=not first_attempt,
                score=30 if first_attempt else 96,
                severity=RiskSeverity.HIGH if first_attempt else RiskSeverity.LOW,
                issues=["Generated artwork contains packaging."] if first_attempt else [],
                layers=concept.layers,
                layout_signature=concept.layout_signature,
                rationale="Retry contaminated artwork." if first_attempt else "Safe layout.",
            ),
            GenerationMetadata(provider="fake", model="fake", operation="visual-layout"),
        )


class AlwaysFailLayoutRefiner(FakeDesignGenerator):
    async def refine_overlay(
        self,
        *,
        artwork_path: Path,
        concept: DesignConcept,
        plan: RenderPlan,
        feedback: list[str] | None = None,
    ) -> tuple[ArtworkLayoutDecision, GenerationMetadata]:
        del artwork_path, plan, feedback
        return (
            ArtworkLayoutDecision(
                passed=False,
                score=10,
                severity=RiskSeverity.BLOCKING,
                issues=["Generated artwork contains text and UI."],
                layers=concept.layers,
                layout_signature=concept.layout_signature,
                rationale="No safe overlay is possible.",
            ),
            GenerationMetadata(provider="fake", model="fake", operation="visual-layout"),
        )


class FakeVisualReviewer:
    async def review_background(
        self, *, candidate_id: str, background_path: Path, plan: RenderPlan
    ) -> QualityReport:
        del background_path, plan
        return QualityReport(
            candidate_id=candidate_id,
            reviewer="background_qa",
            passed=True,
            score=95,
            severity=RiskSeverity.LOW,
        )

    async def review(
        self, *, candidate_id: str, poster_path: Path, blueprint: CreativeBlueprint
    ) -> QualityReport:
        del poster_path, blueprint
        return QualityReport(
            candidate_id=candidate_id,
            reviewer="visual_qa",
            passed=True,
            score=90,
            severity=RiskSeverity.LOW,
        )


class FailingVisualReviewer:
    async def review_background(
        self, *, candidate_id: str, background_path: Path, plan: RenderPlan
    ) -> QualityReport:
        del background_path, plan
        return QualityReport(
            candidate_id=candidate_id,
            reviewer="background_qa",
            passed=True,
            score=95,
            severity=RiskSeverity.LOW,
        )

    async def review(
        self, *, candidate_id: str, poster_path: Path, blueprint: CreativeBlueprint
    ) -> QualityReport:
        del poster_path, blueprint
        return QualityReport(
            candidate_id=candidate_id,
            reviewer="visual_qa",
            passed=False,
            score=40,
            severity=RiskSeverity.BLOCKING,
            issues=["Poster is not production ready."],
        )


class RetryCompositionReviewer(FakeVisualReviewer):
    def __init__(self) -> None:
        self.review_count = 0

    async def review(
        self, *, candidate_id: str, poster_path: Path, blueprint: CreativeBlueprint
    ) -> QualityReport:
        del poster_path, blueprint
        self.review_count += 1
        first_layout = self.review_count == 1
        return QualityReport(
            candidate_id=candidate_id,
            reviewer="visual_qa",
            passed=not first_layout,
            score=55 if first_layout else 95,
            severity=RiskSeverity.HIGH if first_layout else RiskSeverity.LOW,
            issues=["Headline covers the hero subject."] if first_layout else [],
        )


class RetryBackgroundReviewer(FakeVisualReviewer):
    async def review_background(
        self, *, candidate_id: str, background_path: Path, plan: RenderPlan
    ) -> QualityReport:
        del plan
        first_attempt = "attempt-1" in background_path.parts
        return QualityReport(
            candidate_id=candidate_id,
            reviewer="background_qa",
            passed=not first_attempt,
            score=30 if first_attempt else 95,
            severity=RiskSeverity.BLOCKING if first_attempt else RiskSeverity.LOW,
            issues=["Generated background contains packaging."] if first_attempt else [],
        )


class AlwaysFailBackgroundReviewer(FakeVisualReviewer):
    async def review_background(
        self, *, candidate_id: str, background_path: Path, plan: RenderPlan
    ) -> QualityReport:
        del background_path, plan
        return QualityReport(
            candidate_id=candidate_id,
            reviewer="background_qa",
            passed=False,
            score=0,
            severity=RiskSeverity.BLOCKING,
            issues=["Generated background contains text and UI."],
        )


async def _fixture_files(tmp_path: Path, *, approval: ApprovalStatus) -> tuple[Path, Path]:
    brief = _brief()
    artifact = BlueprintArtifact(
        schema_version="2.0",
        thread_id="source-thread",
        brief=brief,
        creative_blueprint=_blueprint(approval=approval),
        status="completed",
    )
    blueprint_path = tmp_path / "creative_blueprint.json"
    await asyncio.to_thread(
        blueprint_path.write_text,
        artifact.model_dump_json(indent=2),
        encoding="utf-8",
    )
    asset_dir = tmp_path / "assets"
    await asyncio.to_thread(asset_dir.mkdir, parents=True)
    logo = Image.new("RGBA", (400, 120), (244, 162, 97, 255))
    product = Image.new("RGBA", (500, 900), (20, 40, 60, 230))
    await asyncio.to_thread(logo.save, asset_dir / "logo.png", "PNG")
    await asyncio.to_thread(product.save, asset_dir / "product.png", "PNG")
    manifest_path = asset_dir / "manifest.json"
    await asyncio.to_thread(
        manifest_path.write_text,
        """{
          "schema_version": "1.0",
          "tenant_id": "tenant-1",
          "brand_id": "brand-1",
          "assets": [
            {"asset_id": "logo", "asset_type": "logo", "path": "logo.png",
             "version": "1", "approval_status": "approved", "allowed_channels": []},
            {"asset_id": "product", "asset_type": "product", "path": "product.png",
             "version": "1", "approval_status": "approved", "allowed_channels": []}
          ]
        }""",
        encoding="utf-8",
    )
    return blueprint_path, manifest_path


async def test_render_graph_creates_reviewed_poster(tmp_path: Path) -> None:
    blueprint_path, manifest_path = await _fixture_files(tmp_path, approval=ApprovalStatus.APPROVED)
    image_generator = FakeImageGenerator()
    graph = build_render_graph(
        design_generator=FakeDesignGenerator(),
        layout_refiner=FakeDesignGenerator(),
        image_generator=image_generator,
        visual_reviewer=FakeVisualReviewer(),
        compositor=PillowPosterCompositor(),
        artifact_store=LocalRenderArtifactStore(),
        checkpointer=InMemorySaver(),
    )
    initial: renderState = {
        "workflow_version": "3.1",
        "render_id": "render-1",
        "blueprint_path": str(blueprint_path),
        "asset_manifest_path": str(manifest_path),
        "render_work_dir": str(tmp_path / "renders" / "render-1"),
        "render_config": RenderConfig(variant_count=3),
        "design_attempt": 0,
        "max_design_attempts": 2,
        "design_generation_metadata": [],
        "render_attempt": 0,
        "review_errors": [],
    }
    result = cast(
        renderState,
        await graph.ainvoke(
            initial,
            config={"configurable": {"thread_id": "render:render-1"}},
        ),
    )

    assert result["status"] == RenderStatus.COMPLETED
    assert result["selection"].approval_status == ApprovalStatus.APPROVED
    assert len(result["composed_candidates"]) == 3
    assert len(result["render_plan"].concepts) == 3
    assert result["render_plan"].diversity.passed
    assert result["render_plan"].supporting_messages == ["Light citrus taste"]
    assert len({item.poster_path.read_bytes() for item in result["composed_candidates"]}) == 3
    assert {item.layout_signature for item in result["composed_candidates"]} == {
        "signature-0",
        "signature-1",
        "signature-2",
    }
    assert {
        next(layer.font_family for layer in concept.layers if layer.layer_type == "headline")
        for concept in result["render_plan"].concepts
    } == {"segoe_ui", "georgia", "bahnschrift"}
    assert all("logo" in item.locked_asset_hashes for item in result["composed_candidates"])
    assert result["final_poster_path"].is_file()
    assert result["final_poster_path"].parent.name == "final"
    assert result["render_manifest_path"].is_file()
    for candidate in result["generated_candidates"]:
        assert "Products, expressive illustrations" in candidate.prompt
        assert "original logo" in candidate.prompt
    assert image_generator.requests
    assert all(not request.reference_paths for request in image_generator.requests)


async def test_render_rejects_unapproved_blueprint(tmp_path: Path) -> None:
    blueprint_path, manifest_path = await _fixture_files(
        tmp_path, approval=ApprovalStatus.NEEDS_REVIEW
    )
    graph = build_render_graph(
        design_generator=FakeDesignGenerator(),
        layout_refiner=FakeDesignGenerator(),
        image_generator=FakeImageGenerator(),
        visual_reviewer=FakeVisualReviewer(),
        compositor=PillowPosterCompositor(),
        artifact_store=LocalRenderArtifactStore(),
        checkpointer=InMemorySaver(),
    )
    result = cast(
        renderState,
        await graph.ainvoke(
            {
                "workflow_version": "3.0",
                "render_id": "render-2",
                "blueprint_path": str(blueprint_path),
                "asset_manifest_path": str(manifest_path),
                "render_work_dir": str(tmp_path / "renders" / "render-2"),
                "render_config": RenderConfig(),
                "render_attempt": 0,
                "review_errors": [],
            },
            config={"configurable": {"thread_id": "render:render-2"}},
        ),
    )

    assert result["status"] == RenderStatus.FAILED
    assert "approved" in result["review_errors"][0]


async def test_render_keeps_failed_candidate_out_of_final_directory(tmp_path: Path) -> None:
    blueprint_path, manifest_path = await _fixture_files(tmp_path, approval=ApprovalStatus.APPROVED)
    work_dir = tmp_path / "renders" / "render-needs-review"
    graph = build_render_graph(
        design_generator=FakeDesignGenerator(),
        layout_refiner=FakeDesignGenerator(),
        image_generator=FakeImageGenerator(),
        visual_reviewer=FailingVisualReviewer(),
        compositor=PillowPosterCompositor(),
        artifact_store=LocalRenderArtifactStore(),
        checkpointer=InMemorySaver(),
    )
    result = cast(
        renderState,
        await graph.ainvoke(
            {
                "workflow_version": "3.0",
                "render_id": "render-needs-review",
                "blueprint_path": str(blueprint_path),
                "asset_manifest_path": str(manifest_path),
                "render_work_dir": str(work_dir),
                "render_config": RenderConfig(variant_count=1, max_render_attempts=1),
                "render_attempt": 0,
                "review_errors": [],
            },
            config={"configurable": {"thread_id": "render:render-needs-review"}},
        ),
    )

    assert result["status"] == RenderStatus.NEEDS_REVIEW
    assert result["selection"].approval_status == ApprovalStatus.NEEDS_REVIEW
    assert result["final_poster_path"].parent.name == "needs_review"
    assert result["final_poster_path"].is_file()
    assert not (work_dir / "final").exists()


async def test_render_retries_layout_without_regenerating_good_artwork(tmp_path: Path) -> None:
    blueprint_path, manifest_path = await _fixture_files(tmp_path, approval=ApprovalStatus.APPROVED)
    image_generator = FakeImageGenerator()
    reviewer = RetryCompositionReviewer()
    graph = build_render_graph(
        design_generator=FakeDesignGenerator(),
        layout_refiner=FakeDesignGenerator(),
        image_generator=image_generator,
        visual_reviewer=reviewer,
        compositor=PillowPosterCompositor(),
        artifact_store=LocalRenderArtifactStore(),
        checkpointer=InMemorySaver(),
    )
    result = cast(
        renderState,
        await graph.ainvoke(
            {
                "workflow_version": "3.2",
                "render_id": "render-layout-retry",
                "blueprint_path": str(blueprint_path),
                "asset_manifest_path": str(manifest_path),
                "render_work_dir": str(tmp_path / "renders" / "render-layout-retry"),
                "render_config": RenderConfig(
                    variant_count=1,
                    max_render_attempts=2,
                    max_layout_attempts=2,
                ),
                "design_attempt": 0,
                "max_design_attempts": 2,
                "design_generation_metadata": [],
                "render_attempt": 0,
                "layout_attempt": 0,
                "review_errors": [],
            },
            config={"configurable": {"thread_id": "render:render-layout-retry"}},
        ),
    )

    assert result["status"] == RenderStatus.COMPLETED
    assert result["render_attempt"] == 1
    assert result["layout_attempt"] == 2
    assert len(image_generator.requests) == 1
    assert reviewer.review_count == 2


async def test_render_retries_when_every_background_is_contaminated(tmp_path: Path) -> None:
    blueprint_path, manifest_path = await _fixture_files(tmp_path, approval=ApprovalStatus.APPROVED)
    graph = build_render_graph(
        design_generator=FakeDesignGenerator(),
        layout_refiner=RetryLayoutRefiner(),
        image_generator=FakeImageGenerator(),
        visual_reviewer=RetryBackgroundReviewer(),
        compositor=PillowPosterCompositor(),
        artifact_store=LocalRenderArtifactStore(),
        checkpointer=InMemorySaver(),
    )
    result = cast(
        renderState,
        await graph.ainvoke(
            {
                "workflow_version": "3.0",
                "render_id": "render-background-retry",
                "blueprint_path": str(blueprint_path),
                "asset_manifest_path": str(manifest_path),
                "render_work_dir": str(tmp_path / "renders" / "render-background-retry"),
                "render_config": RenderConfig(variant_count=1, max_render_attempts=2),
                "render_attempt": 0,
                "review_errors": [],
            },
            config={"configurable": {"thread_id": "render:render-background-retry"}},
        ),
    )

    assert result["status"] == RenderStatus.COMPLETED
    assert result["render_attempt"] == 2
    assert result["background_qa"][0].passed
    assert result["final_poster_path"].parent.name == "final"


async def test_render_preserves_original_artwork_after_background_attempts_are_exhausted(
    tmp_path: Path,
) -> None:
    blueprint_path, manifest_path = await _fixture_files(tmp_path, approval=ApprovalStatus.APPROVED)
    graph = build_render_graph(
        design_generator=FakeDesignGenerator(),
        layout_refiner=AlwaysFailLayoutRefiner(),
        image_generator=FakeImageGenerator(),
        visual_reviewer=AlwaysFailBackgroundReviewer(),
        compositor=PillowPosterCompositor(),
        artifact_store=LocalRenderArtifactStore(),
        checkpointer=InMemorySaver(),
    )
    result = cast(
        renderState,
        await graph.ainvoke(
            {
                "workflow_version": "3.0",
                "render_id": "render-rejected-artwork",
                "blueprint_path": str(blueprint_path),
                "asset_manifest_path": str(manifest_path),
                "render_work_dir": str(tmp_path / "renders" / "render-rejected-artwork"),
                "render_config": RenderConfig(variant_count=3, max_render_attempts=1),
                "render_attempt": 0,
                "review_errors": [],
            },
            config={"configurable": {"thread_id": "render:render-rejected-artwork"}},
        ),
    )

    assert result["status"] == RenderStatus.NEEDS_REVIEW
    assert all(item.provider == "fake" for item in result["generated_candidates"])
    assert all(item.model == "fake-image" for item in result["generated_candidates"])
    assert all(not report.passed for report in result["background_qa"])
    assert not list((tmp_path / "renders").rglob("*safe-fallback.png"))


async def test_compositor_preserves_generated_artwork_from_legacy_full_canvas_shape(
    tmp_path: Path,
) -> None:
    generated_path = tmp_path / "generated.png"
    logo_path = tmp_path / "logo.png"
    output_path = tmp_path / "composed.png"
    source = Image.new("RGB", (400, 400), (12, 34, 56))
    logo = Image.new("RGBA", (80, 40), (36, 99, 235, 255))
    await asyncio.to_thread(source.save, generated_path, "PNG")
    await asyncio.to_thread(logo.save, logo_path, "PNG")

    concept = DesignConcept(
        concept_id="concept-a",
        territory_id="territory-a",
        creative_thesis="Preserve the generated key visual.",
        artwork_prompt="A complete visual artwork.",
        palette_tokens=["white"],
        layers=[
            SceneLayer(
                layer_id="legacy-opaque-background",
                layer_type="shape",
                bounds=NormalizedBox(x=0.0, y=0.0, width=1.0, height=1.0),
                fill_token="#FF0000",
                opacity=1.0,
                z_index=0,
            ),
            SceneLayer(
                layer_id="headline",
                layer_type="headline",
                bounds=NormalizedBox(x=0.05, y=0.05, width=0.3, height=0.1),
                fill_token="white",
                accent_words=["Hello"],
                accent_fill_token="#FF0000",
                font_size_ratio=0.04,
                max_lines=1,
            ),
            SceneLayer(
                layer_id="cta",
                layer_type="call_to_action",
                bounds=NormalizedBox(x=0.05, y=0.85, width=0.3, height=0.08),
                fill_token="white",
                font_size_ratio=0.03,
                max_lines=1,
            ),
            SceneLayer(
                layer_id="logo",
                layer_type="locked_logo",
                bounds=NormalizedBox(x=0.75, y=0.05, width=0.2, height=0.1),
            ),
        ],
        layout_signature="Copy and logo over generated art.",
        rationale="The generated image remains the key visual.",
    )
    plan = RenderPlan(
        width=400,
        height=400,
        safe_margin=20,
        concepts=[concept],
        diversity=DiversityReport(passed=True, score=100),
        headline="Hello",
        primary_message="",
        call_to_action="Connect",
    )
    generated = GeneratedCandidate(
        candidate_id="variant-a",
        concept_id="concept-a",
        attempt=1,
        prompt="test",
        generated_path=generated_path,
        provider="fake",
        model="fake-image",
    )
    assets = ResolvedAssets(
        logo=ResolvedAsset(
            asset_id="logo",
            asset_type=AssetType.LOGO,
            path=logo_path,
            version="1",
            sha256="test-logo-hash",
        )
    )

    composed = await PillowPosterCompositor().compose(
        generated=generated,
        plan=plan,
        assets=assets,
        output_path=output_path,
    )

    with Image.open(generated_path) as generated_image, Image.open(output_path) as composed_image:
        untouched_box = (140, 140, 260, 260)
        assert (
            composed_image.crop(untouched_box).tobytes()
            == generated_image.crop(untouched_box).tobytes()
        )
        headline_colors = cast(
            list[tuple[int, tuple[int, int, int]]],
            composed_image.crop((20, 20, 140, 70)).convert("RGB").getcolors(maxcolors=6000),
        )
        assert any(
            red > 200 and green < 60 and blue < 60 for _, (red, green, blue) in headline_colors
        )
    assert composed.source_path == generated_path
