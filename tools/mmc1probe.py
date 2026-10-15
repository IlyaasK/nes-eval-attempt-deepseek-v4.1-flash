#!/usr/bin/env python3
"""mmc1probe.py -- exercise MMC1 (mapper 1) banking against the reference.

ROM layout: 2 x 16 KiB PRG banks, CHR RAM, NROM-like iNES header with mapper 1.

* bank 0: a marker routine at $BF00 that returns $30 in A.
* bank 1 (fixed to $C000-$FFFF): the main program and a marker routine at
  $BF00 (mirrored at $FF00) that returns $16 in A.

The program selects the control register (PRG mode 3 = fix last bank at $C000,
8 KiB CHR mode), then switches the $8000 window between bank 0 and bank 1,
calling $BF00 each time and painting the returned value into palette[0].  The
framebuffer therefore shows which bank the $8000 window maps to.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
from asm6502 import Assembler  # noqa: E402
from mkrom import build_rom  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAIN = """
start:
        sei
        cld
        ldx #$FF
        txs
        lda #$00
        sta $2000
        sta $2001
        jsr vwait
        jsr vwait
        jsr vwait
        ; control register: PRG mode 3 (fix last bank at $C000), 8K CHR mode
        lda #$0C
        jsr mmc1_ctrl
        ; select PRG bank 0 in the $8000 window
        lda #$00
        jsr mmc1_prg
        jsr $BF00
        jsr paint
        jsr vwait
        ; select PRG bank 1
        lda #$01
        jsr mmc1_prg
        jsr $BF00
        jsr paint
        jsr vwait
        jsr vwait
        jsr vwait
spin:   jmp spin
; --- MMC1 serial writes: A = 5-bit value
mmc1_ctrl:
        sta $12
        ldx #$05
c1:     lda $12
        and #$01
        sta $8000
        lsr $12
        dex
        bne c1
        rts
mmc1_prg:
        sta $12
        ldx #$05
p1:     lda $12
        and #$01
        sta $E000
        lsr $12
        dex
        bne p1
        rts
mmc1_chr0:
        sta $12
        ldx #$05
h1:     lda $12
        and #$01
        sta $A000
        lsr $12
        dex
        bne h1
        rts
mmc1_chr1:
        sta $12
        ldx #$05
h2:     lda $12
        and #$01
        sta $C000
        lsr $12
        dex
        bne h2
        rts
; paint A into palette entry 0 and point v back at it
paint:
        pha
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        pla
        sta $2007
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        rts
vwait:  bit $2002
        bpl vwait
        rts
nmi:    rti
irq:    rti
"""


def marker(value):
    return """
        lda #$%02X
        rts
""" % value


def build_rom_image():
    bank0 = bytearray(b"\xea" * 0x4000)
    a = Assembler(origin=0xBF00)
    for line in marker(0x30).splitlines():
        a.line(line)
    code = a.assemble()
    bank0[0x3F00:0x3F00 + len(code)] = code

    bank1 = bytearray(b"\xea" * 0x4000)
    a = Assembler(origin=0xC000)
    for line in MAIN.splitlines():
        a.line(line)
    code = a.assemble()
    bank1[0x0000:len(code)] = code
    a = Assembler(origin=0xBF00)
    for line in marker(0x16).splitlines():
        a.line(line)
    m = a.assemble()
    bank1[0x3F00:0x3F00 + len(m)] = m
    # vectors (reset/NMI/IRQ -> main)
    reset = 0xC000
    for i, vec in enumerate((0xC000, reset, reset)):
        bank1[0x3FFA + i * 2] = vec & 0xFF
        bank1[0x3FFB + i * 2] = (vec >> 8) & 0xFF
    prg = bytes(bank0) + bytes(bank1)
    return build_rom(prg, b"", 1, "horizontal", 0, False, 0)


def main():
    rom = build_rom_image()
    path = os.path.join(ROOT, "tmp", "mmc1probe.nes")
    with open(path, "wb") as f:
        f.write(rom)
    frames = 12
    base = os.path.join(ROOT, ".oracle-out", "mmc1")
    os.makedirs(base, exist_ok=True)
    os.chmod(base, 0o777)
    rd = os.path.join(base, "ref")
    md = os.path.join(base, "mine")
    for d in (rd, md):
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o777)
    subprocess.run(["oracle", "run", path, str(frames), "--dump-frames", rd],
                   cwd=ROOT, capture_output=True)
    subprocess.run([os.path.join(ROOT, "target/release/nesrun"), path, str(frames),
                    "--out", md], cwd=ROOT, capture_output=True)
    for f in range(frames):
        rp = os.path.join(rd, "frame_%05d.idx" % f)
        mp = os.path.join(md, "frame_%05d.idx" % f)
        if not (os.path.exists(rp) and os.path.exists(mp)):
            break
        r = np.fromfile(rp, dtype="<u2")
        m = np.fromfile(mp, dtype="<u2")
        print("frame %2d: ref=%02X mine=%02X diff=%d"
              % (f, r[0], m[0], int((r != m).sum())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
