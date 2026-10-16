#!/usr/bin/env python3
"""sidediff.py -- side-by-side crop comparison of reference vs local frames.

Usage: sidediff.py <refdir> <minedir> <frame> <r0> <r1> <c0> <c1> <out.png> [scale]
Stacks the reference crop above the local crop separated by a red line.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import idx2png  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    a = np.fromfile(path, dtype="<u2").reshape(240, 256)
    pal = np.array(idx2png.load_palette(os.path.join(ROOT, "spec/nes_palette.pal")), dtype=np.uint8)
    return pal[a.reshape(-1)].reshape(240, 256, 3)


def main():
    ref, mine, f, r0, r1, c0, c1, out = sys.argv[1:9]
    scale = int(sys.argv[9]) if len(sys.argv) > 9 else 4
    a = load(os.path.join(ref, "frame_%05d.idx" % int(f)))[int(r0):int(r1), int(c0):int(c1)]
    b = load(os.path.join(mine, "frame_%05d.idx" % int(f)))[int(r0):int(r1), int(c0):int(c1)]
    sep = np.zeros((2, a.shape[1], 3), dtype=np.uint8)
    sep[:, :, 0] = 255
    img = np.concatenate([a, sep, b], axis=0)
    img = np.repeat(np.repeat(img, scale, axis=0), scale, axis=1)
    idx2png.write_png(out, img)
    print("wrote", out, img.shape)


if __name__ == "__main__":
    main()
