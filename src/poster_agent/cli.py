"""Terminal interface for validating, running, and inspecting campaigns."""

import asyncio
import io
import json
import sys
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import uuid4

import typer
from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from poster_agent.assets.registry import load_asset_manifest, resolve_assets
from poster_agent.config import Settings, get_settings
from poster_agent.domain.blueprint import CreativeBlueprint, ReviewReport
from poster_agent.domain.brand import BrandProfile
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import ApprovalStatus, CampaignStatus, RiskSeverity
from poster_agent.domain.errors import (
    BrandKnowledgeNotFound,
    ConfigurationError,
    PosterAgentError,
)
from poster_agent.domain.render import BlueprintArtifact, RenderConfig, RenderSelection
from poster_agent.graph.rag_builder import build_rag_graph
from poster_agent.graph.rag_state import ragState
from poster_agent.graph.render_builder import build_render_graph
from poster_agent.graph.render_state import renderState
from poster_agent.llm.embedding_gateway import OpenAIEmbeddingGateway
from poster_agent.llm.openai_creative_gateway import OpenAICreativeGenerator
from poster_agent.llm.openai_design_gateway import OpenAIDesignGenerator
from poster_agent.llm.openai_image_gateway import OpenAIImageGenerator, OpenAIVisualReviewer
from poster_agent.observability.logging import configure_logging
from poster_agent.persistence.artifact_store import LocalArtifactStore
from poster_agent.persistence.checkpointer import sqlite_checkpointer
from poster_agent.persistence.render_store import LocalRenderArtifactStore
from poster_agent.rag.ingestion import (
    IngestionReport,
    LocalBrandIngestor,
    discover_brand_documents,
)
from poster_agent.rag.retrieval import SemanticBrandRetriever
from poster_agent.rag.store import SQLiteBrandKnowledgeStore
from poster_agent.rendering.compositor import PillowPosterCompositor


def _enable_utf8_console() -> None:
    """Make Vietnamese output reliable on legacy Windows code pages."""

    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


_enable_utf8_console()
app = typer.Typer(help="Poster Agent backend CLI.", no_args_is_help=True)
brief_app = typer.Typer(help="Validate campaign brief files.")
campaign_app = typer.Typer(help="Run and inspect the Sprint 2 campaign graph.")
brand_app = typer.Typer(help="Ingest and inspect tenant-scoped brand knowledge.")
render_app = typer.Typer(help="Render and inspect Sprint 3 poster workflows.")
app.add_typer(brief_app, name="brief")
app.add_typer(campaign_app, name="campaign")
app.add_typer(brand_app, name="brand")
app.add_typer(render_app, name="render")
console = Console()


def _load_json(path: Path) -> dict[str, Any]:
    decoded: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("JSON root must be an object")
    return decoded


@app.command()
def doctor() -> None:
    """Check local configuration without displaying secrets or calling OpenAI."""

    settings = get_settings()
    table = Table(title="Poster Agent environment")
    table.add_column("Check")
    table.add_column("Status")
    key_status = "configured" if settings.openai_api_key.get_secret_value() else "missing"
    table.add_row("OpenAI API key", key_status)
    table.add_row("OpenAI model", "configured" if settings.openai_model else "missing")
    table.add_row("Embedding model", settings.openai_embedding_model)
    table.add_row("Image model", settings.openai_image_model)
    table.add_row("Checkpoint database", str(settings.checkpoint_db_path))
    table.add_row("Brand knowledge database", str(settings.brand_knowledge_db_path))
    table.add_row("Artifact directory", str(settings.artifacts_dir))
    table.add_row("Environment", settings.app_env)
    console.print(table)


