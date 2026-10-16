//! NES APU (NTSC RP2A03) — self-contained cycle-oriented implementation.
//!
//! This module is deliberately standalone: it has no dependencies on the rest of
//! the emulator and only uses `core`/`std`. It implements the five APU channels
//! (pulse 1/2, triangle, noise, DMC), the frame counter, the $4015/$4017 register
//! behavior, and the non-linear mixer.
//!
//! # Timing model
//!
//! `clock(cpu_cycle)` is called once per CPU cycle (NTSC 2A03, 1.789773 MHz). The
//! pulse, noise and DMC timers, plus the frame counter, live in the "APU cycle"
//! (CPU/2) domain and are ticked on CPU cycles where `cpu_cycle & 1 == 0`. The
//! triangle timer is clocked every CPU cycle (as on hardware). The parity is fixed
//! at power-on (per the ABI, the CPU/APU alignment is not randomized).
//!
//! # Deliberate approximations / deviations from ideal hardware
//!
//! 1. `$4011` direct load vs. a coincident DMC timer clock: the hardware quirk
//!    where the direct load "occasionally" fails is not modeled — the direct load
//!    always wins.
//! 2. Register writes are treated as taking effect at the end of the CPU cycle in
//!    which they arrive; sub-CPU-cycle (half APU cycle) write timing is not
//!    modeled, except where explicitly noted below.
//! 3. `$4017` write latency: the reset takes effect 3 CPU cycles after the write if
//!    the write lands on an APU clock tick, 4 CPU cycles otherwise (per
//!    APU_Frame_Counter.md). If that reset lands exactly on a frame-counter tick,
//!    the step (including a would-be frame IRQ flag set) of that tick is
//!    suppressed. The quarter/half frame *signals* produced by a normal step are
//!    emitted one CPU cycle after the step, as documented. The immediate
//!    quarter+half clock caused by a mode-1 `$4017` write is emitted at the reset
//!    point itself.
//! 4. Reading `$4015` clears the frame IRQ flag only. On hardware the DMC IRQ flag
//!    is *not* cleared by a read (only by a `$4015` write or by clearing `$4010.7`);
//!    this contradicts the "(and DMC IRQ flag)" note in the frozen interface
//!    comment — hardware behavior was chosen. Use [`Apu::clear_dmc_irq`] if the
//!    system needs to clear it explicitly.
//! 5. The `$4015` bit-5 open bus is taken from the `open_bus` argument; bits 0-4,
//!    6 and 7 are driven by the APU, matching APU.md's `IF-D NT21` read layout:
//!    bit 4 = DMC active, bit 6 = frame IRQ flag, bit 7 = DMC IRQ flag. (The frozen
//!    interface comment lists bit 5 as the frame IRQ flag and bit 6 as the DMC IRQ
//!    flag, i.e. shifted by one, and mentions an open-bus bit 7; the hardware
//!    layout from the offline docs was implemented instead.)
//! 6. The noise LFSR is powered up with the value 1 (hardware behavior: the LFSR
//!    can never hold 0). All other state is zeroed on reset.
//! 7. The "an interrupt flag set at the same moment as the $4015 read is read back
//!    as 1 but not cleared" corner case is not modeled.
//! 8. NTSC only. The noise period table uses the standard RP2A03 values (not the
//!    early-revision $F = 2046 value).
//! 9. The triangle channel tracks its DAC value separately from the sequencer
//!    position and powers up with a DAC value of 0 (silence), as required by
//!    "all APU state zeroed" in spec/ABI.md and by power-on silence. On hardware
//!    the (halted) sequencer's combinational output would instead read out the
//!    table entry for position 0. From the first sequencer clock onwards the
//!    behavior is identical to the combinational model.
//! 10. The DMC sample buffer is not cleared by a `$4015` write that disables the
//!     channel: the already-fetched byte finishes playing, as documented.
//!
//! # Integration note
//! The CPU IRQ line this APU drives is `irq_pending() || dmc_irq_flag()`. Do *not*
//! determine it by polling `read($4015, ..)`: that read has the side effect of
//! clearing the frame IRQ flag (this is why `dmc_irq_flag()` exists as a
//! side-effect-free accessor).
//!
//! `clock()` must be called exactly once per CPU cycle with a strictly increasing
//! `cpu_cycle`; duplicate calls for the same cycle are ignored defensively, and
//! the APU cycle parity is derived from `cpu_cycle & 1`. In this module's phase
//! convention, CPU cycles with `cpu_cycle & 1 == 0` are DMA *get* cycles and the
//! odd ones are *put* cycles; the system needs that convention for the DMC DMA
//! halt-cycle rules (see `dmc_dma_is_load`).

// ---------------------------------------------------------------------------
// Constant tables
// ---------------------------------------------------------------------------

/// Length counter load values, indexed by the 5-bit length index.
pub const LENGTH_TABLE: [u8; 32] = [
    10, 254, 20, 2, 40, 4, 80, 6, 160, 8, 60, 10, 14, 12, 26, 14, 12, 16, 24, 18, 48, 20, 96, 22,
    192, 24, 72, 26, 16, 28, 32, 30,
];

