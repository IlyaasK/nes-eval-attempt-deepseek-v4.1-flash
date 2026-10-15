#!/usr/bin/env python3
"""framediff.py -- compare two NES frame dumps produced by the oracle.

Each .idx file is 61440 little-endian u16 values, row-major 256x240, where
every value is `(emphasis << 6) | colour` for that pixel.

Usage:
    framediff.py MINE.idx REF.idx [--ppm-out diff.ppm] [--json] [--fail-on-diff]

Prints the number and percentage of differing pixels, the bounding box of
the differences, the first differing pixel (with emphasis and colour decoded
separately) and the ten scanlines with the most differences.  With
``--ppm-out`` it writes a 256x240 P6 image whose identical pixels are 25%
grey and whose differing pixels are coloured by the magnitude of the
difference.  With ``--json`` it prints a machine-readable summary object
instead of the human-readable report.

Exit status is 0 when the frames match and 1 when they differ; with
``--fail-on-diff`` a mismatch exits with status 2 (and also 2 for bad
input), so the flag is convenient for CI-style checks.
"""

import argparse
import json
import os
import sys

import numpy as np

WIDTH = 256
HEIGHT = 240
NPIX = WIDTH * HEIGHT
FRAME_BYTES = NPIX * 2
GREY = 64  # 25% of 255


class FrameError(Exception):
    pass


def load_idx(path):
    """Load a .idx frame dump as a (240, 256) little-endian u16 array."""
    if not os.path.exists(path):
        raise FrameError("file not found: %s" % path)
    data = open(path, "rb").read()
    if len(data) != FRAME_BYTES:
        raise FrameError(
            "%s is %d bytes, expected exactly %d (256*240 u16)"
            % (path, len(data), FRAME_BYTES)
        )
    arr = np.frombuffer(data, dtype="<u2").reshape(HEIGHT, WIDTH)
    return arr


def decode(value):
    """Split a raw framebuffer value into (emphasis, colour) fields."""
    return (int(value) >> 6) & 0x07, int(value) & 0x3F


def diff_stats(mine, ref):
    """Compute the comparison statistics used by both output modes."""
    if mine.shape != ref.shape:
        raise FrameError("frame shapes differ: %r vs %r" % (mine.shape, ref.shape))

    m = mine.astype(np.int64)
    r = ref.astype(np.int64)
    neq = m != r
    count = int(neq.sum())
    total = NPIX
    percent = 100.0 * count / total

    stats = {
        "width": WIDTH,
        "height": HEIGHT,
        "total_pixels": total,
        "diff_pixels": count,
        "diff_percent": percent,
        "identical": count == 0,
    }

    if count:
        ys, xs = np.nonzero(neq)
        stats["bbox"] = {
            "min_x": int(xs.min()),
            "max_x": int(xs.max()),
            "min_y": int(ys.min()),
            "max_y": int(ys.max()),
        }
        # First differing pixel in row-major order.
        fy = int(ys[0])
        fx = int(xs[0])
        mv = int(m[fy, fx])
        rv = int(r[fy, fx])
        me, mc = decode(mv)
        re, rc = decode(rv)
        stats["first_diff"] = {
            "x": fx,
            "y": fy,
            "offset": fy * WIDTH + fx,
            "mine": mv,
            "ref": rv,
            "mine_emphasis": me,
            "mine_colour": mc,
            "ref_emphasis": re,
            "ref_colour": rc,
        }
        # Per-scanline histogram.
        row_counts = neq.sum(axis=1).astype(int)
        stats["row_counts"] = [int(v) for v in row_counts]
        order = np.argsort(row_counts)[::-1]
        top = []
        for idx in order[:10]:
            if row_counts[idx] == 0:
                break
            top.append({"scanline": int(idx), "count": int(row_counts[idx])})
        stats["top_scanlines"] = top
    else:
        stats["bbox"] = None
        stats["first_diff"] = None
        stats["row_counts"] = [0] * HEIGHT
        stats["top_scanlines"] = []

    return stats


