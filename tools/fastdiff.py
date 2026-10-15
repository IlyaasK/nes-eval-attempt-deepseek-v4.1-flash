#!/usr/bin/env python3
"""fastdiff.py -- run one ROM, diff every frame against a cached reference dump.

Usage:
  fastdiff.py <rom> [frames] [--keys HEX] [--refresh] [--ref DIR] [--out DIR]
              [--quiet] [--from N]

The reference frames are cached in .oracle-out/cache/<rom key> and only
regenerated on --refresh.  Prints per-frame differing pixel counts (compressed
as a run-length summary) and a final verdict.
"""
import argparse
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".oracle-out", "cache")


def key_for(rom, frames, keys):
    base = os.path.basename(rom).replace(".nes", "")
    return "%s_%d_%s" % (base, frames, keys)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("frames", nargs="?", type=int, default=200)
    ap.add_argument("--keys", default="0")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--from", dest="startf", type=int, default=0)
    ap.add_argument("--mine", default=os.path.join(ROOT, "target/release/nesrun"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    key = key_for(args.rom, args.frames, args.keys)
    refdir = os.path.join(CACHE, key)
    os.makedirs(refdir, exist_ok=True)
    os.chmod(refdir, 0o777)
    if args.refresh or not os.path.exists(os.path.join(refdir, "frame_%05d.idx" % (args.frames - 1))):
        for f in os.listdir(refdir):
            os.remove(os.path.join(refdir, f))
        cmd = ["oracle", "run", args.rom, str(args.frames), "--dump-frames", refdir]
        if args.keys != "0":
            replay = os.path.join(refdir, "replay.txt")
            with open(replay, "w") as fh:
                fh.write("0 %s\n" % args.keys)
            cmd += ["--replay", replay]
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print("oracle failed:", r.stdout, r.stderr)
            return 1

    minedir = os.path.join(CACHE, key + "_mine")
    for f in os.listdir(minedir) if os.path.isdir(minedir) else []:
        os.remove(os.path.join(minedir, f))
    os.makedirs(minedir, exist_ok=True)
    r = subprocess.run([args.mine, args.rom, str(args.frames), "--out", minedir,
                        "--keys", args.keys, "--from", str(args.startf)],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print("emulator failed:", r.stdout[-500:], r.stderr[-2000:])
        return 1

    total = 0
    exact = 0
    tot_diff = 0
    first = None
    runs = []
    for n in range(args.startf, args.frames):
        rp = os.path.join(refdir, "frame_%05d.idx" % n)
        mp = os.path.join(minedir, "frame_%05d.idx" % n)
        if not os.path.exists(rp) or not os.path.exists(mp):
            break
        a = np.fromfile(mp, dtype="<u2")
        b = np.fromfile(rp, dtype="<u2")
        d = int((a != b).sum())
        total += 1
        tot_diff += d
        if d == 0:
            exact += 1
            runs.append((n, 0))
        else:
            if first is None:
                first = n
            runs.append((n, d))
    if not args.quiet:
        # compress runs of equal diff counts
        out = []
        i = 0
        while i < len(runs):
            j = i
            while j + 1 < len(runs) and runs[j + 1][1] == runs[i][1]:
                j += 1
            if j > i:
                out.append("f%d-%d:%d" % (runs[i][0], runs[j][0], runs[i][1]))
            else:
                out.append("f%d:%d" % (runs[i][0], runs[i][1]))
            i = j + 1
        print(" ".join(out))
    print("%s: exact %d/%d totdiff %d firstbad %s" %
          (os.path.basename(args.rom), exact, total, tot_diff, first))
    return 0


if __name__ == "__main__":
    sys.exit(main())