/// Pulse duty sequences, indexed by [duty][sequencer position].
const DUTY_TABLE: [[u8; 8]; 4] = [
    [0, 1, 0, 0, 0, 0, 0, 0], // 12.5%
    [0, 1, 1, 0, 0, 0, 0, 0], // 25%
    [0, 1, 1, 1, 1, 0, 0, 0], // 50%
    [1, 0, 0, 1, 1, 1, 1, 1], // 75% (25% negated)
];

/// Triangle step sequence (32 steps).
const TRIANGLE_TABLE: [u8; 32] = [
    15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
    12, 13, 14, 15,
];

/// Noise timer periods in APU cycles (= NTSC CPU cycles / 2).
/// Noise timer periods.  The reference counts these in APU clocks (the timer
/// is clocked once per two CPU cycles), i.e. twice the documented CPU-cycle
/// periods; verified against the reference's measured shift-register rate.
const NOISE_PERIOD_APU: [u16; 16] = [
    4, 8, 16, 32, 64, 96, 128, 160, 202, 254, 380, 508, 762, 1016, 2034, 4068,
];

/// DMC timer periods in CPU cycles (NTSC rate table).
const DMC_RATE_CPU: [u16; 16] = [
    428, 380, 340, 320, 286, 254, 226, 214, 190, 160, 142, 128, 106, 84, 72, 54,
];

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
struct Envelope {
    start: bool,
    divider: u8,
    decay: u8,
}

impl Envelope {
    /// Quarter frame clock.
    fn clock(&mut self, loop_flag: bool, param: u8) {
        if self.start {
            self.start = false;
            self.decay = 15;
            self.divider = param;
        } else if self.divider == 0 {
            self.divider = param;
            if self.decay > 0 {
                self.decay -= 1;
            } else if loop_flag {
                self.decay = 15;
            }
        } else {
            self.divider -= 1;
        }
    }

    fn volume(&self, constant: bool, param: u8) -> u8 {
        if constant {
            param
        } else {
            self.decay
        }
    }
}

static mut APU_IRQ_WRAP: bool = true;
static mut APU_IRQ_14914: bool = true;
#[cfg(feature = "trace")]
fn apu_irq_wrap() -> bool {
    unsafe {
        if let Ok(v) = std::env::var("APU_IRQ_WRAP") {
            APU_IRQ_WRAP = v != "0";
        }
        APU_IRQ_WRAP
    }
}
#[cfg(not(feature = "trace"))]
fn apu_irq_wrap() -> bool {
    unsafe { APU_IRQ_WRAP }
}
#[cfg(feature = "trace")]
fn apu_irq_14914() -> bool {
    unsafe {
        if let Ok(v) = std::env::var("APU_IRQ_14914") {
            APU_IRQ_14914 = v != "0";
        }
        APU_IRQ_14914
    }
}
#[cfg(not(feature = "trace"))]
fn apu_irq_14914() -> bool {
    unsafe { APU_IRQ_14914 }
}

// ---------------------------------------------------------------------------
// Length counter
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
struct LengthCounter {
    value: u8,
    enabled: bool,
}

impl LengthCounter {
    fn load(&mut self, index: u8) {
        if self.enabled {
            self.value = LENGTH_TABLE[(index & 0x1F) as usize];
        }
    }

    fn clock(&mut self, halt: bool) {
        if self.value > 0 && !halt {
            self.value -= 1;
        }
    }

    fn set_enabled(&mut self, enabled: bool) {
        self.enabled = enabled;
        if !enabled {
            self.value = 0;
        }
    }
}

// ---------------------------------------------------------------------------
// Sweep unit
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
struct Sweep {
    enabled: bool,
    period: u8,
    negate: bool,
    shift: u8,
    reload: bool,
    divider: u8,
}

impl Sweep {
    /// Target period (may exceed $7FF; clamped at 0). `pulse1` selects the ones'
    /// complement adder (pulse 1) rather than the two's complement one (pulse 2).
    fn target_period(&self, period: u16, pulse1: bool) -> i32 {
        let change = (period >> (self.shift & 0x07)) as i32;
        let t = if self.negate {
            period as i32 - change - if pulse1 { 1 } else { 0 }
        } else {
            period as i32 + change
        };
        if t < 0 {
            0
        } else {
            t
        }
    }

    /// Sweep muting condition: the current period is below 8, or the sweep is
    /// enabled and its target period would overflow $7FF (or go negative).
    fn muting(&self, period: u16, pulse1: bool) -> bool {
        if period < 8 {
            return true;
        }
        if !self.enabled {
            return false;
        }
        let change = (period >> (self.shift & 0x07)) as i32;
        let t = if self.negate {
            period as i32 - change - if pulse1 { 1 } else { 0 }
        } else {
            period as i32 + change
        };
        t > 0x7FF || t < 0
    }
}

// ---------------------------------------------------------------------------
// Pulse channel
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
struct Pulse {
    duty: u8,
    sequence: u8,
    timer_period: u16,
    timer_counter: u16,
    length: LengthCounter,
    envelope: Envelope,
    halt: bool,
    constant_volume: bool,
    volume: u8,
    sweep: Sweep,
}

