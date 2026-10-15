#!/usr/bin/env python3
"""sweep_suppress.py -- find the $2002 read geometry that matches the reference.

Runs the framecheck probe for several entry offsets against both emulators and
scores each candidate configuration by how many frames' colours agree.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import framecheck  # noqa: E402
from asm6502 import Assembler  # noqa: E402
from mkrom import build_rom  # noqa: E402
from probe import build  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(mine, env, off, frames=20):
    text = framecheck.TEMPLATE % "\n".join("        " + s for s in framecheck.delay_seq(off))
    rom = build(text, vectors=("nmi", "start", "irq"))
    path = os.path.join(ROOT, "tmp", "sweep_sup.nes")
    with open(path, "wb") as f:
        f.write(rom)
    import tempfile
    base = tempfile.mkdtemp(prefix="sw_", dir=os.path.join(ROOT, ".oracle-out"))
    os.chmod(base, 0o777)
    md = os.path.join(base, "mine")
    os.makedirs(md, exist_ok=True)
    os.chmod(md, 0o777)
    e = dict(os.environ)
    e.update(env)
    r = subprocess.run([mine, path, str(frames), "--out", md], cwd=ROOT,
                       capture_output=True, text=True, env=e)
    if r.returncode:
        raise RuntimeError(r.stderr[-300:])
    seq = []
    for f in range(frames):
        p = os.path.join(md, "frame_%05d.idx" % f)
        if not os.path.exists(p):
            break
        v = sorted(set(np.fromfile(p, dtype="<u2").flatten().tolist()))
        seq.append("W" if 0x30 in v else ("B" if 0x0F in v else "?"))
    subprocess.run(["rm", "-rf", base], capture_output=True)
    return "".join(seq)


def main():

    frames = 20
    refs = {}
    for off in range(5):
        text = framecheck.TEMPLATE % "\n".join("        " + s for s in framecheck.delay_seq(off))
        rom = build(text, vectors=("nmi", "start", "irq"))
        path = os.path.join(ROOT, "tmp", "sweep_sup.nes")
        with open(path, "wb") as f:
            f.write(rom)
        import tempfile as _tf
        _b = _tf.mkdtemp(prefix="swr_", dir=os.path.join(ROOT, ".oracle-out"))
        os.chmod(_b, 0o777)
        _rd = os.path.join(_b, "ref")
        os.makedirs(_rd, exist_ok=True)
        os.chmod(_rd, 0o777)
        subprocess.run(["oracle", "run", path, str(frames), "--dump-frames", _rd],
                       cwd=ROOT, capture_output=True)
        ref = [np.fromfile(os.path.join(_rd, "frame_%05d.idx" % f), dtype="<u2").reshape(240, 256)
               for f in range(frames)]
        subprocess.run(["rm", "-rf", _b], capture_output=True)
        seq = []
        for r in ref:
            v = sorted(set(r.flatten().tolist()))
            seq.append("W" if 0x30 in v else ("B" if 0x0F in v else "?"))
        refs[off] = "".join(seq)
        print("ref offset %d: %s" % (off, refs[off]))
    mine_bin = os.path.join(ROOT, "tools", "nesrun_trace")
    for mode in sys.argv[1:] or ["1", "16"]:
        for setdot in ([0, 1, 2, 3] if mode == "16" else [0]):
            env = {"VBL_SUPPRESS": mode, "VBL_SET_DOT": str(setdot)}
            total = 0
            ok = 0
            details = []
            for off in range(5):
                seq = run(mine_bin, env, off, frames)
                miss = sum(1 for a, b in zip(seq, refs[off]) if b == "W" and a == "B")
                spur = sum(1 for a, b in zip(seq, refs[off]) if b == "B" and a == "W")
                details.append("off%d m%d s%d mine=%s" % (off, miss, spur, seq))
            print("mode %s setdot %d:" % (mode, setdot))
            for d in details:
                print("   " + d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
