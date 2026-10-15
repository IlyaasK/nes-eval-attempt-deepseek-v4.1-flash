#!/usr/bin/env python3
"""Run a suite of ROMs through both the oracle and our emulator and report
frame-exactness.  Usage: suite.py [--frames N] [--jobs N] [rom ...]"""
import concurrent.futures
import glob
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = [
    ("dev-roms/robotfindskitten.nes", 400),
    ("dev-roms/rhde.nes", 400),
    ("dev-roms/file-fixers.nes", 400),
    ("dev-roms/stallar.nes", 400),
    ("dev-roms/test/ppu_vbl_nmi__02-vbl_set_time.nes", 200),
    ("dev-roms/test/ppu_vbl_nmi__03-vbl_clear_time.nes", 200),
    ("dev-roms/test/ppu_vbl_nmi__04-nmi_control.nes", 200),
    ("dev-roms/test/ppu_vbl_nmi__06-suppression.nes", 200),
    ("dev-roms/test/ppu_vbl_nmi__07-nmi_on_timing.nes", 200),
    ("dev-roms/test/ppu_vbl_nmi__08-nmi_off_timing.nes", 200),
    ("dev-roms/test/ppu_vbl_nmi__09-even_odd_frames.nes", 200),
    ("dev-roms/test/ppu_vbl_nmi__10-even_odd_timing.nes", 200),
    ("dev-roms/test/sprite_hit_tests__02.alignment.nes", 200),
    ("dev-roms/test/sprite_hit_tests__03.corners.nes", 200),
    ("dev-roms/test/sprite_hit_tests__04.flip.nes", 200),
    ("dev-roms/test/sprite_hit_tests__05.left_clip.nes", 200),
    ("dev-roms/test/sprite_hit_tests__06.right_edge.nes", 200),
    ("dev-roms/test/sprite_hit_tests__07.screen_bottom.nes", 200),
    ("dev-roms/test/sprite_hit_tests__08.double_height.nes", 200),
    ("dev-roms/test/sprite_overflow_tests__2.Details.nes", 200),
    ("dev-roms/test/sprite_overflow_tests__3.Timing.nes", 200),
    ("dev-roms/test/apu_test__2-len_table.nes", 300),
    ("dev-roms/test/apu_test__4-jitter.nes", 300),
    ("dev-roms/test/apu_test__5-len_timing.nes", 300),
    ("dev-roms/test/apu_test__6-irq_flag_timing.nes", 300),
    ("dev-roms/test/apu_test__8-dmc_rates.nes", 300),
    ("dev-roms/test/cpu_interrupts_v2__1-cli_latency.nes", 300),
    ("dev-roms/test/cpu_interrupts_v2__3-nmi_and_irq.nes", 300),
    ("dev-roms/test/mmc3_test_2__2-details.nes", 300),
    ("dev-roms/test/mmc3_test_2__4-scanline_timing.nes", 300),
    ("dev-roms/test/branch_timing_tests__1.Branch_Basics.nes", 300),
    ("dev-roms/test/cpu_reset__registers.nes", 300),
    ("dev-roms/test/ppu_open_bus.nes", 300),
    ("dev-roms/test/instr_timing.nes", 300),
]


def run_one(rom, frames, keys="0"):
    base = tempfile.mkdtemp(prefix="suite_", dir=os.path.join(ROOT, ".oracle-out"))
    os.chmod(base, 0o777)
    refdir = os.path.join(base, "ref")
    minedir = os.path.join(base, "mine")
    os.makedirs(refdir, mode=0o777)
    os.makedirs(minedir, mode=0o777)
    os.chmod(refdir, 0o777)
    os.chmod(minedir, 0o777)
    r1 = subprocess.run(["oracle", "run", rom, str(frames), "--dump-frames", refdir],
                        cwd=ROOT, capture_output=True, text=True)
    r2 = subprocess.run([os.path.join(ROOT, "target/release/nesrun"), rom, str(frames),
                         "--out", minedir, "--keys", keys],
                        cwd=ROOT, capture_output=True, text=True)
    if r1.returncode != 0:
        return rom, "ORACLE FAILED: %s" % (r1.stderr.strip()[:120],), 0, 0
    if r2.returncode != 0:
        return rom, "EMU FAILED: %s" % (r2.stderr.strip()[:120],), 0, 0
    import numpy as np
    exact = 0
    total = 0
    worst = (-1, 0)
    first_bad = None
    for n in range(frames):
        rf = os.path.join(refdir, "frame_%05d.idx" % n)
        mf = os.path.join(minedir, "frame_%05d.idx" % n)
        if not os.path.exists(rf) or not os.path.exists(mf):
            break
        a = np.fromfile(mf, dtype="<u2")
        b = np.fromfile(rf, dtype="<u2")
        total += 1
        d = int((a != b).sum())
        if d == 0:
            exact += 1
        else:
            if first_bad is None:
                first_bad = n
            if d > worst[1]:
                worst = (n, d)
    subprocess.run(["rm", "-rf", base], capture_output=True)
    return rom, first_bad, exact, total


def main():
    args = sys.argv[1:]
    frames_override = None
    jobs = 8
    roms = []
    i = 0
    while i < len(args):
        if args[i] == "--frames":
            frames_override = int(args[i + 1])
            i += 2
        elif args[i] == "--jobs":
            jobs = int(args[i + 1])
            i += 2
        else:
            roms.append((args[i], frames_override or 300))
            i += 1
    if not roms:
        roms = [(r, frames_override or f) for r, f in DEFAULTS]
    os.makedirs(os.path.join(ROOT, ".oracle-out"), exist_ok=True)
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = [ex.submit(run_one, rom, fr) for rom, fr in roms]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())
    results.sort(key=lambda r: str(r[0]))
    print("%-60s %s" % ("ROM", "RESULT"))
    bad = 0
    for rom, first_bad, exact, total in results:
        name = os.path.basename(rom)
        if first_bad is None and total > 0:
            print("%-60s exact %d/%d" % (name, exact, total))
        else:
            bad += 1
            print("%-60s %d/%d exact, first bad frame %s" % (name, exact, total, first_bad))
    print("---\n%d/%d suites fully exact" % (len(results) - bad, len(results)))


if __name__ == "__main__":
    main()