impl Pulse {
    fn clock_timer(&mut self) {
        if self.timer_counter == 0 {
            self.timer_counter = self.timer_period & 0x7FF;
            self.sequence = (self.sequence + 1) & 0x07;
        } else {
            self.timer_counter -= 1;
        }
    }

    fn clock_quarter(&mut self) {
        self.envelope.clock(self.halt, self.volume);
    }

    fn clock_half(&mut self, pulse1: bool) {
        self.length.clock(self.halt);

        let sweep = self.sweep;
        let period = self.timer_period & 0x7FF;
        if sweep.divider == 0 && sweep.enabled && sweep.shift > 0 && !sweep.muting(period, pulse1) {
            self.timer_period = sweep.target_period(period, pulse1) as u16;
        }
        let sweep = &mut self.sweep;
        if sweep.divider == 0 || sweep.reload {
            sweep.divider = sweep.period;
            sweep.reload = false;
        } else {
            sweep.divider -= 1;
        }
    }

    /// DAC value sent to the mixer (0..15).
    fn output(&self, pulse1: bool) -> u8 {
        let period = self.timer_period & 0x7FF;
        if self.length.value == 0 {
            return 0;
        }
        if self.sweep.muting(period, pulse1) {
            return 0;
        }
        if DUTY_TABLE[(self.duty & 0x03) as usize][(self.sequence & 0x07) as usize] == 0 {
            return 0;
        }
        self.envelope.volume(self.constant_volume, self.volume)
    }
}

const PULSE1: bool = true;
const PULSE2: bool = false;

// ---------------------------------------------------------------------------
// Triangle channel
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
struct Triangle {
    control: bool, // $4008 bit 7: length halt + linear counter control
    reload_value: u8,
    reload_flag: bool,
    linear_counter: u8,
    timer_period: u16,
    timer_counter: u16,
    sequence: u8,
    /// Last value driven into the mixer (the channel keeps outputting its last
    /// value when the sequencer is halted). Powered up at 0 = silence.
    dac: u8,
    length: LengthCounter,
}

impl Triangle {
    fn clock_timer(&mut self) {
        if self.timer_counter == 0 {
            self.timer_counter = self.timer_period & 0x7FF;
            // The sequencer is gated by both counters; the timer keeps running.
            if self.length.value > 0 && self.linear_counter > 0 {
                self.sequence = (self.sequence + 1) & 0x1F;
                self.dac = TRIANGLE_TABLE[(self.sequence & 0x1F) as usize];
            }
        } else {
            self.timer_counter -= 1;
        }
    }

    fn clock_quarter(&mut self) {
        if self.reload_flag {
            self.linear_counter = self.reload_value;
        } else if self.linear_counter > 0 {
            self.linear_counter -= 1;
        }
        if !self.control {
            self.reload_flag = false;
        }
    }

    fn clock_half(&mut self) {
        self.length.clock(self.control);
    }

    fn output(&self) -> u8 {
        self.dac
    }
}

// ---------------------------------------------------------------------------
// Noise channel
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
struct Noise {
    /// Diagnostic: number of shift-register clocks since power-on.
    clocks: u64,
    mode: bool,
    period_index: u8,
    timer_counter: u16,
    shift: u16,
    length: LengthCounter,
    envelope: Envelope,
    halt: bool,
    constant_volume: bool,
    volume: u8,
}

impl Noise {
    /// Divider reload value in APU clocks.  The counter is loaded with
    /// period+1 (the reference clocks the shift register once every
    /// (period+1) APU clocks; measured against its output as 8138 CPU cycles
    /// for period index $F).
    fn period(&self) -> u16 {
        NOISE_PERIOD_APU[(self.period_index & 0x0F) as usize] + noise_period_plus() + 1
    }

    fn clock_timer(&mut self) {
        // The period table holds exact CPU-cycle periods, so the divider counts
        // down from `period` and fires when it reaches 0.
        if self.timer_counter > 0 {
            self.timer_counter -= 1;
        }
        if self.timer_counter == 0 {
            self.timer_counter = self.period();
            let tap = match noise_tap_mode() {
                1 => 1,
                6 => 6,
                _ => if self.mode { 6 } else { 1 },
            };
            let feedback = (self.shift & 1) ^ ((self.shift >> tap) & 1);
            self.shift = ((self.shift >> 1) | (feedback << 14)) & 0x7FFF;
            self.clocks = self.clocks.wrapping_add(1);
            #[cfg(feature = "trace")]
            {
                if std::env::var("NOISE_TRACE").is_ok() {
                    eprintln!("NCLK cyc={} shift={:04X} dac={}", APU_NOW.with(|c| c.get()), self.shift, self.output());
                }
            }
        }
    }

    fn clock_quarter(&mut self) {
        self.envelope.clock(self.halt, self.volume);
    }

    fn clock_half(&mut self) {
        self.length.clock(self.halt);
    }

    fn output(&self) -> u8 {
        if self.length.value == 0 || (self.shift & 1) != 0 {
            0
        } else {
            self.envelope.volume(self.constant_volume, self.volume)
        }
    }
}

