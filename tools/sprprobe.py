#!/usr/bin/env python3
"""sprprobe.py -- compare sprite rendering (position, row mapping, flips) with
the reference.

Builds a ROM that shows N sprites with configurable Y/X/tile/attr over a
uniform background (or with the background disabled) and diffs the framebuffer
against the oracle.

Usage: sprprobe.py [--frames N]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
from probe import build, run_both  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# sprite pattern table at $0000: tile 1 = a distinct diagonal-ish pattern
PATTERN = bytes([
    0b10000000, 0b00000000,   # row 0 lo/hi
    0b01000000, 0b00000000,
    0b00100000, 0b00000000,
    0b00010000, 0b00000000,
    0b00001000, 0b00000000,
    0b00000100, 0b00000000,
    0b00000010, 0b00000000,
    0b00000001, 0b00000000,
])


def make_src(sprites, bg_on=True, sp_on=True, sprite_table_high=False):
    lines = []
    for i, (y, tile, attr, x) in enumerate(sprites):
        o = i * 4
        lines.append("lda #$%02X" % y)
        lines.append("sta $02%02X" % o)
        lines.append("lda #$%02X" % tile)
        lines.append("sta $02%02X" % (o + 1))
        lines.append("lda #$%02X" % attr)
        lines.append("sta $02%02X" % (o + 2))
        lines.append("lda #$%02X" % x)
        lines.append("sta $02%02X" % (o + 3))
    for i in range(len(sprites), 64):
        o = i * 4
        lines.append("lda #$F0")
        for j in range(4):
            lines.append("sta $02%02X" % (o + j))
    mask = 0
    if bg_on:
        mask |= 0x08 | 0x02
    if sp_on:
        mask |= 0x10
    ctrl = 0x04 if sprite_table_high else 0x00
    return """
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
        ; palette 0: backdrop $0F, colour 1 $30, colour 2 $16, colour 3 $29
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        lda #$0F
        sta $2007
        lda #$30
        sta $2007
        lda #$16
        sta $2007
        lda #$29
        sta $2007
        ; sprite palette: colours 1,2,3 at $3F11..$3F13
        lda #$3F
        sta $2006
        lda #$11
        sta $2006
        lda #$30
        sta $2007
        lda #$16
        sta $2007
        lda #$29
        sta $2007
%s
        lda #$00
        sta $2003
        lda #$02
        sta $4014
        ; background: nametable all tile 1, attribute 0
        lda #$20
        sta $2006
        lda #$00
        sta $2006
        ldx #$00
        lda #$01
bfill:  sta $2007
        inx
        bne bfill
        ldx #$00
bfill2: sta $2007
        inx
        bne bfill2
        ldx #$00
bfill3: sta $2007
        inx
        bne bfill3
        ldx #$00
bfill4: sta $2007
        inx
        bne bfill4
        lda #$00
        sta $2005
        sta $2005
        lda #$%02X
        sta $2000
        lda #$%02X
        sta $2001
hang:   jmp hang
vwait:
        bit $2002
        bpl vwait
        rts
nmi:    rti
irq:    rti
""" % ("\n".join(lines), ctrl, mask)


def make_rom(sprites, **kw):
    text = make_src(sprites, **kw)
    rom = build(text, vectors=("nmi", "start", "irq"))
    # inject the sprite pattern for tile 1 into CHR RAM: the ROM cannot write
    # CHR RAM from the CPU test image, so instead patch the .nes after build:
    return rom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=6)
    args = ap.parse_args()
    cases = {
        "sprite y=20 x=10": [(20, 1, 0, 10)],
        "sprite y=0 x=0": [(0, 1, 0, 0)],
        "sprite y=255 x=100": [(255, 1, 0, 100)],
        "sprite y=254 x=100": [(254, 1, 0, 100)],
        "sprite flipx": [(20, 1, 0x40, 10)],
        "sprite flipy": [(20, 1, 0x80, 10)],
        "sprite behind bg": [(20, 1, 0x20, 10)],
        "two sprites": [(20, 1, 0, 10), (30, 1, 0, 40)],
        "sprite x=248": [(20, 1, 0, 248)],
        "sprite x=7": [(20, 1, 0, 7)],
    }
    for name, sprites in cases.items():
        rom = make_rom(sprites)
        path = os.path.join(ROOT, "tmp", "sprprobe.nes")
        ref, mine = run_both(path, rom, frames=args.frames)
        worst = 0
        firstbad = None
        for i, (r, m) in enumerate(zip(ref, mine)):
            d = int((r != m).sum())
            if d and firstbad is None:
                firstbad = i
            worst = max(worst, d)
        print("%-24s worst=%5d firstbad=%s" % (name, worst, firstbad))
        if worst:
            r, m = ref[-1], mine[-1]
            d = np.argwhere(r != m)
            print("     sample diffs:", [(int(y), int(x), hex(int(r[y, x])), hex(int(m[y, x])))
                                         for y, x in d[:5]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
