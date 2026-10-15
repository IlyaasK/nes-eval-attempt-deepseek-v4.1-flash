#!/usr/bin/env python3
"""render_vram.py -- render a NES background from a --dumpvram directory.

Usage: render_vram.py DIR OUT.png [--bgpt 0x1000] [--nt 0] [--mirror v|h]
                                  [--sx N] [--sy N] [--finex N] [--finey N]
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pairshot import write_png  # noqa: E402

PAL = np.fromfile("/task/spec/nes_palette.pal", dtype=np.uint8).reshape(-1, 3)


def render(chr_, vram, pal, bgpt, ntbits, mirror, sx, sy, fine_x=0, fine_y=0):
    out = np.zeros((240, 256), dtype=np.uint16)
    for y in range(240):
        for x in range(256):
            vx = x + sx
            vy = y + sy + fine_y
            tx, ty = vx // 8, vy // 8
            row, col = vy % 8, (vx + fine_x) % 8
            h_nt = (ntbits & 1) ^ (1 if tx >= 32 else 0)
            v_nt = ((ntbits >> 1) & 1) ^ (1 if ty >= 30 else 0)
            nt = (v_nt << 1) | h_nt
            phys = h_nt if mirror == "v" else v_nt
            base = phys * 0x400
            tile = vram[base + (ty % 30) * 32 + (tx % 32)]
            addr = bgpt + tile * 16 + row
            lo = chr_[addr & 0x1FFF]
            hi = chr_[(addr + 8) & 0x1FFF]
            bit = 7 - col
            px = ((lo >> bit) & 1) | (((hi >> bit) & 1) << 1)
            if px == 0:
                idx = 0
            else:
                at = vram[base + 0x3C0 + (ty % 30) // 4 * 8 + (tx % 32) // 4]
                shift = ((ty & 2) << 1) | (tx & 2)
                p = (at >> shift) & 3
                idx = p * 4 + px
            out[y, x] = pal[idx & 0x1F] & 0x3F
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("out")
    ap.add_argument("--bgpt", type=lambda s: int(s, 0), default=0x1000)
    ap.add_argument("--nt", type=int, default=0)
    ap.add_argument("--mirror", default="v")
    ap.add_argument("--sx", type=int, default=0)
    ap.add_argument("--sy", type=int, default=0)
    ap.add_argument("--finex", type=int, default=0)
    ap.add_argument("--finey", type=int, default=0)
    ap.add_argument("--cmp", default=None, help="compare with this .idx frame")
    args = ap.parse_args()
    chr_ = np.fromfile(os.path.join(args.dir, "chr.bin"), dtype=np.uint8)
    vram = np.fromfile(os.path.join(args.dir, "vram.bin"), dtype=np.uint8)
    pal = np.fromfile(os.path.join(args.dir, "pal.bin"), dtype=np.uint8)
    img = render(chr_, vram, pal, args.bgpt, args.nt, args.mirror, args.sx, args.sy,
                 args.finex, args.finey)
    write_png(args.out, PAL[img & 0x1FF])
    print("wrote", args.out)
    if args.cmp:
        ref = np.fromfile(args.cmp, dtype="<u2").reshape(240, 256)
        print("diff vs %s: %d" % (args.cmp, int((ref != img).sum())))


if __name__ == "__main__":
    main()