// ---------------------------------------------------------------------------
// DMC channel
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
struct Dmc {
    enabled: bool,
    irq_enable: bool,
    loop_flag: bool,
    irq_flag: bool,
    rate_index: u8,
    timer_counter: u16,
    sample_address: u8,
    sample_length: u8,
    current_address: u16,
    bytes_remaining: u16,
    sample_buffer: Option<u8>,
    shift_register: u8,
    bits_remaining: u8,
    silence: bool,
    output_level: u8,
    /// Type of the next DMC DMA fetch: `true` = "load" DMA (scheduled by the
    /// $4015 D4 write with an empty buffer), `false` = "reload" DMA (scheduled
    /// because the sample buffer emptied during playback). See DMA.md.
    load_dma: bool,
}

impl Dmc {
    fn rate_period(&self) -> u16 {
        DMC_RATE_CPU[(self.rate_index & 0x0F) as usize]
    }

    /// (Re)start the sample at the addresses currently held in $4012/$4013.
    fn restart_sample(&mut self) {
        self.current_address = 0xC000 | ((self.sample_address as u16) << 6);
        self.bytes_remaining = (self.sample_length as u16) * 16 + 1;
    }

    fn clock_timer(&mut self) {
        // The rate table holds exact CPU-cycle periods.
        if self.timer_counter > 0 {
            self.timer_counter -= 1;
        }
        if self.timer_counter == 0 {
            self.timer_counter = self.rate_period();
            self.clock_output_unit();
        }
    }

    fn clock_output_unit(&mut self) {
        if !self.silence {
            if (self.shift_register & 1) != 0 {
                if self.output_level <= 125 {
                    self.output_level += 2;
                }
            } else if self.output_level >= 2 {
                self.output_level -= 2;
            }
        }
        self.shift_register >>= 1;
        if self.bits_remaining > 0 {
            self.bits_remaining -= 1;
        }
        if self.bits_remaining == 0 {
            // Start a new output cycle.
            self.bits_remaining = 8;
            match self.sample_buffer.take() {
                Some(byte) => {
                    self.shift_register = byte;
                    self.silence = false;
                }
                None => self.silence = true,
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Frame counter
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Default)]
struct FrameCounter {
    mode5: bool,
    irq_inhibit: bool,
    irq_flag: bool,
    /// APU cycles since the last reset (0..=14915 in 4-step, 0..=18641 in 5-step).
    cycle: u32,
    /// Absolute CPU cycle at which a pending $4017 reset takes effect
    /// (`None` = no write pending).
    reset_at: Option<u64>,
    /// Quarter/half frame signals from the last step, emitted 1 CPU cycle later.
    pending_quarter: bool,
    pending_half: bool,
}

// ---------------------------------------------------------------------------
// APU
// ---------------------------------------------------------------------------

/// Extra APU cycles added to the noise timer period.
static mut NOISE_PERIOD_PLUS: u16 = 0;
#[cfg(feature = "trace")]
fn noise_period_plus() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("NOISE_PERIOD_PLUS") {
            if let Ok(n) = v.parse::<u16>() {
                NOISE_PERIOD_PLUS = n;
            }
        }
        NOISE_PERIOD_PLUS
    }
}
#[cfg(not(feature = "trace"))]
fn noise_period_plus() -> u16 {
    unsafe { NOISE_PERIOD_PLUS }
}

static mut DMC_DMA_DISABLED: bool = false;
#[cfg(feature = "trace")]
fn dmc_dma_disabled() -> bool {
    unsafe {
        if let Ok(v) = std::env::var("DMC_DMA_OFF") {
            DMC_DMA_DISABLED = v != "0";
        }
        DMC_DMA_DISABLED
    }
}
#[cfg(not(feature = "trace"))]
fn dmc_dma_disabled() -> bool {
    unsafe { DMC_DMA_DISABLED }
}

/// Mixer weight of the noise channel (the classic TND formula uses 2).
static mut NOISE_WEIGHT: usize = 7;
#[cfg(feature = "trace")]
fn noise_weight() -> usize {
    unsafe {
        if let Ok(v) = std::env::var("NOISE_WEIGHT") {
            if let Ok(n) = v.parse::<usize>() {
                NOISE_WEIGHT = n;
            }
        }
        NOISE_WEIGHT
    }
}
#[cfg(not(feature = "trace"))]
fn noise_weight() -> usize {
    unsafe { NOISE_WEIGHT }
}

/// Fixes the noise feedback tap (0 = follow the mode bit, 1 or 6 = always that
/// bit).  Diagnostic knob for matching the reference's LFSR sequence.
static mut NOISE_TAP: u8 = 0;
#[cfg(feature = "trace")]
fn noise_tap_mode() -> u8 {
    unsafe {
        if let Ok(v) = std::env::var("NOISE_TAP") {
            if let Ok(n) = v.parse::<u8>() { NOISE_TAP = n; }
        }
        NOISE_TAP
    }
}
#[cfg(not(feature = "trace"))]
fn noise_tap_mode() -> u8 { unsafe { NOISE_TAP } }

static mut MIX_DC: f32 = 0.25;
/// Scale applied to the TND table's shape: 1 = the fitted nonlinear curve,
/// larger values approach a linear mixer (the reference's sums are linear).
static mut MIX_LIN: f32 = 1.0;

