#!/usr/bin/env python3
"""Run the oracle and the local emulator on the same ROM and compare frames/audio.

Usage: compare.py <rom> <frames> [--keys HEX] [--audio] [--from N] [--mine BIN]
Prints per-frame differing pixel counts (and audio diff stats with --audio).
"""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kw)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 2
    rom, frames = args[0], args[1]
    keys = "0"
    audio = False
    start = 0
    mine = os.path.join(ROOT, "target/release/nesrun")
    i = 2
    while i < len(args):
        if args[i] == "--keys":
            keys = args[i + 1]
            i += 2
        elif args[i] == "--audio":
            audio = True
            i += 1
        elif args[i] == "--from":
            start = int(args[i + 1])
            i += 2
        elif args[i] == "--mine":
            mine = args[i + 1]
            i += 2
        else:
            print("unknown arg", args[i])
            return 2

    base = tempfile.mkdtemp(prefix="cmp_", dir=os.path.join(ROOT, ".oracle-out"))
    os.chmod(base, 0o777)
    refdir = os.path.join(base, "ref")
    minedir = os.path.join(base, "mine")
    os.makedirs(refdir, mode=0o777)
    os.makedirs(minedir, mode=0o777)
    os.chmod(refdir, 0o777)
    os.chmod(minedir, 0o777)

    rc = run(["oracle", "run", rom, frames, "--dump-frames", refdir,
              "--from", str(start)] + (["--dump-audio", os.path.join(base, "ref.wav")] if audio else []))
    if rc.returncode != 0:
        print("oracle failed:", rc.stdout, rc.stderr)
        return 1

    rc = run([mine, rom, frames, "--out", minedir, "--keys", keys,
              "--from", str(start)] + (["--wav", os.path.join(base, "mine.wav")] if audio else []))
    if rc.returncode != 0:
        print("emulator failed:", rc.stdout, rc.stderr)
        return 1

    # frame-by-frame diff
    worst = 0
    exact = 0
    total = 0
    first_bad = None
    for n in range(start, int(frames)):
        rf = os.path.join(refdir, "frame_%05d.idx" % n)
        mf = os.path.join(minedir, "frame_%05d.idx" % n)
        if not os.path.exists(rf) or not os.path.exists(mf):
            print("frame %d: missing dump (%s %s)" % (n, os.path.exists(rf), os.path.exists(mf)))
            break
        out = run(["python3", os.path.join(ROOT, "tools/framediff.py"), mf, rf])
        line = [l for l in out.stdout.splitlines() if "differing pixels" in l]
        total += 1
        if not line:
            print("frame %d: %s" % (n, out.stdout.strip() or out.stderr.strip()))
            continue
        cnt = int(line[0].split()[2])
        if cnt == 0:
            exact += 1
        else:
            if first_bad is None:
                first_bad = n
                print(out.stdout.strip())
        worst = max(worst, cnt)
        print("frame %5d: %6d differing pixels%s" % (n, cnt, "" if cnt else "  (exact)"))
    print("---")
    print("exact frames: %d/%d, worst %d pixels%s" % (exact, total, worst,
          "" if first_bad is None else ", first bad frame %d" % first_bad))

    if audio:
        out = run(["python3", os.path.join(ROOT, "tools/audiodiff.py"),
                   os.path.join(base, "mine.wav"), os.path.join(base, "ref.wav")])
        print(out.stdout.strip())
        print(out.stderr.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
