#!/usr/bin/env python3
"""APU level probe: configures one channel to a steady, audible tone and spins.

Usage: mkapuprobe.py <pulse|tri|noise|pulse2> <out.nes>

Useful for comparing APU levels and waveforms against the reference: the pulse
probe plays duty 2 at constant volume 15 with a ~440 Hz period, the triangle
probe holds its linear counter at $FF, the noise probe uses a mid period.
"""
import struct
import sys

ORIGIN = 0xC000


def build(mode: str, vol: int = 15, lo: int = 0xFD, hi: int = 0x00, duty: int = 2) -> bytes:
    code = bytearray()

    def e(b):
        code.extend(b)

    e(b"\x78\xd8\xa2\xff\x9a")                  # sei, cld, ldx #$FF, txs
    e(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")      # PPU off
    for _ in range(3):                           # wait 3 vblanks
        e(b"\x2c\x02\x20\xd0\xfb".replace(b"\xd0", b"\x10"))  # bit $2002 / bpl
        e(b"\x2c\x02\x20\x30\xfb")               # bit $2002 / bmi
    e(b"\xa9\x40\x8d\x17\x40")                   # $4017 = $40 (4-step, IRQ off)
    if mode == "env":
        e(b"\xa9\x01\x8d\x15\x40")               # enable pulse 1
        e(b"\xa9\x8f\x8d\x00\x40")               # duty 2, envelope mode, period 15
        e(b"\xa9\x00\x8d\x01\x40")
        e(b"\xa9\xfd\x8d\x02\x40")
        e(b"\xa9\x00\x8d\x03\x40")
    elif mode == "pulse":
        e(b"\xa9\x01\x8d\x15\x40")               # enable pulse 1
        e(b"\xa9" + bytes([(duty << 6) | 0x30 | (vol & 0x0F)]) + b"\x8d\x00\x40")
        e(b"\xa9\x00\x8d\x01\x40")               # sweep off
        e(b"\xa9" + bytes([lo]) + b"\x8d\x02\x40")
        e(b"\xa9" + bytes([hi]) + b"\x8d\x03\x40")
    elif mode == "pulse2":
        e(b"\xa9\x02\x8d\x15\x40")
        e(b"\xa9\xbf\x8d\x04\x40")
        e(b"\xa9\x00\x8d\x05\x40")
        e(b"\xa9\xfd\x8d\x06\x40")
        e(b"\xa9\x00\x8d\x07\x40")
    elif mode == "both":
        e(b"\xa9\x03\x8d\x15\x40")               # enable pulse 1 + 2
        e(b"\xa9" + bytes([0xB0 | (vol & 0x0F)]) + b"\x8d\x00\x40")
        e(b"\xa9\x00\x8d\x01\x40")
        e(b"\xa9" + bytes([lo]) + b"\x8d\x02\x40")
        e(b"\xa9" + bytes([hi]) + b"\x8d\x03\x40")
        e(b"\xa9" + bytes([0xB0 | (vol & 0x0F)]) + b"\x8d\x04\x40")
        e(b"\xa9\x00\x8d\x05\x40")
        e(b"\xa9" + bytes([lo]) + b"\x8d\x06\x40")
        e(b"\xa9" + bytes([hi]) + b"\x8d\x07\x40")
    elif mode == "tri":
        e(b"\xa9\x04\x8d\x15\x40")               # enable triangle
        e(b"\xa9\xff\x8d\x08\x40")               # control + reload = $FF
        e(b"\xa9" + bytes([lo]) + b"\x8d\x0a\x40")
        e(b"\xa9" + bytes([hi]) + b"\x8d\x0b\x40")
    elif mode == "noise":
        e(b"\xa9\x08\x8d\x15\x40")               # enable noise
        e(b"\xa9\x3f\x8d\x0c\x40")               # halt, const vol 15
        e(b"\xa9\x08\x8d\x0e\x40")               # mode 0, period index 8
    else:
        raise SystemExit("unknown mode %s" % mode)
    spin = len(code)
    e(b"\x4c" + struct.pack("<H", ORIGIN + spin))   # jmp spin
    prg = bytearray(0x8000)
    off = ORIGIN - 0x8000
    prg[off:off + len(code)] = code
    for a in (0x7FFA, 0x7FFC, 0x7FFE):
        prg[a:a + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    mode, out = sys.argv[1], sys.argv[2]
    vol = int(sys.argv[3]) if len(sys.argv) > 3 else 15
    lo = int(sys.argv[4], 0) if len(sys.argv) > 4 else 0xFD
    hi = int(sys.argv[5], 0) if len(sys.argv) > 5 else 0x00
    duty = int(sys.argv[6], 0) if len(sys.argv) > 6 else 2
    open(out, "wb").write(build(mode, vol, lo, hi, duty))
    print("wrote", out, mode)
