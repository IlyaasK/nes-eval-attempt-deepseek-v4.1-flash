#!/usr/bin/env python3
"""APU mixer probe: sweeps the DMC DAC ($4011 = 0..127, 3 frames each) with all
channels disabled, so the output level directly encodes the mixer's response to
a known digital level.  Comparing the reference's WAV with ours reveals any
mixer curve difference.

Usage: mkapuprobe.py <out.nes>
"""
import struct
import sys

ORIGIN = 0xE000


class Asm:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.fixups = []

    def emit(self, b):
        self.code.extend(b)

    def label(self, name):
        self.labels[name] = len(self.code)

    def branch(self, op, target):
        self.emit(bytes([op]))
        self.fixups.append((len(self.code), target))
        self.emit(b"\x00")

    def resolve(self):
        for pos, target in self.fixups:
            self.code[pos] = (self.labels[target] - (pos + 1)) & 0xFF


def build() -> bytes:
    a = Asm()
    e, br = a.emit, a.branch
    e(b"\x78\xd8\xa2\xff\x9a")              # sei cld ldx #$FF txs
    e(b"\xa9\x00\x8d\x15\x40")              # $4015 = 0 (all channels off)
    e(b"\xa9\x00\x8d\x11\x40")              # $4011 = 0
    e(b"\xa2\x00")                          # X = level
    a.label("outer")
    # wait ~3 frames using the vblank flag
    for i in range(3):
        a.label("w1%d" % i); e(b"\x2c\x02\x20"); br(0x10, "w1%d" % i)
        a.label("w2%d" % i); e(b"\x2c\x02\x20"); br(0x30, "w2%d" % i)
    e(b"\x8e\x11\x40")                      # sta $4011 (X)
    e(b"\xe8")                              # inx
    e(b"\xe0\x80")                          # cpx #$80
    br(0xD0, "outer")
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