static mut TRI_WEIGHT: usize = 12;
#[cfg(feature = "trace")]
fn tri_weight() -> usize {
    unsafe {
        if let Ok(v) = std::env::var("A_TRI_WEIGHT") {
            if let Ok(n) = v.parse::<usize>() { TRI_WEIGHT = n; }
        }
        TRI_WEIGHT
    }
}
#[cfg(not(feature = "trace"))]
fn tri_weight() -> usize { unsafe { TRI_WEIGHT } }

#[cfg(feature = "trace")]
#[cfg(feature = "trace")]
fn mix_lin() -> f32 {
    unsafe {
        if let Ok(v) = std::env::var("A_MIX_LIN") {
            if let Ok(n) = v.parse::<f32>() { MIX_LIN = n; }
        }
        MIX_LIN
    }
}
#[cfg(not(feature = "trace"))]
fn mix_lin() -> f32 { unsafe { MIX_LIN } }

#[cfg(feature = "trace")]
thread_local! {
    static APU_NOW: core::cell::Cell<u64> = const { core::cell::Cell::new(0) };
}

pub struct Apu {
    pulse: [Pulse; 2],
    triangle: Triangle,
    noise: Noise,
    dmc: Dmc,
    frame: FrameCounter,
    pulse_table: [f32; 31],
    tnd_table: [f32; 794],
    /// Last `cpu_cycle` observed by `clock`, used to ignore duplicate calls for
    /// the same CPU cycle (defensive; the contract is one call per cycle).
    last_cycle: u64,
    have_last_cycle: bool,
}

impl Apu {
    pub fn new() -> Apu {
        let mut apu = Apu {
            pulse: [Pulse::default(); 2],
            triangle: Triangle::default(),
            noise: Noise::default(),
            dmc: Dmc::default(),
            frame: FrameCounter::default(),
            pulse_table: [0.0; 31],
            tnd_table: [0.0; 794],
            last_cycle: 0,
            have_last_cycle: false,
        };
        for n in 0..31 {
            apu.pulse_table[n] = if n == 0 {
                0.0
            } else {
                95.52f32 / (8128.0f32 / n as f32 + 100.0f32)
            };
        }
        // TND weights are (triangle 12, noise 7, DMC 4) - the documented
        // 8227:12241:22638 ratio scaled by 4 with the noise term trimmed to
        // match the reference's measured noise level.  The table constant is
        // scaled by the same factor so the curve is unchanged.
        let m = mix_lin();
        for n in 0..794 {
            apu.tnd_table[n] = if n == 0 {
                0.0
            } else {
                (163.67f32 * m) / ((97316.0f32 * m) / n as f32 + 100.0f32)
            };
        }
        apu.reset();
        apu
    }

    /// Cold power-on state (all APU state zeroed, except the noise LFSR which
    /// hardware loads with 1).
    pub fn reset(&mut self) {
        self.pulse = [Pulse::default(); 2];
        self.triangle = Triangle::default();
        self.noise = Noise::default();
        // Hardware loads the noise LFSR with 1 at power-up.
        self.noise.shift = 0x0001;
        self.dmc = Dmc::default();
        self.dmc.silence = true;
        self.frame = FrameCounter::default();
        self.have_last_cycle = false;
    }

    // -- clocking -----------------------------------------------------------

    /// Called exactly once per CPU cycle.
    pub fn clock(&mut self, cpu_cycle: u64) {
        // Defensive: ignore repeated calls for the same CPU cycle.
        if self.have_last_cycle && cpu_cycle == self.last_cycle {
            return;
        }
        self.last_cycle = cpu_cycle;
        self.have_last_cycle = true;
        #[cfg(feature = "trace")]
        APU_NOW.with(|c| c.set(cpu_cycle));

        // Pending $4017 reset (applied 3 or 4 CPU cycles after the write).
        let mut suppress_frame_tick = false;
        if let Some(at) = self.frame.reset_at {
            if cpu_cycle >= at {
                self.frame.reset_at = None;
                // If the reset coincides with an APU clock tick, that tick's step
                // (and any frame IRQ flag set) is suppressed.
                suppress_frame_tick = (cpu_cycle & 1) == 0;
                self.frame.cycle = 0;
                if self.frame.mode5 {
                    self.clock_quarter_frame();
                    self.clock_half_frame();
                }
            }
        }

        // Quarter/half frame signals of a step are emitted 1 CPU cycle later.
        if self.frame.pending_quarter {
            self.frame.pending_quarter = false;
            self.clock_quarter_frame();
        }
        if self.frame.pending_half {
            self.frame.pending_half = false;
            self.clock_half_frame();
        }

        // CPU-cycle domain: triangle timer and DMC timer.
        self.triangle.clock_timer();
        self.dmc.clock_timer();

        // APU-cycle (CPU/2) domain.
        if (cpu_cycle & 1) == 0 {
            self.pulse[0].clock_timer();
            self.pulse[1].clock_timer();
            self.noise.clock_timer();
            if !suppress_frame_tick {
                self.clock_frame_counter();
            }
        }
    }

