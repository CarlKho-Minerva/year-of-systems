#!/usr/bin/env python3
"""Generate the PWA/home-screen icons. Stdlib only — no Pillow, no design tool.

WHY GENERATED AND NOT CHECKED IN AS BINARY: an icon you cannot regenerate is an icon you
cannot change. This is 60 lines and takes 200ms, so the icon stays editable forever.

The mark is the year itself: 52 dots in a 7-wide grid (7 life areas across, 8 rows down),
the first stretch lit to read as progress. Content is inset to ~64% of the canvas so the
Android maskable crop and the iOS rounded-rect mask both land inside the artwork.
"""
import os, struct, zlib

BG = (0x0b, 0x0f, 0x14)
LIT = (0xf0, 0xb4, 0x29)
DIM = (0x26, 0x31, 0x3d)
COLS, ROWS, TOTAL, LIT_COUNT = 7, 8, 52, 18
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def render(size: int) -> bytes:
    px = [[BG] * size for _ in range(size)]
    inset = size * 0.18
    span = size - 2 * inset
    pitch = span / COLS
    r = pitch * 0.30
    top = (size - pitch * ROWS) / 2.0

    for i in range(TOTAL):
        col, row = i % COLS, i // COLS
        cx = inset + pitch * (col + 0.5)
        cy = top + pitch * (row + 0.5)
        colour = LIT if i < LIT_COUNT else DIM
        x0, x1 = max(0, int(cx - r - 2)), min(size, int(cx + r + 2))
        y0, y1 = max(0, int(cy - r - 2)), min(size, int(cy + r + 2))
        for y in range(y0, y1):
            for x in range(x0, x1):
                d = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
                if d <= r - 0.5:
                    px[y][x] = colour
                elif d < r + 0.5:                      # 1px feather, or it looks jagged
                    t = r + 0.5 - d
                    base = px[y][x]
                    px[y][x] = tuple(int(base[k] + (colour[k] - base[k]) * t) for k in range(3))

    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in px)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for s in (180, 192, 512):
        path = os.path.join(OUT, f"icon-{s}.png")
        with open(path, "wb") as f:
            f.write(render(s))
        print(f"wrote {path} ({os.path.getsize(path)} bytes)")
