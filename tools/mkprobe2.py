#!/usr/bin/env python3
"""Probe builder with a memory-based loop counter (bodies may clobber X/Y)."""
import struct
import sys


def build(body, iters, setup=b""):
    code = bytearray()

    def emit(b):
        code.extend(b)

    def bne(target):
        emit(b"\xd0")
        emit(bytes([(target - (len(code) + 1)) & 0xFF]))

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    emit(setup)
    emit(bytes([0xa9, iters & 0xFF, 0x85, 0x14]))       # $14 = low counter
    emit(bytes([0xa9, (iters >> 8) & 0xFF, 0x85, 0x15]))  # $15 = high counter
    top = len(code)
    emit(body)
    emit(b"\xc6\x14")
    emit(b"\xd0")                                        # bne top (low byte)
    emit(bytes([(top - (len(code) + 1)) & 0xFF]))
    emit(b"\xc6\x15")
    bne(top)
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20\xa9\x3f\x8d\x07\x20")
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    spin = len(code)
    emit(b"\x4c" + struct.pack("<H", 0xC000 + spin))
    prg = bytearray(b"\x00" * 0x8000)
    off = 0xC000 - 0x8000
    prg[off:off + len(code)] = code
    for a in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[a:a + 2] = struct.pack("<H", 0xC000)
    return b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    name, out = sys.argv[1], sys.argv[2]
    iters = int(sys.argv[3]) if len(sys.argv) > 3 else 12000
    BODIES = {
        "absx_pc": b"\xbd\xff\x00\xe8",
        "absx_nc": b"\xbd\x00\x00\xe8",
        "absy_pc": b"\xb9\xff\x00\xc8",
        "sta_absx": b"\x9d\x00\x04\xe8",
        "rmw_absx": b"\xfe\x00\x04\xe8",
        "lda_indx": b"\xa1\x10\xe8",
        "rmw_zpx": b"\xf6\x10\xe8",
        "lda_zpx": b"\xb5\x10\xe8",
        "nop_absx": b"\x1c\x00\x04\xe8",
        "jsr_rts": b"\x20\x00\x90\x60",
        "rmw_indy": b"\xf3\x10\xc8",
        "sha_absy": b"\x9f\x00\x04\xc8",
        "bit_abs": b"\x2c\x00\x04",
        "cpx_zp": b"\xe4\x10",
        "asl_acc": b"\x0a",
        "inc_indx": b"\xe3\x10\xe8",
    }
    open(out, "wb").write(build(BODIES[name], iters))
    print("wrote", out, name, iters)
