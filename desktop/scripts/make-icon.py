"""Generate the application icon (multi-size .ico) without external assets.

Run with the backend virtual environment, which already provides Pillow:

    backend\\.venv\\Scripts\\python.exe desktop\\scripts\\make-icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SIZE = 256
OUT = Path(__file__).resolve().parent.parent / "build" / "icon.ico"


def rounded_gradient(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gradient = Image.new("RGBA", (size, size))
    pixels = gradient.load()
    for y in range(size):
        for x in range(size):
            ratio = (x + y) / (2 * (size - 1))
            pixels[x, y] = (
                int(20 + (13 - 20) * ratio),
                int(184 + (148 - 184) * ratio),
                int(166 + (136 - 166) * ratio),
                255,
            )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255
    )
    image.paste(gradient, (0, 0), mask)
    return image


def build() -> None:
    image = rounded_gradient(SIZE)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=int(SIZE * 0.62))
    letter = "S"
    left, top, right, bottom = draw.textbbox((0, 0), letter, font=font)
    draw.text(
        ((SIZE - (right - left)) / 2 - left, (SIZE - (bottom - top)) / 2 - top),
        letter,
        font=font,
        fill=(4, 47, 46, 255),
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(
        OUT,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()
