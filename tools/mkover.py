#!/usr/bin/env python3
"""mkover.py -- sprite overflow probe (mapper 0, NROM-256, CHR RAM).

OAM is filled with N sprites whose Y is a chosen value; the rest get a
non-matching Y.  After the pre-render clears the flags, the ROM polls $2002
until a flag appears and paints the backdrop white (vblank seen first) or
black (sprite overflow seen first).

Usage: mkover.py OUT.nes [--count N] [--y 0xFF] [--rest 0xF0]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mkrom import build_rom  # noqa: E402


def assemble(count, y, rest):
    code = bytearray()

    def emit(b):
        code.extend(b)

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    # OAM: sprite i Y = y for i < count, rest otherwise; X=0 tile=0 attr=0
    emit(b"\xa2\x00")                       # ldx #0
    fill = len(code)
    emit(b"\x8a\x4a\x4a\x29\x3f")           # txa / lsr lsr / and #$3F  (n = x>>2)
    emit(b"\xc9" + bytes([count]))          # cmp #count
    emit(b"\x90\x02")                       # bcc +2 (skip 2-byte lda)
    emit(b"\xa9" + bytes([rest]))
    emit(b"\x9d\x00\x02")                   # sta $0200,x
    emit(b"\xe8\xd0")                       # inx / bne fill
    emit(bytes([(fill - (len(code) + 1)) & 0xFF]) )
    # set the Y bytes for i < count to `y`
    emit(b"\xa2\x00")
    yl = len(code)
    emit(b"\x8a\x4a\x4a")                   # txa >> 2 = index
    emit(b"\xc9" + bytes([count]))
    emit(b"\xb0\x03")                       # bcs +3 -> done-ish
    emit(b"\xa9" + bytes([y]))
    emit(b"\x9d\x00\x02")
    emit(b"\xe8\xd0")
    emit(bytes([(yl - (len(code) + 1)) & 0xFF]))
    emit(b"\x20\x00\x02")                   # jsr $0200  (no-op filler, harmless)
    return bytes(code)


def assemble_full(count, y, rest):
    code = bytearray()

    def emit(b):
        code.extend(b)

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    # palette: [0] = $0F (black) default; change to $3F (white) if vblank wins
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20\xa9\x0f\x8d\x07\x20")
    # fill OAM: 64 sprites, Y = rest, X=0, tile=0, attr=0
    for i in range(64):
        addr = i * 4
        emit(b"\xa9" + bytes([rest]))
        emit(b"\x8d\x00\x02" if addr == 0 else b"\x8d" + bytes([addr & 0xFF, 0x02]))
    # first `count` sprites get Y = y
    for i in range(count):
        addr = i * 4
        emit(b"\xa9" + bytes([y]))
        emit(b"\x8d" + bytes([addr & 0xFF, 0x02]))
    # wait for 2 vblanks (warm-up), then do the measurement each frame
    for _ in range(2):
        w = len(code)
        emit(b"\x2c\x02\x20\x10\xfb")
    loop = len(code)
    # wait for vblank then for pre-render clear: use $2002 polling
    w1 = len(code)
    emit(b"\x2c\x02\x20\x30")               # bit $2002 / bmi w1
    emit(bytes([(w1 - (len(code) + 1)) & 0xFF]))
    # OAM DMA
    emit(b"\xa9\x00\x8d\x03\x20\xa9\x02\x8d\x14\x40")
    # now poll until a flag appears
    p = len(code)
    emit(b"\x2c\x02\x20")                   # bit $2002
    emit(b"\xf0")                           # beq p
    emit(bytes([(p - (len(code) + 1)) & 0xFF]))
    # which bit?  bit 6 = overflow (keep black), bit 7 = vblank (paint white)
    emit(b"\x50\x04")                       # bvc +4 -> overflow: keep black... (V=bit6)
    # vblank/when bit7 set: paint white
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20\xa9\x3f\x8d\x07\x20")
    emit(b"\x4c" + bytes([loop & 0xFF, 0xC0]))
    return bytes(code)


def build(count, y, rest):
    code = assemble_full(count, y, rest)
    body = bytearray(b"\xea" * 0x4000)
    body[0x0000:len(code)] = code
    body[0x3FFC] = 0x00
    body[0x3FFD] = 0xC0
    body[0x3FFE] = 0x00
    body[0x3FFF] = 0xC0
    return bytes(body) * 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--count", type=int, default=9)
    ap.add_argument("--y", type=lambda s: int(s, 0), default=0xFF)
    ap.add_argument("--rest", type=lambda s: int(s, 0), default=0xF0)
    args = ap.parse_args()
    rom = build(args.count, args.y, args.rest)
    with open(args.out, "wb") as f:
        f.write(build_rom(rom, b"", 0, "horizontal", 0, False, 0))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
