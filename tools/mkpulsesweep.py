#!/usr/bin/env python3
"""Pulse mixer-curve probe: holds pulse 1 at a fixed ~110 Hz duty-2 square wave
while stepping its constant volume 0..15 (3 frames each, twice).  The observed
plateau amplitudes give the mixer's response to each pulse DAC level.

Usage: mkpulsesweep.py <out.nes>
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
    e(b"\xa9\x00\x8d\x15\x40")
    e(b"\xa9\x40\x8d\x17\x40")
    e(b"\xa9\x01\x8d\x15\x40")          # enable pulse 1 first (length loads)
    e(b"\xa9\xbf\x8d\x00\x40")          # duty 2, halt, const volume 15
    e(b"\xa9\x08\x8d\x01\x40")          # sweep off
    e(b"\xa9\xf8\x8d\x02\x40")          # period low
    e(b"\xa9\x03\x8d\x03\x40")          # period high
    e(b"\xa2\x00")                      # X = volume
    a.label("outer")
    for i in range(2):
        a.label("w1%d" % i); e(b"\x2c\x02\x20"); br(0x10, "w1%d" % i)
        a.label("w2%d" % i); e(b"\x2c\x02\x20"); br(0x30, "w2%d" % i)
    e(b"\x8a")                          # txa
    e(b"\x09\xb0")                      # ora #$B0  (duty 2, halt, const vol)
    e(b"\x8d\x00\x40")                  # sta $4000
    e(b"\xe8")                          # inx
    e(b"\xe0\x10")                      # cpx #$10
    br(0xD0, "outer")
    e(b"\xa2\x00")                      # second pass
    a.label("outer2")
    for i in range(2):
        a.label("v1%d" % i); e(b"\x2c\x02\x20"); br(0x10, "v1%d" % i)
        a.label("v2%d" % i); e(b"\x2c\x02\x20"); br(0x30, "v2%d" % i)
    e(b"\x8a"); e(b"\x09\xb0"); e(b"\x8d\x00\x40")
    e(b"\xe8"); e(b"\xe0\x10")
    br(0xD0, "outer2")
    a.label("spin"); e(b"\x4c" + struct.pack("<H", ORIGIN + len(a.code)))
    a.resolve()
    prg = bytearray(0x4000)
    prg[0x2000:0x2000 + len(a.code)] = a.code
    for v in (0x3FFA, 0x3FFC, 0x3FFE):
        prg[v:v + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([1, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    open(sys.argv[1], "wb").write(build())
    print("wrote", sys.argv[1])
