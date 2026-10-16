"""Persist a reviewed Sprint 2 creative blueprint."""

from collections.abc import Callable, Coroutine
from typing import Any

from poster_agent.domain.enums import ApprovalStatus, CampaignStatus
from poster_agent.graph.sprint2_state import Sprint2State
from poster_agent.persistence.artifact_store import BlueprintArtifactStore

GraphNode = Callable[[Sprint2State], Coroutine[Any, Any, Sprint2State]]


def make_save_blueprint_node(store: BlueprintArtifactStore) -> GraphNode:
    async def save_blueprint(state: Sprint2State) -> Sprint2State:
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
