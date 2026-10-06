#!/usr/bin/env python3
"""Documentation tool: how the EXACT_DUPLICATES / NEAR_DUPLICATES pins in
hc18_pins.py were found. Not called by build.sh or verify.sh.

Decodes all 1,334 published image members from the local archives, computes a
24x16 block-mean thumbnail per image (every 6th pixel in each block), compares
every pair of thumbnails (mean absolute difference), and for each pair below
THUMB_THRESHOLD reports the full-resolution differing-pixel fraction when the
shapes match. Local files only.

Usage: near_duplicate_screen.py <data_root>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hc18_decode as decoder  # noqa: E402
import hc18_pins as pins  # noqa: E402

GRID_X, GRID_Y, STEP = 24, 16, 6
THUMB_THRESHOLD = 4.0


def thumbnail(pixels: bytes, width: int, height: int) -> bytes:
    cells = []
    for by in range(GRID_Y):
        for bx in range(GRID_X):
            total = count = 0
            for y in range(by * height // GRID_Y + 2, (by + 1) * height // GRID_Y, STEP):
                row = y * width
                for x in range(bx * width // GRID_X + 2, (bx + 1) * width // GRID_X, STEP):
                    total += pixels[row + x]
                    count += 1
            cells.append(total // count)
    return bytes(cells)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    download_dir = Path(argv[1]).resolve() / "downloads" / pins.DATASET_ID
    images: list[tuple[str, tuple[int, int], bytes, bytes]] = []
    for split in pins.SPLITS:
        archive = download_dir / split["archive"]
        entries = decoder.select_images(decoder.read_central_directory(archive), split)
        with archive.open("rb") as fh:
            for entry in entries:
                width, height = pins.expected_size(entry["name"])
                pixels, _ = decoder.decode_png(decoder.read_member(fh, entry), width, height)
                images.append((entry["name"], (width, height), pixels, thumbnail(pixels, width, height)))
    print(f"decoded {len(images)} images")
    for i, (name_a, shape_a, pixels_a, thumb_a) in enumerate(images):
        for name_b, shape_b, pixels_b, thumb_b in images[i + 1 :]:
            distance = sum(abs(x - y) for x, y in zip(thumb_a, thumb_b)) / len(thumb_a)
            if distance >= THUMB_THRESHOLD:
                continue
            if shape_a == shape_b:
                differing = sum(1 for x, y in zip(pixels_a, pixels_b) if x != y)
                detail = f"differing_pixels={differing} ({differing / len(pixels_a):.4%})"
            else:
                detail = f"shapes differ {shape_a} vs {shape_b}"
            pinned = pins.SKIPPED_MEMBERS.get(name_b) == name_a
            print(f"thumb_mad={distance:5.2f} {name_a} {name_b} {detail} pinned={pinned}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
