"""Generic Scene Graph renderer with locked brand-asset composition."""

import asyncio
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageDraw, ImageFont, ImageOps

from poster_agent.domain.errors import RenderError
from poster_agent.domain.render import (
    ComposedCandidate,
    DesignConcept,
    GeneratedCandidate,
    NormalizedBox,
    RenderPlan,
    ResolvedAssets,
    SceneLayer,
)


class PosterCompositor(Protocol):
    """Render an agent-authored scene graph using trusted copy and brand assets."""

    async def compose(
        self,
        *,
        generated: GeneratedCandidate,
        plan: RenderPlan,
        assets: ResolvedAssets,
        output_path: Path,
    ) -> ComposedCandidate: ...


class PillowPosterCompositor:
    """Overlay trusted copy and assets while preserving the generated key visual."""

    async def compose(
        self,
        *,
        generated: GeneratedCandidate,
        plan: RenderPlan,
        assets: ResolvedAssets,
        output_path: Path,
    ) -> ComposedCandidate:
        concept = _concept_for(generated, plan)
        await asyncio.to_thread(
            self._compose_sync,
            generated,
            plan,
            concept,
            assets,
            output_path,
        )
        asset_ids = [assets.logo.asset_id]
        hashes = {assets.logo.asset_id: assets.logo.sha256}
        if any(item.layer_type == "approved_product" for item in concept.layers):
            if assets.product is None:
                raise RenderError("Scene Graph requested an approved product asset that is absent.")
            asset_ids.append(assets.product.asset_id)
            hashes[assets.product.asset_id] = assets.product.sha256
        return ComposedCandidate(
            candidate_id=generated.candidate_id,
            concept_id=concept.concept_id,
            attempt=generated.attempt,
            source_path=generated.generated_path,
            poster_path=output_path,
            width=plan.width,
            height=plan.height,
            rendered_text=_rendered_text(plan, concept),
            asset_ids=asset_ids,
            locked_asset_hashes=hashes,
            layout_signature=concept.layout_signature,
        )

    def _compose_sync(
        self,
        generated: GeneratedCandidate,
        plan: RenderPlan,
        concept: DesignConcept,
        assets: ResolvedAssets,
        output_path: Path,
    ) -> None:
        with Image.open(generated.generated_path) as raw_artwork:
            canvas = ImageOps.fit(
                ImageOps.exif_transpose(raw_artwork).convert("RGB"),
                (plan.width, plan.height),
                method=Image.Resampling.LANCZOS,
            ).convert("RGBA")

        logo_layers: list[SceneLayer] = []
        for layer in sorted(concept.layers, key=lambda item: (item.z_index, item.layer_id)):
            if layer.layer_type == "locked_logo":
                logo_layers.append(layer)
                continue
            if layer.layer_type == "shape":
                # Generated artwork is the single source of truth for illustration, UI,
                # objects, surfaces, and decorative geometry. Older checkpoints may still
                # contain shape layers, so keep them schema-compatible but never let them
                # repaint or conceal the generated key visual during composition.
                continue
            elif layer.layer_type == "approved_product":
                if assets.product is None:
                    raise RenderError(
                        "Scene Graph requested an approved product asset that is absent."
                    )
                self._place_asset(canvas, assets.product.path, _pixel_box(layer.bounds, plan))
            else:
                self._draw_copy(canvas, layer, concept=concept, plan=plan, assets=assets)

        # The approved source logo is always the final layer and cannot be covered or regenerated.
        for layer in logo_layers:
            self._place_asset(canvas, assets.logo.path, _pixel_box(layer.bounds, plan))
        _atomic_save_png(canvas.convert("RGB"), output_path)

    @classmethod
    def _draw_copy(
        cls,
        canvas: Image.Image,
        layer: SceneLayer,
        *,
        concept: DesignConcept,
        plan: RenderPlan,
        assets: ResolvedAssets,
    ) -> None:
        text = _text_for_layer(layer, concept=concept, plan=plan)
        if text is None:
            return
        text = _transform_text(text, layer.text_transform)
        draw = ImageDraw.Draw(canvas)
        box = _pixel_box(layer.bounds, plan)
        padding = round(plan.width * layer.padding_ratio)
        inner = (
            box[0] + padding,
            box[1] + padding,
            box[2] - padding,
            box[3] - padding,
        )
        if inner[2] <= inner[0] or inner[3] <= inner[1]:
            raise RenderError(f"Layer '{layer.layer_id}' has no room after padding.")
        font_path = _font_path(assets, layer=layer)
        requested = max(8, round(plan.width * layer.font_size_ratio))
        minimum = max(8, min(requested, round(plan.width * 0.014)))
        _draw_fitted_text(
            draw,
            text,
            inner,
            font_path=font_path,
            max_size=requested,
            min_size=minimum,
            max_lines=layer.max_lines,
            fill=_resolve_text_color(layer.fill_token, plan),
            accent_fill=(
                _resolve_text_color(layer.accent_fill_token, plan)
                if layer.accent_fill_token
                else None
            ),
            accent_words=layer.accent_words,
            align=layer.text_align,
            vertical_align=layer.vertical_align,
            line_spacing_ratio=layer.line_spacing_ratio,
        )

    @staticmethod
    def _place_asset(
        canvas: Image.Image,
        path: Path,
        box: tuple[int, int, int, int],
    ) -> None:
        left, top, right, bottom = box
        with Image.open(path) as raw_asset:
            asset = ImageOps.exif_transpose(raw_asset).convert("RGBA")
            asset.thumbnail((right - left, bottom - top), Image.Resampling.LANCZOS)
            x = left + ((right - left - asset.width) // 2)
            y = top + ((bottom - top - asset.height) // 2)
            canvas.alpha_composite(asset, (x, y))


def _concept_for(generated: GeneratedCandidate, plan: RenderPlan) -> DesignConcept:
    for concept in plan.concepts:
        if concept.concept_id == generated.concept_id:
            return concept
    raise RenderError(f"No design concept found for '{generated.candidate_id}'.")


def _rendered_text(plan: RenderPlan, concept: DesignConcept) -> list[str]:
    layer_types = {item.layer_type for item in concept.layers}
    values = [plan.headline]
    if "primary_message" in layer_types:
        values.append(plan.primary_message)
    values.extend(concept.selected_support_messages)
    values.append(plan.call_to_action)
    return values


def _text_for_layer(layer: SceneLayer, *, concept: DesignConcept, plan: RenderPlan) -> str | None:
    if layer.layer_type == "headline":
        return plan.headline
    if layer.layer_type == "primary_message":
        return plan.primary_message
    if layer.layer_type == "call_to_action":
        return plan.call_to_action
    if layer.layer_type == "support_message":
        if layer.support_index is None or layer.support_index >= len(
            concept.selected_support_messages
        ):
            raise RenderError(f"Layer '{layer.layer_id}' has an invalid support_index.")
        return concept.selected_support_messages[layer.support_index]
    return None


def _pixel_box(box: NormalizedBox, plan: RenderPlan) -> tuple[int, int, int, int]:
    return (
        round(box.x * plan.width),
        round(box.y * plan.height),
        round((box.x + box.width) * plan.width),
        round((box.y + box.height) * plan.height),
    )


def _font_path(assets: ResolvedAssets, *, layer: SceneLayer) -> Path | None:
    role = layer.font_role
    desired = (
        assets.brand_tokens.heading_font_asset_id
        if role == "heading"
        else assets.brand_tokens.body_font_asset_id
    )
    if layer.font_family == "brand" and desired:
        match = next((item.path for item in assets.fonts if item.asset_id == desired), None)
        if match:
            return match
    if layer.font_family == "brand" and assets.fonts:
        return assets.fonts[0].path
    weight = layer.font_weight
    if weight == "auto":
        weight = "bold" if role == "heading" else "regular"
    family = "segoe_ui" if layer.font_family == "brand" else layer.font_family
    return _system_font_path(
        family=family,
        weight=weight,
        italic=layer.font_style == "italic",
    )


def _resolve_text_color(token: str | None, plan: RenderPlan) -> str:
    color = _resolve_color(token, plan)
    if color is None or color[3] == 0:
        return "#111111"
    return _to_hex(color[:3])


def _resolve_color(
    token: str | None, plan: RenderPlan, *, alpha: float = 1.0
) -> tuple[int, int, int, int] | None:
    if token is None or token == "transparent":
        return None
    standards = {"black": "#000000", "white": "#FFFFFF"}
    value = standards.get(token, plan.brand_tokens.colors.get(token, token))
    rgb = _rgb(value)
    return (*rgb, round(255 * alpha))


def _rgb(value: str) -> tuple[int, int, int]:
    match = re.search(r"#([0-9a-fA-F]{6})", value)
    if not match:
        raise RenderError(f"Color '{value}' is not a six-digit hexadecimal brand token.")
    raw = match.group(1)
    channels = tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4))
    return channels  # type: ignore[return-value]


