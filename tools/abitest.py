#!/usr/bin/env python3
"""ABI conformance test: load the wasm via wasmtime and exercise the ABI.

Uses the wasmtime CLI to run a tiny host shim written in Rust?  No - we drive
the exported functions through `wasmtime`'s `run --invoke` is too limited, so we
use a small Rust host binary instead (`tools/abitest`).
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    wasm = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "target/wasm32-unknown-unknown/release/nes_emu.wasm")
    rom = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "dev-roms/robotfindskitten.nes")
    frames = sys.argv[3] if len(sys.argv) > 3 else "30"
    host = os.path.join(ROOT, "tools/abitest/target/release/abitest")
    r = subprocess.run([host, wasm, rom, frames], capture_output=True, text=True)
    print(r.stdout, end="")
    if r.returncode != 0:
        print(r.stderr)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
