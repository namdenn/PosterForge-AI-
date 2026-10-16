"""Artifact storage port and atomic local-filesystem adapter."""

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Protocol

from poster_agent.domain.blueprint import CreativeBlueprint
from poster_agent.domain.brief import CampaignBrief
from poster_agent.domain.enums import ApprovalStatus, CampaignStatus
from poster_agent.domain.errors import PersistenceError
from poster_agent.domain.strategy import CampaignStrategy
from poster_agent.llm.gateway import GenerationMetadata


class ArtifactStore(Protocol):
    """Boundary used by graph nodes to persist approved outputs."""

    async def save_strategy(
        self,
        *,
        thread_id: str,
        brief: CampaignBrief,
        strategy: CampaignStrategy,
        metadata: GenerationMetadata,
    ) -> Path:
        """Persist one strategy and return its location."""

        ...


class BlueprintArtifactStore(Protocol):
    """Boundary used by Sprint 2 to persist a reviewed creative blueprint."""

    async def save_blueprint(
        self,
        *,
        thread_id: str,
        brief: CampaignBrief,
        blueprint: CreativeBlueprint,
        metadata: list[GenerationMetadata],
    ) -> Path: ...


class LocalArtifactStore:
    """Save JSON atomically under ``root/campaign_id/thread_id``."""

    def __init__(self, root: Path) -> None:
        self._root = root

    async def save_strategy(
        self,
        *,
        thread_id: str,
        brief: CampaignBrief,
        strategy: CampaignStrategy,
        metadata: GenerationMetadata,
    ) -> Path:
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "thread_id": thread_id,
            "brief": brief.model_dump(mode="json"),
            "strategy": strategy.model_dump(mode="json"),
            "generation": metadata.model_dump(mode="json"),
        }
        target = (
            self._root
            / self._safe_component(brief.campaign_id)
            / self._safe_component(thread_id)
            / "strategy.json"
        )
        try:
            await asyncio.to_thread(self._atomic_write_json, target, payload)
        except OSError as exc:
            raise PersistenceError(f"Cannot save artifact to '{target}': {exc}") from exc
        return target

    async def save_blueprint(
        self,
        *,
        thread_id: str,
        brief: CampaignBrief,
        blueprint: CreativeBlueprint,
        metadata: list[GenerationMetadata],
    ) -> Path:
        payload: dict[str, Any] = {
            "schema_version": "2.0",
            "thread_id": thread_id,
            "brief": brief.model_dump(mode="json"),
            "creative_blueprint": blueprint.model_dump(mode="json"),
            "generation": [item.model_dump(mode="json") for item in metadata],
            "status": (
                CampaignStatus.COMPLETED.value
                if blueprint.approval_status == ApprovalStatus.APPROVED
                else CampaignStatus.NEEDS_REVIEW.value
            ),
        }
        target = (
            self._root
            / self._safe_component(brief.campaign_id)
            / self._safe_component(thread_id)
            / "creative_blueprint.json"
        )
        try:
            await asyncio.to_thread(self._atomic_write_json, target, payload)
        except OSError as exc:
            raise PersistenceError(f"Cannot save artifact to '{target}': {exc}") from exc
        return target

    @staticmethod
    def _safe_component(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
        return safe[:100] or "unnamed"

    @staticmethod
    def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.stem}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_name = temporary.name
            os.replace(temporary_name, target)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.unlink(temporary_name)
