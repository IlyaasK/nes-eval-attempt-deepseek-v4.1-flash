#!/usr/bin/env python3
"""Quick frame-by-frame comparison summary for several ROMs."""
import os, subprocess, sys, tempfile
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def one(rom, frames):
    base = tempfile.mkdtemp(prefix="qd_", dir=os.path.join(ROOT, ".oracle-out"))
    os.chmod(base, 0o777)
    rd, md = os.path.join(base, "ref"), os.path.join(base, "mine")
    for d in (rd, md):
        os.makedirs(d, exist_ok=True); os.chmod(d, 0o777)
    r1 = subprocess.run(["oracle", "run", rom, str(frames), "--dump-frames", rd], cwd=ROOT, capture_output=True)
    r2 = subprocess.run([os.path.join(ROOT, "target/release/nesrun"), rom, str(frames), "--out", md], cwd=ROOT, capture_output=True)
    if r1.returncode or r2.returncode:
        return "%s: FAILED %s %s" % (os.path.basename(rom), r1.stderr[-80:], r2.stderr[-80:])
    exact = 0; total = 0; worst = 0; first = None
    for n in range(frames):
        rf = os.path.join(rd, "frame_%05d.idx" % n); mf = os.path.join(md, "frame_%05d.idx" % n)
        if not (os.path.exists(rf) and os.path.exists(mf)):
            break
        a = np.fromfile(mf, dtype="<u2"); b = np.fromfile(rf, dtype="<u2")
        total += 1
        d = int((a != b).sum())
        if d == 0: exact += 1
        else:
            if first is None: first = n
            worst = max(worst, d)
    subprocess.run(["rm", "-rf", base], capture_output=True)
    return "%-42s %3d/%3d exact  worst %6d  first bad %s" % (os.path.basename(rom), exact, total, worst, first)
if __name__ == "__main__":
    frames = int(sys.argv[1])
    for rom in sys.argv[2:]:
        print(one(rom, frames), flush=True)
