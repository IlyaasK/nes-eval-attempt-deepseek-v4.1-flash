#!/usr/bin/env python3
"""Run the local emulator on a recorded replay and diff against the cached
reference dumps, printing total differing pixels and differing frames.

Usage: measure_replay.py <rom-name> <replay> <frames> [VAR=value ...]
The reference dumps must already exist at .oracle-out/rep_<rom>/ref/.
"""
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    rom = sys.argv[1]
    replay = sys.argv[2]
    frames = sys.argv[3]
    env = dict(os.environ)
    env.update({k: v for k, v in (a.split("=", 1) for a in sys.argv[4:])})
    ref = os.path.join(ROOT, ".oracle-out", "rep_%s" % rom, "ref")
    out = "/tmp/rep_%s" % rom
    subprocess.run(["rm", "-rf", out])
    os.makedirs(out, exist_ok=True)
    subprocess.run(
        [os.path.join(ROOT, "tools/nesrun_trace"), os.path.join(ROOT, "dev-roms", "%s.nes" % rom),
         frames, "--out", out, "--replay", replay],
        capture_output=True, env=env)
    tot = 0
    nfr = 0
    for f in sorted(os.listdir(ref)):
        if not f.endswith(".idx"):
            continue
        a = np.fromfile(os.path.join(ref, f), dtype="<u2")
        b = np.fromfile(os.path.join(out, f), dtype="<u2")
        if a.shape != b.shape:
            continue
        n = int((a != b).sum())
        if n:
            tot += n
            nfr += 1
    print("%s -> %d px in %d frames" % (sys.argv[4:] or "default", tot, nfr))


if __name__ == "__main__":
    sys.exit(main())
