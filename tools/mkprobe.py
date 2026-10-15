#!/usr/bin/env python3
"""Build small hand-assembled NES probe ROMs (mapper 0, NROM-256, CHR RAM).

Probe layout: the ROM waits for the first VBL, then runs a loop of `N`
iterations of a chosen instruction sequence, then switches palette entry 0 to
$3F (black).  The scanline at which the framebuffer turns black therefore
encodes the total cycle count of the loop, letting us compare CPU timing with
the reference emulator to the cycle.
"""
import struct
import sys


def build_probe(loop_body: bytes, iterations: int, origin=0xC000) -> bytes:
    """Assemble the probe ROM.  loop_body must not clobber X (used as the
    low byte of the loop counter) unless it is a self-contained sequence."""
    code = bytearray()
    labels = {}

    def emit(b):
        code.extend(b)

    # --- reset
    emit(b"\x78")              # sei
    emit(b"\xd8")              # cld
    emit(b"\xa2\xff")          # ldx #$FF
    emit(b"\x9a")              # txs
    emit(b"\xa9\x00")          # lda #0
    emit(b"\x8d\x00\x20")      # sta $2000
    emit(b"\x8d\x01\x20")      # sta $2001
    emit(b"\x85\x10")          # sta $10
    emit(b"\x85\x11")          # sta $11
    # wait for VBL
    wait = len(code)
    emit(b"\x2c\x02\x20")      # bit $2002
    emit(b"\x10\xfb")          # bpl wait
    # loop counter: X = iterations mod 256, plus a page counter in $11
    pages = iterations // 256
    rem = iterations % 256
    emit(b"\xa9" + bytes([rem]))     # lda #rem
    emit(b"\xaa")                    # tax
    emit(b"\xa9" + bytes([pages]))   # lda #pages
    emit(b"\x85\x11")                # sta $11
    if rem == 0:
        emit(b"\xe8")                # inx  (so that dex wraps after 256)
    loop_top = len(code)
    emit(loop_body)
    # loop control: dex / bne loop_top ; dec $11 / bne loop_top
    emit(b"\xca")              # dex
    emit(b"\xd0")              # bne loop_top
    emit(bytes([(loop_top - (len(code) + 1)) & 0xFF]))
    emit(b"\xc6\x11")          # dec $11
    emit(b"\xd0")              # bne loop_top
    emit(bytes([(loop_top - (len(code) + 1)) & 0xFF]))
    # palette: $2006 = $3F00, $2007 = $3F
    emit(b"\xa9\x3f\x8d\x06\x20")
    emit(b"\xa9\x00\x8d\x06\x20")
    emit(b"\xa9\x3f\x8d\x07\x20")
    # point v back at $3F00 so the backdrop shows palette[0]
    emit(b"\xa9\x3f\x8d\x06\x20")
    emit(b"\xa9\x00\x8d\x06\x20")
    spin = len(code)
    emit(b"\x4c")              # jmp spin
    emit(struct.pack("<H", origin + spin))

    prg = bytearray(b"\x00" * 0x8000)
    assert origin + len(code) <= 0x10000
    off = origin - 0x8000
    prg[off:off + len(code)] = code
    # vectors
    prg[0x7FFA:0x7FFC] = struct.pack("<H", origin)  # NMI
    prg[0x7FFC:0x7FFE] = struct.pack("<H", origin)  # RESET
    prg[0x7FFE:0x8000] = struct.pack("<H", origin)  # IRQ

    header = b"NES\x1a" + bytes([2, 0, 0, 0]) + b"\x00" * 8
    return header + bytes(prg)


# instruction sequences to probe
PROBES = {
    "nop2": b"\xea\xea",                       # 2x NOP implied
    "lda_ind_y": b"\xb1\x10",                  # lda ($10),y
    "lda_abs_x": b"\xbd\x00\x04",              # lda $0400,x
    "lda_abs_x_pc": b"\xbd\xf8\x04",           # lda $04F8,x (page crossing)
    "sta_ind_y": b"\x91\x10",                  # sta ($10),y
    "inc_zp": b"\xe6\x10",                     # inc $10
    "jsr_rts": b"\x20\x00\x90\x60",            # jsr $9000 (contains rts)
    "bit_abs": b"\x2c\x02\x20",                # bit $2002 (VBL read)
    "sprite_dma": b"\x8d\x14\x40",             # sta $4014 -> OAM DMA
    "branch_taken": b"\xa9\x01\xd0\x00\xea",   # taken branch
    "adc_imm": b"\x69\x01",                    # adc #1
    "plp_php": b"\x08\x28",                    # php / plp
}


def main():
    if len(sys.argv) < 3:
        print("usage: mkprobe.py <name> <out.nes> [iterations]")
        return 2
    name = sys.argv[1]
    out = sys.argv[2]
    iters = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    body = PROBES[name]
    data = build_probe(body, iters)
    with open(out, "wb") as f:
        f.write(data)
    print("wrote %s (%d bytes, probe %s, %d iterations)" % (out, len(data), name, iters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
