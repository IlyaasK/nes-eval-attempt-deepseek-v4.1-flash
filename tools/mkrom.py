#!/usr/bin/env python3
"""mkrom.py -- build an iNES ROM image from raw PRG/CHR pieces.

Usage:
    mkrom.py --prg PRG.bin --chr CHR.bin --mapper N
             --mirroring horizontal|vertical --out ROM.nes
             [--prg-ram N] [--nes2] [--submapper N]

Writes a 16-byte iNES 1.0 header (or an NES 2.0 header when ``--nes2`` is
given) followed by the PRG and CHR data.  CHR data is zero-padded up to the
next multiple of 8 KiB when needed; PRG must already be a multiple of 16 KiB
and CHR a multiple of 8 KiB (the reference iNES 1.0 format cannot express a
finer granularity than the header's 16 KiB/8 KiB size fields).  CHR may be
empty, which marks the board as using CHR RAM.

Header layout (iNES 1.0):
    0       "NES\\x1a"
    1..4    PRG size in 16 KiB units, CHR size in 8 KiB units (low nibbles)
    5       flags 6: mirroring (bit 0), battery (bit 1), trainer (bit 2),
                     four-screen (bit 3), mapper low nibble (bits 4-7)
    6       flags 7: mapper high nibble (bits 4-7)
    7..15   zero (iNES 1.0); NES 2.0 uses these for the extended fields.

NES 2.0:
    7       flags 7: bits 0-1 = console type, 2-3 = NES 2.0 marker (0b10),
                     bits 4-7 = mapper high nibble
    8       flags 8: bits 0-3 = mapper submapper, 4-7 = mapper bits 8-11
    9       PRG size high nibble (bits 0-3), CHR size high nibble (bits 4-7)
    10      PRG-RAM/EEPROM size in 64-byte units (shift count)
    11      PRG-NVRAM size, same encoding
"""
import argparse
import os
import sys

CHR_BANK = 8192
PRG_BANK = 16384
HEADER_SIZE = 16
MAX_MAPPER_1_0 = 0x0F
MAX_MAPPER_2_0 = 0xFFF
MAX_SUBMAPPER = 0x0F


class MkromError(Exception):
    pass


MIRROR_BITS = {
    "horizontal": 0,
    "vertical": 1,
    "single0": 2,
    "single1": 3,
    "four": 4,
}


def read_file(path, what):
    if not os.path.exists(path):
        raise MkromError("%s file not found: %s" % (what, path))
    data = open(path, "rb").read()
    return data


def pad_to(data, multiple):
    if len(data) % multiple == 0:
        return data
    want = len(data) + (multiple - len(data) % multiple)
    return data + b"\x00" * (want - len(data))


def nvram_shift(size):
    """Encode a PRG-RAM size as the NES 2.0 shift count (0 = none)."""
    if size <= 0:
        return 0
    if size % 64 != 0:
        raise MkromError("PRG-RAM size must be a multiple of 64 bytes")
    shift = 0
    units = size // 64
    while units % 2 == 0 and units > 1:
        units //= 2
        shift += 1
    if units != 1:
        raise MkromError(
            "PRG-RAM size %d is not representable in NES 2.0 (must be 64 << n)"
            % size
        )
    return shift


