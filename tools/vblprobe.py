#!/usr/bin/env python3
"""vblprobe.py -- sweep the $2002 read phase across the vblank flag set.

Syncs on the NMI (asserted at the vblank flag set), waits almost one frame,
then reads $2002 and paints the backdrop white when the flag was visible and
black otherwise.  The CPU cycle grid drifts against the 341-dot scanline by
2/3 or 1/3 cycle per frame, so the read offset sweeps across the flag-set dot
and the colour sequence reveals the suppression window.

Usage: vblprobe.py [--frames N] [--delay N]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
from probe import build, run_both  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAME_CYCLES = 29780.67

TEMPLATE = """
start:
        sei
        cld
        ldx #$FF
        txs
        lda #$00
        sta $2000
        sta $2001
        lda #$00
        sta $10
        jsr vwait
        jsr vwait
        jsr vwait
        lda #$80
        sta $2000
        ; discard the NMI that the previous vblank may have triggered
        lda $10
        pha
        jsr vwait
        lda $10
        cmp $10
loop:
        lda $10
w1:     cmp $10
        beq w1
        ; delay: ~one frame
        ldx #%d
        ldy #%d
d1:     dex
        bne d1
        dey
        bne d1
        bit $2002
        bpl black
        lda #$30
        jmp paint
black:
        lda #$0F
paint:
        pha
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        pla
        sta $2007
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        jmp loop
vwait:
        pha
v2:     bit $2002
        bpl v2
        pla
        rts
nmi:
        inc $10
        pha
        lda #$00
        sta $00
        pla
        rti
irq:
        rti
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=48)
    ap.add_argument("--delay", type=int, default=200)
    args = ap.parse_args()
    inner = 256
    total = args.delay + 5 * inner + 30
    outer = max(1, (args.delay + 20000) // (inner * 5))
    text = TEMPLATE % (inner - 1, outer)
    rom = build(text, vectors=("nmi", "start", "irq"))
    path = os.path.join(ROOT, "tmp", "vblprobe.nes")
    ref, mine = run_both(path, rom, frames=args.frames)
    diffs = 0
    for i, (r, m) in enumerate(zip(ref, mine)):
        rv = sorted(set(r.flatten().tolist()))
        mv = sorted(set(m.flatten().tolist()))
        if rv != mv:
            diffs += 1
        print("frame %2d: ref=%-14s mine=%-14s %s" % (i, rv, mv, "" if rv == mv else "  <-- DIFF"))
    print("total mismatching frames: %d" % diffs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
