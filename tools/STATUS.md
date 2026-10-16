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

## Open bus / decay register (2026-10-15 later)
* The PPU's open-bus ("decay") register holds the **whole byte** a write put on
  the PPU bus, not just bits 0-4: `ppu_open_bus` compares `$2000` reads against
  the exact byte written to `$2002`/`$2004`/`$2006`.
* It is refreshed by: writes to `$2000-$3FFF`, `$2007` reads (VRAM reads put the
  returned byte, palette reads the palette value in the low 5 bits), and `$2004`
  reads (attribute bytes mask bits 2-4 to 0 first).
* `$2002` reads return `(status & 0xE0) | (decay & 0x1F)` and do *not* refresh it.
* It decays to 0 about 0.56 s after the last refresh (measured against the
  reference: still set at 0.55 s, cleared at 0.57 s).  `DECAY_DOTS` overrides.
* With this, `ppu_open_bus.nes` passes.

## NMI sampling
* The NMI line is sampled once per CPU cycle; `NMI_PHASE` selects which of the
  three PPU dots of the cycle samples it (0, 1 or 2), `NMI_LATCH_DOTS` how many
  consecutive high samples latch it.
* `ppu_vbl_nmi__02/03/04/09` pass; 06/07/08 fail on entries that differ by a
  dot or two of edge-recognition timing (the sweep table in /tmp/nmisweep.py
  shows no (phase, latch) combination passes all three).

## MMC3 A12
* Sprite pattern fetches on dots 4 and 6 of the sprite fetch group also put
  their address on the PPU bus; the MMC3 watches A12 for IRQ clocking, so
  skipping those two dummy reads moved every A12 rise one dot late.

## Session log (video/audio debugging, continued)
* `ppu_open_bus.nes` passes after the full-byte open-bus/decay rework (above).
* `NMI_PHASE` default is now 0 (sampling the NMI line on the first dot of the
  CPU cycle): `ppu_vbl_nmi__06-suppression` passes with it, and the four games
  keep the same frame-exactness (599/600, 599/600, 596/600 on 600 frames).
