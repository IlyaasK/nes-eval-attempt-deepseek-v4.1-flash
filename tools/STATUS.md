# Emulator status (measured against the bundled reference)

Tools: `tools/fastdiff.py` (per-frame pixel comparison against cached
reference dumps), `tools/score.py` (aggregate), `tools/teststatus.py` (reads
the $6000 result byte/ log blargg's suites write), `tools/audiodiff.py`
(sample-exact audio comparison), `tools/probe.py` + `tools/asm6502.py`
(hand-assembled probe ROMs run on both emulators), `tools/nesrun_trace`
(native harness with env-gated tracing).

## Games

600 frames, no input, identical startup state:

| ROM | exact frames | total differing pixels |
|-----|--------------|------------------------|
| robotfindskitten.nes | 599/600 | 2 |
| file-fixers.nes      | 596/600 | 21 |
| stallar.nes          | 592/600 | 19 |
| rhde.nes             | 299/300 | 2 |

All four games are now frame-exact apart from a couple of transition frames
(2/21/19/2 differing pixels over 300 frames), and with an input replay the
games stay within a few hundred pixels.

With a Start/A input replay the games still follow the reference (robotfindskitten
and stallar stay within a few hundred pixels over 300 frames).

## Test ROMs that reproduce the reference exactly

* `ppu_vbl_nmi__02-vbl_set_time`, `__03-vbl_clear_time` - $00 (passed)
* `apu_test__4-jitter`, `__5-len_timing`, `__6-irq_flag_timing`,
  `__8-dmc_rates` - "Passed"
* `mmc3_test_2__2-details` - "Passed"
* `ppu_vbl_nmi__06-suppression` - $00 (passed)
* `sprite_hit_tests__02..08`, `sprite_overflow_tests__2/3`,
  `branch_timing_tests__1` - final screen identical to the reference
* `sprite_hit_tests__02..08`, `sprite_overflow_tests__2.Details`,
  `sprite_overflow_tests__3.Timing`, `branch_timing_tests__1.Branch_Basics` -
  final screen byte-identical to the reference (same verdict)
* `ppu_vbl_nmi__04-nmi_control`, `__09-even_odd_frames` - running/passed
* `instr_timing`: the illegal 2-byte NOPs ($80/$82/$89/$C2/$E2) now take the
  documented 2 cycles, which removed the "was 1, should be 2" failure; the test
  then runs long (it still does not terminate within 6000 frames).

## Still failing

* `ppu_vbl_nmi__06-suppression`, `__07-nmi_on_timing`, `__08-nmi_off_timing`
  (the exact $2002 suppression / NMI window geometry)
* `ppu_vbl_nmi__10-even_odd_timing`
* `cpu_interrupts_v2__1-cli_latency` (subtests 1-9 pass, #10 fails),
  `__3-nmi_and_irq`
* `mmc3_test_2__4-scanline_timing`
* `ppu_open_bus`

## Notes on the audio pipeline

* The mixer must keep the classic formula's non-zero DC (`95.52/100`,
  `159.79/100`); the reference's output starts with a decaying transient that a
  zero-DC mixer never produces (measured with a DMC-DAC step probe: the
  reference starts at ~6300 and decays).
* The reference's step response is undelayed, while the 35-tap FIR used here
  adds a 17-sample group delay.  With the DC enabled and the FIR disabled the
  step response matches (rms 68 vs 941), but the steady-state music of the
  games matches better with the FIR and no DC, which is the current default.
* Output resampling modes are selectable with `FIR=0/1/2` (hold / FIR /
  linear interpolation) and the mixer DC with `MIX_DC` in trace builds.

## Audio

| ROM | sample-exact after alignment |
|-----|------------------------------|
| robotfindskitten.nes | 99.7% |
| file-fixers.nes      | 59.5% |

Individual channel probes (pulse, triangle, noise with both LFSR modes, DMC DAC
level, envelope decay, sweep, multi-channel sum) all match at 99.3% or better;
per-frame sample counts match the reference (0, then 733-734 per frame).
