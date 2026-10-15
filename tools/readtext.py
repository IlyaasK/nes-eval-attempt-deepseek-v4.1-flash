#!/usr/bin/env python3
"""readtext.py -- decode NES text screens into ASCII using a ROM's font.

Usage: readtext.py <rom> <frame.idx> [--font-base 0000] [--grid 8]

Blargg-style test ROMs draw text with an ASCII-indexed font in CHR, one
8x8 cell per character.  The frame is compared against every tile pattern
and the best match, if good enough, becomes the character.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pairshot import load  # noqa: E402


def font_tiles(rom_path, base, chr_file=None):
    if chr_file:
        chr_ = open(chr_file, "rb").read()[:8192]
    else:
        data = open(rom_path, "rb").read()
        chr_off = 16 + 16384 * (data[4] & 0x0F)
        chr_ = data[chr_off:chr_off + 8192]
    tiles = []
    for t in range(256):
        o = base + t * 16
        tile = chr_[o:o + 16]
        if len(tile) < 16:
            tiles.append(None)
            continue
        mask = np.zeros((8, 8), dtype=np.uint8)
        for r in range(8):
            lo = tile[r]
            hi = tile[8 + r]
            for c in range(8):
                mask[r, c] = ((lo >> (7 - c)) & 1) | (((hi >> (7 - c)) & 1) << 1)
        tiles.append(mask)
    return tiles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("frame")
    ap.add_argument("--font-base", default="0000")
    ap.add_argument("--bg", default=None, help="backdrop pixel value (default: most common)")
    ap.add_argument("--rows", default="0:30")
    ap.add_argument("--chr", default=None, help="raw 8 KiB CHR image (for CHR-RAM ROMs)")
    args = ap.parse_args()

    base = int(args.font_base, 16)
    tiles = font_tiles(args.rom, base, args.chr)
    if not any(m is not None and m.any() for m in tiles):
        print("(CHR has no font data at %04X - ROM probably uses CHR-RAM)" % base)
        return
    img = load(args.frame)
    vals, counts = np.unique(img, return_counts=True)
    bg = int(vals[np.argmax(counts)]) if args.bg is None else int(args.bg, 16)

    r0, r1 = (int(x) for x in args.rows.split(":"))
    # Find the fine scroll offset (0..7 in each axis) that best explains the
    # screen with the font: test ROMs often display their log with a fine Y
    # scroll that is not a multiple of 8.
    best_off, best_total = (0, 0), -1
    for dy in range(8):
        for dx in range(8):
            total = 0
            for row in range(r0, min(r1, 29)):
                for col in range(31):
                    y = row * 8 - dy
                    x = col * 8 - dx
                    if y < 0 or y + 8 > 240 or x < 0 or x + 8 > 256:
                        continue
                    cell = img[y:y + 8, x:x + 8]
                    on = (cell != bg).astype(np.uint8)
                    if not on.any():
                        total += 64
                        continue
                    cands = [int(((mask != 0).astype(np.uint8) == on).sum())
                             for mask in tiles if mask is not None and mask.any()]
                    best = max(cands) if cands else 0
                    total += best
            if total > best_total:
                best_total, best_off = total, (dy, dx)
    dy, dx = best_off
    lines = []
    for row in range(r0, r1):
        line = []
        for col in range(32):
            y = row * 8 - dy
            x = col * 8 - dx
            if y < 0 or y + 8 > 240 or x < 0 or x + 8 > 256:
                line.append(" ")
                continue
            cell = img[y:y + 8, x:x + 8]
            on = (cell != bg)
            if not on.any():
                line.append(" ")
                continue
            best, bestscore = "?", -1
            for t, mask in enumerate(tiles):
                if mask is None or not mask.any():
                    continue
                # score = matching bits over the 64 pixels
                score = int(((mask != 0).astype(np.uint8) == on.astype(np.uint8)).sum())
                if score > bestscore:
                    bestscore, best = score, chr(t) if 32 <= t < 127 else "?"
            line.append(best if bestscore >= 60 else "?")
        lines.append("".join(line).rstrip())
    print("fine scroll dy=%d dx=%d" % (dy, dx))
    print("\n".join("%2d| %s" % (r0 + i, l) for i, l in enumerate(lines)))


if __name__ == "__main__":
    main()
