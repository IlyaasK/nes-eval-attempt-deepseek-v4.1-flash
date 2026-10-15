# Emulator status (measured against the bundled reference)

Everything below is measured with `tools/fastdiff.py` (per-frame pixel
comparison against cached reference dumps) and `tools/teststatus.py` (the
$6000 result byte blargg's suites write).

## Games (300 frames, no input)

| ROM | exact frames | total differing pixels |
|-----|--------------|------------------------|
| robotfindskitten.nes | 299/300 | 2 |
| file-fixers.nes      | 296/300 | 21 |
| stallar.nes          | 292/300 | 19 |
| rhde.nes             | 23/300  | 335618 (about 1216/frame after frame 23) |

## Test ROMs that reproduce the reference result

* `ppu_vbl_nmi__02-vbl_set_time`, `__03-vbl_clear_time` - `$00` (passed)
* `apu_test__4-jitter`, `__5-len_timing`, `__6-irq_flag_timing`,
  `__8-dmc_rates` - passed
* `mmc3_test_2__2-details` - passed
* `sprite_hit_tests__02..08`, `sprite_overflow_tests__2.Details`,
  `sprite_overflow_tests__3.Timing`, `branch_timing_tests__1.Branch_Basics` -
  the final screen is byte-identical to the reference (same verdict)
* `cpu_reset__registers` needs the reset button; `instr_timing` and
  `apu_test__2-len_table` run long.

## Still failing

* `ppu_vbl_nmi__06-suppression`, `__07-nmi_on_timing`, `__08-nmi_off_timing`
* `ppu_vbl_nmi__10-even_odd_timing`
* `cpu_interrupts_v2__1-cli_latency`, `__3-nmi_and_irq`
* `mmc3_test_2__4-scanline_timing`
* `ppu_open_bus`

## Audio

Compared with `tools/audiodiff.py` (exact sample equality after alignment):

| ROM | equal samples |
|-----|---------------|
| robotfindskitten.nes | 99.7% |
| file-fixers.nes      | 59.5% |

Individual channel probes (pulse, triangle, noise incl. short mode, DMC DAC,
envelope, sweep, multi-channel sum) all match at 99.3% or better.
