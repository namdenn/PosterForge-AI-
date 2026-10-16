"""Atomic filesystem persistence for Sprint 3 render artifacts."""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from poster_agent.domain.enums import RenderStatus
from poster_agent.domain.errors import PersistenceError
from poster_agent.domain.render import RenderManifest


class RenderArtifactStore(Protocol):
    """Persist a selected poster plus its complete audit manifest."""

    async def save(
        self, *, manifest: RenderManifest, render_work_dir: Path
    ) -> tuple[Path, Path]: ...


class LocalRenderArtifactStore:
    """Finalize a render inside its isolated artifact directory."""

    async def save(self, *, manifest: RenderManifest, render_work_dir: Path) -> tuple[Path, Path]:
        output_dir = render_work_dir / (
            "final" if manifest.status == RenderStatus.COMPLETED else "needs_review"
        )
        output_path = output_dir / "poster.png"
        manifest_path = render_work_dir / "render_manifest.json"
        try:
            await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
            if manifest.selection.poster_path.resolve() != output_path.resolve():
                await asyncio.to_thread(
                    _atomic_copy,
                    manifest.selection.poster_path,
                    output_path,
                )
            persisted = manifest.model_copy(update={"final_poster_path": output_path})
            await asyncio.to_thread(_atomic_write_json, manifest_path, persisted)
        except OSError as exc:
            raise PersistenceError(f"Cannot save Sprint 3 render artifact: {exc}") from exc
        return manifest_path, output_path


def _atomic_copy(source: Path, target: Path) -> None:
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
        shutil.copyfile(source, temporary_name)
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _atomic_write_json(target: Path, manifest: RenderManifest) -> None:
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
            json.dump(manifest.model_dump(mode="json"), temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
