#!/usr/bin/env python3
"""firstframe.py -- print the first frame with text pixels (not 0x0F backdrop / 0x00).

Usage: firstframe.py <rom> <frames> [VAR=value ...]
Useful for timing-sensitive test ROMs that blank the screen until a result is
ready: the first non-blank frame measures how long the ROM took.
"""
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    rom, frames = sys.argv[1], sys.argv[2]
    env = dict(os.environ)
    env.update({k: v for k, v in (a.split("=", 1) for a in sys.argv[3:])})
    out = "/tmp/ff_%d" % os.getpid()
    subprocess.run(["rm", "-rf", out])
    os.makedirs(out, exist_ok=True)
    subprocess.run([os.path.join(ROOT, "tools/nesrun_trace"), rom, frames, "--out", out],
                   capture_output=True, env=env)
    nz = None
    for f in range(int(frames)):
        p = os.path.join(out, "frame_%05d.idx" % f)
        if not os.path.exists(p):
            continue
        a = np.fromfile(p, dtype="<u2")
        if int(((a != 0x0F) & (a != 0x00)).sum()) != 0:
            nz = f
            break
    print("%s -> first non-blank frame %s" % (sys.argv[3:] or "default", nz))


if __name__ == "__main__":
    sys.exit(main())