    fn clock_frame_counter(&mut self) {
        self.frame.cycle += 1;
        let last = if self.frame.mode5 { 18641 } else { 14915 };
        if self.frame.cycle >= last {
            self.frame.cycle = 0;
            // The frame interrupt flag is also set on the cycle the sequence
            // wraps (APU cycle 14915 == 0 of the next sequence).
            if !self.frame.mode5 && !self.frame.irq_inhibit && apu_irq_wrap() {
                self.frame.irq_flag = true;
            }
        }
        let cycle = self.frame.cycle;

        let (mut quarter, mut half) = (false, false);
        if self.frame.mode5 {
            match cycle {
                3728 => quarter = true,
                7456 => {
                    quarter = true;
                    half = true;
                }
                11185 => quarter = true,
                14914 => {} // step 4 clocks nothing in 5-step mode
                18640 => {
                    quarter = true;
                    half = true;
                }
                _ => {}
            }
        } else {
            match cycle {
                3728 => quarter = true,
                7456 => {
                    quarter = true;
                    half = true;
                }
                11185 => quarter = true,
                14914 => {
                    quarter = true;
                    half = true;
                    if !self.frame.irq_inhibit && apu_irq_14914() {
                        self.frame.irq_flag = true;
                    }
                }
                _ => {}
            }
        }

        if quarter {
            self.frame.pending_quarter = true;
        }
        if half {
            self.frame.pending_half = true;
        }
    }

    fn clock_quarter_frame(&mut self) {
        self.pulse[0].clock_quarter();
        self.pulse[1].clock_quarter();
        self.triangle.clock_quarter();
        self.noise.clock_quarter();
    }

    fn clock_half_frame(&mut self) {
        self.pulse[0].clock_half(PULSE1);
        self.pulse[1].clock_half(PULSE2);
        self.triangle.clock_half();
        self.noise.clock_half();
    }

    // -- bus ----------------------------------------------------------------

    pub fn read(&mut self, addr: u16, open_bus: u8) -> u8 {
        match addr {
            0x4015 => {
                let mut status = open_bus & 0x20; // bit 5 is open bus
                if self.pulse[0].length.value > 0 {
                    status |= 0x01;
                }
                if self.pulse[1].length.value > 0 {
                    status |= 0x02;
                }
                if self.triangle.length.value > 0 {
                    status |= 0x04;
                }
                if self.noise.length.value > 0 {
                    status |= 0x08;
                }
                if self.dmc.bytes_remaining > 0 {
                    status |= 0x10;
                }
                if self.frame.irq_flag {
                    status |= 0x40;
                }
                if self.dmc.irq_flag {
                    status |= 0x80;
                }
                self.frame.irq_flag = false;
                status
            }
            _ => open_bus,
        }
    }

    pub fn write(&mut self, addr: u16, val: u8, cpu_cycle: u64) {
        #[cfg(feature = "trace")]
        {
            if std::env::var("APU_WLOG").is_ok() {
                eprintln!("AW {:04X} {:02X} cyc={}", addr, val, cpu_cycle);
            }
        }
        #[cfg(feature = "trace")]
        if std::env::var("TRACE_APUW").is_ok() {
            eprintln!("APUW cyc={} addr={:04X} val={:02X}", cpu_cycle, addr, val);
        }
        match addr {
            0x4000..=0x4003 => self.write_pulse(0, (addr & 0x03) as u8, val),
            0x4004..=0x4007 => self.write_pulse(1, (addr & 0x03) as u8, val),
            0x4008 => {
                self.triangle.control = (val & 0x80) != 0;
                self.triangle.reload_value = val & 0x7F;
            }
            0x400A => {
                self.triangle.timer_period =
                    (self.triangle.timer_period & 0x700) | (val as u16);
            }
            0x400B => {
                self.triangle.timer_period =
                    (self.triangle.timer_period & 0x0FF) | (((val & 0x07) as u16) << 8);
                self.triangle.length.load(val >> 3);
                self.triangle.reload_flag = true;
            }
            0x400C => {
                self.noise.halt = (val & 0x20) != 0;
                self.noise.constant_volume = (val & 0x10) != 0;
                self.noise.volume = val & 0x0F;
            }
            0x400E => {
                self.noise.mode = (val & 0x80) != 0;
                self.noise.period_index = val & 0x0F;
            }
            0x400F => {
                self.noise.length.load(val >> 3);
                self.noise.envelope.start = true;
            }
            0x4010 => {
                self.dmc.irq_enable = (val & 0x80) != 0;
                if !self.dmc.irq_enable {
                    self.dmc.irq_flag = false;
                }
                self.dmc.loop_flag = (val & 0x40) != 0;
                self.dmc.rate_index = val & 0x0F;
            }
            0x4011 => self.dmc.output_level = val & 0x7F,
            0x4012 => self.dmc.sample_address = val,
            0x4013 => self.dmc.sample_length = val,
            0x4015 => {
                self.pulse[0].length.set_enabled((val & 0x01) != 0);
                self.pulse[1].length.set_enabled((val & 0x02) != 0);
                self.triangle.length.set_enabled((val & 0x04) != 0);
                self.noise.length.set_enabled((val & 0x08) != 0);
                self.dmc.irq_flag = false;
                if (val & 0x10) != 0 {
                    self.dmc.enabled = true;
                    if self.dmc.bytes_remaining == 0 {
                        self.dmc.restart_sample();
                        // A fetch scheduled straight from the $4015 write with an
                        // empty buffer is a load DMA; otherwise the fetch happens
                        // when the buffered byte is consumed (reload DMA).
                        self.dmc.load_dma = self.dmc.sample_buffer.is_none();
                    }
                } else {
                    self.dmc.enabled = false;
                    self.dmc.bytes_remaining = 0;
                }
            }
            0x4017 => {
                self.frame.mode5 = (val & 0x80) != 0;
                self.frame.irq_inhibit = (val & 0x40) != 0;
                if self.frame.irq_inhibit {
                    self.frame.irq_flag = false;
                }
                // Effects land 3 CPU cycles after the write if it happens on an
                // APU clock tick, 4 CPU cycles otherwise.
                let delay = if (cpu_cycle & 1) == 0 { 3 } else { 4 };
                self.frame.reset_at = Some(cpu_cycle + delay);
            }
            _ => {}
        }
    }

