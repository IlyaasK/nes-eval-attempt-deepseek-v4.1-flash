#!/usr/bin/env python3
"""Single-read vblank probe: burn `burn` CPU cycles after power-on, read $2002
exactly once, then paint palette[0] white if bit 7 was set, black otherwise.
Sweeping `burn` maps the exact CPU cycle at which the vblank flag becomes
visible (and where a read suppresses it) for comparison with the reference.

Usage: mkvbl1.py <burn_cycles> <out.nes>
"""
import struct
import sys

ORIGIN = 0xC000


def build(burn: int, origin=ORIGIN) -> bytes:
    code = bytearray()

    def emit(b):
        code.extend(b)

    def bne(target):
        emit(b"\xd0")
        emit(bytes([(target - (len(code) + 1)) & 0xFF]))

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    # Burn exactly `burn` cycles after the 15 cycles emitted so far is not
    # required; the caller sweeps relative values.
    blocks = burn // 1280
    rest = burn - 1280 * blocks
    k = rest // 5
    tail = rest - 5 * k
    tail_instr = []
    if tail % 2 == 1:
        tail_instr.append(b"\xa5\x10")       # lda $10 : 3 cycles
        tail -= 3
    tail_instr.append(b"\xea" * (tail // 2))
    if blocks > 0:
        if blocks > 255:
            raise SystemExit("burn too large")
        emit(b"\xa9" + bytes([blocks]))
        emit(b"\x85\x12")
        outer = len(code)
        emit(b"\xa2\x00")
        inner = len(code)
        emit(b"\xca"); bne(inner)
        emit(b"\xc6\x12")
        bne(outer)
    if k > 0:
        emit(b"\xa2" + bytes([k & 0xFF]))
        top = len(code)
        emit(b"\xca"); bne(top)
    for ins in tail_instr:
        emit(ins)
    emit(b"\xad\x02\x20")                    # lda $2002 (single read)
    emit(b"\x29\x80")                        # and #$80
    beq_black = len(code)
    emit(b"\xf0\x00")                        # beq black (patched)
    emit(b"\xa9\x30")                        # lda #$30 (white)
    jmp_store = len(code)
    emit(b"\xd0\x00")                        # bne store (patched)
    black = len(code)
    emit(b"\xa9\x0f")                        # lda #$0F (black)
    store = len(code)
    code[beq_black + 1] = (black - (beq_black + 2)) & 0xFF
    code[jmp_store + 1] = (store - (jmp_store + 2)) & 0xFF
    emit(b"\xa2\x3f\x8e\x06\x20\xa2\x00\x8e\x06\x20")  # $2006 = $3F00
    emit(b"\x8d\x07\x20")                    # sta $2007
    spin = len(code)
    emit(b"\x4c" + struct.pack("<H", origin + spin))
    prg = bytearray(0x8000)
    off = origin - 0x8000
    assert off + len(code) <= 0x8000
    prg[off:off + len(code)] = code
    for a in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[a:a + 2] = struct.pack("<H", origin)
    return b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    burn = int(sys.argv[1])
    out = sys.argv[2]
    open(out, "wb").write(build(burn))
    print("wrote", out, "burn", burn)