@brief_app.command("validate")
def validate_brief_file(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Validate a JSON brief without calling OpenAI."""

    try:
        brief = CampaignBrief.model_validate(_load_json(path))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        console.print(f"[red]Invalid brief:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Valid brief[/green]: {brief.campaign_id} — {brief.campaign_name}")


async def _run_campaign(
    *, brief_path: Path, thread_id: str, max_attempts: int, settings: Settings
) -> dict[str, Any]:
    settings.require_openai()
    settings.prepare_local_directories()
    generator = OpenAICreativeGenerator(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    embedder = OpenAIEmbeddingGateway(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_embedding_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    knowledge_store = SQLiteBrandKnowledgeStore(settings.brand_knowledge_db_path)
    await knowledge_store.setup()
    try:
        preflight_brief = CampaignBrief.model_validate(_load_json(brief_path))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ValidationError):
        preflight_brief = None
    if preflight_brief is not None:
        profile = await knowledge_store.get_profile(
            tenant_id=preflight_brief.tenant_id,
            brand_id=preflight_brief.brand_id,
        )
        if profile is None:
            raise BrandKnowledgeNotFound(
                "Brand knowledge is missing. Run 'poster-agent brand ingest' before campaign run."
            )
    retriever = SemanticBrandRetriever(store=knowledge_store, embedder=embedder)
    artifact_store = LocalArtifactStore(settings.artifacts_dir)
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        graph = build_rag_graph(
            generator=generator,
            retriever=retriever,
            knowledge_store=knowledge_store,
            artifact_store=artifact_store,
            checkpointer=checkpointer,
            top_k=settings.rag_top_k,
        )
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        if await checkpointer.aget_tuple(config) is not None:
            raise ConfigurationError(
                f"Thread '{thread_id}' already exists. Use campaign resume or choose a new ID."
            )
        initial: ragState = {
            "workflow_version": "2.0",
            "thread_id": thread_id,
            "brief_path": str(brief_path),
            "concept_attempt": 0,
            "max_concept_attempts": max_attempts,
            "generation_metadata": [],
        }
        async for update in graph.astream(initial, config=config, stream_mode="updates"):
            node_name = next(iter(update), "unknown")
            console.print(f"[cyan]✓[/cyan] {node_name}")
        snapshot = await graph.aget_state(config)
        return cast(dict[str, Any], snapshot.values)


@campaign_app.command("run")
def run_campaign(
    brief_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    thread_id: Annotated[str | None, typer.Option(help="Stable checkpoint thread ID.")] = None,
    max_attempts: Annotated[
        int, typer.Option(min=1, max=5, help="Maximum strategy generations.")
    ] = 2,
) -> None:
    """Run the Sprint 2 RAG and multi-parallel campaign workflow."""

    settings = get_settings()
    configure_logging(settings.log_level)
    actual_thread_id = thread_id or str(uuid4())
    console.print(f"Thread: [bold]{actual_thread_id}[/bold]")
    try:
        result = asyncio.run(
            _run_campaign(
                brief_path=brief_path,
                thread_id=actual_thread_id,
                max_attempts=max_attempts,
                settings=settings,
            )
        )
    except (PosterAgentError, OSError) as exc:
        console.print(f"[red]Run failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    status = result.get("status", "unknown")
    console.print(f"Status: [bold]{status}[/bold]")
    if errors := result.get("validation_errors") or result.get("review_errors"):
        for error in errors:
            console.print(f"[yellow]- {error}[/yellow]")
    if artifact_path := result.get("artifact_path"):
        console.print(f"Artifact: [green]{artifact_path}[/green]")


async def _inspect_campaign(thread_id: str, settings: Settings) -> dict[str, Any] | None:
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        checkpoint = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
        if checkpoint is None:
            return None
        values = checkpoint.checkpoint.get("channel_values", {})
        return values


async def _resume_campaign(thread_id: str, settings: Settings) -> dict[str, Any] | None:
    settings.require_openai()
    settings.prepare_local_directories()
    generator = OpenAICreativeGenerator(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    embedder = OpenAIEmbeddingGateway(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_embedding_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    knowledge_store = SQLiteBrandKnowledgeStore(settings.brand_knowledge_db_path)
    await knowledge_store.setup()
    retriever = SemanticBrandRetriever(store=knowledge_store, embedder=embedder)
    artifact_store = LocalArtifactStore(settings.artifacts_dir)
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        existing = await checkpointer.aget_tuple(config)
        if existing is None:
            return None
        values = existing.checkpoint.get("channel_values", {})
        if values.get("workflow_version") != "2.0":
            raise ConfigurationError(
                "This checkpoint was created by another workflow version and cannot be resumed."
            )
        graph = build_rag_graph(
            generator=generator,
            retriever=retriever,
            knowledge_store=knowledge_store,
            artifact_store=artifact_store,
            checkpointer=checkpointer,
            top_k=settings.rag_top_k,
        )
        async for update in graph.astream(None, config=config, stream_mode="updates"):
            node_name = next(iter(update), "unknown")
            console.print(f"[cyan]✓[/cyan] {node_name}")
        snapshot = await graph.aget_state(config)
        return cast(dict[str, Any], snapshot.values)


@campaign_app.command("inspect")
def inspect_campaign(thread_id: Annotated[str, typer.Argument()]) -> None:
    """Inspect the latest durable state for a thread without calling OpenAI."""

    settings = get_settings()
    values = asyncio.run(_inspect_campaign(thread_id, settings))
    if values is None:
        console.print(f"[yellow]No checkpoint found for thread {thread_id}.[/yellow]")
        raise typer.Exit(code=1)
    console.print_json(json=json.dumps(values, ensure_ascii=False, default=str))


@campaign_app.command("resume")
def resume_campaign(thread_id: Annotated[str, typer.Argument()]) -> None:
    """Continue a previously interrupted thread from its latest checkpoint."""

    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        values = asyncio.run(_resume_campaign(thread_id, settings))
    except (PosterAgentError, OSError) as exc:
        console.print(f"[red]Resume failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if values is None:
        console.print(f"[yellow]No checkpoint found for thread {thread_id}.[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"Status: [bold]{values.get('status', 'unknown')}[/bold]")
    if artifact_path := values.get("artifact_path"):
        console.print(f"Artifact: [green]{artifact_path}[/green]")


async def _approve_campaign(
    *, thread_id: str, reason: str, settings: Settings
) -> dict[str, Any] | None:
    settings.require_openai()
    settings.prepare_local_directories()
    generator = OpenAICreativeGenerator(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    embedder = OpenAIEmbeddingGateway(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_embedding_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    knowledge_store = SQLiteBrandKnowledgeStore(settings.brand_knowledge_db_path)
    await knowledge_store.setup()
    graph_config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        graph = build_rag_graph(
            generator=generator,
            retriever=SemanticBrandRetriever(store=knowledge_store, embedder=embedder),
            knowledge_store=knowledge_store,
            artifact_store=LocalArtifactStore(settings.artifacts_dir),
            checkpointer=checkpointer,
            top_k=settings.rag_top_k,
        )
        snapshot = await graph.aget_state(graph_config)
        values = cast(dict[str, Any], snapshot.values)
        if not values:
            return None
        if values.get("workflow_version") != "2.0":
            raise ConfigurationError("Only Sprint 2 checkpoints support human approval.")
        blueprint = values.get("blueprint")
        if not isinstance(blueprint, CreativeBlueprint):
            raise ConfigurationError("This thread has no creative blueprint to approve.")
        human_report = ReviewReport(
            reviewer="human_approver",
            passed=True,
            severity=RiskSeverity.LOW,
            recommendations=[reason],
        )
        approved = blueprint.model_copy(
            update={
                "approval_status": ApprovalStatus.APPROVED,
                "reviews": [*blueprint.reviews, human_report],
            }
        )
        await graph.aupdate_state(
            graph_config,
            {
                "blueprint": approved,
                "review_errors": [],
                "status": CampaignStatus.RUNNING,
            },
            as_node="review_join",
        )
        await graph.ainvoke(None, config=graph_config)
        final_snapshot = await graph.aget_state(graph_config)
        return cast(dict[str, Any], final_snapshot.values)


@campaign_app.command("approve")
def approve_campaign(
    thread_id: Annotated[str, typer.Argument()],
    reason: Annotated[
        str, typer.Option("--reason", help="Audit note explaining the human approval.")
    ],
) -> None:
    """Approve a needs-review blueprint and persist the final artifact."""

    settings = get_settings()
    try:
        values = asyncio.run(
            _approve_campaign(thread_id=thread_id, reason=reason, settings=settings)
        )
    except (PosterAgentError, OSError, ValueError) as exc:
        console.print(f"[red]Approval failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if values is None:
        console.print(f"[yellow]No checkpoint found for thread {thread_id}.[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"Status: [bold]{values.get('status', 'unknown')}[/bold]")
    if artifact_path := values.get("artifact_path"):
        console.print(f"Artifact: [green]{artifact_path}[/green]")


async def _ingest_brand(
    *,
    source: Path,
    tenant_id: str,
    brand_id: str,
    brand_name: str,
    settings: Settings,
) -> tuple[list[IngestionReport], BrandProfile]:
    settings.require_openai()
    settings.prepare_local_directories()
    embedder = OpenAIEmbeddingGateway(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_embedding_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    knowledge_store = SQLiteBrandKnowledgeStore(settings.brand_knowledge_db_path)
    await knowledge_store.setup()
    ingestor = LocalBrandIngestor(
        store=knowledge_store,
        embedder=embedder,
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
    )
    documents = await discover_brand_documents(
        source,
        tenant_id=tenant_id,
        brand_id=brand_id,
    )
    reports = []
    for document in documents:
        reports.append(await ingestor.ingest(document))

    retriever = SemanticBrandRetriever(store=knowledge_store, embedder=embedder)
    evidence = await retriever.retrieve(
        tenant_id=tenant_id,
        brand_id=brand_id,
        query=(
            "brand personality tone of voice visual identity color rules product claims "
            "target audience and prohibited marketing claims"
        ),
        limit=max(settings.rag_top_k * 3, 12),
    )
    profile_builder = OpenAICreativeGenerator(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    profile = await profile_builder.build(
        tenant_id=tenant_id,
        brand_id=brand_id,
        brand_name=brand_name,
        evidence=evidence,
    )
    await knowledge_store.save_profile(profile)
    return reports, profile


@brand_app.command("ingest")
def ingest_brand(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    tenant_id: Annotated[str, typer.Option("--tenant-id")],
    brand_id: Annotated[str, typer.Option("--brand-id")],
    brand_name: Annotated[str, typer.Option("--brand-name")],
) -> None:
    """Index brand documents and build an evidence-backed BrandProfile."""

    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        reports, profile = asyncio.run(
            _ingest_brand(
                source=source,
                tenant_id=tenant_id,
                brand_id=brand_id,
                brand_name=brand_name,
                settings=settings,
            )
        )
    except (PosterAgentError, OSError, ValueError) as exc:
        console.print(f"[red]Ingestion failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    chunk_count = sum(report.chunks_indexed for report in reports)
    console.print(
        f"[green]Indexed[/green] {len(reports)} documents / {chunk_count} chunks for "
        f"{profile.tenant_id}/{profile.brand_id}"
    )
    console.print("Brand profile created and ready for campaign generation.")


async def _inspect_brand(
    *, tenant_id: str, brand_id: str, settings: Settings
) -> tuple[int, BrandProfile | None]:
    store = SQLiteBrandKnowledgeStore(settings.brand_knowledge_db_path)
    await store.setup()
    count = await store.count_chunks(tenant_id=tenant_id, brand_id=brand_id)
    profile = await store.get_profile(tenant_id=tenant_id, brand_id=brand_id)
    return count, profile


@brand_app.command("inspect")
def inspect_brand(
    tenant_id: Annotated[str, typer.Option("--tenant-id")],
    brand_id: Annotated[str, typer.Option("--brand-id")],
) -> None:
    """Inspect indexed chunk count and BrandProfile without calling OpenAI."""

    count, profile = asyncio.run(
        _inspect_brand(tenant_id=tenant_id, brand_id=brand_id, settings=get_settings())
    )
    if profile is None:
        console.print(f"[yellow]No profile found. Indexed chunks: {count}[/yellow]")
        raise typer.Exit(code=1)
    console.print(f"Indexed chunks: {count}")
    console.print_json(json=profile.model_dump_json(indent=2))


def _render_checkpoint_id(render_id: str) -> str:
    return f"render:{render_id}"


def _build_render_graph(*, settings: Settings, checkpointer: Any) -> Any:
    api_key = settings.openai_api_key.get_secret_value()
    design_generator = OpenAIDesignGenerator(
        api_key=api_key,
        model=settings.openai_model,
        timeout_seconds=max(settings.openai_timeout_seconds, 120.0),
    )
    return build_render_graph(
        design_generator=design_generator,
        layout_refiner=design_generator,
        image_generator=OpenAIImageGenerator(
            api_key=api_key,
            model=settings.openai_image_model,
            timeout_seconds=max(settings.openai_timeout_seconds, 120.0),
        ),
        visual_reviewer=OpenAIVisualReviewer(
            api_key=api_key,
            model=settings.openai_model,
            timeout_seconds=max(settings.openai_timeout_seconds, 120.0),
        ),
        compositor=PillowPosterCompositor(),
        artifact_store=LocalRenderArtifactStore(),
        checkpointer=checkpointer,
    )


async def _validate_render_inputs(
    *, blueprint_path: Path, asset_manifest_path: Path
) -> tuple[BlueprintArtifact, int]:
    try:
        artifact = BlueprintArtifact.model_validate(_load_json(blueprint_path))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise ConfigurationError(f"Invalid Sprint 2 blueprint artifact: {exc}") from exc
    if artifact.schema_version != "2.0":
        raise ConfigurationError("Sprint 3 requires a schema_version 2.0 blueprint artifact.")
    if artifact.creative_blueprint.approval_status != ApprovalStatus.APPROVED:
        raise ConfigurationError("Sprint 3 only renders an approved CreativeBlueprint.")
    manifest = await load_asset_manifest(asset_manifest_path)
    assets = await resolve_assets(
        manifest,
        manifest_path=asset_manifest_path,
        tenant_id=artifact.brief.tenant_id,
        brand_id=artifact.brief.brand_id,
        channel=artifact.brief.channel,
    )
    product_count = 1 if assets.product is not None else 0
    return artifact, 1 + product_count + len(assets.fonts) + len(assets.references)


@render_app.command("validate")
def validate_render_inputs(
    blueprint_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    assets: Annotated[
        Path,
        typer.Option("--assets", exists=True, dir_okay=False, readable=True),
    ],
) -> None:
    """Validate an approved blueprint and exact visual assets without calling OpenAI."""

    try:
        artifact, asset_count = asyncio.run(
            _validate_render_inputs(
                blueprint_path=blueprint_path,
                asset_manifest_path=assets,
            )
        )
    except (PosterAgentError, OSError, ValueError) as exc:
        console.print(f"[red]Render input validation failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"[green]Ready[/green]: {artifact.brief.campaign_id} — "
        f"{artifact.brief.tenant_id}/{artifact.brief.brand_id}; {asset_count} assets resolved."
    )


async def _run_render(
    *,
    blueprint_path: Path,
    asset_manifest_path: Path,
    render_id: str,
    render_config: RenderConfig,
    settings: Settings,
) -> dict[str, Any]:
    settings.require_image_openai()
    settings.prepare_local_directories()
    resolved_blueprint, resolved_manifest = await asyncio.gather(
        asyncio.to_thread(blueprint_path.resolve),
        asyncio.to_thread(asset_manifest_path.resolve),
    )
    work_dir = resolved_blueprint.parent / "renders" / render_id
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        graph = _build_render_graph(settings=settings, checkpointer=checkpointer)
        config: RunnableConfig = {"configurable": {"thread_id": _render_checkpoint_id(render_id)}}
        if await checkpointer.aget_tuple(config) is not None:
            raise ConfigurationError(
                f"Render '{render_id}' already exists. Use render resume or choose a new ID."
            )
        initial: renderState = {
            "workflow_version": "3.2",
            "render_id": render_id,
            "blueprint_path": str(resolved_blueprint),
            "asset_manifest_path": str(resolved_manifest),
            "render_work_dir": str(work_dir),
            "render_config": render_config,
            "design_attempt": 0,
            "max_design_attempts": 2,
            "design_generation_metadata": [],
            "render_attempt": 0,
            "layout_attempt": 0,
            "review_errors": [],
        }
        async for update in graph.astream(initial, config=config, stream_mode="updates"):
            node_name = next(iter(update), "unknown")
            console.print(f"[cyan]✓[/cyan] {node_name}")
        snapshot = await graph.aget_state(config)
        return cast(dict[str, Any], snapshot.values)


@render_app.command("run")
def run_render(
    blueprint_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    assets: Annotated[
        Path,
        typer.Option("--assets", exists=True, dir_okay=False, readable=True),
    ],
    render_id: Annotated[str | None, typer.Option(help="Stable Sprint 3 render ID.")] = None,
    variants: Annotated[int | None, typer.Option(min=1, max=3)] = None,
    max_attempts: Annotated[int | None, typer.Option(min=1, max=3)] = None,
) -> None:
    """Render an approved Sprint 2 blueprint into reviewed poster candidates."""

    settings = get_settings()
    configure_logging(settings.log_level)
    actual_render_id = render_id or str(uuid4())
    console.print(f"Render: [bold]{actual_render_id}[/bold]")
    try:
        config = RenderConfig.model_validate(
            {
                "generation_size": settings.poster_generation_size,
                "generation_quality": settings.poster_generation_quality,
                "variant_count": variants or settings.poster_variant_count,
                "max_render_attempts": max_attempts or settings.poster_max_render_attempts,
                "qa_threshold": settings.poster_qa_threshold,
            }
        )
        result = asyncio.run(
            _run_render(
                blueprint_path=blueprint_path,
                asset_manifest_path=assets,
                render_id=actual_render_id,
                render_config=config,
                settings=settings,
            )
        )
    except (PosterAgentError, OSError, ValueError) as exc:
        console.print(f"[red]Render failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    _print_render_result(result)


async def _inspect_render(render_id: str, settings: Settings) -> dict[str, Any] | None:
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        checkpoint = await checkpointer.aget_tuple(
            {"configurable": {"thread_id": _render_checkpoint_id(render_id)}}
        )
        if checkpoint is None:
            return None
        return checkpoint.checkpoint.get("channel_values", {})


@render_app.command("inspect")
def inspect_render(render_id: Annotated[str, typer.Argument()]) -> None:
    """Inspect a Sprint 3 checkpoint without calling OpenAI."""

    values = asyncio.run(_inspect_render(render_id, get_settings()))
    if values is None:
        console.print(f"[yellow]No render checkpoint found for {render_id}.[/yellow]")
        raise typer.Exit(code=1)
    console.print_json(json=json.dumps(values, ensure_ascii=False, default=str))


async def _resume_render(render_id: str, settings: Settings) -> dict[str, Any] | None:
    settings.require_image_openai()
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        config: RunnableConfig = {"configurable": {"thread_id": _render_checkpoint_id(render_id)}}
        existing = await checkpointer.aget_tuple(config)
        if existing is None:
            return None
        values = existing.checkpoint.get("channel_values", {})
        if values.get("workflow_version") != "3.2":
            raise ConfigurationError(
                "This checkpoint predates the image-aware Sprint 3.6 layout workflow. "
                "Start a new render ID."
            )
        graph = _build_render_graph(settings=settings, checkpointer=checkpointer)
        async for update in graph.astream(None, config=config, stream_mode="updates"):
            node_name = next(iter(update), "unknown")
            console.print(f"[cyan]✓[/cyan] {node_name}")
        snapshot = await graph.aget_state(config)
        return cast(dict[str, Any], snapshot.values)


@render_app.command("resume")
def resume_render(render_id: Annotated[str, typer.Argument()]) -> None:
    """Continue an interrupted Sprint 3 render from its latest checkpoint."""

    settings = get_settings()
    try:
        values = asyncio.run(_resume_render(render_id, settings))
    except (PosterAgentError, OSError, ValueError) as exc:
        console.print(f"[red]Render resume failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if values is None:
        console.print(f"[yellow]No render checkpoint found for {render_id}.[/yellow]")
        raise typer.Exit(code=1)
    _print_render_result(values)


async def _approve_render(
    *, render_id: str, candidate_id: str | None, reason: str, settings: Settings
) -> dict[str, Any] | None:
    settings.require_image_openai()
    async with sqlite_checkpointer(settings.checkpoint_db_path) as checkpointer:
        config: RunnableConfig = {"configurable": {"thread_id": _render_checkpoint_id(render_id)}}
        graph = _build_render_graph(settings=settings, checkpointer=checkpointer)
        snapshot = await graph.aget_state(config)
        values = cast(dict[str, Any], snapshot.values)
        if not values:
            return None
        if values.get("workflow_version") not in {"3.0", "3.1", "3.2"}:
            raise ConfigurationError("Only Sprint 3 checkpoints support render approval.")
        selection = values.get("selection")
        if not isinstance(selection, RenderSelection):
            raise ConfigurationError("This render has no selected poster candidate.")
        selected = selection
        if candidate_id is not None:
            candidates = values.get("composed_candidates", [])
            candidate = next(
                (item for item in candidates if item.candidate_id == candidate_id),
                None,
            )
            if candidate is None:
                available = ", ".join(item.candidate_id for item in candidates)
                raise ConfigurationError(
                    f"Unknown candidate '{candidate_id}'. Available: {available or 'none'}."
                )
            reports = [
                item for item in values.get("all_reviews", []) if item.candidate_id == candidate_id
            ]
            score = (
                sum(item.score for item in reports) / len(reports) if reports else selection.score
            )
            selected = RenderSelection(
                candidate_id=candidate.candidate_id,
                poster_path=candidate.poster_path,
                score=score,
                approval_status=selection.approval_status,
            )
        approved = selected.model_copy(
            update={"approval_status": ApprovalStatus.APPROVED, "human_reason": reason}
        )
        await graph.aupdate_state(
            config,
            {"selection": approved, "review_errors": []},
            as_node="join_quality_reviews",
        )
        await graph.ainvoke(None, config=config)
        final = await graph.aget_state(config)
        return cast(dict[str, Any], final.values)


@render_app.command("approve")
def approve_render(
    render_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option("--reason")],
    candidate: Annotated[
        str | None,
        typer.Option("--candidate", help="Optional variant-a, variant-b, or variant-c."),
    ] = None,
) -> None:
    """Approve a chosen needs-review poster and finalize it."""

    try:
        values = asyncio.run(
            _approve_render(
                render_id=render_id,
                candidate_id=candidate,
                reason=reason,
                settings=get_settings(),
            )
        )
    except (PosterAgentError, OSError, ValueError) as exc:
        console.print(f"[red]Render approval failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    if values is None:
        console.print(f"[yellow]No render checkpoint found for {render_id}.[/yellow]")
        raise typer.Exit(code=1)
    _print_render_result(values)


def _print_render_result(result: dict[str, Any]) -> None:
    console.print(f"Status: [bold]{result.get('status', 'unknown')}[/bold]")
    for error in result.get("review_errors", []):
        console.print(f"[yellow]- {error}[/yellow]")
    if poster_path := result.get("final_poster_path"):
        console.print(f"Poster: [green]{poster_path}[/green]")
    if manifest_path := result.get("render_manifest_path"):
        console.print(f"Manifest: [green]{manifest_path}[/green]")


def main() -> None:
    """Console-script entry point."""

    app()


if __name__ == "__main__":
    main()