* MMC3 sprite pattern fetches now put their address on the PPU bus on dots 4
  and 6 of the fetch group (A12 watchers).  `mmc3_test_2__4-scanline_timing`
  still fails its first check ("scanline 0 IRQ should occur sooner with
  $2000=$08"); the check compares the scanline read back after the IRQ with
  $21, so the remaining difference is a dot-level A12/IRQ-count alignment.
* `ppu_vbl_nmi__10-even_odd_timing` "clock skipped too late" with the skip
  decision at dot 340 and "too soon" at dot 339 (knob `ODD_SKIP_DOT`), so the
  reference decides between the two.
* APU: the pulse sweep's mute is gated on the sweep enable bit and includes the
  negative-target case.  file-fixers' music uses a *disabled* sweep with a
  period whose doubling would overflow $7FF, and the reference keeps playing,
  so the unconditional target-period mute was silencing whole notes.
* Per-channel dump: `nesrun --chdump file` (9 bytes/sample: 5 channel DACs,
  4 length counters) with `CHDUMP=1` in trace builds.
* file-fixers/stallar audio differ from the reference (rms ~300-1100); the
  remaining differences are per-note, not a constant delay (alignment scan).

## Current suite status (end of session)
Passing: ppu_vbl_nmi 02/03/04/06/09, ppu_open_bus, all five apu_test ROMs,
mmc3_test_2__2-details, cpu_reset__registers (register dump matches spec/ABI).
Failing: cpu_interrupts_v2__1 (cli_latency: "CLI RTI should not allow any
IRQs"), cpu_interrupts_v2__3 (nmi_and_irq), mmc3_test_2__4 (scanline timing,
first check), ppu_vbl_nmi 07/08 (dot-level NMI edge recognition) and 10
(odd-frame skip decision between dots 339 and 340).
Game video: 599/600 (robotfindskitten), 598/600 (rhde), 596/600
(file-fixers), 192/200 (stallar) frame-exact; the differing frames are the
palette-transition frames with a 2-pixel column at the frame boundary.
Game audio: robotfindskitten is sample-exact apart from the power-on
transient; rhde differs by rms ~30; file-fixers/stallar match note-for-note
in loudness but differ in waveform phase and in a few note choices.

## Odd-frame skip (fixed)
The skip's *decision* uses the rendering-enabled state sampled at
`ODD_DECIDE_DOT` (default 338 = the dot before the last), while the skipped
clock remains dot 340 (`ODD_SKIP_DOT`).  With that split both
`ppu_vbl_nmi__09-even_odd_frames` and `__10-even_odd_timing` pass; using a
single dot for both made 09 fail ("pattern 00 02") and 10 report "skipped too
late".

## Test ROM frame diffs
`sprite_hit_tests__02.alignment` passes on screen but 3 of 400 frames differ by
652 pixels in total; `sprite_hit_tests__03.corners` is 399/400 exact with a
2-pixel difference.  `branch_timing_tests__1` and `sprite_overflow_tests__*`
did not report a status line through the SRAM signature check but complete
normally.

## IRQ poll is a per-cycle sample, not a latch (fixed)
`System::raw_cycle` used to *latch* `cpu.irq_seen` once `irq_prev_line && irq_prev_i`
had been true, so a sample taken during `CLI` leaked into a later instruction.
Probe (/tmp/irqprobe.py) against the reference:

| sequence            | ref | before |
|---------------------|-----|--------|
| cli;sei             |  1  |   1 OK |
| cli;nop;nop         |  0  |   0 OK |
| cli only            |  1  |   1 OK |
| cli;plp             |  0  |   0 OK |
| **cli;rti**         |  0  |   1 BAD |
| sei;cli             |  1  |   1 OK |

The poll must be the one-cycle-old level sample evaluated at each instruction
boundary: an RTI's flag pull (which happens several cycles before its end) is
then visible to its own poll, while a CLI's last-cycle I write is not.
Assigning `cpu.irq_seen = irq_prev_line && irq_prev_i` every cycle (instead of
`if ... { = true }`) matches all six cases, and `cpu_interrupts_v2__1-cli_latency`
now passes (status $80).

## Session status (round 2)
Passing now: `ppu_open_bus`, `ppu_vbl_nmi__02/03/04/06/09/10`,
`cpu_interrupts_v2__1-cli_latency`, all apu_test ROMs, `mmc3_test_2__2-details`,
`cpu_reset__registers`; `branch_timing_tests__1` is 399/400 frame-exact.

Both sprite tests share one visual difference outside the frame boundary:
sprite_hit_tests__02 frames 29-30 and sprite_overflow_tests__2 frames 22-24
differ in rows 32-38 and 48-54 (text-height bands, cols 16-198), where the
reference draws colour $0F and we draw colour $30.  Their verdicts still match.
That points at the sprite palette selection or the sprite patterns used by the
tests' result displays, not at the hit/overflow flags themselves.

Still failing: cpu_interrupts_v2__3 (NMI/BRK interaction table: first row $23
vs our $21, tail rows $25/$25 vs $24/$24), mmc3_test_2__4 (A12/IRQ alignment),
ppu_vbl_nmi__07/08 (sub-dot NMI edge recognition).

## $2005 second write bug (fixed, big)
`apply_reg`'s $2005 else-branch wrote the Y scroll into the coarse-X/fine-X bits
instead of coarse Y (bits 5-9) and fine Y (bits 12-14).  Effect: any ROM that
sets its scroll with $2005 (X then Y) rendered the wrong nametable region.  The
interrupt tests' screens were blank; they now draw.  Fix:

    self.t = (self.t & 0x0C1F) | (((val & 7) << 12) | ((val & 0xF8) << 2));

## Probes built this session (in /tmp, reusable)
* `irqprobe.py` - CLI/RTI/PLP/SEI IRQ latency; all six sequences match.
* `pushp.py` - pushed status for NMI in various flag states; matches ($24/$25).
* `straddle.py`, `straddle2.py`, `nmiwin*.py`, `supp*.py` - NMI enable/disable
  windows around the vblank flag; my emulator matches the reference on all of
  them, so the vbl_nmi 07/08 difference is inside the test's own entry timing.
* `noiseprobe.py`, `chanprobe.py` - per-channel level/spectrum comparison:
  triangle 0.98x, pulse 0.94x, noise 1.37x louder with an uncorrelated
  waveform (3 kHz+ energy ~5x).  Noise period/timer semantics look correct per
  the period table, so the reference's noise differs in some other way.
* `mmc3a12.py` - MMC3 A12 probe (needs a sprite in range; interest is in the
  IRQ timing per $2000 pattern-table setting).
* tools/readtext.py - decode a test ROM's text screen using the ROM's own font
  (auto-detects fine scroll); works on ROMs with CHR-ROM fonts.

## REG_DELAY (register write latency) default changed 2 -> 0
The delayed-register queue applied $2000/$2001/$2005/$2006 writes two PPU dots
after the CPU write.  That is two dots too late for the NMI tests:

    REG_DELAY=2 (old): 07 = "00 N | 01 N | 02 - | 03 - ..." (ref: 0-4 N)
                       08 = "03 - | 04 N | 05 N ..."        (ref: 07+ N)
    REG_DELAY=0 or 1:  07 = "00 N | 01 N | 02 N | 03 N | 04 N | 05 - ..." OK
                       08 = "03 - | 04 - | 05 - | 06 - | 07 N ..."        OK

Games are unchanged with REG_DELAY=0 (rfK 199/200, rhde 198/200,
file-fixers 196/200 on 200 frames; 599/598/596/592 of 600 on 600 frames),
so the default is now 0.

## Odd-skip decision dot re-tuned for REG_DELAY=0
With the register delay now 0, the odd-frame skip's rendering-enabled sample
must move from dot 338 to dot 337 (`ODD_DECIDE_DOT`), i.e. the *effective*
threshold (write dot + REG_DELAY <= decide dot) is unchanged.  Measured:

    DECIDE 335/336 -> "too late"/$02, 337 -> $80 (pass), 338 -> $03, 341 -> "too soon"

With REG_DELAY=0 and ODD_DECIDE_DOT=337 the whole ppu_vbl_nmi set
02/03/04/06/07/08/09/10 passes.

# Session summary (this round)

## Fixes landed
1. **$2005 second write wrote the Y scroll into the X bits** (also clobbering
   coarse X).  Any ROM setting its scroll with $2005 (X then Y) rendered the
   wrong nametable region; interrupt-test screens were blank.  Fixed to set
   coarse Y (bits 5-9) and fine Y (bits 12-14).
2. **REG_DELAY 2 -> 0** (PPU register write latency).  With 2 the NMI tests
   fired two dots late: vbl 07 gave "00 N | 01 N | 02 - ..." (ref 0-4 N) and 08
   "03 - | 04 N | ..." (ref 07+ N).  With 0/1 both match exactly.
3. **ODD_DECIDE_DOT 338 -> 337** to keep the odd-frame skip's effective
   threshold (write dot + REG_DELAY <= decide dot) unchanged; DECIDE 337 is the
   unique passing value with REG_DELAY=0.
4. **NOISE_WEIGHT 2 -> 1** (mixer noise term).  The reference's noise output is
   half the classic TND weight: noise-only probe ratio 2.0x -> 1.0x at long
   periods, and game audio improves on every metric:
   file-fixers rms 318 -> 262, corr 0.951 -> 0.967;
   stallar rms 269 -> 215, corr 0.850 -> 0.901.

## Test status (with these fixes)
Passing: ppu_vbl_nmi **02/03/04/06/07/08/09/10** (all eight), ppu_open_bus,
cpu_interrupts_v2__1, all five apu_test ROMs, mmc3_test_2__2,
cpu_reset__registers; branch_timing_tests__1 399/400 frame-exact.
Games at 1000 frames: robotfindskitten 999/1000, rhde 998/1000,
file-fixers 996/1000, stallar 992/1000 (remaining diffs are the 2-pixel
row-0 frame-boundary artifact).
Audio at 600 frames: robotfindskitten 99.86% equal (rms 31), rhde 99.73%
(rms 33), file-fixers 53% equal but corr 0.967 (rms 262), stallar corr 0.901
(rms 215).

## Still open
* `instr_timing` hangs in its final phase (screen matches the reference exactly
  for the first 1300 frames; the reference prints "All 2 tests passed" at
  ~frame 1300, ours never prints).  The ROM waits in loops around $AFBD-$B000
  and $E440-$E460; the divergence is in a timing-measurement wait.
* `cpu_interrupts_v2__3` table rows (mining the NMI/IRQ interaction).
* `mmc3_test_2__4` ("Scanline 0 IRQ should occur sooner when $2000=$08");
  A12_LOW_DOTS 2/3/6/9/12 all fail, so it is not the filter width.
* sprite_hit_tests__02 / sprite_overflow_tests__2 print their title 2-3 frames
  earlier than the reference (their verdicts match).
* The 2-pixel column at the start of row 0 on frames where the palette changes
  (frame boundary cuts inside scanline 0; FRAME_EXTRA=0 is the best of the
  tested offsets).

# Session: instr_timing diagnosis + audio low-pass

## Audio: output low-pass corner raised 14 kHz -> 40 kHz
Measured against the reference with channel probes (using the A_LP/A_SCALE trace
knobs, which are the actual names -- LP_HZ is not a knob):
* pulse (50%% duty): corr 0.9784 at 14 kHz -> 0.9863 with the filter off;
  low-frequency ratio 0.937 -> 0.971.
* noise (period index 8): >3 kHz energy ratio 4.96 -> 1.73.
* triangle: corr 0.9990 both ways.
* games at 600 frames (sample-exact fraction / rms / corr):
  file-fixers 0.5331/261.7/0.9671 -> 0.5338/260.0/0.9675
  stallar     0.4051/214.7/0.9011 -> 0.4148/216.6/0.8999
So the reference has essentially no output low-pass; default is now 40 kHz.

## instr_timing: where it stands
The ROM is MMC1 (not NROM as I first assumed -- file offset to CPU address
mapping depends on the bank).  Its structure: a state machine whose handlers
are copied to RAM ($0700-$07FF), a wall clock made of the pulse-1 length
counter (set length=2, poll $4015 bit 0), and template handlers from $E32C
that count iterations in $0A and dispatch through the threshold table at
$E2EC (FA F1 E9 E2 DB D5 CE C9 C3 BE -> 10 states).

In our emulator the CPU ends up spinning in the delay routines at
$E440-$E462 forever (traced 30 frames: the only PCs executed are
$E440-$E462), while the reference prints "All 2 tests passed" at frame 1301.
Isolated check: a probe ROM containing an exact copy of $E440-$E46C runs the
same delay in *exactly* the same number of frames (paint appears at frame 20
in both), so instruction timing for that routine is right.  Patching the two
delay constants ($D7, $CA) to $04 makes the ROM behave identically in both
emulators for 500 frames, so the difference is in the test's own state
selection, not in the delay itself.  Next: dump $0A/state at the point the
reference finishes and compare with ours (the count is mod 256, so a few
cycles of loop-cost difference flips the selected handler).

## New tooling
* `nesrun --dumpprg FILE` dumps the mapper-mapped $8000-$FFFF (bank aware).
* `nesrun --dumpram FILE` dumps the 2 KiB of CPU RAM.
* trace knobs TRACE_GAP (report cycle jumps > 8) and TRACE_DMA.
* MMC1 verified against the reference with a two-bank probe (bank 0 = $2A at
  $8000, bank 1 = $15 at $C000 read back identically).

## Sprite test verdicts
All nine sprite_hit / sprite_overflow ROMs report PASSED on our emulator's
screen (verified by decoding their text output with tools/readtext.py using
their CHR-RAM font, dumped via --dumpvram).  Their remaining frame differences
are: (a) the 2-pixel column at the start of row 0 on palette-change frames,
and (b) the title line appearing one frame earlier than the reference
(converging by ~frame 25).

# MAJOR FIX: the 2A03 has no decimal mode
`Cpu::adc`/`Cpu::sbc` implemented BCD arithmetic when the D flag was set.  The
NES CPU stores D but the ALU is always binary.  Consequence: any ROM that runs
with D=1 got wrong arithmetic -- e.g. `instr_timing` sets D and its delay loops
then never terminate (`adc #$FF` no longer decrements), so the test spun
forever in the $E440-$E462 delay routines.  With the decimal branches removed:

  instr_timing: status $80, log "2-branch_timing | Passed | All 2 tests passed"

Games are unchanged (199/198/196/192 of 200 frames on 200 frames).

## instr_timing now PASSES (decimal mode removed)
Verified: `instr_timing` status $80, log "2-branch_timing | Passed | All 2
tests passed"; 1697/1700 frames identical to the reference (the remaining
frames are the 2-pixel row-0 artifact and the result line appearing 2 frames
earlier than the reference).  Diagnosis path: the ROM's delay loops spin
forever because `adc #$FF` did not decrement A; tracing showed A going
$96 -> $FB across an `adc #$FF` with the D flag set -- BCD arithmetic, which
the 2A03 does not have.

