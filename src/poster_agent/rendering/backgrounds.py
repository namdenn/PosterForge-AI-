"""Deterministic, text-free fallback backgrounds for production-safe rendering."""

import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def create_safe_background(
    target: Path,
    *,
    width: int,
    height: int,
    palette: list[str],
    variant_index: int,
) -> None:
    """Create an abstract background that cannot contain text, logos, people, or UI."""

    colors = _palette_colors(palette)
    chromatic = [color for color in colors if max(_rgb(color)) - min(_rgb(color)) >= 60]
    blue = chromatic[0] if chromatic else "#2463EB"
    purple = chromatic[-1] if len(chromatic) > 1 else "#8B3DFF"
    dark = min(colors, key=_luminance) if colors else "#0B1020"
    light = max(colors, key=_luminance) if colors else "#F5F8FF"

    if variant_index == 1:
        canvas = _linear_gradient((width, height), dark, blue, horizontal=False)
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(glow)
        draw.ellipse(
            (int(width * 0.48), -int(height * 0.12), int(width * 1.18), int(height * 0.58)),
            fill=(*_rgb(purple), 125),
        )
        draw.ellipse(
            (-int(width * 0.18), int(height * 0.56), int(width * 0.52), int(height * 1.18)),
            fill=(*_rgb(blue), 100),
        )
        canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(110)))
    elif variant_index == 2:
        canvas = _linear_gradient((width, height), "#FFFFFF", light, horizontal=True)
        shapes = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(shapes)
        draw.polygon(
            [
                (int(width * 0.62), 0),
                (width, 0),
                (width, int(height * 0.48)),
                (int(width * 0.82), int(height * 0.64)),
            ],
            fill=(*_rgb(blue), 55),
        )
        draw.ellipse(
            (-int(width * 0.22), int(height * 0.64), int(width * 0.42), int(height * 1.15)),
            fill=(*_rgb(purple), 65),
        )
        canvas = Image.alpha_composite(canvas, shapes.filter(ImageFilter.GaussianBlur(70)))
    else:
        canvas = _linear_gradient((width, height), "#FFFFFF", light, horizontal=False)
        shapes = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(shapes)
        draw.ellipse(
            (int(width * 0.54), -int(height * 0.16), int(width * 1.24), int(height * 0.52)),
            fill=(*_rgb(blue), 75),
        )
        draw.ellipse(
            (int(width * 0.70), int(height * 0.48), int(width * 1.22), int(height * 1.05)),
            fill=(*_rgb(purple), 65),
        )
        canvas = Image.alpha_composite(canvas, shapes.filter(ImageFilter.GaussianBlur(95)))

    _atomic_save(canvas.convert("RGB"), target)


def _linear_gradient(
    size: tuple[int, int], start: str, end: str, *, horizontal: bool
) -> Image.Image:
    width, height = size
    length = width if horizontal else height
    first = _rgb(start)
    second = _rgb(end)
    strip = Image.new("RGB", (length, 1))
    pixels = strip.load()
    if pixels is None:
        raise RuntimeError("Pillow did not expose writable gradient pixels.")
    for position in range(length):
        ratio = position / max(1, length - 1)
        pixels[position, 0] = tuple(
            round(first[channel] + ((second[channel] - first[channel]) * ratio))
            for channel in range(3)
        )
    gradient = strip if horizontal else strip.transpose(Image.Transpose.ROTATE_90)
    return gradient.resize(size).convert("RGBA")


def _palette_colors(values: list[str]) -> list[str]:
    return [
        match.group(0)
        for value in values
        if (match := re.search(r"#[0-9A-Fa-f]{6}", value)) is not None
    ]


def _rgb(value: str) -> tuple[int, int, int]:
    normalized = value.lstrip("#")
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )


def _luminance(value: str) -> float:
    red, green, blue = _rgb(value)
    return (0.2126 * red) + (0.7152 * green) + (0.0722 * blue)


def _atomic_save(image: Image.Image, target: Path) -> None:
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
        image.save(temporary_name, format="PNG", optimize=True)
        with open(temporary_name, "rb+") as saved:
            os.fsync(saved.fileno())
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
