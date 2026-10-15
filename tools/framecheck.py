#!/usr/bin/env python3
"""framecheck.py -- does a `bit $2002 / bpl` vblank poll lose frames?

The ROM counts NMIs (one per frame) around a vblank poll loop and paints the
backdrop white when the loop took more than one frame (i.e. the poll missed the
vblank because a read dropped the flag) and black otherwise.

Each run sweeps a small entry offset (in CPU cycles) before entering the poll
loop, which shifts where the loop's reads land relative to the flag-set dot.

Usage: framecheck.py [--frames N] [--offset 0..4] [--pre N]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
from probe import build, run_both  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# nop/nop... variants that add exactly `n` CPU cycles (2-cycle nop, 3-cycle inc)
def delay_seq(n):
    out = []
    while n >= 3:
        out.append("inc $00")
        n -= 3
    while n >= 2:
        out.append("nop")
        n -= 2
    for _ in range(n):
        out.append("bit $00")
    return out


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
loop:
        lda $10
        sta $11
%s
poll:
        bit $2002
        bpl poll
        lda $10
        sec
        sbc $11
        cmp #1
        beq one
        lda #$30
        jmp paint
one:
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
        ; wait for the pre-render so we don't perturb the next measurement
        jsr vwait
        jmp loop
vwait:
        pha
v2:     bit $2002
        bpl v2
        pla
        rts
nmi:
        inc $10
        rti
irq:
        rti
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    offsets = range(5) if args.all else [args.offset]
    for off in offsets:
        text = TEMPLATE % "\n".join("        " + s for s in delay_seq(off))
        rom = build(text, vectors=("nmi", "start", "irq"))
        path = os.path.join(ROOT, "tmp", "framecheck.nes")
        ref, mine = run_both(path, rom, frames=args.frames)
        rseq = []
        mseq = []
        for r, m in zip(ref, mine):
            rv = sorted(set(r.flatten().tolist()))
            mv = sorted(set(m.flatten().tolist()))
            rseq.append("W" if 0x30 in rv else ("B" if 0x0F in rv else "?"))
            mseq.append("W" if 0x30 in mv else ("B" if 0x0F in mv else "?"))
        print("offset %d:" % off)
        print("  ref : %s" % "".join(rseq))
        print("  mine: %s" % "".join(mseq))
    return 0


if __name__ == "__main__":
    sys.exit(main())
