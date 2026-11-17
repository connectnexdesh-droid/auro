"""Generate the AURO Windows application icon during desktop builds."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    output = Path(__file__).resolve().parent / "assets" / "auro.ico"
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (8, 8, 248, 248), radius=54,
        fill=(17, 24, 39, 255), outline=(48, 67, 91, 255), width=5,
    )
    draw.rounded_rectangle(
        (30, 30, 226, 42), radius=6, fill=(47, 190, 170, 255),
    )
    draw.polygon(
        [(128, 57), (61, 199), (94, 199), (128, 124), (162, 199), (195, 199)],
        fill=(229, 239, 249, 255),
    )
    draw.rounded_rectangle(
        (91, 151, 165, 170), radius=5, fill=(47, 190, 170, 255),
    )
    draw.polygon(
        [(128, 107), (111, 151), (145, 151)],
        fill=(17, 24, 39, 255),
    )
    image.save(
        output,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"Created {output}")


if __name__ == "__main__":
    main()
