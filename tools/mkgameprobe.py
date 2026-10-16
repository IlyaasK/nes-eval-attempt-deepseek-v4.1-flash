#!/usr/bin/env python3
"""Game-like enable probe: waits a few frames with rendering off, then during a
vblank runs the register sequence games use ($2006 x2, $2005 x2, $2000, $2001)
and freezes.  Compares the first rendered line's pipeline fill.

Usage: mkgameprobe.py <delay_cycles> <out.nes>
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
    e(b"\x78\xd8\xa2\xff\x9a")
    e(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    e(b"\xa9\x40\x8d\x17\x40")   # $4017 = $40: 4-step, IRQ inhibited
    for i in range(3):
        a.label("w1%d" % i); e(b"\x2c\x02\x20"); br(0x10, "w1%d" % i)
        a.label("w2%d" % i); e(b"\x2c\x02\x20"); br(0x30, "w2%d" % i)
    # CHR: tile 0 pattern bit0 = 11000000, bit1 = 0; tile1 pattern = 00111100
    e(b"\xa9\x00\x8d\x06\x20\x8d\x06\x20")
    e(b"\xa2\x08\xa9\xc0")
    a.label("c1"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c1")
    e(b"\xa2\x08\xa9\x00")
    a.label("c2"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c2")
    e(b"\xa2\x08\xa9\x3c")                      # tile 1 bit0
    a.label("c3"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c3")
    e(b"\xa2\x08\xa9\x00")
    a.label("c4"); e(b"\x8d\x07\x20\xca"); br(0xD0, "c4")
    # palette: 0F 30 16 27
    e(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa9\x0f\x8d\x07\x20\xa9\x30\x8d\x07\x20\xa9\x16\x8d\x07\x20\xa9\x27\x8d\x07\x20")
    # nametable: row 0 = tile 0 x32, then zeros
    e(b"\xa9\x20\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa2\x20\xa9\x00")                       # 32 x tile 0
    a.label("n1"); e(b"\x8d\x07\x20\xca"); br(0xD0, "n1")
    e(b"\xa9\x01")                               # tile 1 for the 2nd tile
    e(b"\x8d\x07\x20")
    e(b"\xa2\x1f\xa9\x00")
    a.label("n2"); e(b"\x8d\x07\x20\xca"); br(0xD0, "n2")
    e(b"\xa0\x03\xa2\x00\xa9\x00")
    a.label("n3"); e(b"\x8d\x07\x20\xe8"); br(0xD0, "n3")
    e(b"\x88"); br(0xD0, "n3b")
    a.label("n3b"); e(b"\xa2\x00"); br(0xD0, "n3")
    e(b"\xa2\x40\xa9\x00")
    a.label("n4"); e(b"\x8d\x07\x20\xca"); br(0xD0, "n4")
    # wait for vblank set, burn `delay`, then the game-like sequence
    a.label("v1"); e(b"\x2c\x02\x20"); br(0x10, "v1")
    blocks = delay // 1280
    rest = delay - 1280 * blocks
    k = rest // 5
    tail = rest - 5 * k
    if blocks > 0:
        e(b"\xa9" + bytes([blocks]) + b"\x85\x12\xa2\x00")
        a.label("ob"); e(b"\xca"); br(0xD0, "ob")
        e(b"\xc6\x12"); br(0xD0, "ob")
    if k > 0:
        e(b"\xa2" + bytes([k & 0xFF]))
        a.label("ib"); e(b"\xca"); br(0xD0, "ib")
    e(b"\xa9" * 0)
    # $2006 = 0, $2006 = 0, $2005 = 0, $2005 = 0, $2000 = $88, $2001 = $1E
    e(b"\xa9\x00\x8d\x06\x20\x8d\x06\x20")
    e(b"\x8d\x05\x20\x8d\x05\x20")
    e(b"\xa9\x88\x8d\x00\x20")
    e(b"\xa9\x1e\x8d\x01\x20")
    endspin = len(a.code)
    e(b"\x4c\x00\x00")                 # jmp spin (patched below)
    # NMI handler: plain RTI (the game-like sequence enables NMI).
    a.label("nmi"); e(b"\x40")
    a.label("spin"); e(b"\x4c" + struct.pack("<H", ORIGIN + len(a.code)))
    spin_addr = ORIGIN + a.labels["spin"]
    a.code[endspin + 1] = spin_addr & 0xFF
    a.code[endspin + 2] = (spin_addr >> 8) & 0xFF
    a.resolve()
    prg = bytearray(0x4000)
    prg[0x2000:0x2000 + len(a.code)] = a.code
    for v in (0x3FFC, 0x3FFE):
        prg[v:v + 2] = struct.pack("<H", ORIGIN)
    prg[0x3FFA:0x3FFC] = struct.pack("<H", ORIGIN + a.labels["nmi"])
    return b"NES\x1a" + bytes([1, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    d = int(sys.argv[1])
    open(sys.argv[2], "wb").write(build(d))
    print("wrote", sys.argv[2], "delay", d)
