#!/usr/bin/env python3
"""Controller probe: strobes $4016 and shifts in the 8 button bits, drawing each
as a pixel in row 1 (0x30 = pressed, 0x0F = released).  Run with the same key
state on both emulators to compare input latching.

Usage: mkpadprobe.py <out.nes>
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


def build() -> bytes:
    a = Asm(); e, br = a.emit, a.branch
    e(b"\x78\xd8\xa2\xff\x9a")
    e(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    e(b"\xa9\x40\x8d\x17\x40")
    for i in range(3):
        a.label("w1%d" % i); e(b"\x2c\x02\x20"); br(0x10, "w1%d" % i)
        a.label("w2%d" % i); e(b"\x2c\x02\x20"); br(0x30, "w2%d" % i)
    # palette: backdrop 0x0F, colour 1 = 0x30, colour 2 = 0x10
    e(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa9\x0f\x8d\x07\x20\xa9\x30\x8d\x07\x20\xa9\x10\x8d\x07\x20")
    # CHR: tile 0 = colour 1, tile 1 = colour 2
    e(b"\xa9\x00\x8d\x06\x20\x8d\x06\x20")
    for _ in range(8):
        e(b"\xa9\xff\x8d\x07\x20")
    for _ in range(8):
        e(b"\xa9\x00\x8d\x07\x20")
    for _ in range(8):
        e(b"\xa9\x00\x8d\x07\x20")
    for _ in range(8):
        e(b"\xa9\xff\x8d\x07\x20")
    # nametable $2000: 960 zeros, attr 0
    e(b"\xa9\x20\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa0\x04\xa2\x00\xa9\x00")
    a.label("nt"); e(b"\x8d\x07\x20\xe8"); br(0xD0, "nt")
    e(b"\x88"); br(0xD0, "nt2")
    a.label("nt2"); e(b"\xa2\x00"); br(0xD0, "nt")
    # enable rendering (BG + left column)
    e(b"\xa9\x0a\x8d\x01\x20")
    # loop: each frame, strobe the controller, read 8 bits, write them to the
    # nametable row 1 (address $2020..$2027) as tiles 1 or 0.
    a.label("frame")
    # wait for vblank end (start of a frame)
    a.label("v1"); e(b"\x2c\x02\x20"); br(0x10, "v1")
    a.label("v2"); e(b"\x2c\x02\x20"); br(0x30, "v2")
    # strobe
    e(b"\xa9\x01\x8d\x16\x40\xa9\x00\x8d\x16\x40")
    # vram address = $2020
    e(b"\xa9\x20\x8d\x06\x20\xa9\x20\x8d\x06\x20")
    e(b"\xa2\x08")                       # 8 bits
    a.label("bits")
    e(b"\xad\x16\x40")                   # lda $4016
    e(b"\x29\x01")
    e(b"\x8d\x07\x20")                   # sta $2007 (tile 0 or 1)
    e(b"\xca"); br(0xD0, "bits")
    e(b"\x4c" + struct.pack("<H", ORIGIN + 0))
    a.label("spin"); e(b"\x4c" + struct.pack("<H", ORIGIN + len(a.code)))
    # patch the frame jump to `frame`
    a.resolve()
    # fix the 'jmp frame' operand (emitted with a placeholder 0)
    code = a.code
    idx = code.find(b"\x4c\x00\x00")
    if idx >= 0:
        tgt = ORIGIN + a.labels["frame"]
        code[idx + 1] = tgt & 0xFF
        code[idx + 2] = (tgt >> 8) & 0xFF
    prg = bytearray(0x4000)
    prg[0x2000:0x2000 + len(code)] = code
    for v in (0x3FFA, 0x3FFC, 0x3FFE):
        prg[v:v + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([1, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    open(sys.argv[1], "wb").write(build())
    print("wrote", sys.argv[1])
