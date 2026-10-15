#!/usr/bin/env python3
"""Step the oracle session one frame at a time and report per-frame audio counts
and framebuffer hashes, for comparing frame/audio alignment with our emulator.

Usage: session_step.py <rom> <frames>
Prints: frame index, audio samples produced during that frame, framebuffer hash.
"""
import hashlib
import json
import subprocess
import sys

ORACLE = "oracle"


def run(*args, binary=False):
    p = subprocess.run([ORACLE, "session", *args], capture_output=True,
                       text=not binary)
    if p.returncode != 0:
        sys.stderr.write((p.stderr or b"").decode(errors="replace"))
        sys.exit(1)
    if binary:
        return p.stdout if isinstance(p.stdout, bytes) else p.stdout.encode()
    return p.stdout if isinstance(p.stdout, str) else p.stdout.decode()


def main():
    rom = sys.argv[1]
    frames = int(sys.argv[2])
    info = json.loads(run("start", rom))
    sid = info["id"]
    total = 0
    try:
        for f in range(frames):
            run("run-frame", sid, "1")
            audio = run("audio", sid, binary=True)
            n = len(audio) // 2
            total += n
            fb = run("framebuffer", sid, binary=True)
            h = hashlib.sha256(fb).hexdigest()[:16]
            pre = hashlib.sha256(audio[:16]).hexdigest()[:8] if audio else "-"
            print("frame %5d: samples %4d  total %6d  fb %s  audio_head %s" % (f, n, total, h, pre))
    finally:
        run("end", sid)


if __name__ == "__main__":
    main()