    fn write_pulse(&mut self, idx: usize, reg: u8, val: u8) {
        let pulse = &mut self.pulse[idx];
        match reg {
            0 => {
                pulse.duty = val >> 6;
                pulse.halt = (val & 0x20) != 0;
                pulse.constant_volume = (val & 0x10) != 0;
                pulse.volume = val & 0x0F;
            }
            1 => {
                pulse.sweep.enabled = (val & 0x80) != 0;
                pulse.sweep.period = (val >> 4) & 0x07;
                pulse.sweep.negate = (val & 0x08) != 0;
                pulse.sweep.shift = val & 0x07;
                pulse.sweep.reload = true;
            }
            2 => {
                pulse.timer_period = (pulse.timer_period & 0x700) | (val as u16);
            }
            3 => {
                pulse.timer_period =
                    (pulse.timer_period & 0x0FF) | (((val & 0x07) as u16) << 8);
                pulse.length.load(val >> 3);
                pulse.envelope.start = true;
                pulse.sequence = 0;
            }
            _ => {}
        }
    }

    // -- interrupts / DMA ---------------------------------------------------

    pub fn irq_pending(&self) -> bool {
        self.frame.irq_flag && !self.frame.irq_inhibit
    }

    pub fn dmc_dma_request(&self) -> bool {
        if dmc_dma_disabled() {
            return false;
        }
        self.dmc.sample_buffer.is_none() && self.dmc.bytes_remaining > 0
    }

    /// Type of the pending DMC DMA fetch, valid while [`Apu::dmc_dma_request`] is
    /// true. `true` = "load" DMA: it was scheduled by a `$4015` write that enabled
    /// or restarted the sample with an empty buffer, so on hardware the halt
    /// attempt happens on a *get* cycle during the 2nd APU cycle after that write
    /// (3 CPU cycles + any write-cycle delays, and the DMA takes 3 cycles).
    /// `false` = "reload" DMA: it was scheduled because the sample buffer emptied
    /// during playback; the halt attempt happens on a *put* cycle (the DMA takes
    /// 4 cycles unless the halt is delayed). See spec/docs/nesdev-wiki/DMA.md.
    ///
    /// Cycle-phase convention of this module: CPU cycles with `cpu_cycle & 1 == 0`
    /// are *get* cycles (the same parity on which the APU itself is ticked), and
    /// `cpu_cycle & 1 == 1` are *put* cycles.
    pub fn dmc_dma_is_load(&self) -> bool {
        self.dmc.load_dma
    }

    pub fn dmc_dma_ack(&mut self, val: u8) {
        if self.dmc.sample_buffer.is_none() && self.dmc.bytes_remaining > 0 {
            self.dmc.sample_buffer = Some(val);
            self.dmc.current_address = self.dmc.current_address.wrapping_add(1);
            if self.dmc.current_address < 0x8000 {
                // Address wrapped past $FFFF.
                self.dmc.current_address = 0x8000;
            }
            self.dmc.bytes_remaining -= 1;
            if self.dmc.bytes_remaining == 0 {
                if self.dmc.loop_flag {
                    self.dmc.restart_sample();
                } else if self.dmc.irq_enable {
                    self.dmc.irq_flag = true;
                }
            }
            // Whatever fetch comes next is scheduled because the buffer emptied,
            // i.e. a reload DMA.
            self.dmc.load_dma = false;
        }
    }

    // -- mixer --------------------------------------------------------------

    /// Instantaneous analog output level (0.0..=1.0), accurate non-linear mixer.
    pub fn mix(&self) -> f32 {
        let pulses = (self.pulse[0].output(PULSE1) + self.pulse[1].output(PULSE2)) as usize;
        // Weights (triangle 12, noise 5.6, DMC 2.2) are calibrated against the
        // reference's measured levels for each channel (tools: mixcurve.py,
        // mixcurve2.py, dmccurve.py); the table's constant uses the same scale.
        let tnd = tri_weight() * self.triangle.output() as usize
            + (28 * noise_weight() / 7 * self.noise.output() as usize) / 5
            + (22 * self.dmc.output_level as usize) / 10;
        // The NES DACs are unipolar, so the mixer has a constant idle offset.
        // The reference keeps it: the output filters turn it into the fixed
        // start-up transient that every one of its recordings begins with.
        // The value is calibrated against the reference (0.25 of the mixer's
        // full scale); the offset itself is then removed by the DC blockers, so
        // it does not affect steady-state output.
        self.pulse_table[pulses] + self.tnd_table[tnd] + unsafe { MIX_DC }
    }

