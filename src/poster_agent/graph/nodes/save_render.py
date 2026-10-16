"""Persist a reviewed Sprint 3 poster and render manifest."""

from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from poster_agent.domain.enums import ApprovalStatus, RenderStatus
from poster_agent.domain.render import RenderManifest
from poster_agent.graph.sprint3_state import Sprint3State
from poster_agent.persistence.render_store import RenderArtifactStore

GraphNode = Callable[[Sprint3State], Coroutine[Any, Any, Sprint3State]]


def make_save_render_node(store: RenderArtifactStore) -> GraphNode:
    async def save_render(state: Sprint3State) -> Sprint3State:
        selection = state["selection"]
        status = (
            RenderStatus.COMPLETED
            if selection.approval_status == ApprovalStatus.APPROVED
            else RenderStatus.NEEDS_REVIEW
        )
        manifest = RenderManifest(
            render_id=state["render_id"],
            source_thread_id=state["source_thread_id"],
            tenant_id=state["brief"].tenant_id,
            campaign_id=state["brief"].campaign_id,
            brand_id=state["brief"].brand_id,
            status=status,
            selection=selection,
            candidates=state["composed_candidates"],
            reviews=state["all_reviews"],
            render_plan=state["render_plan"],
            final_poster_path=selection.poster_path,
        )
        manifest_path, final_path = await store.save(
            manifest=manifest,
            render_work_dir=Path(state["render_work_dir"]),
        )
        return {
            "render_manifest_path": manifest_path,
            "final_poster_path": final_path,
            "status": status,
        }

    return save_render