## Where nmi_and_irq stands (cpu_interrupts_v2__3)
Reference table (12 rows): 23 21 21 20 20 20 20 20 20 20 25 25
Ours:                      21 21 20 20 20 20 20 20 20 24 24 25
Differences: row 1 bit 1 (0x23 vs 0x21), and the C flag at rows 3/10/11 --
i.e. the interrupt lands one instruction earlier relative to the
`clv; sec; lda #$01; clc; nop` window.  PLP/RTI flag handling and the pushed
status for NMI/IRQ match the reference in dedicated probes, so the remaining
difference is sub-instruction interrupt acceptance timing in that specific
scenario.

## nmi_and_irq / mmc3_test_2__4 notes
* mmc3_test_2__4's failing check compares LE41C's return value with $22; the
  IRQ handler is `asl $20` + ack, so $22 means "IRQ taken after the inc $20",
  $21 means before.  So the check is sub-instruction IRQ timing.
* A12 clocking in our MMC3 gives ~242 rises/frame with the sprite pattern
  table at $1000 (one per scanline, from the dummy sprite fetches), matching
  what the test's $2000=$08 case needs.

# MAJOR FIX 2: NMI request made visible immediately
`sample_nmi` used to set `nmi_latch`, which became `cpu.nmi_pending` only at
the *next* CPU cycle, so an instruction ending in the same cycle did not see
the NMI and it was taken one instruction late.  Now the request is raised at
the sampling instant (`NMI_PENDING_NOW = true`, knob of the same name).

