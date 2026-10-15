#!/usr/bin/env python3
"""ovfprobe.py -- decide whether the sprite overflow flag is raised for a set
of sprites with a given Y value (default $FF, i.e. in range for scanline 0).

The ROM keeps `count` sprites at Y=y and the rest at Y=$F0.  Each frame it
waits for the vblank flag, runs the OAM DMA, then at the NEXT vblank checks
bit 6 of $2002 (which accumulates over the visible part of the frame) and
paints the backdrop white when the overflow flag was raised, black otherwise.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe import build, run_both  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 9
Y = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0xFF
REST = int(sys.argv[3], 0) if len(sys.argv) > 3 else 0xF0

init = []
for i in range(64):
    init.append("lda #$%02X" % REST)
    init.append("sta $02%02X" % (i * 4))
    init.append("lda #$00")
    init.append("sta $02%02X" % (i * 4 + 1))
    init.append("sta $02%02X" % (i * 4 + 2))
    init.append("sta $02%02X" % (i * 4 + 3))
for i in range(COUNT):
    init.append("lda #$%02X" % Y)
    init.append("sta $02%02X" % (i * 4))

src = """
        sei
        cld
        ldx #$FF
        txs
        lda #$00
        sta $2000
        sta $2001
%s
        ; warm up two frames (writes to $2000-$2006 are ignored until then)
        jsr vsync
        jsr vsync
        ; palette[0] = black (backdrop), enable background rendering so that
        ; sprite evaluation runs
        lda #$0F
        jsr paint
        lda #$0A
        sta $2001
loop:
        jsr vsync
        lda #$00
        sta $2003
        lda #$02
        sta $4014
        jsr vsync
        bvc noovf
        ; overflow flag was raised during the visible part: white
        lda #$30
        jsr paint
        jmp loop
noovf:
        lda #$0F
        jsr paint
        jmp loop
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
        rts
vsync:
w:      bit $2002
        bpl w
        rts
""" % "\n".join(init)

rom = build(src)
path = os.path.join(ROOT, "tmp", "ovfprobe.nes")
ref, mine = run_both(path, rom, frames=8)
for i, (r, m) in enumerate(zip(ref, mine)):
    print("frame %d: ref=%s mine=%s" % (i, sorted(set(r.flatten().tolist()))[:4],
                                        sorted(set(m.flatten().tolist()))[:4]))
print("count=%d y=$%02X rest=$%02X" % (COUNT, Y, REST))
