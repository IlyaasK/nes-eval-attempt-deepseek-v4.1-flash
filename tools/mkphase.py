#!/usr/bin/env python3
"""Phase probe: measure which pixel column a CPU write to palette RAM affects,
so the CPU<->PPU sub-cycle alignment can be compared with the reference.

Rendering is enabled with an all-transparent background, so the whole screen
shows the backdrop colour (palette[0]).  After waiting for the VBL, the ROM
spends a calibrated number of cycles and then writes palette[0] once; the
resulting colour boundary column reveals the exact dot at which the write took
effect.

Usage: mkphase.py <delay_cycles> <out.nes>
"""
import struct
import sys

ORIGIN = 0xC000


def build(delay: int) -> bytes:
    code = bytearray()

    def emit(b):
        code.extend(b)

    def bne(target):
        emit(b"\xd0")
        emit(bytes([(target - (len(code) + 1)) & 0xFF]))

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    # burn ~40000 cycles (past the PPU warm-up)
    emit(b"\xa9\x1f\x85\x12")            # $12 = 31 (~40k cycles)
    outer = len(code)
    emit(b"\xa2\x00")                    # ldx #0
    inner = len(code)
    emit(b"\xca")
    bne(inner)
    emit(b"\xc6\x12")
    bne(outer)
    # palette[0] = black before the real test, and enable rendering
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    emit(b"\xa9\x0f\x8d\x07\x20")        # palette[0] = $0F
    emit(b"\xa9\x0a\x8d\x01\x20")        # rendering on (BG)
    # loop: wait for VBL, delay, write palette[0] = $30
    emit(b"\xa9\x30\x85\x13")            # $13 = the colour to write
    loop = len(code)
    emit(b"\x2c\x02\x20\x10\xfb")        # bit $2002 / bpl
    # calibrated delay: nested blocks of 16*1290 cycles plus a 5-cycle tail
    per16 = 16 * (255 * 5 + 2 + 5 + 3) + 2 + 5 + 3
    outer_blocks = delay // per16
    rest = delay - outer_blocks * per16
    per_outer = 255 * 5 + 2 + 5 + 3
    blocks = rest // per_outer
    rest2 = rest - blocks * per_outer
    k = rest2 // 5
    tail = rest2 - 5 * k
    if outer_blocks > 0:
        if outer_blocks > 255:
            raise SystemExit("delay too large")
        emit(b"\xa9" + bytes([outer_blocks]) + b"\x85\x15")
        oouter = len(code)
        emit(b"\xa9" + bytes([16]) + b"\x85\x14")
        outer = len(code)
        emit(b"\xa2\xff")
        inner = len(code)
        emit(b"\xca")
        bne(inner)
        emit(b"\xc6\x14")
        bne(outer)
        emit(b"\xc6\x15")
        bne(oouter)
    if blocks > 0:
        emit(b"\xa9" + bytes([blocks]) + b"\x85\x14")
        outer = len(code)
        emit(b"\xa2\xff")
        inner = len(code)
        emit(b"\xca")
        bne(inner)
        emit(b"\xc6\x14")
        bne(outer)
    if k > 0:
        emit(b"\xa2" + bytes([k & 0xFF]))
        top = len(code)
        emit(b"\xca")
        bne(top)
    for _ in range(tail // 2):
        emit(b"\xea")                    # nop (2 cycles)
    if tail % 2:
        emit(b"\xa5\x13")                # lda $13 (3 cycles) - odd residue
    # v = $3F00 and write the palette entry
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    emit(b"\xa5\x13\x8d\x07\x20")        # sta $2007
    emit(b"\x4c" + struct.pack("<H", ORIGIN + loop))
    prg = bytearray(0x8000)
    off = ORIGIN - 0x8000
    assert off + len(code) < 0x8000
    prg[off:off + len(code)] = code
    for a in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[a:a + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    delay = int(sys.argv[1])
    out = sys.argv[2]
    open(out, "wb").write(build(delay))
    print("wrote", out, "delay", delay)
