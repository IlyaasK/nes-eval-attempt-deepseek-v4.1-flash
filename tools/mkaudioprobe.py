#!/usr/bin/env python3
"""Audio probe: hold a constant APU state so the reference's audio pipeline can
be characterised (DC level mapping, resampler response).

Usage: mkaudioprobe.py <mode> <out.nes> [value]
Modes:
  dmc <v>    constant DMC DAC level (writes $4011 = v) after a delay
  dmc_step   steps through several DMC levels, holding each for a while
  pulse      pulse 1 with a fixed period/duty (a square wave)
"""
import struct
import sys

origin = 0xC000


def build_dmc(value: int) -> bytes:
    code = bytearray()
    def emit(b): code.extend(b)
    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    # burn ~30000 cycles so the probe starts after power-on transients
    emit(b"\xa2\x00\xa0\x00")
    top = len(code)
    emit(b"\xca")
    emit(b"\xd0\xfd")
    emit(b"\xc8")
    emit(b"\xc0\x1e")
    emit(b"\xd0\xf7")
    emit(b"\xa9" + bytes([value & 0x7F]))
    emit(b"\x8d\x11\x40")          # $4011 = DMC level
    spin = len(code)
    emit(b"\x4c" + struct.pack("<H", origin + spin))
    return assemble(code)


def build_dmc_step(values) -> bytes:
    code = bytearray()
    def emit(b): code.extend(b)
    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    emit(b"\xa2\x00\xa0\x00")
    top = len(code)
    emit(b"\xca")
    emit(b"\xd0\xfd")
    emit(b"\xc8")
    emit(b"\xc0\x1e")
    emit(b"\xd0\xf7")
    loop = len(code)
    for v in values:
        emit(b"\xa9" + bytes([v & 0x7F]))
        emit(b"\x8d\x11\x40")
        emit(b"\xa2\x00\xa0\x00")
        hold = len(code)
        emit(b"\xca")
        emit(b"\xd0\xfd")
        emit(b"\xc8")
        emit(b"\xc0\x28")
        emit(b"\xd0\xf7")
    emit(b"\x4c" + struct.pack("<H", origin + loop))
    return assemble(code)


def build_pulse(bits, period, duty=2) -> bytes:
    code = bytearray()
    def emit(b): code.extend(b)
    emit(b"\x78\xd8\xa2\xff\x9a")
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")
    # $4000 = duty 2, constant volume 15 (no envelope), no length halt
    emit(b"\xa9" + bytes([(duty << 6) | 0x30]))
    emit(b"\x8d\x00\x40")
    emit(b"\xa9" + bytes([period & 0xFF]))
    emit(b"\x8d\x02\x40")
    emit(b"\xa9" + bytes([(period >> 8) & 0x07]))
    emit(b"\x8d\x03\x40")
    emit(b"\xa9\x01")
    emit(b"\x8d\x15\x40")          # enable pulse 1
    spin = len(code)
    emit(b"\x4c" + struct.pack("<H", origin + spin))
    return assemble(code)


def assemble(code: bytearray) -> bytes:
    prg = bytearray(0x8000)
    off = origin - 0x8000
    assert off + len(code) < 0x8000
    prg[off:off + len(code)] = code
    for a in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[a:a + 2] = struct.pack("<H", origin)
    return b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    mode = sys.argv[1]
    out = sys.argv[2]
    if mode == "dmc":
        data = build_dmc(int(sys.argv[3]))
    elif mode == "dmc_step":
        vals = [0, 16, 32, 48, 64, 80, 96, 112, 127, 127, 96, 64, 32, 0, 0]
        data = build_dmc_step(vals)
    elif mode == "pulse":
        data = build_pulse(None, int(sys.argv[3]))
    else:
        raise SystemExit("unknown mode")
    open(out, "wb").write(data)
    print("wrote", out)
