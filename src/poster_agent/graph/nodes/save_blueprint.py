"""Persist a reviewed Sprint 2 creative blueprint."""

from collections.abc import Callable, Coroutine
from typing import Any

from poster_agent.domain.enums import ApprovalStatus, CampaignStatus
from poster_agent.graph.rag_state import ragState
from poster_agent.persistence.artifact_store import BlueprintArtifactStore

GraphNode = Callable[[ragState], Coroutine[Any, Any, ragState]]


def make_save_blueprint_node(store: BlueprintArtifactStore) -> GraphNode:
    async def save_blueprint(state: ragState) -> ragState:
        path = await store.save_blueprint(
            thread_id=state["thread_id"],
            brief=state["brief"],
            blueprint=state["blueprint"],
            metadata=state.get("generation_metadata", []),
        )
        status = (
            CampaignStatus.COMPLETED
            if state["blueprint"].approval_status == ApprovalStatus.APPROVED
            else CampaignStatus.NEEDS_REVIEW
        )
        return {"artifact_path": path, "status": status}

    return save_blueprint
