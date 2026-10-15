#!/usr/bin/env python3
"""idx2png.py -- render an NES frame dump to an 8-bit RGB PNG.

Usage:
    idx2png.py FILE.idx OUT.png [--scale N] [--palette PATH]

The input is a `.idx` frame dump: 61440 little-endian u16 values, row-major
256x240, each value being ``(emphasis << 6) | colour``.  It is turned into RGB
through the fixed palette ``spec/nes_palette.pal`` (512 entries x 3 bytes,
R G B, indexed by the same 9-bit value).  The output is a colour-type-2
(truecolour) 8-bit PNG written with nothing but the standard library
(``struct`` + ``zlib``).

``--scale N`` upscales by integer nearest-neighbour (default 1).  The palette
path defaults to ``spec/nes_palette.pal`` relative to the current directory,
then next to this script's parent, and can be overridden with ``--palette``
or $NES_PALETTE.
"""

import argparse
import os
import struct
import sys
import zlib

import numpy as np

WIDTH = 256
HEIGHT = 240
NPIX = WIDTH * HEIGHT
FRAME_BYTES = NPIX * 2
PALETTE_ENTRIES = 512
PALETTE_BYTES = PALETTE_ENTRIES * 3


class IdxError(Exception):
    pass


def default_palette_path():
    """Locate spec/nes_palette.pal relative to cwd or this script's parent."""
    candidates = []
    env = os.environ.get("NES_PALETTE")
    if env:
        candidates.append(env)
    candidates.append(os.path.join("spec", "nes_palette.pal"))
    here = os.path.dirname(os.path.abspath(__file__))
    for root in (os.path.dirname(here), here):
        candidates.append(os.path.join(root, "spec", "nes_palette.pal"))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def load_palette(path):
    if not os.path.exists(path):
        raise IdxError("palette file not found: %s" % path)
    data = open(path, "rb").read()
    if len(data) != PALETTE_BYTES:
        raise IdxError(
            "palette %s is %d bytes, expected exactly %d (512 RGB triples)"
            % (path, len(data), PALETTE_BYTES)
        )
    return np.frombuffer(data, dtype=np.uint8).reshape(PALETTE_ENTRIES, 3)


def load_idx(path):
    if not os.path.exists(path):
        raise IdxError("frame dump not found: %s" % path)
    data = open(path, "rb").read()
    if len(data) != FRAME_BYTES:
        raise IdxError(
            "%s is %d bytes, expected exactly %d (256*240 u16)"
            % (path, len(data), FRAME_BYTES)
        )
    return np.frombuffer(data, dtype="<u2").reshape(HEIGHT, WIDTH)


def png_chunk(tag, payload):
    """Build one PNG chunk: length, type, data, CRC32(type + data)."""
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def write_png(path, rgb):
    """Write an (H, W, 3) uint8 array as an 8-bit truecolour PNG."""
    height, width = rgb.shape[0], rgb.shape[1]
    ihdr = struct.pack(
        ">IIBBBBB",
        width,
        height,
        8,  # bit depth
        2,  # colour type 2 = truecolour RGB
        0,  # compression method (deflate)
        0,  # filter method (adaptive)
        0,  # interlace (none)
    )
    # Each scanline is prefixed with a filter-type byte (0 = None).
    raw = bytearray()
    rows = np.ascontiguousarray(rgb, dtype=np.uint8)
    for y in range(height):
        raw.append(0)
        raw += rows[y].tobytes()
    idat = zlib.compress(bytes(raw), 9)
    signature = b"\x89PNG\r\n\x1a\n"
    with open(path, "wb") as fh:
        fh.write(signature)
        fh.write(png_chunk(b"IHDR", ihdr))
        fh.write(png_chunk(b"IDAT", idat))
        fh.write(png_chunk(b"IEND", b""))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="idx2png.py",
        description="Render an NES .idx frame dump to an 8-bit RGB PNG "
        "using spec/nes_palette.pal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("idx", help="input .idx frame dump (61440 u16 LE)")
    parser.add_argument("png", help="output .png path")
    parser.add_argument(
        "--scale",
        type=int,
        default=1,
        metavar="N",
        help="integer nearest-neighbour upscale factor (default 1)",
    )
    parser.add_argument(
        "--palette",
        metavar="PATH",
        default=None,
        help="palette file (512 x RGB); defaults to spec/nes_palette.pal",
    )
    args = parser.parse_args(argv)

    if args.scale < 1:
        print("idx2png.py: error: --scale must be >= 1", file=sys.stderr)
        return 2

    pal_path = args.palette or default_palette_path()
    if pal_path is None:
        print(
            "idx2png.py: error: could not locate spec/nes_palette.pal; "
            "pass --palette PATH",
            file=sys.stderr,
        )
        return 2

    try:
        palette = load_palette(pal_path)
        frame = load_idx(args.idx)
        indices = frame.astype(np.uint16) & 0x1FF
        rgb = palette[indices]
        if args.scale > 1:
            rgb = np.repeat(np.repeat(rgb, args.scale, axis=0), args.scale, axis=1)
        outdir = os.path.dirname(os.path.abspath(args.png))
        if outdir:
            os.makedirs(outdir, exist_ok=True)
        write_png(args.png, rgb)
    except IdxError as exc:
        print("idx2png.py: error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("idx2png.py: error: %s" % exc, file=sys.stderr)
        return 2

    h, w = rgb.shape[0], rgb.shape[1]
    print(
        "wrote %s (%dx%d, scale %d, palette %s)"
        % (args.png, w, h, args.scale, pal_path)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
