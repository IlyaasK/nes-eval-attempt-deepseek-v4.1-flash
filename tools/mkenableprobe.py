#!/usr/bin/env python3
"""Render-enable probe: sets up a uniform background, waits a few frames, then
enables rendering at a precise CPU cycle inside a vblank and freezes.  The first
rendered line's leftmost pixels reveal the PPU pipeline's fill state at the
moment rendering starts, which can be compared against the reference.

Usage: mkenableprobe.py <delay_cycles> <out.nes>
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


def build(delay: int) -> bytes:
    a = Asm(); e, br = a.emit, a.branch
    e(b"\x78\xd8\xa2\xff\x9a")                 # sei cld ldx #$FF txs
    e(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")     # $2000 = $2001 = 0
    # wait 3 frames to clear the warm-up and settle
    for i in range(3):
        a.label("w1%d" % i); e(b"\x2c\x02\x20"); br(0x10, "w1%d" % i)
        a.label("w2%d" % i); e(b"\x2c\x02\x20"); br(0x30, "w2%d" % i)
    # CHR RAM: tile 0 = bit0 set (colour 1)
    e(b"\xa9\x00\x8d\x06\x20\x8d\x06\x20")
    e(b"\xa2\x08\xa9\xc0")   # bit0 = 11000000 -> shift-sensitive
    a.label("c1"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c1")
    e(b"\xa2\x08\xa9\x00")
    a.label("c2"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c2")
    # palette: backdrop 0x0F, colour 1 = 0x30
    e(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa9\x0f\x8d\x07\x20\xa9\x30\x8d\x07\x20")
    # nametable $2000: 960 x tile 0, then 64 zeros
    e(b"\xa9\x20\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa0\x03\xa2\x00\xa9\x00")
    a.label("p1"); e(b"\x8d\x07\x20\xe8"); br(0xD0, "p1")
    e(b"\x88"); br(0xD0, "p1b")
    a.label("p1b"); e(b"\xa2\x00"); br(0xD0, "p1")
    e(b"\xa2\x40\xa9\x00")
    a.label("p2"); e(b"\x8d\x07\x20\xca"); br(0xD0, "p2")
    # scroll = 0
    e(b"\xa9\x00\x8d\x05\x20\x8d\x05\x20")
    # wait for vblank (set then clear), then burn `delay` cycles, then enable
    a.label("v1"); e(b"\x2c\x02\x20"); br(0x10, "v1")
    blocks = delay // 1280
    rest = delay - 1280 * blocks
    k = rest // 5
    tail = rest - 5 * k
    if blocks > 0:
        e(b"\xa9" + bytes([blocks]) + b"\x85\x12\xa2\x00")
        a.label("ob"); e(b"\xca"); br(0xD0, "ob")
        e(b"\xc6\x12"); br(0xD0, "ob2")
        a.label("ob2"); br(0xD0, "ob2b")
        a.label("ob2b"); e(b"\xc6\x12"); br(0xD0, "ob")
    if k > 0:
        e(b"\xa2" + bytes([k & 0xFF]))
        a.label("ib"); e(b"\xca"); br(0xD0, "ib")
    e(b"\xca" * 1)
    # enable rendering: $2001 = 0x0A (BG + left 8 pixels shown)
    e(b"\xa9\x0a\x8d\x01\x20")
    a.label("spin"); e(b"\x4c" + struct.pack("<H", ORIGIN + len(a.code)))
    a.resolve()
    prg = bytearray(0x4000)
    prg[0x2000:0x2000 + len(a.code)] = a.code
    for v in (0x3FFA, 0x3FFC, 0x3FFE):
        prg[v:v + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([1, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    d = int(sys.argv[1])
    open(sys.argv[2], "wb").write(build(d))
    print("wrote", sys.argv[2], "delay", d)