def write_ppm(path, mine, ref):
    """Write the difference image: identical pixels 25% grey, differing ones
    coloured by the magnitude of the (signed) difference, R=min(255,32*|dm|)."""
    m = mine.astype(np.int64)
    r = ref.astype(np.int64)
    neq = m != r
    dm = m - r

    img = np.empty((HEIGHT, WIDTH, 3), dtype=np.uint8)
    img[:, :, 0] = GREY
    img[:, :, 1] = GREY
    img[:, :, 2] = GREY
    if neq.any():
        mag = np.minimum(255, 32 * np.abs(dm))
        img[:, :, 0] = np.where(neq, mag, GREY).astype(np.uint8)
        img[:, :, 1] = np.where(neq, np.minimum(255, 8 * np.abs(dm)), GREY).astype(
            np.uint8
        )
        img[:, :, 2] = np.where(
            neq, np.minimum(255, 2 * np.abs(dm) + 16), GREY
        ).astype(np.uint8)

    header = b"P6\n%d %d\n255\n" % (WIDTH, HEIGHT)
    with open(path, "wb") as fh:
        fh.write(header)
        fh.write(img.tobytes())


def print_report(stats, mine_path, ref_path):
    print("mine: %s" % mine_path)
    print("ref : %s" % ref_path)
    print(
        "differing pixels: %d / %d (%.4f%%)"
        % (stats["diff_pixels"], stats["total_pixels"], stats["diff_percent"])
    )
    if stats["identical"]:
        print("bounding box: none (frames are identical)")
        print("first differing pixel: none")
        print("top scanlines: none")
        return
    bb = stats["bbox"]
    fd = stats["first_diff"]
    print(
        "bounding box: x %d..%d, y %d..%d"
        % (bb["min_x"], bb["max_x"], bb["min_y"], bb["max_y"])
    )
    print(
        "first differing pixel: (x=%d, y=%d)  mine=0x%03X (emphasis=%d colour=%d)  "
        "ref=0x%03X (emphasis=%d colour=%d)"
        % (
            fd["x"],
            fd["y"],
            fd["mine"],
            fd["mine_emphasis"],
            fd["mine_colour"],
            fd["ref"],
            fd["ref_emphasis"],
            fd["ref_colour"],
        )
    )
    print("scanlines with most differences:")
    for entry in stats["top_scanlines"]:
        print("    y=%-3d  %d differing pixels" % (entry["scanline"], entry["count"]))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="framediff.py",
        description="Compare two NES frame dumps (.idx, 256x240 u16 LE).",
        epilog=__doc__.split("Exit status")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("mine", help="frame dump produced by your emulator")
    parser.add_argument("ref", help="reference frame dump from the oracle")
    parser.add_argument(
        "--ppm-out",
        metavar="FILE",
        default=None,
        help="write a 256x240 P6 difference image",
    )
    parser.add_argument(
        "--json", action="store_true", help="print a machine-readable summary object"
    )
    parser.add_argument(
        "--fail-on-diff",
        action="store_true",
        help="exit with status 2 (not 1) when the frames differ",
    )
    args = parser.parse_args(argv)

    try:
        mine = load_idx(args.mine)
        ref = load_idx(args.ref)
        stats = diff_stats(mine, ref)
        if args.ppm_out:
            write_ppm(args.ppm_out, mine, ref)
    except FrameError as exc:
        print("framediff.py: error: %s" % exc, file=sys.stderr)
        return 2
    except OSError as exc:
        print("framediff.py: error: %s" % exc, file=sys.stderr)
        return 2

    if args.json:
        out = dict(stats)
        out["mine"] = args.mine
        out["ref"] = args.ref
        if args.ppm_out:
            out["ppm_out"] = args.ppm_out
        print(json.dumps(out, indent=2))
    else:
        print_report(stats, args.mine, args.ref)
        if args.ppm_out:
            print("difference image written to %s" % args.ppm_out)

    if stats["identical"]:
        return 0
    return 2 if args.fail_on_diff else 1


if __name__ == "__main__":
    sys.exit(main())
