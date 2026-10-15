#!/usr/bin/env python3
"""mkbar.py -- palette raster-bar probe (mapper 0, NROM-256, CHR RAM).

Syncs to the VBL flag, waits a fixed delay so that the loop starts near the
frame boundary, then writes an increasing colour to palette entry 0 every
23 CPU cycles.  The framebuffer shows a ladder of colour bands whose position
and width encode the reference's palette/rendering pipeline offset exactly.

Usage: mkbar.py OUT.nes [--delay-rows N] [--iters N] [--per N]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mkrom import build_rom  # noqa: E402

CYCLES_PER_ROW = 341.0 / 3.0


def assemble(delay_rows=20, iters=128, per=23):
    code = bytearray()

    def emit(b):
        code.extend(b)

    emit(b"\x78")                      # sei
    emit(b"\xd8")                      # cld
    emit(b"\xa2\xff")                  # ldx #$FF
    emit(b"\x9a")                      # txs
    emit(b"\xa9\x00")                  # lda #0
    emit(b"\x8d\x00\x20")              # sta $2000
    emit(b"\x8d\x01\x20")              # sta $2001
    # wait for two VBL flags so the PPU warm-up window has passed
    wait = len(code)
    emit(b"\x2c\x02\x20")              # bit $2002
    emit(b"\x10\xfb")                  # bpl wait
    emit(b"\x2c\x02\x20")              # bit $2002
    emit(b"\x10\xfb")                  # bpl wait

    # Fixed delay in CPU cycles: delay_rows rows worth minus loop overhead.
    total = int(delay_rows * CYCLES_PER_ROW)
    # 16-bit down counter: outer * inner * 5 cycles (dex,bne) + overhead
    inner = 255
    outer = max(1, (total - 20) // (inner * 5))
    emit(b"\xa2" + bytes([inner]))     # ldx #inner
    emit(b"\xa0" + bytes([outer & 0xFF]))  # ldy #outer
    d1 = len(code)
    emit(b"\xca")                      # dex
    emit(b"\xd0\xfd")                  # bne d1
    emit(b"\x88")                      # dey
    emit(b"\xd0\xf9")                  # bne d1
    # palette bar loop: colour = loop counter
    emit(b"\xa2" + bytes([iters & 0xFF]))  # ldx #iters
    loop = len(code)
    emit(b"\xa9\x3f\x8d\x06\x20")      # lda #$3F / sta $2006
    emit(b"\xa9\x00\x8d\x06\x20")      # lda #$00 / sta $2006
    emit(b"\x8a")                      # txa
    emit(b"\x8d\x07\x20")              # sta $2007
    emit(b"\xca")                      # dex
    emit(b"\xd0" + bytes([(loop - (len(code) + 2)) & 0xFF]))  # bne loop
    emit(b"\x8d\x07\x20")              # sta $2007 (leave v at $3F00+)
    emit(b"\xa9\x3f\x8d\x06\x20")      # lda #$3F / sta $2006
    emit(b"\xa9\x00\x8d\x06\x20")      # lda #$00 / sta $2006
    spin = len(code)
    emit(b"\x4c" + bytes([spin & 0xFF, 0xC0]))  # jmp spin
    return bytes(code)


def build(delay_rows=20, iters=128, per=23):
    code = assemble(delay_rows, iters, per)
    body = bytearray(b"\xea" * 0x4000)
    body[0x0000:len(code)] = code
    body[0x3FFC] = 0x00
    body[0x3FFD] = 0xC0
    body[0x3FFE] = 0x00
    body[0x3FFF] = 0xC0
    prg = bytes(body) * 2
    return prg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--delay-rows", type=int, default=20)
    ap.add_argument("--iters", type=int, default=128)
    args = ap.parse_args()
    rom = build(args.delay_rows, args.iters)
    img = build_rom(rom, b"", 0, "horizontal", 0, False, 0)
    with open(args.out, "wb") as f:
        f.write(img)
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
