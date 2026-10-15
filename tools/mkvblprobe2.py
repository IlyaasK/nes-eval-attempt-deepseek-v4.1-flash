#!/usr/bin/env python3
"""Read $2002 exactly `delay` cycles after power-on, then report bit 7 in the
backdrop colour.  Sweeping the delay maps the exact PPU dot at which the VBL
flag becomes visible (and whether a read suppresses it), for comparison with
the reference.

Usage: mkvblprobe2.py <delay_cycles> <out.nes>
"""
import struct
import sys

ORIGIN = 0xC000


def _burn(emit, bne, cycles):
    """Emit code burning exactly `cycles` cycles (cycles >= 0)."""
    if cycles < 0:
        raise SystemExit("negative")
    # outer blocks of 255*5 + 10 cycles
    per_outer = 255 * 5 + 2 + 5 + 3
    blocks = cycles // per_outer
    rest = cycles - blocks * per_outer
    k = rest // 5
    tail = rest - 5 * k
    if tail == 4:
        # 4 = 2+2 (two nops) is fine; no special case needed
        pass
    if blocks > 0:
        if blocks > 255:
            raise SystemExit("delay too large")
        emit(b"\xa9" + bytes([blocks]) + b"\x85\x14")
        outer = None
        emit(b"\xa2\xff")
        inner = None
        # placeholders resolved below
    return (blocks, k, tail)


def build(delay: int) -> bytes:
    code = bytearray()

    def emit(b):
        code.extend(b)

    def bne(target):
        emit(b"\xd0")
        emit(bytes([(target - (len(code) + 1)) & 0xFF]))

    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    emit(b"\xa9\x00\x85\x10")
    # burn up to the read point
    per_outer = 255 * 5 + 2 + 5 + 3
    blocks = delay // per_outer
    rest = delay - blocks * per_outer
    k = rest // 5
    tail = rest - 5 * k
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
        emit(b"\xea")
    if tail % 2:
        emit(b"\xa5\x10")               # lda $10 (3 cycles)
    # the probe read
    emit(b"\xad\x02\x20")               # lda $2002
    emit(b"\x29\x80")                   # and #$80
    emit(b"\x85\x10")                   # sta $10
    # burn past the PPU warm-up (~30000 cycles) so palette writes take effect
    emit(b"\xa2\x00")
    emit(b"\xa0\x00")
    outer2 = len(code)
    emit(b"\xca")
    bne(outer2)
    emit(b"\xc8")
    emit(b"\xc0\x28")
    bne(outer2)
    # palette[0] = $30 if the flag was set, $0F otherwise
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    emit(b"\xa5\x10")                   # lda $10
    emit(b"\xf0\x04")                   # beq +4 (skip)
    emit(b"\xa9\x30")
    emit(b"\xd0\x02")                   # bne +2 (skip)
    emit(b"\xa9\x0f")
    emit(b"\x8d\x07\x20")
    # point v back at $3F00 so the backdrop shows palette[0]
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    spin = len(code)
    emit(b"\x4c" + struct.pack("<H", ORIGIN + spin))
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
