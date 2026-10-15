#!/usr/bin/env python3
"""mkframe.py -- build a frame-phase probe ROM (mapper 0, NROM-256, CHR RAM).

The ROM shows the current frame counter as the backdrop colour: it waits for
the VBL flag, increments a counter, and writes the counter to palette entry 0.
Frame N of the reference therefore shows colour (start + N + k) for a fixed k
depending on the emulator's frame boundary, which lets us compare frame phase
against the reference exactly.

Usage: mkframe.py OUT.nes [--delay N] [--start C]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mkrom import build_rom  # noqa: E402


def assemble(delay=0, start=0):
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
    emit(b"\xa9" + bytes([start]))     # lda #start
    emit(b"\x85\x10")                  # sta $10
    for _ in range(delay):             # ldx #1 / dex / bne ($0 cycles total)
        emit(b"\xa2\x01\xca\xd0\xfd")
    wait = len(code)
    emit(b"\x2c\x02\x20")              # bit $2002
    emit(b"\x10\xfb")                  # bpl wait
    emit(b"\xa9\x3f\x8d\x06\x20")      # lda #$3F / sta $2006
    emit(b"\xa9\x00\x8d\x06\x20")      # lda #$00 / sta $2006
    emit(b"\xe6\x10")                  # inc $10
    emit(b"\xa5\x10")                  # lda $10
    emit(b"\x8d\x07\x20")              # sta $2007
    emit(b"\xa9\x3f\x8d\x06\x20")      # lda #$3F / sta $2006
    emit(b"\xa9\x00\x8d\x06\x20")      # lda #$00 / sta $2006
    emit(b"\x4c" + bytes([wait & 0xFF, 0xC0]))  # jmp wait
    return bytes(code)


def build(delay=0, start=0):
    code = assemble(delay, start)
    prg = bytearray(b"\xff" * 0x4000)
    body = bytearray(b"\xea" * 0x4000)
    body[0x0000:len(code)] = code
    body[0x3FFC] = 0x00
    body[0x3FFD] = 0xC0
    body[0x3FFE] = 0x00
    body[0x3FFF] = 0xC0
    prg[0x0000:0x4000] = body
    prg[0x4000:0x8000] = body
    assert len(prg) == 0x8000
    return bytes(prg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--delay", type=int, default=0)
    ap.add_argument("--start", type=lambda s: int(s, 0), default=0)
    args = ap.parse_args()
    rom = build(args.delay, args.start)
    img = build_rom(rom, b"", 0, "horizontal", 0, False, 0)
    with open(args.out, "wb") as f:
        f.write(img)
    print("wrote %s (%d bytes)" % (args.out, len(img)))


if __name__ == "__main__":
    main()
