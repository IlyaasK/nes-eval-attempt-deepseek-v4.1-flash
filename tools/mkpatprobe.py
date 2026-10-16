#!/usr/bin/env python3
"""Pattern-table probe: fills CHR RAM with distinct tiles in tables $0000 and
$1000, sets $2000 = $08 (docs: BG table $1000, sprites $0000), fills the
nametable with tile 1, and displays.  The screen colour reveals which table the
background actually fetches from.

Usage: mkpatprobe.py <out.nes>
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
            off = (self.labels[target] - (pos + 1)) & 0xFF
            self.code[pos] = off


def build() -> bytes:
    a = Asm()
    e, br = a.emit, a.branch
    e(b"\x78\xd8\xa2\xff\x9a")                    # sei cld ldx #$FF txs
    e(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")        # $2000 = $2001 = 0
    for i in range(3):
        a.label("w1%d" % i); e(b"\x2c\x02\x20"); br(0x10, "w1%d" % i)
        a.label("w2%d" % i); e(b"\x2c\x02\x20"); br(0x30, "w2%d" % i)
    # CHR table $0000: 16 zeros, then tile 1 = 8 x $FF, 8 x $00
    e(b"\xa9\x00\x8d\x06\x20\x8d\x06\x20")
    e(b"\xa2\x10\xa9\x00")
    a.label("c1"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c1")
    e(b"\xa2\x08\xa9\xff")
    a.label("c2"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c2")
    e(b"\xa2\x08\xa9\x00")
    a.label("c3"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c3")
    # CHR table $1000: tile 1 = 8 x $00, 8 x $FF
    e(b"\xa9\x10\x8d\x06\x20\xa9\x10\x8d\x06\x20")
    e(b"\xa2\x08\xa9\x00")
    a.label("c4"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c4")
    e(b"\xa2\x08\xa9\xff")
    a.label("c5"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c5")
    # palette $3F00 = 0F 30 16
    e(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa9\x0f\x8d\x07\x20\xa9\x30\x8d\x07\x20\xa9\x16\x8d\x07\x20")
    # nametable $2000: 960 x tile 1 then 64 x 0
    e(b"\xa9\x20\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa0\x03")                                # y = 3
    a.label("page"); e(b"\xa2\x00\xa9\x01")
    a.label("pg"); e(b"\x8d\x07\x20\xe8"); br(0xD0, "pg")
    e(b"\x88"); br(0xD0, "page")
    e(b"\xa2\xc0\xa9\x01")                        # 192 more
    a.label("pg2"); e(b"\x8d\x07\x20\xca"); br(0xD0, "pg2")
    e(b"\xa2\x40\xa9\x00")                        # 64 zeros (attribute)
    a.label("pg3"); e(b"\x8d\x07\x20\xca"); br(0xD0, "pg3")
    # scroll 0, $2000 = $08, $2001 = $0A
    e(b"\xa9\x00\x8d\x05\x20\xa9\x00\x8d\x05\x20")
    e(b"\xa9\x08\x8d\x00\x20\xa9\x0a\x8d\x01\x20")
    a.label("spin"); e(b"\x4c" + struct.pack("<H", ORIGIN + len(a.code)))
    a.resolve()
    prg = bytearray(0x4000)
    assert len(a.code) < 0x2000, len(a.code)
    prg[0x2000:0x2000 + len(a.code)] = a.code
    for v in (0x3FFA, 0x3FFC, 0x3FFE):
        prg[v:v + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([1, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    open(sys.argv[1], "wb").write(build())
    print("wrote", sys.argv[1])
