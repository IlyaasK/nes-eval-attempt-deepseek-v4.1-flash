#!/usr/bin/env python3
"""Per-channel APU probe.  Sets up a single channel at a fixed pitch/volume and
spins, so the reference's WAV can be compared against ours for that channel
alone.

Usage: mkchprobe.py <mode> <out.nes>
Modes: tri, pulse1, pulse2, noise, dmc
"""
import struct
import sys

ORIGIN = 0xE000


class Asm:
    def __init__(self):
        self.code = bytearray()
        self.labels = {}
        self.fixups = []

    def emit(self, b):
        self.code.extend(b)

    def label(self, name):
        self.labels[name] = len(self.code)

    def branch(self, op, target):
        self.emit(bytes([op]))
        self.fixups.append((len(self.code), target))
        self.emit(b"\x00")

    def resolve(self):
        for pos, target in self.fixups:
            self.code[pos] = (self.labels[target] - (pos + 1)) & 0xFF


def build(mode: str) -> bytes:
    a = Asm()
    e, br = a.emit, a.branch
    e(b"\x78\xd8\xa2\xff\x9a")              # sei cld ldx #$FF txs
    e(b"\xa9\x00\x8d\x15\x40")              # $4015 = 0
    e(b"\xa9\x40\x8d\x17\x40")              # $4017 = $40 (frame counter: 4-step, IRQ off)
    # Enable the channel first: the length counter only loads from the table
    # while the channel's $4015 enable flag is set.
    en_all = {"pulse1": 0x01, "pulse2": 0x02, "tri": 0x04, "noise": 0x08, "dmc": 0x10,
              "noise_env": 0x08, "noise_mode1": 0x08, "pulse_env": 0x01, "combo": 0x07,
              "tri_lc": 0x04, "tri_lc2": 0x04, "tri_p1": 0x04, "tri_p2": 0x04,
              "noise_fast": 0x08, "noise_fast1": 0x08,
              "pulse_sweep": 0x01, "pulse_sweep2": 0x01}[mode]
    e(b"\xa9" + bytes([en_all]) + b"\x8d\x15\x40")
    if mode == "tri":
        # length halt + linear reload 127; period 558 -> ~100 Hz
        e(b"\xa9\xff\x8d\x08\x40")
        e(b"\xa9\x2e\x8d\x0a\x40")
        e(b"\xa9\x02\x8d\x0b\x40")
        e(b"\xa9\x04\x8d\x15\x40")          # enable triangle
    elif mode in ("pulse1", "pulse2"):
        base = 0x4000 if mode == "pulse1" else 0x4004
        en = 0x01 if mode == "pulse1" else 0x02
        e(b"\xa9\xbf\x8d" + bytes([base & 0xFF, base >> 8]))       # duty 2, halt, const vol 15
        e(b"\xa9\x08\x8d" + bytes([(base + 1) & 0xFF, base >> 8])) # sweep off
        e(b"\xa9\xf8\x8d" + bytes([(base + 2) & 0xFF, base >> 8])) # period low (1016 -> ~110 Hz)
        e(b"\xa9\x03\x8d" + bytes([(base + 3) & 0xFF, base >> 8]))
        e(b"\xa9" + bytes([en]) + b"\x8d\x15\x40")
    elif mode == "noise_env":
        e(b"\xa9\x08\x8d\x0c\x40")          # envelope mode, period 8, no halt
        e(b"\xa9\x04\x8d\x0e\x40")          # mode 0, period index 4
        e(b"\xa9\x08\x8d\x0f\x40")
        e(b"\xa9\x08\x8d\x15\x40")
    elif mode == "noise_mode1":
        e(b"\xa9\x3f\x8d\x0c\x40")          # halt, const vol 15
        e(b"\xa9\x8f\x8d\x0e\x40")          # mode 1 (periodic), index 15 (slow)
        e(b"\xa9\x08\x8d\x0f\x40")
        e(b"\xa9\x08\x8d\x15\x40")
    elif mode == "pulse_env":
        e(b"\xa9\x08\x8d\x01\x40")          # sweep off
        e(b"\xa9\xf8\x8d\x02\x40")
        e(b"\xa9\x03\x8d\x03\x40")
        e(b"\xa9\x08\x8d\x15\x40")          # enable first so length loads
        e(b"\xa9\x28\x8d\x00\x40")          # duty 2, envelope mode, period 8
        e(b"\xa9\xf8\x8d\x02\x40")
        e(b"\xa9\x03\x8d\x03\x40")
        e(b"\xa9\x01\x8d\x15\x40")
    elif mode == "tri_lc":
        # control=0 (one-shot linear counter), reload 127
        e(b"\xa9\x7f\x8d\x08\x40")
        e(b"\xa9\x2e\x8d\x0a\x40")
        e(b"\xa9\x02\x8d\x0b\x40")
        e(b"\xa9\x04\x8d\x15\x40")
    elif mode == "tri_lc2":
        # control=0, reload 64, longer period
        e(b"\xa9\x40\x8d\x08\x40")
        e(b"\xa9\x86\x8d\x0a\x40")
        e(b"\xa9\x04\x8d\x0b\x40")
        e(b"\xa9\x04\x8d\x15\x40")
    elif mode == "tri_p1":
        # control=1 (constant), long period (low pitch)
        e(b"\xa9\xff\x8d\x08\x40")
        e(b"\xa9\x86\x8d\x0a\x40")
        e(b"\xa9\x04\x8d\x0b\x40")
        e(b"\xa9\x04\x8d\x15\x40")
    elif mode == "tri_p2":
        # control=1, short period (high pitch)
        e(b"\xa9\xff\x8d\x08\x40")
        e(b"\xa9\x10\x8d\x0a\x40")
        e(b"\xa9\x00\x8d\x0b\x40")
        e(b"\xa9\x04\x8d\x15\x40")
    elif mode == "combo":
        e(b"\xa9\x0f\x8d\x15\x40")          # enable pulse1+pulse2+triangle+noise? just p1,p2,tri
        e(b"\xa9\xbf\x8d\x00\x40")          # pulse1: duty2, halt, const vol 15
        e(b"\xa9\x08\x8d\x01\x40")
        e(b"\xa9\xf8\x8d\x02\x40")
        e(b"\xa9\x03\x8d\x03\x40")
        e(b"\xa9\x7f\x8d\x04\x40")          # pulse2: duty1, halt, const vol 15
        e(b"\xa9\x08\x8d\x05\x40")
        e(b"\xa9\x30\x8d\x06\x40")
        e(b"\xa9\x02\x8d\x07\x40")
        e(b"\xa9\xff\x8d\x08\x40")          # triangle: halt + linear reload 127
        e(b"\xa9\x2e\x8d\x0a\x40")
        e(b"\xa9\x02\x8d\x0b\x40")
        e(b"\xa9\x07\x8d\x15\x40")          # enable p1,p2,tri
    elif mode == "noise_fast":
        e(b"\xa9\x3f\x8d\x0c\x40")          # halt, const vol 15
        e(b"\xa9\x04\x8d\x0e\x40")          # mode 0, period index 4 (fast)
        e(b"\xa9\x08\x8d\x0f\x40")
        e(b"\xa9\x08\x8d\x15\x40")
    elif mode == "noise_fast1":
        e(b"\xa9\x3f\x8d\x0c\x40")
        e(b"\xa9\x84\x8d\x0e\x40")          # mode 1, index 4
        e(b"\xa9\x08\x8d\x0f\x40")
        e(b"\xa9\x08\x8d\x15\x40")
    elif mode == "pulse_sweep":
        e(b"\xa9\x01\x8d\x15\x40")          # enable pulse 1 first
        e(b"\xa9\xbf\x8d\x00\x40")          # duty 2, halt, const vol 15
        e(b"\xa9\x81\x8d\x01\x40")          # sweep: enable, period 0, shift 1 (up)
        e(b"\xa9\x00\x8d\x02\x40")          # period low = 0
        e(b"\xa9\x02\x8d\x03\x40")          # period high = 2 (period 0x200)
        e(b"\xa9\x01\x8d\x15\x40")
    elif mode == "pulse_sweep2":
        e(b"\xa9\x01\x8d\x15\x40")
        e(b"\xa9\xbf\x8d\x00\x40")
        e(b"\xa9\x8f\x8d\x01\x40")          # sweep: enable, period 0, shift 7
        e(b"\xa9\x00\x8d\x02\x40")
        e(b"\xa9\x01\x8d\x03\x40")
        e(b"\xa9\x01\x8d\x15\x40")
    elif mode == "noise":
        e(b"\xa9\x3f\x8d\x0c\x40")          # halt, const vol 15
        e(b"\xa9\x0f\x8d\x0e\x40")          # mode 0, period index 15 (slow)
        e(b"\xa9\x08\x8d\x0f\x40")
        e(b"\xa9\x08\x8d\x15\x40")
    elif mode == "dmc":
        e(b"\xa9\x0f\x8d\x10\x40")          # DMC rate index 15, no IRQ, no loop
        e(b"\xa9\x40\x8d\x11\x40")          # direct load $40
        e(b"\xa9\x10\x8d\x15\x40")
    else:
        raise SystemExit("bad mode")
    a.label("spin"); e(b"\x4c" + struct.pack("<H", ORIGIN + len(a.code)))
    a.resolve()
    prg = bytearray(0x4000)
    prg[0x2000:0x2000 + len(a.code)] = a.code
    for v in (0x3FFA, 0x3FFC, 0x3FFE):
        prg[v:v + 2] = struct.pack("<H", ORIGIN)
    return b"NES\x1a" + bytes([1, 0, 0, 0]) + b"\x00" * 8 + bytes(prg)


if __name__ == "__main__":
    mode, out = sys.argv[1], sys.argv[2]
    open(out, "wb").write(build(mode))
    print("wrote", out, "mode", mode)