    // -- extra introspection (not part of the frozen interface) -------------

    /// Pulse 1's period and the sweep's target period (diagnostics).
    pub fn pulse1_debug(&self) -> (u16, u8, u8, u8, u8, u8) {
        let p = self.pulse[0].timer_period & 0x7FF;
        (
            p,
            self.pulse[0].envelope.decay,
            self.pulse[0].duty,
            (self.pulse[0].sequence & 7) | ((self.pulse[0].timer_counter > 0x3FF) as u8) << 4,
            self.pulse[0].length.value,
            self.pulse[0].output(PULSE1),
        )
    }

    /// Raw DAC value of a channel: 0=pulse1, 1=pulse2, 2=triangle, 3=noise,
    /// 4=DMC (0..127 for the DMC, 0..15 for the others).
    pub fn channel_dac(&self, channel: usize) -> u8 {
        match channel {
            0 => self.pulse[0].output(PULSE1),
            1 => self.pulse[1].output(PULSE2),
            2 => self.triangle.output(),
            3 => self.noise.output(),
            _ => self.dmc.output_level,
        }
    }

    /// Length counter value (0=pulse1, 1=pulse2, 2=triangle, 3=noise).
    pub fn length_counter(&self, channel: usize) -> u8 {
        match channel {
            0 => self.pulse[0].length.value,
            1 => self.pulse[1].length.value,
            2 => self.triangle.length.value,
            _ => self.noise.length.value,
        }
    }

    /// $4015 enable flag (0=pulse1, 1=pulse2, 2=triangle, 3=noise, 4=DMC).
    pub fn channel_enabled(&self, channel: usize) -> bool {
        match channel {
            0 => self.pulse[0].length.enabled,
            1 => self.pulse[1].length.enabled,
            2 => self.triangle.length.enabled,
            3 => self.noise.length.enabled,
            _ => self.dmc.enabled,
        }
    }

    /// Current envelope volume (0=pulse1, 1=pulse2, 2=noise).
    pub fn envelope_volume(&self, channel: usize) -> u8 {
        match channel {
            0 => self.pulse[0]
                .envelope
                .volume(self.pulse[0].constant_volume, self.pulse[0].volume),
            1 => self.pulse[1]
                .envelope
                .volume(self.pulse[1].constant_volume, self.pulse[1].volume),
            _ => self.noise
                .envelope
                .volume(self.noise.constant_volume, self.noise.volume),
        }
    }

    /// Pulse timer period (0=pulse1, 1=pulse2).
    pub fn pulse_period(&self, channel: usize) -> u16 {
        self.pulse[channel & 1].timer_period & 0x7FF
    }

    /// Pulse sequencer position (0..7).
    pub fn pulse_sequence(&self, channel: usize) -> u8 {
        self.pulse[channel & 1].sequence
    }

    /// Pulse sequencer output bit at the current position.
    pub fn pulse_sequence_bit(&self, channel: usize) -> bool {
        let p = &self.pulse[channel & 1];
        DUTY_TABLE[(p.duty & 0x03) as usize][(p.sequence & 0x07) as usize] != 0
    }

    /// Whether the sweep unit is currently muting the channel.
    pub fn pulse_sweep_muting(&self, channel: usize) -> bool {
        let p = &self.pulse[channel & 1];
        p.sweep.muting(p.timer_period & 0x7FF, channel == 0)
    }

    pub fn triangle_period(&self) -> u16 {
        self.triangle.timer_period & 0x7FF
    }

    pub fn triangle_linear_counter(&self) -> u8 {
        self.triangle.linear_counter
    }

    /// Current triangle sequence value (0..15).
    pub fn triangle_sequence(&self) -> u8 {
        self.triangle.output()
    }

    pub fn noise_clocks(&self) -> u64 {
        self.noise.clocks
    }

    pub fn noise_shift_register(&self) -> u16 {
        self.noise.shift
    }

    /// Noise timer period in APU cycles.
    pub fn noise_period_apu(&self) -> u16 {
        self.noise.period()
    }

    pub fn dmc_output_level(&self) -> u8 {
        self.dmc.output_level
    }

    pub fn dmc_bytes_remaining(&self) -> u16 {
        self.dmc.bytes_remaining
    }

    pub fn dmc_current_address(&self) -> u16 {
        self.dmc.current_address
    }

    pub fn dmc_irq_flag(&self) -> bool {
        self.dmc.irq_flag
    }

    pub fn clear_dmc_irq(&mut self) {
        self.dmc.irq_flag = false;
    }

    pub fn frame_irq_flag(&self) -> bool {
        self.frame.irq_flag
    }

    /// APU cycles elapsed in the frame counter since its last reset.
    pub fn frame_cycle(&self) -> u32 {
        self.frame.cycle
    }

    pub fn frame_mode5(&self) -> bool {
        self.frame.mode5
    }
}
