#!/usr/bin/env python3
"""Empirical tuner for the audio output stage: runs our emulator on probe ROMs
with given knob settings and scores the RMS error against cached reference WAVs."""
import os, subprocess, sys, wave
import numpy as np

ROM = '/task/target/release/nesrun'
PROBES = [('ch_pulse1', 200), ('ch_tri', 200)]
REF = {}

def rd(p):
    w = wave.open(p); n = w.getnframes()
    a = np.frombuffer(w.readframes(n), dtype='<i2').astype(np.float64); w.close()
    return a

def load_refs():
    for name, frames in PROBES:
        REF[name] = rd('/task/.oracle-out/%s/ref.wav' % name)

def run_probe(name, frames, extra_env):
    out = '/tmp/tune_%s.wav' % name
    env = dict(os.environ); env.update(extra_env)
    subprocess.run([ROM, '/task/tmp/%s.nes' % name, str(frames), '--wav', out],
                   capture_output=True, env=env, cwd='/task')
    if not os.path.exists(out): return None
    return rd(out)

def score(extra_env, verbose=False):
    tot = 0.0; parts = []
    for name, frames in PROBES:
        b = run_probe(name, frames, extra_env)
        if b is None: return 1e18, []
        a = REF[name]
        n = min(len(a), len(b))
        e = np.sqrt(((a[:n] - b[:n]) ** 2).mean())
        parts.append((name, e)); tot += e
    if verbose: print('   ', ['%s=%.1f' % p for p in parts])
    return tot / len(PROBES), parts

if __name__ == '__main__':
    load_refs()
    base = {}
    for kv in sys.argv[1:]:
        k, v = kv.split('=')
        base[k] = v
    s, parts = score(base, verbose=True)
    print('score %.3f' % s)
