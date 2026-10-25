#!/usr/bin/env python3
"""Generate the application icon.

The icon is a disk divided into sectors, with one sector highlighted: that
is the partition the tool looks for.  It is drawn with plain arithmetic and
written as a PNG wrapped in an ICO container, so the project keeps its
"no third party runtime dependency" promise even for the build.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

SIZE = 256
SUPERSAMPLE = 4

#: The highlighted sector, in degrees, measured from the positive x axis.
LOST_SECTOR = (-58.0, -12.0)


def _rounded_rect(x: float, y: float, size: int, radius: float) -> bool:
    """True when (x, y) lies inside a rounded square."""
    lo, hi = 0.0, float(size)
    if x < lo or x > hi or y < lo or y > hi:
        return False
    cx = min(max(x, lo + radius), hi - radius)
    cy = min(max(y, lo + radius), hi - radius)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def _in_lost_sector(x: float, y: float, cx: float, cy: float) -> bool:
    angle = math.degrees(math.atan2(y - cy, x - cx))
    start, end = LOST_SECTOR
    if start <= end:
        return start <= angle <= end
    return angle >= start or angle <= end


def render() -> list[bytearray]:
    """Render the icon and return one RGBA row per pixel."""
    cx = cy = SIZE / 2.0
    outer = SIZE * 0.365
    inner = SIZE * 0.255

    rows: list[bytearray] = []
    step = 1.0 / SUPERSAMPLE
    for py in range(SIZE):
        row = bytearray()
        for px in range(SIZE):
            r_sum = g_sum = b_sum = a_sum = 0.0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    x = px + (sx + 0.5) * step
                    y = py + (sy + 0.5) * step
                    if not _rounded_rect(x, y, SIZE, SIZE * 0.22):
                        continue
                    # Background: a vertical gradient.
                    t = y / SIZE
                    colour = (
                        int(30 + 10 * t),
                        int(41 + 12 * t),
                        int(59 + 16 * t),
                    )
                    distance = math.hypot(x - cx, y - cy)
                    if inner <= distance <= outer:
                        # The ring of the disk.
                        if _in_lost_sector(x, y, cx, cy):
                            colour = (245, 158, 11)
                        else:
                            colour = (203, 213, 225)
                    elif distance < inner:
                        # The hub, with a gap that marks the missing entry.
                        if _in_lost_sector(x, y, cx, cy):
                            colour = (120, 53, 15)
                        else:
                            colour = (71, 85, 105)
                    r_sum += colour[0]
                    g_sum += colour[1]
                    b_sum += colour[2]
                    a_sum += 255
            samples = SUPERSAMPLE * SUPERSAMPLE
            if a_sum == 0:
                row += bytes((0, 0, 0, 0))
            else:
                covered = a_sum / 255.0
                row += bytes((
                    int(r_sum / covered),
                    int(g_sum / covered),
                    int(b_sum / covered),
                    int(a_sum / samples),
                ))
        rows.append(row)
    return rows


def png_bytes(rows: list[bytearray]) -> bytes:
    """Encode the rows as a PNG."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(b"\x00" + bytes(row) for row in rows)
    header = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def ico_bytes(png: bytes, size: int = SIZE) -> bytes:
    """Wrap a PNG in an ICO container."""
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        size % 256, size % 256, 0, 0,
        1, 32,
        len(png),
        22,
    )
    return header + entry + png


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    rows = render()
    png = png_bytes(rows)
    (ASSETS / "lostpart.png").write_bytes(png)
    (ASSETS / "lostpart.ico").write_bytes(ico_bytes(png))
    print(f"wrote {ASSETS / 'lostpart.png'} ({len(png)} bytes)")
    print(f"wrote {ASSETS / 'lostpart.ico'} ({len(ico_bytes(png))} bytes)")


if __name__ == "__main__":
    main()
