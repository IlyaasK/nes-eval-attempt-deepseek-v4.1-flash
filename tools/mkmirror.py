#!/usr/bin/env python3
"""mkmirror.py -- nametable mirroring probe (mapper 0, NROM-256, CHR RAM).

Writes a nametable byte at one of $2000/$2400/$2800/$2C00 and renders
nametable 0 with scroll 0.  Tile 0 is transparent (backdrop = white $3F),
tile 1 is opaque black ($0F).  The top-left pixel of the frame therefore
reports whether the two 1 KiB banks alias.

Usage: mkmirror.py OUT.nes [--addr 2400] [--off 0] [--dump]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mkrom import build_rom  # noqa: E402


def assemble(addr, off, dump=False):
    code = bytearray()

    def emit(b):
        code.extend(b)

    emit(b"\x78\xd8\xa2\xff\x9a")            # sei cld ldx #$ff txs
    emit(b"\xa9\x00\x8d\x00\x20\x8d\x01\x20")  # lda #0 / sta $2000 / sta $2001
    for _ in range(3):                       # wait out the PPU warm-up window
        w = len(code)
        emit(b"\x2c\x02\x20\x10\xfb")     # bit $2002 / bpl w

    # palette: $3F00 = $3F (white backdrop), $3F03 = $0F (black)
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    emit(b"\xa9\x3f\x8d\x07\x20")
    emit(b"\xa9\x3f\x8d\x06\x20\xa9\x03\x8d\x06\x20")
    emit(b"\xa9\x0f\x8d\x07\x20")

    # CHR: tile 1 = all colour 3 (16 bytes of $FF)
    emit(b"\xa9\x00\x8d\x06\x20\xa9\x10\x8d\x06\x20")
    emit(b"\xa2\x0f")                        # ldx #15
    lob = len(code)
    emit(b"\xa9\xff\x8d\x07\x20\xca\x10\xfa")  # lda #$FF / sta $2007 / dex / bpl
    # fill $2000-$23FF with tile 0
    emit(b"\xa9\x20\x8d\x06\x20\xa9\x00\x8d\x06\x20")
    emit(b"\xa2\x00\xa9\x00")
    for _ in range(5):
        f1 = len(code)
        emit(b"\x8d\x07\x20\xe8\xd0")        # sta $2007 / inx / bne f1
        emit(bytes([(f1 - (len(code) + 1)) & 0xFF]))
    # also fill $2000-$203F attribute area with 0 (already zero)
    # write tile 1 at the probe address
    hi = (addr >> 8) & 0xFF
    lo = addr & 0xFF
    emit(b"\xa9" + bytes([hi]) + b"\x8d\x06\x20")
    emit(b"\xa9" + bytes([lo + off]) + b"\x8d\x06\x20")
    emit(b"\xa9\x01\x8d\x07\x20")
    if dump:
        # read the byte back from $2000+off and expose it in the palette entry 0
        emit(b"\xa9\x20\x8d\x06\x20\xa9" + bytes([off]) + b"\x8d\x06\x20")
        emit(b"\xad\x07\x20")                # lda $2007 (prime)
        emit(b"\xad\x07\x20")                # lda $2007 (data)
        emit(b"\x29\x3f\x85\x10")            # and #$3F / sta $10
        emit(b"\xa9\x3f\x8d\x06\x20\xa9\x00\x8d\x06\x20")
        emit(b"\xa5\x10\x8d\x07\x20")        # sta $2007 -> palette[0]
    else:
        # enable rendering with nametable 0, scroll 0
        emit(b"\xa9\x00\x8d\x05\x20\x8d\x05\x20")
        emit(b"\xa9\x00\x8d\x00\x20")
        emit(b"\xa9\x0a\x8d\x01\x20")        # BG on + left column
    spin = len(code)
    emit(b"\x4c" + bytes([spin & 0xFF, 0xC0]))
    return bytes(code)


def build(addr, off, dump=False):
    code = assemble(addr, off, dump)
    body = bytearray(b"\xea" * 0x4000)
    body[0x0000:len(code)] = code
    body[0x3FFC] = 0x00
    body[0x3FFD] = 0xC0
    body[0x3FFE] = 0x00
    body[0x3FFF] = 0xC0
    return bytes(body) * 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--addr", type=lambda s: int(s, 16), default=0x2400)
    ap.add_argument("--off", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--mirroring", default="horizontal", choices=["horizontal", "vertical"])
    args = ap.parse_args()
    rom = build(args.addr, args.off, args.dump)
    with open(args.out, "wb") as f:
        f.write(build_rom(rom, b"", 0, args.mirroring, 0, False, 0))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
