#!/usr/bin/env python3
"""CPU semantics probe: runs a battery of instructions and encodes a 16-bit
checksum of (A, X, Y, P) after each into palette entry 0 (low byte) and a
second ROM (high byte).  Comparing them against the reference finds semantic
differences in instruction behaviour.

Usage: mkprobe3.py <battery-name> <low|high> <out.nes>
"""
import struct
import sys

# ---- the test battery -------------------------------------------------------
# Each test: (setup bytes, instruction bytes). Setup runs before the instruction
# every iteration; the instruction's result is accumulated.
TESTS = {}


def add(name, setup, ins):
    TESTS[name] = (setup, ins)


# ADC / SBC flag behaviour (V, C, N, Z) with tricky operands
for nm, ins in [("adc_imm", b"\x69"), ("sbc_imm", b"\xE9")]:
    for a, v in [(0x7F, 0x01), (0x80, 0xFF), (0x00, 0x00), (0xF0, 0x10), (0x0F, 0x01),
                 (0xFF, 0x01), (0x50, 0x50), (0xAA, 0x55)]:
        add("%s_%02X%02X" % (nm, a, v), bytes([0xA9, a, 0x18]), bytes([ins[0], v]))
        add("%s_c_%02X%02X" % (nm, a, v), bytes([0xA9, a, 0x38]), bytes([ins[0], v]))

# CMP/CPX/CPY
for reg, ins in [("a", 0xC9), ("x", 0xE0), ("y", 0xC0)]:
    for a, v in [(0x00, 0x00), (0x80, 0x7F), (0x7F, 0x80), (0xFF, 0x01)]:
        setup = bytes([0xA9, a, 0xAA, 0xA8])
        add("cmp_%s_%02X%02X" % (reg, a, v), setup, bytes([ins, v]))

# BIT
for a, v in [(0xF0, 0x40), (0x0F, 0x80), (0x00, 0xC0), (0xFF, 0x01)]:
    add("bit_%02X%02X" % (a, v), bytes([0xA9, a, 0x85, 0x20]), bytes([0x24, 0x20]))

# shifts/rotates on A and memory
for nm, ins in [("asl", 0x0A), ("lsr", 0x4A), ("rol", 0x2A), ("ror", 0x6A)]:
    for a, c in [(0x80, 0x18), (0x01, 0x18), (0x00, 0x38), (0xFF, 0x38), (0x55, 0x18)]:
        add("%s_a_%02X%02X" % (nm, a, c), bytes([0xA9, a, c]), bytes([ins]))
        add("%s_m_%02X%02X" % (nm, a, c), bytes([0xA9, a, 0x85, 0x20, c]), bytes([ins + 0x06 - 0x0A, 0x20]))

# INC/DEC
for nm, ins in [("inc", 0xE6), ("dec", 0xC6)]:
    for v in [0x00, 0x7F, 0x80, 0xFF]:
        add("%s_%02X" % (nm, v), bytes([0xA9, v, 0x85, 0x20]), bytes([ins, 0x20]))

# logical ops
for nm, ins, a, v in [("and", 0x29, 0xF0, 0x0F), ("ora", 0x09, 0x0F, 0xF0), ("eor", 0x49, 0xFF, 0x55)]:
    add("%s_%02X%02X" % (nm, a, v), bytes([0xA9, a]), bytes([ins, v]))

# transfers / loads (N,Z)
for nm, ins in [("tax", 0xAA), ("tay", 0xA8), ("txa", 0x8A), ("tya", 0x98),
                ("tsx", 0xBA), ("txs", 0x9A), ("inx", 0xE8), ("iny", 0xC8),
                ("dex", 0xCA), ("dey", 0x88)]:
    for a in [0x00, 0x7F, 0x80, 0xFF]:
        add("%s_%02X" % (nm, a), bytes([0xA9, a, 0xAA, 0xA8]), bytes([ins]))

# loads
for nm, ins in [("lda", 0xA9), ("ldx", 0xA2), ("ldy", 0xA0)]:
    for v in [0x00, 0x80, 0xFF]:
        add("%s_%02X" % (nm, v), b"", bytes([ins, v]))

