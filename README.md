# NES Eval attempt: DeepSeek V4.1 Flash (river.ai) in omp, max thinking, 24 hours

One run of [NES Eval](https://github.com/IlyaasK/nes-eval): a model gets an
empty Rust project, the NES Eval task, and a black-box reference emulator,
and has 24 hours to write an NES emulator that compiles to WebAssembly.
This repository is the model's working directory, saved every 15 minutes,
plus the transcript and the grades.

| | |
|---|---|
| Model | `deepseek-ai/DeepSeek-V4.1-Flash` via river.ai |
| Thinking | `max` |
| Agent harness | omp (oh-my-pi) 18.11.0, `omp -p --mode json` |
| Environment | NES Eval `quickstart/` task container (commit `77c709b`) |
| Run length | 24 hours, 2026-10-15 17:36:19 to 2026-10-16 17:36:40 UTC |
| Saves | every 15 minutes, 92 commits |
| Grades | every 4 hours plus a final one: 6 checkpoints, all built and graded |

## Score

| Checkpoint | Overall | Procedural | Replay | Audio |
|---|---|---|---|---|
| 4 h | 0.5564 | | | |
| 8 h | 0.8880 | | | |
| 12 h | 0.8934 | | | |
| 16 h | 0.9132 | | | |
| 20 h | 0.9272 | | | |
| **final (24 h)** | **0.9272** | 0.7700 | 0.9955 | 0.8797 |

22 of the 29 testcases score at or above 0.999. Three things hold the score
back, and each is a distinct kind of failure:

| Testcase | Score | What happens |
|---|---|---|
| `instr-official` | 0.0000 | First difference at frame 15; 1,084 of 2,430 frames differ. blargg's official-opcode suite fails, so some instruction's flags or addressing must be wrong. Audio for the same ROM is 0.99999 — the emulator produces sound correctly, it just doesn't show the right verdict. |
| `holy-mapperel-mmc1` (and the MMC3, UxROM and CNROM variants) | 0.0000 | First difference at frame 151, 119 of 270 frames. All four mapper report ROMs fail, pointing at cartridge-board behaviour (banking or mirroring reads) rather than at the CPU, PPU or APU. |
| `nova-the-squirrel-gameplay`, `thwaite-gameplay` | 0.9835, 0.9894 | Near-misses, not breakage: 4,965 of 5,400 frames differ slightly in the first, 69 of 6,000 in the second. The other four homebrew games replay frame-exactly. |

Replay scoring is the strongest section at 0.9955, which is the opposite
shape from the hand-written `nes-core` baseline (0.4569 replay, 0.8300
procedural): this emulator runs real games almost perfectly but fails test
ROMs that probe specific hardware corners.

For scale, on the same grader: the reference scores 1.0000, GPT-6.1 Sol
0.9860, `nes-core` 0.5811, Space Bunny Free 0.0594, and the Qwen3.8 27B run
never compiled.

## What it built

7,329 lines of Rust, 92 commits:

| File | Lines | What |
|---|---|---|
| `src/cpu.rs` | 1,754 | 6502 core and bus |
| `src/ppu.rs` | 1,650 | dot-level rendering, scrolling, sprites, palette |
| `src/system.rs` | 1,230 | console wiring, frame loop, controller, ABI entry points |
| `src/apu.rs` | 1,203 | pulse, triangle, noise, DMC, frame counter, mixer, resampling |
| `src/mapper.rs` | 823 | mappers 0–4 |
| `src/bin/nesrun.rs` | 382 | native runner for debugging outside wasm |
| `src/ines.rs` | 159 | iNES and NES 2.0 headers |
| `src/lib.rs` | 128 | the wasm ABI from `spec/ABI.md` |

It also wrote 59 Python tools of its own under `tools/` — `compare.py`,
`audiodiff.py`, `cpufuzz.py`, `asm6502.py`, `dis6502.py`, `attrprobe.py` and
so on — plus `tools/STATUS.md`, its own running notes on what still differs
from the reference.

## How the run went

72 agent invocations, all of which exited on their own (`rc=0`, none killed
by the watchdog). Median invocation 8.8 minutes, longest 2.2 hours; 23.85 of
the 24 hours had an agent actually working. `omp -p` ends after a turn, so
the supervisor simply re-invoked it with "continue" each time; `stall_restarts`
is 0.

Tokens: 27,744,662 input, 4,250,206 output (3,116,450 of them reasoning),
1,587,737,344 cache reads — 1.62B total. At river.ai's listed prices
($0.12/M input, $0.48/M output, $0.0024/M cached) that is about **$9** for
the 24 hours. The provider's concurrency cap did bite occasionally
("Model serving capacity is currently full"), but no turn was lost to it.

### A note on the first attempt

This run is the second. The first started at 03:17 UTC and **ended after
2h45m**, and it was NES Eval's fault, not the model's: the supervisor's
stall watchdog `stat`ed the agent's log file, that stat races the background
redirect which creates the log, and an empty value inside `$(( ))` does not
merely fail the test — it aborts the enclosing `while` loop, so the
supervisor fell through to "run completed".

That is fixed in NES Eval (`77c709b`) with `log_age()`, which always returns
a number, plus `scripts/test-run-agent.sh`, a regression test that deletes
the agent's log mid-run and requires the run to survive: pre-fix code ends a
144-second run after 35 seconds, fixed code runs the full 174. The truncated
attempt's artifacts are kept in the NES Eval working tree under
`results/deepseek-v4.1-flash-24h.ended-early-2h45m/`; it had reached 0.3538
in 2h45m, and its checkpoint labelled "final" is a 2h45m snapshot, not a
24-hour score.

## Files

- `src/`, `Cargo.toml`, `tools/`: the emulator and the model's own tooling,
  as of its last commit.
- `tmp/`: the model's scratch directory — 36,353 small files (frame dumps,
  probe output). It is 3.6 GB unpacked but about 10 MB in the git pack.
- `TASK.md`, `spec/`, `dev-roms/`: the task environment as handed to the
  model (first commit).
- `transcripts/transcript.md`: the conversation, all 3,422 tool calls with
  their commands and outputs, and the 6 context compactions (long outputs cut
  to 4,000 characters). Rendered with NES Eval's
  `scripts/render-omp-transcript.py`.
- `transcripts/session.jsonl.xz`: the complete omp session (24 MB
  uncompressed).
- `transcripts/subagents/`: the log of the one subagent it spawned.
- `grading/`: `run.json` (per-checkpoint commits, build and grade results),
  the supervisor log, each checkpoint's `summary.json`, and the final
  checkpoint's end screens (`<test>.ref.png` next to `<test>.cand.png`).

No credentials appear anywhere in this repository: the API key lives only in
the container's `~/.omp/agent/models.yml`, outside `/task`, and I grepped
both the working tree and the full session for it before publishing.

## Reproduce the grade

```sh
git clone https://github.com/IlyaasK/nes-eval-attempt-deepseek-v4.1-flash && cd nes-eval-attempt-deepseek-v4.1-flash
cargo build --release --lib --target wasm32-unknown-unknown
# then, from a NES Eval checkout:
target/release/grader <path>/target/wasm32-unknown-unknown/release/nes_emu.wasm corpus/ out/deepseek
```

The grader is deterministic, so this reproduces 0.9272.
