#!/usr/bin/env python3
"""audiodiff.py -- compare two mono 16-bit WAV files sample by sample.

Usage:
    audiodiff.py A.wav B.wav [--json] [--alignment N] [--fail-on-diff]

Both files must be mono 16-bit; 44100 Hz is expected but not required (a
different rate only produces a warning).  For every alignment offset in
``-N..=N`` (default just 0) the tool reports

    * the maximum absolute sample difference,
    * the RMS of the sample differences,
    * how many exactly-equal samples the overlap holds,
    * the Pearson correlation of the two overlap sequences,

then prints the offset with the lowest maximum absolute difference.  Negative
offsets mean B is shifted earlier relative to A: sample ``A[i]`` is compared
against ``B[i + offset]``.

Exit status is 0 when the best alignment matches exactly, 1 when it does not,
and 2 for usage or file errors; ``--fail-on-diff`` makes a mismatch exit 2
instead of 1.
"""

import argparse
import json
import os
import sys
import wave

import numpy as np

EXPECTED_RATE = 44100


class AudioError(Exception):
    pass


def load_wav(path):
    """Load a mono 16-bit WAV; returns (samples int16 array, rate)."""
    if not os.path.exists(path):
        raise AudioError("file not found: %s" % path)
    try:
        with wave.open(path, "rb") as w:
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            rate = w.getframerate()
            nframes = w.getnframes()
            raw = w.readframes(nframes)
    except wave.Error as exc:
        raise AudioError("%s is not a readable WAV: %s" % (path, exc))
    if channels != 1:
        raise AudioError("%s has %d channels, expected mono" % (path, channels))
    if sampwidth != 2:
        raise AudioError(
            "%s has %d-byte samples, expected 16-bit" % (path, sampwidth)
        )
    samples = np.frombuffer(raw, dtype="<i2")
    return samples, rate


def compare_at(a, b, offset):
    """Compare a and b with B shifted by `offset` samples."""
    if offset >= 0:
        a_cut = a[: a.size - offset] if offset < a.size else a[:0]
        b_cut = b[offset:]
    else:
        a_cut = a[-offset:]
        b_cut = b[: b.size + offset]
    n = min(a_cut.size, b_cut.size)
    a_cut = a_cut[:n].astype(np.float64)
    b_cut = b_cut[:n].astype(np.float64)
    if n == 0:
        return {
            "offset": offset,
            "overlap": 0,
            "max_abs_diff": None,
            "rms_diff": None,
            "equal_samples": 0,
            "correlation": None,
        }
    diff = a_cut - b_cut
    max_abs = float(np.max(np.abs(diff)))
    rms = float(np.sqrt(np.mean(diff * diff)))
    equal = int(np.count_nonzero(diff == 0.0))
    if n > 1 and np.std(a_cut) > 0 and np.std(b_cut) > 0:
        corr = float(np.corrcoef(a_cut, b_cut)[0, 1])
    else:
        corr = None
    return {
        "offset": offset,
        "overlap": int(n),
        "max_abs_diff": max_abs,
        "rms_diff": rms,
        "equal_samples": equal,
        "correlation": corr,
    }


def analyse(a, b, alignment, rate_a, rate_b):
    length_a = int(a.size)
    length_b = int(b.size)
    results = [compare_at(a, b, off) for off in range(-alignment, alignment + 1)]
    best = min(
        results,
        key=lambda r: (
            r["max_abs_diff"] if r["max_abs_diff"] is not None else float("inf"),
            r["offset"],
        ),
    )
    return {
        "a_samples": length_a,
        "b_samples": length_b,
        "sample_count_diff": length_a - length_b,
        "a_rate": rate_a,
        "b_rate": rate_b,
        "alignment_range": alignment,
        "results": results,
        "best": best,
    }


def print_summary(info, path_a, path_b):
    print("A: %s  (%d samples @ %d Hz)" % (path_a, info["a_samples"], info["a_rate"]))
    print("B: %s  (%d samples @ %d Hz)" % (path_b, info["b_samples"], info["b_rate"]))
    diff = info["sample_count_diff"]
    print(
        "length difference: %+d samples (A %d, B %d)"
        % (diff, info["a_samples"], info["b_samples"])
    )
    if diff != 0:
        print(
            "WARNING: lengths differ by %d samples (%.4f s); comparison uses the "
            "overlapping region" % (abs(diff), abs(diff) / float(info["a_rate"] or 1))
        )
    if info["a_rate"] != info["b_rate"]:
        print("WARNING: sample rates differ (%d vs %d)" % (info["a_rate"], info["b_rate"]))

    print("alignment scan (%d offset(s)):" % len(info["results"]))
    for r in info["results"]:
        if r["overlap"] == 0:
            print("    offset %+4d  (no overlap)" % r["offset"])
            continue
        corr = "n/a" if r["correlation"] is None else "%.6f" % r["correlation"]
        print(
            "    offset %+4d  overlap=%-7d maxdiff=%-10s rms=%-12s equal=%-7d corr=%s"
            % (
                r["offset"],
                r["overlap"],
                "%.1f" % r["max_abs_diff"],
                "%.6f" % r["rms_diff"],
                r["equal_samples"],
                corr,
            )
        )
    best = info["best"]
    if best["overlap"] == 0:
        print("best alignment: offset %+d (no overlap between the two files)" % best["offset"])
    else:
        print(
            "best alignment: offset %+d  maxdiff=%.1f rms=%.6f equal=%d/%d (%.2f%%)"
            % (
                best["offset"],
                best["max_abs_diff"],
                best["rms_diff"],
                best["equal_samples"],
                best["overlap"],
                100.0 * best["equal_samples"] / best["overlap"],
            )
        )
    if info["a_samples"] == info["b_samples"] and best["offset"] == 0 and best["max_abs_diff"] == 0.0:
        print("RESULT: identical (every sample matches exactly)")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="audiodiff.py",
        description="Compare two mono 16-bit WAV files.",
        epilog=__doc__.split("Exit status")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("a", help="first WAV file")
    parser.add_argument("b", help="second WAV file")
    parser.add_argument(
        "--json", action="store_true", help="print a machine-readable summary object"
    )
    parser.add_argument(
        "--alignment",
        type=int,
        default=0,
        metavar="N",
        help="scan every offset in -N..=N (default 0, i.e. no shift)",
    )
    parser.add_argument(
        "--fail-on-diff",
        action="store_true",
        help="exit with status 2 (not 1) when the files differ",
    )
    args = parser.parse_args(argv)

    if args.alignment < 0:
        print("audiodiff.py: error: --alignment must be >= 0", file=sys.stderr)
        return 2

    try:
        a, rate_a = load_wav(args.a)
        b, rate_b = load_wav(args.b)
    except AudioError as exc:
        print("audiodiff.py: error: %s" % exc, file=sys.stderr)
        return 2

    info = analyse(a, b, args.alignment, rate_a, rate_b)
    info["a"] = args.a
    info["b"] = args.b

    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print_summary(info, args.a, args.b)

    best = info["best"]
    identical = (
        info["a_samples"] == info["b_samples"]
        and best["offset"] == 0
        and best["max_abs_diff"] == 0.0
    )
    if identical:
        return 0
    return 2 if args.fail_on_diff else 1


if __name__ == "__main__":
    sys.exit(main())
