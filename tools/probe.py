#!/usr/bin/env python3
"""probe.py -- build a small NROM probe ROM from assembly and run it on both
the reference and our emulator, then compare framebuffers.

Library use:
    from probe import build, run_both
    rom = build(asm_text, chr=bytes(...))
    ref, mine = run_both("tmp/x.nes", rom, frames=4)

CLI:
    probe.py SRC.asm OUT.nes [--frames N]
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asm6502 import Assembler  # noqa: E402
from mkrom import build_rom  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(asm_text, chr_ram=True, mirroring="horizontal", origin=0xC000,
          prg_banks=2, vectors=("start", "start", "start"), mapper=0, chr_bytes=None,
          bank_size=0x4000):
    a = Assembler(origin=origin)
    for line in asm_text.splitlines():
        a.line(line)
    code = a.assemble()
    body = bytearray(b"\xea" * bank_size)
    body[0x0000:len(code)] = code
    v = [a.labels[x] if isinstance(x, str) else x for x in vectors]
    vec_off = bank_size - 6
    for i in range(3):
        body[vec_off + i * 2] = v[i] & 0xFF
        body[vec_off + i * 2 + 1] = (v[i] >> 8) & 0xFF
    prg = bytes(body) * prg_banks
    if chr_bytes is not None:
        chr_ = chr_bytes
    else:
        chr_ = b"" if chr_ram else bytes(8192)
    return build_rom(prg, chr_, mapper, mirroring, 0, False, 0)


def run_both(path, rom, frames=4, keys="0"):
    with open(path, "wb") as f:
        f.write(rom)
    base = tempfile.mkdtemp(prefix="probe_", dir=os.path.join(ROOT, ".oracle-out"))
    os.chmod(base, 0o777)
    rd, md = os.path.join(base, "ref"), os.path.join(base, "mine")
    for d in (rd, md):
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o777)
    r1 = subprocess.run(["oracle", "run", path, str(frames), "--dump-frames", rd],
                        cwd=ROOT, capture_output=True, text=True)
    r2 = subprocess.run([os.path.join(ROOT, "target/release/nesrun"), path, str(frames),
                         "--out", md, "--keys", keys], cwd=ROOT, capture_output=True, text=True)
    if r1.returncode:
        raise RuntimeError("oracle failed: " + r1.stderr[-300:])
    if r2.returncode:
        raise RuntimeError("emu failed: " + r2.stderr[-300:])
    ref = [np.fromfile(os.path.join(rd, "frame_%05d.idx" % f), dtype="<u2").reshape(240, 256)
           for f in range(frames) if os.path.exists(os.path.join(rd, "frame_%05d.idx" % f))]
    mine = [np.fromfile(os.path.join(md, "frame_%05d.idx" % f), dtype="<u2").reshape(240, 256)
            for f in range(frames) if os.path.exists(os.path.join(md, "frame_%05d.idx" % f))]
    subprocess.run(["rm", "-rf", base], capture_output=True)
    return ref, mine


def main():
    src = sys.argv[1]
    out = sys.argv[2]
    frames = 6
    if "--frames" in sys.argv:
        frames = int(sys.argv[sys.argv.index("--frames") + 1])
    text = open(src).read()
    rom = build(text)
    ref, mine = run_both(out, rom, frames)
    for i, (r, m) in enumerate(zip(ref, mine)):
        d = int((r != m).sum())
        print("frame %d: %d differing pixels (ref uniq %d, mine uniq %d)"
              % (i, d, len(np.unique(r)), len(np.unique(m))))


if __name__ == "__main__":
    main()
