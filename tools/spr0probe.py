#!/usr/bin/env python3
"""spr0probe.py -- measure the sprite-0 hit timing/scanline vs the reference.

Sprite 0 is placed at a chosen Y/X over an opaque background.  The ROM polls
$2002 bit 6 and, the moment the hit is seen, changes palette entry 0 to white,
so the frame shows the scanline at which the hit was noticed.

Usage: spr0probe.py [--frames N]
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
        ; palette 0 backdrop black, colour 1..3 for bg/sprite
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        lda #$0F
        sta $2007
        lda #$0F
        sta $2007
        lda #$0F
        sta $2007
        lda #$0F
        sta $2007
        ; sprite palette $3F11..$3F13 also $0F
        lda #$3F
        sta $2006
        lda #$11
        sta $2006
        lda #$0F
        sta $2007
        sta $2007
        sta $2007
        ; CHR RAM: tile 1 pattern = pixel colour 2 (lo=0, hi=FF)
        lda #$00
        sta $2006
        lda #$10
        sta $2006
        ldx #$00
        lda #$00
pat1:   sta $2007
        inx
        cpx #$08
        bne pat1
        ldx #$00
        lda #$FF
pat2:   sta $2007
        inx
        cpx #$08
        bne pat2
        ; sprite 0 at (y=Y, x=X), tile 1, attr 0
        lda #$%02X
        sta $0200
        lda #$01
        sta $0201
        lda #$00
        sta $0202
        lda #$%02X
        sta $0203
        ; hide the rest
        ldx #$04
fill:   lda #$F0
        sta $0200,X
        inx
        bne fill
        lda #$00
        sta $2003
        lda #$02
        sta $4014
        ; nametable: all tile 1
        lda #$20
        sta $2006
        lda #$00
        sta $2006
        ldx #$00
        lda #$01
fill2:  sta $2007
        inx
        bne fill2
        ldx #$00
fill3:  sta $2007
        inx
        bne fill3
        ldx #$00
fill4:  sta $2007
        inx
        bne fill4
        ldx #$00
fill5:  sta $2007
        inx
        bne fill5
        lda #$00
        sta $2005
        sta $2005
        lda #$80
        sta $2000
        lda #$1E
        sta $2001
loop:
        lda $10
w1:     cmp $10
        beq w1
        ; wait for the sprite 0 flag to be clear (cleared at pre-render)
w2:     bit $2002
        bvs w2
        ; now wait for the hit
w3:     bit $2002
        bvc w3
        ; paint background colour 2 white (reset by the NMI handler)
        lda #$3F
        sta $2006
        lda #$02
        sta $2006
        lda #$30
        sta $2007
        lda #$3F
        sta $2006
        lda #$02
        sta $2006
        jmp loop
vwait:
        bit $2002
        bpl vwait
        rts
nmi:
        inc $10
        pha
        lda #$3F
        sta $2006
        lda #$02
        sta $2006
        lda #$0F
        sta $2007
        lda #$3F
        sta $2006
        lda #$02
        sta $2006
        pla
        rti
irq:
        rti
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=6)
    args = ap.parse_args()
    for y, x in [(100, 100), (0, 0), (0, 100), (255, 100), (20, 10)]:
        text = TEMPLATE % (y, x)
        rom = build(text, vectors=("nmi", "start", "irq"))
        path = os.path.join(ROOT, "tmp", "spr0probe.nes")
        ref, mine = run_both(path, rom, frames=args.frames)
        def rows(img):
            white = np.argwhere((img == 0x30).any(axis=1)).flatten()
            return (int(white.min()), int(white.max())) if len(white) else None
        print("y=%3d x=%3d: ref rows %s mine %s  lastframe diff %d"
              % (y, x, rows(ref[-1]), rows(mine[-1]), int((ref[-1] != mine[-1]).sum())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
