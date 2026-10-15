#!/usr/bin/env python3
"""sweep_dropdot.py -- find the vblank-flag drop dot that matches the reference.

Sweeps the dot (on scanline 241, then 240) at which a $2002 read drops the
vblank flag and scores each candidate against the reference using the
framecheck probe (which reports frame losses as backdrop colours).
"""
import concurrent.futures
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import framecheck  # noqa: E402
from probe import build  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = 20
MINE = os.path.join(ROOT, "tools", "nesrun_trace")


def build_probe(off):
    text = framecheck.TEMPLATE % "\n".join("        " + s for s in framecheck.delay_seq(off))
    return build(text, vectors=("nmi", "start", "irq"))


def classify(vals):
    return "W" if 0x30 in vals else ("B" if 0x0F in vals else "?")


def ref_seq(off, base):
    rom = build_probe(off)
    path = os.path.join(base, "probe_%d.nes" % off)
    with open(path, "wb") as f:
        f.write(rom)
    rd = os.path.join(base, "ref_%d" % off)
    os.makedirs(rd, exist_ok=True)
    os.chmod(rd, 0o777)
    subprocess.run(["oracle", "run", path, str(FRAMES), "--dump-frames", rd],
                   cwd=ROOT, capture_output=True)
    out = []
    for f in range(FRAMES):
        p = os.path.join(rd, "frame_%05d.idx" % f)
        if not os.path.exists(p):
            break
        out.append(classify(np.fromfile(p, dtype="<u2").flatten().tolist()))
    return "".join(out)


def mine_seq(off, drop_dot, scanline, base):
    rom = build_probe(off)
    path = os.path.join(base, "mp_%d_%d_%d.nes" % (off, scanline, drop_dot))
    with open(path, "wb") as f:
        f.write(rom)
    md = os.path.join(base, "mine_%d_%d_%d" % (off, scanline, drop_dot))
    os.makedirs(md, exist_ok=True)
    env = dict(os.environ)
    env.update({"VBL_SUPPRESS": "16", "VBL_SET_DOT": "1",
                "VBL_DROP_DOT": str(drop_dot), "VBL_DROP_SL": str(scanline)})
    r = subprocess.run([MINE, path, str(FRAMES), "--out", md], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr[-300:])
    out = []
    for f in range(FRAMES):
        p = os.path.join(md, "frame_%05d.idx" % f)
        if not os.path.exists(p):
            break
        out.append(classify(np.fromfile(p, dtype="<u2").flatten().tolist()))
    return "".join(out)


def main():
    base = tempfile.mkdtemp(prefix="dd_", dir=os.path.join(ROOT, ".oracle-out"))
    os.chmod(base, 0o777)
    refs = {}
    for off in range(5):
        refs[off] = ref_seq(off, base)
        print("ref off%d: %s" % (off, refs[off]), flush=True)

    jobs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for sl in (241,):
            for d in range(0, 341):
                jobs.append(ex.submit(mine_seq, 1, d, sl, base))
    # map back
    results = {}
    i = 0
    for sl in (241,):
        for d in range(0, 341):
            results[(sl, d)] = jobs[i].result()
            i += 1
    scored = []
    for (sl, d), seq in results.items():
        miss = sum(1 for a, b in zip(seq, refs[1]) if b == "W" and a != "W")
        spur = sum(1 for a, b in zip(seq, refs[1]) if b != "W" and a == "W")
        scored.append((miss + spur, sl, d, miss, spur, seq))
    scored.sort()
    for sc, sl, d, miss, spur, seq in scored[:10]:
        print("sl=%d dot=%3d score=%d (miss=%d spur=%d) %s" % (sl, d, sc, miss, spur, seq))
    subprocess.run(["rm", "-rf", base], capture_output=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