def build_rom(prg, chr_, mapper, mirroring, prg_ram, nes2, submapper):
    prg_banks = len(prg) // PRG_BANK
    chr_banks = len(chr_) // CHR_BANK

    header = bytearray(HEADER_SIZE)
    header[0:4] = b"NES\x1a"
    header[4] = prg_banks & 0xFF
    header[5] = chr_banks & 0xFF

    mirror_bits = MIRROR_BITS[mirroring]
    if mirror_bits > 3 and not nes2:
        raise MkromError(
            "--mirroring four is only expressible in NES 2.0 (or four-screen "
            "flag, which is not supported here)"
        )
    # flags 6: mirroring in bits 0-1, mapper low nibble in bits 4-7
    header[6] = (mirror_bits & 0x03) | ((mapper & 0x0F) << 4)

    if not nes2:
        # flags 7: mapper high nibble in bits 4-7
        header[7] = ((mapper >> 4) & 0x0F) << 4
        # bytes 8..15 stay zero in iNES 1.0
    else:
        # flags 7: console type 0 (NES/Famicom), NES 2.0 marker 0b10
        header[7] = ((mapper >> 4) & 0x0F) << 4 | 0x08
        # flags 8: submapper low nibble, mapper bits 8-11 high nibble
        header[8] = (submapper & 0x0F) | (((mapper >> 8) & 0x0F) << 4)
        # flags 9: PRG/CHR bank count high nibbles
        header[9] = ((prg_banks >> 8) & 0x0F) | (((chr_banks >> 8) & 0x0F) << 4)
        # flags 10: PRG-RAM (volatile) size, shift count
        header[10] = nvram_shift(prg_ram)
        # flags 11: PRG-NVRAM size (zero here)
        header[11] = 0

    return bytes(header) + prg + chr_


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="mkrom.py",
        description="Build an iNES ROM image from raw PRG/CHR files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--prg", required=True, metavar="PRG.bin", help="PRG ROM data")
    parser.add_argument(
        "--chr",
        metavar="CHR.bin",
        default=None,
        help="CHR ROM data (omit or pass an empty file for CHR RAM)",
    )
    parser.add_argument("--mapper", type=int, required=True, help="mapper number")
    parser.add_argument(
        "--mirroring",
        required=True,
        choices=sorted(MIRROR_BITS),
        help="nametable mirroring",
    )
    parser.add_argument("--out", required=True, metavar="ROM.nes", help="output ROM path")
    parser.add_argument(
        "--prg-ram",
        type=int,
        default=0,
        metavar="N",
        help="PRG-RAM size in bytes (NES 2.0 only; 0 = none)",
    )
    parser.add_argument(
        "--nes2", action="store_true", help="emit an NES 2.0 header instead of iNES 1.0"
    )
    parser.add_argument(
        "--submapper", type=int, default=0, metavar="N", help="NES 2.0 submapper (0-15)"
    )
    args = parser.parse_args(argv)

    try:
        prg = read_file(args.prg, "PRG")

        if args.chr is None:
            chr_ = b""
        else:
            chr_ = read_file(args.chr, "CHR")

        if len(prg) == 0:
            raise MkromError("PRG is empty")
        if len(prg) % PRG_BANK != 0:
            raise MkromError(
                "PRG size %d is not a multiple of %d bytes (16 KiB); "
                "pad the file yourself" % (len(prg), PRG_BANK)
            )
        if len(chr_) % CHR_BANK != 0:
            raise MkromError(
                "CHR size %d is not a multiple of %d bytes (8 KiB); "
                "pad the file yourself" % (len(chr_), CHR_BANK)
            )
        if args.mapper < 0:
            raise MkromError("mapper number must be >= 0")
        if args.submapper < 0 or args.submapper > MAX_SUBMAPPER:
            raise MkromError("submapper must be 0..15")
        if args.prg_ram < 0:
            raise MkromError("--prg-ram must be >= 0")

        if not args.nes2:
            if args.mapper > MAX_MAPPER_1_0:
                raise MkromError(
                    "mapper %d does not fit an iNES 1.0 header (max %d); pass --nes2"
                    % (args.mapper, MAX_MAPPER_1_0)
                )
            if args.prg_ram or args.submapper:
                raise MkromError(
                    "--prg-ram/--submapper are not encodable in an iNES 1.0 header; "
                    "pass --nes2"
                )
        else:
            if args.mapper > MAX_MAPPER_2_0:
                raise MkromError("mapper %d exceeds the NES 2.0 range (max %d)"
                                 % (args.mapper, MAX_MAPPER_2_0))

        rom = build_rom(prg, chr_, args.mapper, args.mirroring, args.prg_ram, args.nes2,
                        args.submapper)

        outdir = os.path.dirname(os.path.abspath(args.out))
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        with open(args.out, "wb") as fh:
            fh.write(rom)
    except MkromError as exc:
        print("mkrom.py: error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("mkrom.py: error: %s" % exc, file=sys.stderr)
        return 2

    print(
        "wrote %s: %s, mapper %d mirroring %s, PRG %d KiB (%d bank%s), "
        "CHR %d KiB (%d bank%s)%s"
        % (
            args.out,
            "NES 2.0" if args.nes2 else "iNES",
            args.mapper,
            args.mirroring,
            len(prg) // 1024,
            len(prg) // PRG_BANK,
            "" if len(prg) == PRG_BANK else "s",
            len(chr_) // 1024,
            len(chr_) // CHR_BANK,
            "" if len(chr_) == CHR_BANK else "s",
            " + CHR RAM" if not chr_ else "",
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