def _to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in rgb)


def _draw_fitted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    *,
    font_path: Path | None,
    max_size: int,
    min_size: int,
    max_lines: int,
    fill: str,
    accent_fill: str | None,
    accent_words: list[str],
    align: str,
    vertical_align: str,
    line_spacing_ratio: float,
) -> None:
    left, top, right, bottom = box
    font, lines, gap = _fit_text(
        draw,
        text,
        font_path=font_path,
        max_size=max_size,
        min_size=min_size,
        max_width=right - left,
        max_height=bottom - top,
        max_lines=max_lines,
        line_spacing_ratio=line_spacing_ratio,
    )
    total_height = sum(_line_height(draw, line, font) for line in lines) + gap * (len(lines) - 1)
    if vertical_align == "top":
        y = top
    elif vertical_align == "bottom":
        y = bottom - total_height
    else:
        y = top + max(0, ((bottom - top) - total_height) // 2)
    for line in lines:
        line_box = draw.textbbox((0, 0), line, font=font)
        line_width = line_box[2] - line_box[0]
        if align == "center":
            x = left + ((right - left - line_width) // 2)
        elif align == "right":
            x = right - line_width
        else:
            x = left
        if accent_fill and accent_words:
            _draw_styled_line(
                draw,
                line,
                x=x,
                y=y,
                font=font,
                fill=fill,
                accent_fill=accent_fill,
                accent_words=accent_words,
            )
        else:
            draw.text((x, y), line, font=font, fill=fill)
        y += _line_height(draw, line, font) + gap


def _draw_styled_line(
    draw: ImageDraw.ImageDraw,
    line: str,
    *,
    x: float,
    y: float,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: str,
    accent_fill: str,
    accent_words: list[str],
) -> None:
    accents = {_normalize_word(word) for word in accent_words}
    cursor = x
    for segment in re.findall(r"\S+\s*", line):
        color = accent_fill if _normalize_word(segment) in accents else fill
        draw.text((cursor, y), segment, font=font, fill=color)
        box = draw.textbbox((0, 0), segment, font=font)
        cursor += box[2] - box[0]


def _normalize_word(value: str) -> str:
    return re.sub(r"^\W+|\W+$", "", value.strip(), flags=re.UNICODE).casefold()


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font_path: Path | None,
    max_size: int,
    min_size: int,
    max_width: int,
    max_height: int,
    max_lines: int,
    line_spacing_ratio: float,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, list[str], int]:
    for size in range(max_size, min_size - 1, -1):
        font = _load_font(font_path, size)
        lines: list[str] = []
        current = ""
        for word in text.split():
            candidate = f"{current} {word}".strip()
            width = draw.textbbox((0, 0), candidate, font=font)[2]
            if current and width > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        gap = max(1, round(size * line_spacing_ratio))
        height = sum(_line_height(draw, line, font) for line in lines) + gap * (len(lines) - 1)
        if len(lines) <= max_lines and height <= max_height:
            return font, lines, gap
    raise RenderError("Agent-authored text layer is too small for its required content.")


def _line_height(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> int:
    box = draw.textbbox((0, 0), text or "Ag", font=font)
    return max(1, round(box[3] - box[1]))


def _load_font(path: Path | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if path:
        return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _system_font_path(*, family: str, weight: str, italic: bool) -> Path | None:
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    bold = weight in {"semibold", "bold", "black"}
    windows_names = {
        "segoe_ui": {
            (False, False): "segoeui.ttf",
            (True, False): "segoeuib.ttf",
            (False, True): "segoeuii.ttf",
            (True, True): "segoeuiz.ttf",
        },
        "arial": {
            (False, False): "arial.ttf",
            (True, False): "arialbd.ttf",
            (False, True): "ariali.ttf",
            (True, True): "arialbi.ttf",
        },
        "calibri": {
            (False, False): "calibri.ttf",
            (True, False): "calibrib.ttf",
            (False, True): "calibrii.ttf",
            (True, True): "calibriz.ttf",
        },
        "bahnschrift": {
            (False, False): "bahnschrift.ttf",
            (True, False): "bahnschrift.ttf",
            (False, True): "bahnschrift.ttf",
            (True, True): "bahnschrift.ttf",
        },
        "georgia": {
            (False, False): "georgia.ttf",
            (True, False): "georgiab.ttf",
            (False, True): "georgiai.ttf",
            (True, True): "georgiaz.ttf",
        },
        "cambria": {
            (False, False): "cambria.ttc",
            (True, False): "cambriab.ttf",
            (False, True): "cambriai.ttf",
            (True, True): "cambriaz.ttf",
        },
        "constantia": {
            (False, False): "constan.ttf",
            (True, False): "constanb.ttf",
            (False, True): "constani.ttf",
            (True, True): "constanz.ttf",
        },
        "corbel": {
            (False, False): "corbel.ttf",
            (True, False): "corbelb.ttf",
            (False, True): "corbeli.ttf",
            (True, True): "corbelz.ttf",
        },
        "times_new_roman": {
            (False, False): "times.ttf",
            (True, False): "timesbd.ttf",
            (False, True): "timesi.ttf",
            (True, True): "timesbi.ttf",
        },
        "trebuchet_ms": {
            (False, False): "trebuc.ttf",
            (True, False): "trebucbd.ttf",
            (False, True): "trebucit.ttf",
            (True, True): "trebucbi.ttf",
        },
        "verdana": {
            (False, False): "verdana.ttf",
            (True, False): "verdanab.ttf",
            (False, True): "verdanai.ttf",
            (True, True): "verdanaz.ttf",
        },
    }
    selected = windows_names.get(family, windows_names["segoe_ui"])[(bold, italic)]
    fallback_family = "DejaVuSans" if family != "georgia" else "DejaVuSerif"
    fallback_name = (
        f"{fallback_family}-BoldItalic.ttf"
        if bold and italic
        else f"{fallback_family}-Bold.ttf"
        if bold
        else f"{fallback_family}-Italic.ttf"
        if italic
        else f"{fallback_family}.ttf"
    )
    candidates = [windows / selected, Path("/usr/share/fonts/truetype/dejavu") / fallback_name]
    return next((item for item in candidates if item.is_file()), None)


def _transform_text(text: str, transform: str) -> str:
    if transform == "uppercase":
        return text.upper()
    if transform == "lowercase":
        return text.lower()
    if transform == "titlecase":
        return text.title()
    return text


def _atomic_save_png(image: Image.Image, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.stem}-",
            suffix=".png",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
        image.save(temporary_name, "PNG", optimize=True)
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
