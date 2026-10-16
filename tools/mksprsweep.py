#!/usr/bin/env python3
"""Sprite X sweep probe (8 sprites at x..x+7): uploads a solid sprite tile, places sprites at
chosen positions, and renders them, so sprite placement/shape/priority can be
compared with the reference.

Usage: mksprite.py <x> <y> <out.nes>
"""
import struct
import sys

ORIGIN = 0xC000


def build(x: int, y: int, attr: int = 0, second=False) -> bytes:
    code = bytearray()

    def emit(b):
        code.extend(b)

    def bne(target):
        emit(b"\xd0")
        emit(bytes([(target - (len(code) + 1)) & 0xFF]))

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    # burn ~40000 cycles
    emit(b"\xa9\x1f\x85\x12")
    outer = len(code)
    emit(b"\xa2\x00")
    inner = len(code)
    emit(b"\xca")
    bne(inner)
    emit(b"\xc6\x12")
    bne(outer)
    # palette: entry 0 = $0F, sprite palette 0 colour 1..3 = $30,$10,$20
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    for v in (0x0F, 0x0F, 0x0F, 0x0F, 0x30, 0x10, 0x20, 0x0F):
        emit(b"\xa9" + bytes([v]) + b"\x8d\x07\x20")   # writes $3F00..$3F07
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x10\x8d\x06\x20")
    for v in (0x0F, 0x30, 0x10, 0x20, 0x0F, 0x0F, 0x0F, 0x0F):
        emit(b"\xa9" + bytes([v]) + b"\x8d\x07\x20")   # writes $3F10..$3F17
    # CHR: tile 1 at $1000 = solid colour 1 (lo plane $FF, hi plane 0)
    emit(b"\xa9\x10\x8d\x06\x20\xa9\x10\x8d\x06\x20")   # vram $1010 (tile 1)
    for _ in range(8):
        emit(b"\xa9\xff\x8d\x07\x20")
    for _ in range(8):
        emit(b"\xa9\x00\x8d\x07\x20")
    # OAM: 8 sprites; sprite i at (x+i, 16*(i+1)), tile 1, attr 0
    emit(b"\xa9\x00\x8d\x03\x20")                       # OAMADDR = 0
    for i in range(8):
        emit(b"\xa9" + bytes([(16 * (i + 1)) & 0xFF]) + b"\x8d\x04\x20")
        emit(b"\xa9\x01\x8d\x04\x20")
        emit(b"\xa9\x00\x8d\x04\x20")
        emit(b"\xa9" + bytes([(x + i) & 0xFF]) + b"\x8d\x04\x20")
    # clear the rest of OAM to y=$FF
    for _ in range(56):
        emit(b"\xa9\xff\x8d\x04\x20")
        emit(b"\xa9\x00\x8d\x04\x20")
        emit(b"\xa9\x00\x8d\x04\x20")
        emit(b"\xa9\x00\x8d\x04\x20")
    # enable sprites + BG, sprite pattern table $1000, NMI off
    emit(b"\xa9\x18\x8d\x00\x20")       # ctrl: sprite pattern = $1000, bg = $1000
    emit(b"\xa9\x1e\x8d\x01\x20")       # mask: show bg+sprites, no clipping
    spin = len(code)
    emit(b"\x4c" + struct.pack("<H", ORIGIN + spin))
    prg = bytearray(0x8000)
    off = ORIGIN - 0x8000
    assert off + len(code) < 0x8000
    prg[off:off + len(code)] = code
    for a in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[a:a + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    x, y = int(sys.argv[1]), 0
    out = sys.argv[2]
    second = False
    attr = 0
    open(out, "wb").write(build(x, y, attr, second))
    print("wrote", out, "x", x, "y", y)
