#!/usr/bin/env python3
"""Generate a probe ROM that reads $2002 at a precisely known CPU cycle and
then counts how long it takes for the VBL flag to become visible.

Layout: reset -> burn `burn` cycles -> read $2002 (probe read) -> count poll
iterations until bit 7 becomes set (capped at 255) -> write the count into
palette entry 0 and freeze.  The palette value observed in the final frame
therefore encodes the poll count.
"""
import struct
import sys

FRAME_DOTS = 341 * 262


def build(burn: int, origin=0xC000) -> bytes:
    code = bytearray()
    def emit(b): code.extend(b)
    def bne(target):
        emit(b"\xd0"); emit(bytes([(target - (len(code) + 1)) & 0xFF]))

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    # Burn `burn` cycles: outer loop over 1280-cycle blocks (inner 256x(dex/bne)),
    # then 5-cycle iterations, then a tail of NOPs (2) / lda (3) for residues.
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
        emit(b"\xa9" + bytes([blocks]))       # lda #blocks
        emit(b"\x85\x12")                    # sta $12
        outer = len(code)
        emit(b"\xa2\x00")                    # ldx #0
        inner = len(code)
        emit(b"\xca"); bne(inner)
        emit(b"\xc6\x12")                    # dec $12
        bne(outer)
    if k > 0:
        emit(b"\xa2" + bytes([k & 0xFF]))
        top = len(code)
        emit(b"\xca"); bne(top)              # 5 cycles per iteration
    for ins in tail_instr:
        emit(ins)
    # probe read (a distinctive instruction so it can be traced)
    emit(b"\xad\x02\x20")                    # lda $2002
    # poll until bit 7 set, counting in X (cap 255)
    emit(b"\xa2\x00")                        # ldx #0
    poll = len(code)
    emit(b"\x2c\x02\x20")                    # bit $2002
    emit(b"\x30\x05")                        # bmi done (+5)
    emit(b"\xe8")                            # inx
    emit(b"\xd0\xf8")                        # bne poll
    emit(b"\xa2\xff")                        # ldx #$FF (cap)
    # write X into palette[0]
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    emit(b"\x8e\x07\x20")                    # stx $2007
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    spin = len(code)
    emit(b"\x4c" + struct.pack("<H", origin + spin))
    prg = bytearray(0x8000)
    off = origin - 0x8000
    assert off + len(code) <= 0x8000, (off, len(code))
    prg[off:off + len(code)] = code
    for a in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[a:a + 2] = struct.pack("<H", origin)
    return b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    burn = int(sys.argv[1])
    out = sys.argv[2]
    open(out, "wb").write(build(burn))
    print("wrote", out, "burn", burn)
