#!/usr/bin/env python3
"""Frame-boundary probe: rendering stays off (so the framebuffer is filled with
the backdrop), the palette backdrop is changed after a fixed delay, and the
CPU then spins in a pure NOP loop.  The frame that first shows the new backdrop
in a row's leading pixels reveals how many PPU dots past the 261->0 boundary the
emulator processed before run_frame returned.

Usage: mkboundprobe.py <init_nops> <out.nes>
"""
import struct
import sys

ORIGIN = 0xE000


def build(init_nops: int) -> bytes:
    code = bytearray()

    def e(b):
        code.extend(b)

    e(b"\x78\xd8\xa2\xff\x9a")                 # sei, cld, ldx #$FF, txs
    e(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")     # $2000 = $2001 = 0
    # burn ~30000 cycles: $2006 writes are ignored during PPU warm-up
    for _ in range(2):
        e(b"\xa0\xff")                          # ldy #$FF
        e(b"\xa2\xff")                          # w1: ldx #$FF
        e(b"\xca")                              # w2: dex
        e(b"\xd0\xfd")                          # bne w2
        e(b"\x88")                              # dey
        e(b"\xd0\xf8")                          # bne w1
    # palette: $3F00 = $0F (backdrop), $3F01 = $30 (colour 1)
    e(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20\xa9\x0f\x8d\x07\x20\xa9\x30\x8d\x07\x20")
    # CHR tile 1 low plane = $AA (alternating columns), high plane = 0
    e(b"\xa9\x00\x8d\x06\x20\xa9\x10\x8d\x06\x20")
    for _ in range(8):
        e(b"\xa9\xaa\x8d\x07\x20")
    for _ in range(8):
        e(b"\xa9\x00\x8d\x07\x20")
    # nametable: 960 bytes of tile 1 (lo), then attributes = 0
    e(b"\xa9\x20\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    e(b"\xa0\x04\xa2\x00\xa9\x01")          # y=4 pages, x=0, A=1
    e(b"\x8d\x07\x20\xe8")                    # nt: sta $2007 / inx
    e(b"\xd0\xf8")                              #   bne nt
    e(b"\x88")
    e(b"\xd0\xf2")                              # nt2: dey / bne nt2
    e(b"\xa2\x40\xa9\x00")                    # 64 attribute bytes = 0
    e(b"\x8d\x07\x20\xca")
    e(b"\xd0\xfa")
    e(b"\xa9\x0a\x8d\x01\x20")                # enable BG rendering
    # phase control
    for _ in range(init_nops):
        e(b"\xea")
    # ~11 frames of delay, twice
    for _ in range(2):
        e(b"\xa0\xff")                          # ldy #$FF
        e(b"\xa2\xff")                          # outer: ldx #$FF
        e(b"\xca")                              # inner: dex
        e(b"\xd0\xfd")                          # bne inner
        e(b"\x88")                              # dey
        e(b"\xd0\xf8")                          # bne outer
    # palette $3F00 = $10
    e(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20\xa9\x10\x8d\x07\x20")
    spin = len(code)
    e(b"\x4c" + struct.pack("<H", ORIGIN + spin))   # jmp spin
    prg = bytearray(0x4000)
    prg[0x2000:0x2000 + len(code)] = code
    for v in (0x3FFA, 0x3FFC, 0x3FFE):
        prg[v:v + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([1, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    n = int(sys.argv[1])
    open(sys.argv[2], "wb").write(build(n))
    print("wrote", sys.argv[2], "init_nops", n)
