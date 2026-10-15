#!/usr/bin/env python3
"""Aggregate frame-diff score for ROMs: exact frames, total differing pixels.

Usage: score.py [--frames N] [--jobs N] [rom ...]
"""
import concurrent.futures
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np

DEFAULTS = [
    ("dev-roms/robotfindskitten.nes", 400),
    ("dev-roms/rhde.nes", 400),
    ("dev-roms/file-fixers.nes", 400),
    ("dev-roms/stallar.nes", 400),
]


def run_one(rom, frames, keys="0"):
    base = tempfile.mkdtemp(prefix="sc_", dir=os.path.join(ROOT, ".oracle-out"))
    os.chmod(base, 0o777)
    refdir = os.path.join(base, "ref")
    minedir = os.path.join(base, "mine")
    for d in (refdir, minedir):
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o777)
    r1 = subprocess.run(["oracle", "run", rom, str(frames), "--dump-frames", refdir],
                        cwd=ROOT, capture_output=True, text=True)
    r2 = subprocess.run([os.path.join(ROOT, "target/release/nesrun"), rom, str(frames),
                         "--out", minedir, "--keys", keys],
                        cwd=ROOT, capture_output=True, text=True)
    if r1.returncode != 0:
        return rom, None, "ORACLE FAILED: %s" % (r1.stderr.strip()[:120],)
    if r2.returncode != 0:
        return rom, None, "EMU FAILED: %s" % (r2.stderr.strip()[:120],)
    exact = 0
    total = 0
    tot_diff = 0
    worst = (-1, 0)
    hist = []
    for n in range(frames):
        rf = os.path.join(refdir, "frame_%05d.idx" % n)
        mf = os.path.join(minedir, "frame_%05d.idx" % n)
        if not os.path.exists(rf) or not os.path.exists(mf):
            break
        a = np.fromfile(mf, dtype="<u2")
        b = np.fromfile(rf, dtype="<u2")
        total += 1
        d = int((a != b).sum())
        tot_diff += d
        hist.append(d)
        if d == 0:
            exact += 1
        elif d > worst[1]:
            worst = (n, d)
    subprocess.run(["rm", "-rf", base], capture_output=True)
    return rom, (exact, total, tot_diff, worst, hist), None


def main():
    args = sys.argv[1:]
    frames_override = None
    jobs = 8
    keys = "0"
    roms = []
    i = 0
    while i < len(args):
        if args[i] == "--frames":
            frames_override = int(args[i + 1]); i += 2
        elif args[i] == "--jobs":
            jobs = int(args[i + 1]); i += 2
        elif args[i] == "--keys":
            keys = args[i + 1]; i += 2
        else:
            roms.append((args[i], frames_override or 300)); i += 1
    if not roms:
        roms = [(r, frames_override or f) for r, f in DEFAULTS]
    os.makedirs(os.path.join(ROOT, ".oracle-out"), exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(run_one, rom, fr, keys) for rom, fr in roms]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda r: str(r[0]))
    print("%-52s %s" % ("ROM", "RESULT"))
    for rom, res, err in results:
        name = os.path.basename(rom)
        if err:
            print("%-52s %s" % (name, err))
            continue
        exact, total, tot_diff, worst, hist = res
        first = next((n for n, d in enumerate(hist) if d), None)
        print("%-52s exact %4d/%4d  totdiff %8d  worst %6d @%s  first %s"
              % (name, exact, total, tot_diff, worst[1], worst[0], first))
    return 0


if __name__ == "__main__":
    sys.exit(main())