# addressing-mode results: (zp),Y and abs,X reads of a RAM page we fill
for base in [0x00, 0x01, 0x7F, 0xFF]:
    for idx in [0, 1, 2, 0x7F, 0xFF]:
        # store a marker at 0x0200 + base + idx, load through (zp),Y
        setup = bytes([0xA9, 0x5A, 0x8D]) + struct.pack("<H", 0x0200 + ((base + idx) & 0xFFFF)) \
            + bytes([0xA0, idx, 0xA9, base & 0xFF, 0x85, 0x30, 0xA9, (base >> 8) & 0xFF, 0x85, 0x31])
        add("indy_%02X_%02X" % (base, idx), setup, bytes([0xB1, 0x30]))

# RMW memory ops with zp,X / abs,X / (zp),Y
for nm, ins in [("asl_zx", b"\x16"), ("lsr_zx", b"\x56"), ("rol_zx", b"\x36"), ("ror_zx", b"\x76"),
                ("inc_zx", b"\xF6"), ("dec_zx", b"\xD6")]:
    for v in [0x01, 0x80, 0xFF, 0x00]:
        add("%s_%02X" % (nm, v), bytes([0xA9, v, 0x85, 0x21, 0xA2, 0x01, 0x18]), bytes([ins[0], 0x20]))

# stack ops
add("pha_pla", bytes([0xA9, 0x5A, 0x48]), bytes([0x68]))
add("php_plp", bytes([0x38, 0x08]), bytes([0x28]))
add("jsr_rts", b"", bytes([0x20, 0x00, 0x90]))   # $9000 holds an RTS


def build(battery, high, out, reps=8):
    code = bytearray()

    def emit(b):
        code.extend(b)

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    emit(b"\xa9\x00\x85\x10\x85\x11")
    # repeat the battery `reps` times so a single instruction's result is
    # accumulated several times (amplifying differences)
    emit(bytes([0xa9, reps]))
    emit(b"\x85\x12")
    loop = len(code)
    for name in battery:
        setup, ins = TESTS[name]
        emit(setup)
        emit(ins)
        if name == "jsr_rts":
            pass
        # accumulate: $10 ^= A; $11 = ($11 + P) ^ X; $10 ^= Y
        emit(b"\x08")                    # php
        emit(b"\x68")                    # pla
        emit(b"\x45\x10")                # eor $10
        emit(b"\x85\x10")                # sta $10
        emit(b"\x8a")                    # txa
        emit(b"\x45\x11")                # eor $11
        emit(b"\x85\x11")                # sta $11
        emit(b"\x98")                    # tya
        emit(b"\x45\x10")                # eor $10
        emit(b"\x85\x10")                # sta $10
        emit(b"\xa5\x11")                # lda $11
        emit(b"\x69\x01")                # adc #1
        emit(b"\x85\x11")                # sta $11
    emit(b"\xc6\x12")                    # dec $12
    emit(b"\xf0\x03")                    # beq +3 (skip the jmp)
    emit(b"\x4c" + struct.pack("<H", 0xC000 + loop))
    # write $10 (or $11) to palette[0]
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    emit(b"\xa5" + bytes([0x11 if high else 0x10]))
    emit(b"\x8d\x07\x20")
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    spin = len(code)
    emit(b"\x4c" + struct.pack("<H", 0xC000 + spin))
    prg = bytearray(0x8000)
    off = 0xC000 - 0x8000
    assert off + len(code) < 0x8000
    prg[off:off + len(code)] = code
    # an RTS at $9000 for the jsr_rts test
    prg[0x9000 - 0x8000] = 0x60
    for a in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[a:a + 2] = struct.pack("<H", 0xC000)
    return b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    which = sys.argv[1]
    part = sys.argv[2]
    out = sys.argv[3]
    reps = int(sys.argv[4]) if len(sys.argv) > 4 else 8
    if which == "all":
        battery = list(TESTS.keys())
    else:
        battery = sorted(TESTS.keys())
    open(out, "wb").write(build(battery, part == "high", out, reps))
    print("wrote %s (%d tests)" % (out, len(battery)))
