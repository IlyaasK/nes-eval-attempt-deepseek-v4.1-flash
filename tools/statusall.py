#!/usr/bin/env python3
"""Run every dev-roms/test ROM through our emulator and print its final log."""
import concurrent.futures, glob, os, re, subprocess, sys
ROOT = "/task"
def one(rom):
    frames = 3000 if "apu_test" in rom or "mmc3" in rom else 900
    try:
        p = subprocess.run([os.path.join(ROOT,"tools/nesrun_trace"), rom, str(frames), "--prgram"],
                           cwd=ROOT, capture_output=True, timeout=frames*0.3+60)
        out = p.stdout.decode("utf8","replace")
        lines = [l for l in out.splitlines() if l.startswith("frame ")]
        last = lines[-1] if lines else p.stderr.decode()[-200:]
        m = re.search(r"status=\$([0-9A-Fa-f]{2}) sig=(\S+) log=\"(.*)\"", last)
        if m:
            return (rom, m.group(1), m.group(3))
        return (rom, "??", last[:150])
    except Exception as e:
        return (rom, "ERR", str(e)[:120])
if __name__ == "__main__":
    roms = sorted(glob.glob(os.path.join(ROOT,"dev-roms/test/*.nes")))
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for rom, st, log in ex.map(one, roms):
            name = os.path.basename(rom)
            ok = "Passed" in log
            print("%-46s %s %s %s" % (name, st, "PASS" if ok else "     ", log[:110]))
            sys.stdout.flush()
