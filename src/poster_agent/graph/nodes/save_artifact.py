"""Persist an approved strategy through an injected storage port."""

from collections.abc import Callable, Coroutine
from typing import Any

from poster_agent.domain.enums import CampaignStatus
from poster_agent.graph.state import CampaignState
from poster_agent.persistence.artifact_store import ArtifactStore

GraphNode = Callable[[CampaignState], Coroutine[Any, Any, CampaignState]]


def make_save_artifact_node(store: ArtifactStore) -> GraphNode:
    """Bind an artifact store to a graph node."""

    async def save_artifact(state: CampaignState) -> CampaignState:
        path = await store.save_strategy(
            thread_id=state["thread_id"],
            brief=state["brief"],
            strategy=state["strategy"],
            metadata=state["generation_metadata"],
        )
        return {"artifact_path": path, "status": CampaignStatus.COMPLETED}

    return save_artifact
