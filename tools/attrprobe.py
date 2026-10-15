#!/usr/bin/env python3
"""attrprobe.py -- verifies background attribute (palette) selection.

CHR tile 1 is a solid colour-1 tile, so every opaque background pixel is
palette <attr> colour 1.  The attribute table is filled with a pseudo-random
pattern (a function of the byte index), so the screen shows exactly which
attribute byte and quadrant shift the PPU uses for each 4x4 tile block.

Usage: attrprobe.py [--frames N] [--nt 0] [--bgpt 0]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
from probe import build, run_both  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEMPLATE = """
start:
        sei
        cld
        ldx #$FF
        txs
        lda #$00
        sta $2000
        sta $2001
        jsr vwait
        jsr vwait
        jsr vwait
        ; CHR: tile 1 = solid colour 1 (lo plane $FF, hi plane $00)
        lda #$00
        sta $2006
        lda #$10
        sta $2006
        ldx #$08
        lda #$FF
t1:     sta $2007
        dex
        bne t1
        ldx #$08
        lda #$00
t1b:    sta $2007
        dex
        bne t1b
        ; nametable: all tile 1
        lda #$20
        sta $2006
        lda #$00
        sta $2006
        ldy #$04
        ldx #$00
f0:     lda #$01
        sta $2007
        inx
        bne f0
        dey
        bne f0
        ; attribute table: index i -> (i*37+11) & $FF
        lda #$23
        sta $2006
        lda #$C0
        sta $2006
        ldx #$00
at:     txa
        sta $2007
        inx
        bne at
        ; palette: colour 1 of each palette = distinct colours $11+4k+1
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        lda #$0F
        sta $2007
        lda #$31
        sta $2007
        lda #$3F
        sta $2006
        lda #$05
        sta $2006
        lda #$15
        sta $2007
        lda #$3F
        sta $2006
        lda #$09
        sta $2006
        lda #$25
        sta $2007
        lda #$3F
        sta $2006
        lda #$0D
        sta $2006
        lda #$35
        sta $2007
        lda #$00
        sta $2005
        sta $2005
        lda #$%02X
        sta $2000
        lda #$0A
        sta $2001
spin:   jmp spin
vwait:  bit $2002
        bpl vwait
        rts
nmi:    rti
irq:    rti
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--nt", type=int, default=0)
    ap.add_argument("--bgpt", type=int, default=0)
    args = ap.parse_args()
    ctrl = ((args.nt & 3) | (0x10 if args.bgpt else 0))
    text = TEMPLATE % ctrl
    rom = build(text, vectors=("nmi", "start", "irq"))
    path = os.path.join(ROOT, "tmp", "attrprobe.nes")
    ref, mine = run_both(path, rom, frames=args.frames)
    r, m = ref[-1], mine[-1]
    d = int((r != m).sum())
    print("final frame diff: %d  (ref uniq %s)" % (d, sorted(set(r.flatten().tolist()))[:8]))
    if d:
        ys, xs = np.where(r != m)
        print("first differences:")
        for i in range(0, min(len(ys), 10)):
            y, x = int(ys[i]), int(xs[i])
            print("   (%3d,%3d) tile(%2d,%2d) ref=%02X mine=%02X"
                  % (y, x, x // 8, y // 8, r[y, x], m[y, x]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
