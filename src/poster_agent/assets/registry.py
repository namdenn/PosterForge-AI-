"""Local, exact-match asset registry for brand-safe poster composition."""

import asyncio
import hashlib
from pathlib import Path

from pydantic import ValidationError

from poster_agent.domain.enums import ApprovalStatus, AssetType, MarketingChannel
from poster_agent.domain.errors import AssetValidationError
from poster_agent.domain.render import (
    AssetManifest,
    AssetRecord,
    ResolvedAsset,
    ResolvedAssets,
)


async def load_asset_manifest(path: Path) -> AssetManifest:
    """Read and validate one asset manifest without calling an external service."""

    try:
        raw = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return AssetManifest.model_validate_json(raw)
    except (OSError, UnicodeError, ValidationError) as exc:
        raise AssetValidationError(f"Cannot load asset manifest '{path}': {exc}") from exc


async def resolve_assets(
    manifest: AssetManifest,
    *,
    manifest_path: Path,
    tenant_id: str,
    brand_id: str,
    channel: MarketingChannel,
) -> ResolvedAssets:
    """Resolve one unambiguous logo/product pair inside the requested scope."""

    if manifest.tenant_id != tenant_id or manifest.brand_id != brand_id:
        raise AssetValidationError(
            "Asset manifest scope does not match the blueprint tenant_id and brand_id."
        )

    eligible = [
        item
        for item in manifest.assets
        if item.approval_status == ApprovalStatus.APPROVED
        and (not item.allowed_channels or channel in item.allowed_channels)
    ]
    logos = [item for item in eligible if item.asset_type == AssetType.LOGO]
    products = [item for item in eligible if item.asset_type == AssetType.PRODUCT]
    if len(logos) != 1:
        raise AssetValidationError(
            f"Expected exactly one approved logo for channel '{channel}', found {len(logos)}."
        )
    if len(products) > 1:
        raise AssetValidationError(
            f"Expected at most one approved product image for channel '{channel}', "
            f"found {len(products)}."
        )

    root = await asyncio.to_thread(lambda: manifest_path.resolve().parent)
    resolved = [await _resolve_record(item, root=root) for item in eligible]
    logo = next(item for item in resolved if item.asset_type == AssetType.LOGO)
    product = next((item for item in resolved if item.asset_type == AssetType.PRODUCT), None)
    return ResolvedAssets(
        logo=logo,
        product=product,
        fonts=[item for item in resolved if item.asset_type == AssetType.FONT],
        references=[item for item in resolved if item.asset_type == AssetType.REFERENCE],
        brand_tokens=manifest.brand_tokens,
    )


async def _resolve_record(record: AssetRecord, *, root: Path) -> ResolvedAsset:
    path = (root / record.path).resolve()
    if not path.is_relative_to(root):
        raise AssetValidationError(f"Asset '{record.asset_id}' escapes the manifest directory.")
    if not path.is_file():
        raise AssetValidationError(f"Asset '{record.asset_id}' does not exist: {path}")
    digest = await asyncio.to_thread(_sha256, path)
    return ResolvedAsset(
        asset_id=record.asset_id,
        asset_type=record.asset_type,
        path=path,
        version=record.version,
        sha256=digest,
        description=record.description,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
