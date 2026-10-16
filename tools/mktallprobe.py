#!/usr/bin/env python3
"""8x16 sprite probe: sprite pattern table $1000, tile 0 = colour 1, tile 1 =
colour 2; one 8x16 sprite (tile index 1 -> table $1000, pair = tiles 0/1).
Compares tall-sprite row/tile selection with the reference.

Usage: mktallprobe.py <y> <x> <flip> <out.nes>
"""
import struct, sys

ORIGIN = 0xE000


class Asm:
    def __init__(self):
        self.code = bytearray(); self.labels = {}; self.fixups = []
    def emit(self, b): self.code.extend(b)
    def label(self, n): self.labels[n] = len(self.code)
    def branch(self, op, t):
        self.emit(bytes([op])); self.fixups.append((len(self.code), t)); self.emit(b"\x00")
    def resolve(self):
        for pos, t in self.fixups:
            self.code[pos] = (self.labels[t] - (pos + 1)) & 0xFF


def build(y: int, x: int, flip: int) -> bytes:
    a = Asm(); e, br = a.emit, a.branch
    e(b"\x78\xd8\xa2\xff\x9a")
    e(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    e(b"\xa9\x40\x8d\x17\x40")
    # wait 3 frames (past warm-up)
    for i in range(3):
        a.label("w1%d" % i); e(b"\x2c\x02\x20"); br(0x10, "w1%d" % i)
        a.label("w2%d" % i); e(b"\x2c\x02\x20"); br(0x30, "w2%d" % i)
    # palette: backdrop 0F, sprite palette 0: 0F, 30 (c1), 10 (c2), 20 (c3)
    e(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    for v in (0x0F, 0x0F, 0x0F, 0x0F, 0x0F, 0x30, 0x10, 0x20):
        e(b"\xa9" + bytes([v]) + b"\x8d\x07\x20")
    e(b"\xa9\x3f\x8d\x06\x20\xa9\x10\x8d\x06\x20")
    for v in (0x0F, 0x30, 0x10, 0x20, 0x0F, 0x0F, 0x0F, 0x0F):
        e(b"\xa9" + bytes([v]) + b"\x8d\x07\x20")
    # CHR $1000-$100F (tile 0) = colour 1, $1010-$101F (tile 1) = colour 2
    e(b"\xa9\x10\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    for _ in range(8):
        e(b"\xa9\xff\x8d\x07\x20")
    for _ in range(8):
        e(b"\xa9\x00\x8d\x07\x20")
    for _ in range(8):
        e(b"\xa9\x00\x8d\x07\x20")
    for _ in range(8):
        e(b"\xa9\xff\x8d\x07\x20")
    # OAM: sprite 0 with tile 1, tall mode
    e(b"\xa9\x00\x8d\x03\x20")
    e(b"\xa9" + bytes([y & 0xFF]) + b"\x8d\x04\x20")
    e(b"\xa9\x01\x8d\x04\x20")
    e(b"\xa9" + bytes([flip & 0xFF]) + b"\x8d\x04\x20")
    e(b"\xa9" + bytes([x & 0xFF]) + b"\x8d\x04\x20")
    for _ in range(63 * 4):
        e(b"\xa9\xff\x8d\x04\x20")
    # enable: $2000 = $20 (8x16 sprites, BG $0000, nametable 0), $2001 = $14 (sprites + left col)
    e(b"\xa9\x20\x8d\x00\x20")
    e(b"\xa9\x14\x8d\x01\x20")
    a.label("spin"); e(b"\x4c" + struct.pack("<H", ORIGIN + len(a.code)))
    a.resolve()
    prg = bytearray(0x4000)
    prg[0x2000:0x2000 + len(a.code)] = a.code
    for v in (0x3FFA, 0x3FFC, 0x3FFE):
        prg[v:v + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([1, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    y, x, fl = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
    open(sys.argv[4], "wb").write(build(y, x, fl))
    print("wrote", sys.argv[4])
