#!/usr/bin/env python3
"""Dump side-by-side PNGs of the last frame for a ROM: ref | mine | diff.

Usage: pairshot.py <rom> [frames] [--keys HEX] [--frame N] [--out FILE]
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAL = np.fromfile(os.path.join(ROOT, "spec/nes_palette.pal"), dtype=np.uint8).reshape(-1, 3)


def load(path):
    return np.fromfile(path, dtype="<u2").reshape(240, 256)


def to_rgb(idx):
    return PAL[(idx & 0x1FF).astype(np.int32)]


def main():
    rom = sys.argv[1]
    frames = int(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else 200
    keys = "0"
    frame = None
    out = None
    args = sys.argv[3:] if (len(sys.argv) > 2 and not sys.argv[2].startswith("-")) else sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--keys":
            keys = args[i + 1]; i += 2
        elif args[i] == "--frame":
            frame = int(args[i + 1]); i += 2
        elif args[i] == "--out":
            out = args[i + 1]; i += 2
        else:
            print("unknown", args[i]); return 2
    if frame is None:
        frame = frames - 1
    base = tempfile.mkdtemp(prefix="ps_", dir=os.path.join(ROOT, ".oracle-out"))
    os.chmod(base, 0o777)
    refdir = os.path.join(base, "ref")
    minedir = os.path.join(base, "mine")
    for d in (refdir, minedir):
        os.makedirs(d, exist_ok=True)
        os.chmod(d, 0o777)
    r1 = subprocess.run(["oracle", "run", rom, str(frame + 1), "--dump-final", refdir],
                        cwd=ROOT, capture_output=True, text=True)
    r2 = subprocess.run([os.path.join(ROOT, "target/release/nesrun"), rom, str(frame + 1),
                         "--out", minedir, "--keys", keys, "--from", str(frame)],
                        cwd=ROOT, capture_output=True, text=True)
    if r1.returncode or r2.returncode:
        print("fail", r1.stderr[-200:], r2.stderr[-200:])
        return 1
    rp = os.path.join(refdir, "frame_%05d.idx" % frame)
    mp = os.path.join(minedir, "frame_%05d.idx" % frame)
    r = load(rp)
    m = load(mp)
    rgb_r = to_rgb(r)
    rgb_m = to_rgb(m)
    d = (r != m)
    rgb_d = np.zeros_like(rgb_r)
    rgb_d[..., 0] = np.where(d, 255, 0)
    rgb_d[..., 1] = np.where(d, 255, 0)
    rgb_d[..., 2] = np.where(d, 255, 0)
    gap = np.zeros((240, 4, 3), dtype=np.uint8)
    img = np.concatenate([rgb_m, gap, rgb_r, gap, rgb_d], axis=1)
    img4 = np.concatenate([img, np.full((240, img.shape[1], 1), 255, dtype=np.uint8)], axis=2)
    out = out or os.path.join(ROOT, "tmp", "pair_%s.png" % os.path.basename(rom).replace(".nes", ""))
    scale = 3
    big = np.repeat(np.repeat(img4, scale, axis=0), scale, axis=1)
    write_png(out, big)
    print("wrote %s  (%d differing pixels)" % (out, int(d.sum())))
    subprocess.run(["rm", "-rf", base], capture_output=True)
    return 0


def write_png(path, arr):
    import zlib
    h, w, _ = arr.shape
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (len(data).to_bytes(4, "big") + tag + data +
                (zlib.crc32(tag + data) & 0xFFFFFFFF).to_bytes(4, "big"))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0]))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    sys.exit(main())
