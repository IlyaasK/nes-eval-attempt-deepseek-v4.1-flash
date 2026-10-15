#!/usr/bin/env python3
"""Run test ROMs and report the $6000 status/log each writes."""
import os, re, subprocess, sys
ROOT = "/task"
def run(rom, frames=400):
    p = subprocess.run([os.path.join(ROOT,"target/release/nesrun"), rom, str(frames), "--prgram"],
                       cwd=ROOT, capture_output=True, text=True)
    lines = [l for l in p.stderr.splitlines() if "status=$" in l]
    if not lines:
        return "no $6000 output", ""
    last = lines[-1]
    m = re.search(r"status=\$([0-9A-F]{2}) sig=([0-9A-F]{6}) log=(.*)", last)
    if not m:
        return last, ""
    return "$%s" % m.group(1), m.group(3)
for rom in sys.argv[1:]:
    st, log = run(rom)
    name = os.path.basename(rom)
    print("%-42s %s %s" % (name, st, log[:90]))