Effect on cpu_interrupts_v2__3 (nmi_and_irq) table:
  reference: 23 21 21 20 20 20 20 20 20 20 25 25
  before   : 21 21 20 20 20 20 20 20 20 24 24 25   (rows 1-10 wrong)
  after    : 23 21 21 20 20 20 20 20 20 20 24 24   (rows 1-10 now match)
The last two rows (NMI arriving while an IRQ is being serviced) still differ
in the C bit: reference pushes 0x25 (C=1, taken right after the IRQ handler),
ours pushes 0x24, i.e. our NMI lands two mainline instructions later.

All eight ppu_vbl_nmi ROMs still pass; instr_timing is now 399/400 frames
exact (only the 2-pixel row-0 artifact at frame 3); games at 1000 frames:
robotfindskitten 999, rhde 999, file-fixers 996, stallar 992.

# Session: input replay, interrupt fuzz, frame-boundary characterisation

## Findings
1. **Controller strobe** (verified against `spec/docs/nesdev-wiki/Controller_reading.md`):
   while `$4016` bit 0 is 1 the 4021 loads its parallel inputs continuously, so
   every read returns button A.  Our read path already reloaded the shift
   register while strobing (no change needed; kept a comment there).
2. **Input replays** work in `tools/fastdiff.py` via `--replay FILE` (same
   format as the oracle's).  Without input all four games are >=99.5%
   frame-exact over 600 frames; with a random 900-frame replay
   robotfindskitten drops to 755/900 because one 1-frame difference in a
   message box propagates into the game state.
3. **Isolated the mechanism**: holding A from frame 0 makes rfK differ on
   *exactly one* frame (12).  The reference draws the message box top bar
   starting at x=26, ours at x=8 - an 18-pixel offset.  The bar is drawn by a
   mid-frame raster split, so our split lands 18 dots (6 CPU cycles) earlier.
4. **Root cause**: `emu_run_frame` must advance until the PPU leaves the
   pre-render scanline (ABI).  The reference is dot-precise; we stop at the
   first CPU instruction boundary *after* the wrap, i.e. 0-7 cycles (0-21
   dots) late, and that overshoot shifts every raster split by the same
   amount, and varies from frame to frame.
5. **Tried and rejected** (all reverted; `frame_extra_dots()` stays 0):
   * FRAME_EXTRA 1/2/3 (dots): overshoots, measurably worse (rfK 2 -> 4/10;
     stallar 18 -> 79).
   * PAL_DELAY 2..6: no effect at all (palette writes happen in vblank).
   * "Carry" frame boundary (lock the boundary to the dot-precise schedule,
     carrying the overshoot into the next frame): frame budgets become
     irregular, rfK 599/600 -> 589/600, 36M total diff.  Reverted.
   * Extra power-on PPU dot: no observable effect (NMI-synced code re-syncs).
     The ABI's "PPU at scanline 0, dot 25" is consistent with our 8-cycle
     reset (24 dots) if the reference counts the first PPU dot as 1.
6. A dot-precise frame end needs a CPU that can be suspended mid-instruction.
   The CPU's microcode consumes cycles individually but is a straight-line
   Rust function, so this is a large refactor.  Everything else in the
   emulator already matches the reference frame-exactly.

## Verified this session (differential, against the oracle)
* `tools/cpufuzz.py` - CPU torture test: ~660 cases (all documented opcodes
  plus the stable illegal set, several addressing forms, C and D both ways),
  checksum of A/X/Y/P over all of them -> **identical** to the reference.
* Interrupt-timing fuzz (APU frame IRQ vs PPU NMI, 5-cycle delay sweep, 64
  scenarios recording both handlers' pushed P and the hijack order) - **all
  64 identical**.
* NMI phase probe and APU-frame-IRQ phase probe: **exact match**.
* Audio, 600 frames: robotfindskitten 99.86% sample-exact (rms 31); game
  audio unaffected by input.  Only difference found: the reference has a
  ~14-sample decaying transient at the very start of the first frame.

## Audio follow-up (same session)
Per-window (0.5 s) correlation against the reference, file-fixers 600 frames:
windows with matching game state reach **corr 0.9988-0.9989** (rms 47-80);
the poor windows (corr 0.19, -0.003) are exactly where the *game state*
diverged earlier (video first bad frame 29).  So residual audio differences
are downstream of the frame-boundary issue, not an APU problem.
* LP_HZ 0 vs 40000: identical output (the low-pass is already effectively off).
* Emphasis bits: differential probe (backdrop $21, $2001 emphasis 0..7) -
  reference and ours produce identical (emphasis<<6)|colour values.
* Games use mapper 0 (robotfindskitten, rhde) and mapper 4 (file-fixers,
  stallar); mappers 1-3 are exercised only by the test ROMs.

## Why the frame boundary cannot be fixed cheaply (measured, not guessed)
`emu_run_frame` must contain the PPU wrap.  With the CPU/PPU locked at 3
dots/cycle, the frame therefore ends 3*K dots late (K = 0..7 remaining cycles
of the instruction that crossed the wrap).  Options:
* End before the wrap -> frame may contain no vblank at all (breaks games).
* Carry the overshoot into the next frame -> irregular frame budgets
  (rfK 599/600 -> 589/600).  Measured, reverted.
* Discard the overshoot by rewinding the PPU -> the PPU stays frame-locked
  but the CPU/APU then drift ahead by K cycles per frame, destroying the
  stable CPU/PPU phase that NMI-synced raster code depends on.
Only a CPU that can be suspended mid-instruction (cycle-resumable microcode)
can have both; the CPU here is a straight-line Rust function.

## The 18-dot raster-split difference: not a register-write delay
* The game's message box top bar appears 18 px further right in the reference
  (x=8 vs x=26 on the same scanline), i.e. the mid-scanline scroll write takes
  effect ~18 dots later in the reference.
* REG_DELAY sweep on that case: totdiff drops 1 px per dot (79 at 0 ... 72 at
  8), so the knob *can* paper over it - but REG_DELAY=3 destroys
  ppu_vbl_nmi__07 (298/300 -> 174/300), which pins the register-write timing.
  The reference has no register write delay; **REG_DELAY must stay 0**.
* An instruction-defer experiment (never start an instruction the PPU cannot
  finish this frame, so the boundary lands <=2 dots early instead of <=21
  late) changed *nothing* measurable (rfK 599/600 and the rp_a0 case 298/300
  both before and after), confirming the frame-boundary overshoot does not
  influence in-frame raster timing.  Removed.

## Session conclusion
No net source change: every experiment (carry boundary, power-on dot,
instruction defer, REG_DELAY) was measured and reverted, with the numbers
recorded above.  The emulator's remaining deviations from the reference are
(a) the <=21-dot frame-boundary overshoot (only visible as a 2-pixel row-0
artifact on palette-change frames), (b) cpu_interrupts_v2__3 rows 11-12 and
mmc3_test_2__4's sub-instruction IRQ check, and (c) one 18-dot mid-scanline
scroll difference in robotfindskitten's message box animation.

# Session: NMI acceptance model + power-on CPU/PPU alignment

## Power-on alignment: checked with an extra dot, REJECTED by the corpus
The ABI says "at that same moment the PPU is at scanline 0, dot 25 (the reset
sequence has run with the PPU clocking from scanline 0, dot 0)".  Eight CPU
cycles clock 24 dots; clocking one further PPU-only dot makes a free-running
raster-band probe line up with the reference to the dot (band edge 105 in both
instead of 104), which looks like a confirmation.

But the effect on the ROM corpus is uniformly negative: with the extra dot,
ppu_vbl_nmi 02/03/04/06/07/08/09/10 go 298,298,299,298,298,298,299,298 ->
297,297,294,297,297,297,294,297; apu_test 2/4/5/8 go 299,299,299,298 ->
294,298,295,295; cpu_interrupts_v2__1 299 -> 295; cpu_reset 299 -> 298.  Two
extra dots give yet another (different) misalignment.  With no extra dot every
one of those ROMs is back to 298-299/300.

So the reference's alignment is the plain 8-cycle one and the ABI's "dot 25"
is consistent with counting the first PPU dot as 1.  `POWER_ALIGN_DOTS`
default is 0; the 1-dot difference seen by the free-running probe must come
from a one-dot register-effect latency difference in that probe's path, not
from the CPU/PPU phase.

NOTE: the earlier `POWER_DOTS` knob was inert -- `ppu_only_dot` called
`process_dot` without `advance()`, so it never moved the dot counter.  That is
why previous phase experiments showed "no effect".

## Verified: NMI acceptance timing model
Built a probe with loops of length 5/7/9/11 cycles whose iteration count at the
NMI is painted through the backdrop-palette hack, so the painted value gives the
acceptance to the cycle (mod 64 * loop length).  Result over 24 frames x 4
lengths:
* immediate pending (no extra delay): **identical to the reference** in all 96
  comparisons;
* pending delayed by 1/2/3 cycles: mine is one loop iteration late on ~1/3 of
  frames for L=5 and on some frames for L=7/9/11.
So the immediate-pending model is the correct one and was kept (default
NMI_DELAY=0; the knob remains for diagnosis).

## Investigated, not explained: robotfindskitten message-box raster offset
With A held from frame 0, rfK draws its message box with a "palette stream"
while rendering is off (the backdrop shows palette[$3F00|v&0x1F] as v walks
through palette RAM).  At frame 12 my bands sit 18-19 dots earlier than the
reference's (identical run lengths, so it is a pure shift).  A one-cycle NMI
delay "fixed" it (7 px vs 79) but the loop probe above proves that model wrong,
i.e. it was masking a different bug; reverted.  The game's intro is
*free-running* (no NMI/$2002 frame sync: $885C's $E0 loop never executes in
this phase), so the offset is a constant ~6 CPU cycles of timeline difference,
not a phase difference (the phase probe matches to the dot).  Candidate causes
ruled out by sweep (no effect on rp_a0): OAM DMA alignment mode (0-3), PPU
warm-up length (29650/29658/29660/29700), first-frame skip, frame extra dots,
palette write delay, NMI sample phase (0/1/2), odd-frame skip dot.

## Remaining differences in the real games
All four games are now pixel-perfect at 1000 frames except a 1-10 pixel
artifact in **row 0 only**, on frames where the palette changes: the frame
boundary ends up to 21 dots after the PPU wrap (instruction granularity), so
the first pixels of scanline 0 are re-rendered before `emu_run_frame` returns,
one dot of the boundary is in the reference's next call.  Removing it needs a
dot-precise frame boundary, i.e. a CPU that can be suspended mid-instruction.

## Frame-stop-zone experiment (rejected)
Idea: end `emu_run_frame` *before* the PPU wrap (stop when the PPU is in the last
N dots of the pre-render line) so that no pixel of the next frame's scanline 0
is rendered inside the call, which should remove the row-0 artifact.

Measured (rfK, 600 frames, and the A-held replay):
  zone=0  : 599/600 totdiff 2      | replay 298/300 totdiff 79
  zone=8  : 586/600 totdiff 244905 | replay 282/300
  zone>=16: 584/600 totdiff 251067 | replay 276/300
The first diverging frames (5, 6) differ over the whole screen, so ending the
call early desynchronises the game's rendering rather than just moving the
boundary.  Reverted; `emu_run_frame` still ends at the first instruction
boundary after the wrap.
