//! Machine: CPU + PPU + APU + cartridge glue, DMA, controllers, audio output.

use crate::apu::Apu;
use crate::cpu::Cpu;
use crate::mapper::Mapper;
use crate::ppu::Ppu;

pub const CPU_HZ: f64 = 1789772.7272727273;
pub const SAMPLE_RATE: u32 = 44100;

/// Windowed-sinc low-pass (35 taps, 13 kHz, Blackman) applied to the output,
/// matching the reference's band-limited resampling (17-sample group delay).
const FIR_TAPS: usize = 35;
const FIR_COEFFS: [f64; FIR_TAPS] = [
    -0.0000000000, -0.0000582377, 0.0000971652, 0.0003321966, -0.0013859498, 0.0020410250, -0.0002454556,
    -0.0049364911, 0.0103932113, -0.0088657946, -0.0054848168, 0.0282752741, -0.0409680922, 0.0191226842,
    0.0492957274, -0.1486955687, 0.2382745806, 0.7256170843, 0.2382745806, -0.1486955687, 0.0492957274,
    0.0191226842, -0.0409680922, 0.0282752741, -0.0054848168, -0.0088657946, 0.0103932113, -0.0049364911,
    -0.0002454556, 0.0020410250, -0.0013859498, 0.0003321966, 0.0000971652, -0.0000582377, -0.0000000000,
];

/// Output resampling mode: 0 = hold the chain output, 1 = windowed-sinc FIR,
/// 2 = linear interpolation between output samples.
static mut FIR_MODE: u32 = 1;
#[cfg(feature = "trace")]
fn fir_mode() -> u32 {
    unsafe {
        if let Ok(v) = std::env::var("FIR") {
            if let Ok(n) = v.parse::<u32>() {
                FIR_MODE = n;
            }
        }
        FIR_MODE
    }
}
#[cfg(not(feature = "trace"))]
fn fir_mode() -> u32 {
    unsafe { FIR_MODE }
}

/// Audio pipeline constants (tuned against the reference emulator).
const AUDIO_START_DELAY: f64 = -(728.0 / (CPU_HZ / SAMPLE_RATE as f64));
/// Scale applied to the DC-blocked mixer output.
static mut AUDIO_SCALE: f64 = 32000.0;
static mut HP1_HZ: f64 = 90.0;
static mut HP2_HZ: f64 = 440.0;
static mut LP_HZ: f64 = 14000.0;

#[cfg(feature = "trace")]
fn load_audio_env() {
    unsafe {
        if let Ok(v) = std::env::var("A_SCALE") {
            if let Ok(f) = v.parse::<f64>() { AUDIO_SCALE = f; }
        }
        if let Ok(v) = std::env::var("A_HP1") {
            if let Ok(f) = v.parse::<f64>() { HP1_HZ = f; }
        }
        if let Ok(v) = std::env::var("A_HP2") {
            if let Ok(f) = v.parse::<f64>() { HP2_HZ = f; }
        }
        if let Ok(v) = std::env::var("A_LP") {
            if let Ok(f) = v.parse::<f64>() { LP_HZ = f; }
        }
    }
}
#[cfg(not(feature = "trace"))]
fn load_audio_env() {}
fn hp_coef(hz: f64) -> f64 {
    let rc = 1.0 / (2.0 * core::f64::consts::PI * hz);
    let dt = 1.0 / SAMPLE_RATE as f64;
    rc / (rc + dt)
}
fn lp_coef(hz: f64) -> f64 {
    let rc = 1.0 / (2.0 * core::f64::consts::PI * hz);
    let dt = 1.0 / SAMPLE_RATE as f64;
    dt / (rc + dt)
}

/// How many consecutive samples the NMI line must be high before the CPU's
/// edge detector latches an interrupt.
static mut NMI_LATCH_DOTS: u32 = 1;
#[cfg(feature = "trace")]
fn nmi_latch_dots() -> u32 {
    unsafe {
        if let Ok(v) = std::env::var("NMI_LATCH_DOTS") {
            if let Ok(n) = v.parse::<u32>() {
                NMI_LATCH_DOTS = n;
            }
        }
        NMI_LATCH_DOTS
    }
}
#[cfg(not(feature = "trace"))]
fn nmi_latch_dots() -> u32 {
    unsafe { NMI_LATCH_DOTS }
}

/// Which dot of the three-dot CPU cycle samples the NMI line (0, 1, or 2).
static mut NMI_SAMPLE_PHASE: u32 = 0;
#[cfg(feature = "trace")]
fn nmi_sample_phase() -> u32 {
    unsafe {
        if let Ok(v) = std::env::var("NMI_PHASE") {
            if let Ok(n) = v.parse::<u32>() {
                NMI_SAMPLE_PHASE = n;
            }
        }
        NMI_SAMPLE_PHASE
    }
}
#[cfg(not(feature = "trace"))]
fn nmi_sample_phase() -> u32 {
    unsafe { NMI_SAMPLE_PHASE }
}

/// PPU dots clocked before the CPU's bus access inside its CPU cycle.
const ACCESS_PHASE: u32 = 2;

/// Whether DMA "get" (read) cycles fall on even CPU cycles. The reference fixes
/// this at power-on; it only affects DMA alignment cycles.
const GET_ON_EVEN: bool = true;

#[derive(Clone, Copy)]
enum Access {
    Read(u16),
    Write(u16, u8),
}

impl Access {
    fn is_write(&self) -> bool {
        matches!(self, Access::Write(..))
    }
}

struct OamDma {
    remaining: u32,
    page: u16,
    offset: u16,
    latch: u8,
    writing: bool,
    dummy_cycles: u32,
}

pub struct System {
    pub cpu: Cpu,
    pub ppu: Ppu,
    pub apu: Apu,
    pub mapper: Box<dyn Mapper>,
    pub ram: [u8; 2048],

    pub keys: [u8; 2],
    pub shift: [u8; 2],
    pub strobe: bool,

    /// CPU cycles elapsed since power-on.
    pub cycles: u64,
    prev_nmi: bool,
    /// NMI edge detected this cycle; promoted to `cpu.nmi_pending` at the start
    /// of the next CPU cycle (hardware's edge detector output appears one cycle
    /// after the edge is seen on the line).
    nmi_latch: bool,
    /// IRQ line and I-flag state as sampled at the end of the previous cycle.
    irq_prev_line: bool,
    irq_prev_i: bool,
    /// Consecutive PPU dots the NMI line has been high (the CPU's edge
    /// detector needs the line up for a few dots before it latches).
    nmi_high_dots: u32,
    oam_dma: Option<OamDma>,

    /// Pending access to repeat on DMA halt cycles.
    halt_addr: u16,
    /// The reference's first `emu_run_frame` call returns without emulating
    /// anything, which shifts every subsequent frame boundary by one frame.
    first_frame: bool,
    pub hist_enabled: bool,
    pub pcwatch: u64,
    pub hist: Vec<u16>,

    // Audio output
    pub out: Vec<i16>,
    audio_acc: f64,
    #[cfg(feature = "trace")]
    pub mix_dump: Vec<f32>,
    #[cfg(feature = "trace")]
    pub y3_dump: Vec<f32>,
    #[cfg(feature = "trace")]
    pub ch_dump: [Vec<u8>; 5],
    #[cfg(feature = "trace")]
    pub len_dump: [Vec<u8>; 4],
    #[cfg(feature = "trace")]
    pub p1_dump: Vec<(u16, u8, u8, u8, u8, u8)>,
    /// Chain output at the previous output sample (for interpolation).
    prev_y3: f64,
    /// High-pass filter states (DC blockers) and low-pass state.
    hp1_x: f64,
    hp1_y: f64,
    hp2_x: f64,
    hp2_y: f64,
    lp_y: f64,
    fir_hist: [f64; FIR_TAPS],
}

impl System {
    pub fn new(mapper: Box<dyn Mapper>) -> System {
        let mut s = System {
            cpu: Cpu::new(),
            ppu: Ppu::new(),
            apu: Apu::new(),
            mapper,
            ram: [0; 2048],
            keys: [0; 2],
            shift: [0; 2],
            strobe: false,
            cycles: 0,
            prev_nmi: false,
            nmi_latch: false,
            irq_prev_line: false,
            irq_prev_i: false,
            nmi_high_dots: 0,
            oam_dma: None,
            halt_addr: 0,
            first_frame: true,
            hist_enabled: false,
            pcwatch: std::env::var("PCWATCH").ok().and_then(|v| v.parse().ok()).unwrap_or(0),
            hist: Vec::new(),
            out: Vec::with_capacity(8192),
            audio_acc: 0.0,
            #[cfg(feature = "trace")]
            mix_dump: Vec::new(),
            #[cfg(feature = "trace")]
            ch_dump: [Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new()],
            #[cfg(feature = "trace")]
            len_dump: [Vec::new(), Vec::new(), Vec::new(), Vec::new()],
            #[cfg(feature = "trace")]
            p1_dump: Vec::new(),
            #[cfg(feature = "trace")]
            y3_dump: Vec::new(),
            prev_y3: 0.0,
            hp1_x: 0.0,
            hp1_y: 0.0,
            hp2_x: 0.0,
            hp2_y: 0.0,
            lp_y: 0.0,
            fir_hist: [0.0; FIR_TAPS],
        };
        load_audio_env();
        s.power_on();
        s
    }

    pub fn power_on(&mut self) {
        self.cpu = Cpu::new();
        self.cpu.sp = 0x00;
        self.cpu.p = 0x24;
        self.ppu.reset();
        self.apu.reset();
        self.ram = [0; 2048];
        self.keys = [0; 2];
        self.shift = [0; 2];
        self.strobe = false;
        self.cycles = 0;
        self.prev_nmi = false;
        self.nmi_latch = false;
        self.irq_prev_line = false;
        self.irq_prev_i = false;
        self.nmi_high_dots = 0;
        self.oam_dma = None;
        self.halt_addr = 0;
        self.first_frame = true;
        self.out.clear();
        #[cfg(feature = "trace")]
        {
            self.mix_dump.clear();
            self.ch_dump = [Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new()];
            self.len_dump = [Vec::new(), Vec::new(), Vec::new(), Vec::new()];
            self.p1_dump.clear();
        }
        self.audio_acc = AUDIO_START_DELAY;
        self.prev_y3 = 0.0;
        self.hp1_x = 0.0;
        self.hp1_y = 0.0;
        self.hp2_x = 0.0;
        self.hp2_y = 0.0;
        self.lp_y = 0.0;
        for v in self.fir_hist.iter_mut() {
            *v = 0.0;
        }
        self.reset_sequence();
    }

    // ------------------------------------------------------------ clocking ---

    #[inline]
    fn clock_dot(&mut self, access: Option<Access>) -> u8 {
        {
            let System { ppu, mapper, .. } = self;
            ppu.process_dot(mapper.as_mut());
        }
        let mut result = self.cpu.bus_latch;
        match access {
            Some(Access::Read(addr)) => {
                result = self.bus_read(addr);
                self.cpu.bus_latch = result;
            }
            Some(Access::Write(addr, val)) => {
                self.bus_write(addr, val);
                self.cpu.bus_latch = val;
            }
            None => {}
        }
        // The NMI input is sampled at the end of each PPU dot, that is after
        // the CPU bus access: a $2002 read in the same dot can therefore
        // suppress the NMI, but a read that merely clears the flag cannot hide
        // an edge that has already been asserted.
        // The CPU samples the NMI line once per machine cycle, on its bus
        // access dot; a $2002 read on that dot (or one that clears the vblank
        // flag before it) hides the edge, which is why reads a dot or two after
        // the flag set suppress the NMI.
        self.ppu.advance();
        result
    }

    /// Sample the PPU's NMI line at one point of the CPU cycle: it is high
    /// while the vblank flag and the NMI enable are both set, and the CPU
    /// latches on a rising edge.
    #[inline]
    fn sample_nmi(&mut self) {
        let line = self.ppu.nmi_line();
        if line {
            self.nmi_high_dots = self.nmi_high_dots.saturating_add(1);
            if self.nmi_high_dots == nmi_latch_dots() {
                self.nmi_latch = true;
            }
        } else {
            self.nmi_high_dots = 0;
        }
        self.prev_nmi = line;
    }

    /// A single CPU cycle without any of the DMA handling.
    #[inline]
    fn raw_cycle(&mut self, access: Option<Access>) -> u8 {
        let phase = nmi_sample_phase();
        let v = self.clock_dot(access);
        if phase == ACCESS_PHASE {
            self.sample_nmi();
        }
        // The IRQ input is level-sensitive.  The CPU polls it on the cycle
        // before an instruction's last cycle, so the value consulted at the
        // instruction boundary is the one-cycle-old level sample: a CLI's I
        // write (last cycle) is not seen by its own poll, while an RTI's
        // flag pull (earlier cycle) is.  This must not be sticky, or a sample
        // taken during CLI's instruction would leak into the next one.
        self.cpu.irq_seen = self.irq_prev_line && self.irq_prev_i;
        self.irq_prev_line = self.irq_line();
        self.irq_prev_i = !self.cpu.flag(crate::cpu::FLAG_I);

        self.apu.clock(self.cycles);
        for i in 0..(2u32.saturating_sub(ACCESS_PHASE)) {
            self.clock_dot(None);
            if ACCESS_PHASE + 1 + i == phase {
                self.sample_nmi();
            }
        }
        self.cycles += 1;
        self.audio_tick();
        v
    }

    #[inline]
    fn cpu_cycle(&mut self, access: Option<Access>) -> u8 {
        if self.nmi_latch {
            self.nmi_latch = false;
            self.cpu.nmi_pending = true;
        }
        // Number of PPU dots clocked *before* the CPU's bus access within its
        // CPU cycle (the CPU/PPU sub-cycle alignment).
        {
            let phase = nmi_sample_phase();
            for i in 0..ACCESS_PHASE {
                self.clock_dot(None);
                if i == phase {
                    self.sample_nmi();
                }
            }
        }
        // A pending DMC DMA halts the CPU, but only on read cycles.
        let can_halt = match access {
            Some(a) if a.is_write() => false,
            _ => true,
        };
        if can_halt && self.apu.dmc_dma_request() {
            let addr = match access {
                Some(Access::Read(a)) => a,
                _ => self.cpu.pc,
            };
            self.halt_addr = addr;
            self.dmc_dma_run(addr);
        }
        self.raw_cycle(access)
    }

    /// Steal cycles for a DMC sample fetch: halt, dummy, [align], get.
    fn dmc_dma_run(&mut self, addr: u16) {
        let load = self.apu.dmc_dma_is_load();
        // Halt cycle: the CPU repeats its attempted read.
        self.raw_cycle(Some(Access::Read(addr)));
        // Dummy cycle.
        self.raw_cycle(Some(Access::Read(addr)));
        if !load {
            // Reload DMAs need an alignment cycle.
            self.raw_cycle(Some(Access::Read(addr)));
        }
        let dmc_addr = self.apu.dmc_current_address();
        let val = self.raw_cycle(Some(Access::Read(dmc_addr)));
        self.apu.dmc_dma_ack(val);
    }

    /// A cycle stolen by DMA: the CPU bus access is replaced by the DMA access.
    #[inline]
    fn dma_cycle(&mut self, access: Option<Access>) -> u8 {
        {
            let phase = nmi_sample_phase();
            for i in 0..ACCESS_PHASE {
                self.clock_dot(None);
                if i == phase {
                    self.sample_nmi();
                }
            }
        }
        let v = self.clock_dot(access);
        self.apu.clock(self.cycles);
        for _ in 0..(2u32.saturating_sub(ACCESS_PHASE)) {
            self.clock_dot(None);
        }
        self.cycles += 1;
        self.audio_tick();
        v
    }

    /// One cycle of OAM DMA. Returns true when the DMA has finished.
    fn oam_dma_cycle(&mut self) -> bool {
        let mut phase_write = false;
        let mut dummy = false;
        let mut page_addr = 0u16;
        let mut latch = 0u8;
        let done;
        match self.oam_dma.as_mut() {
            Some(d) => {
                d.remaining -= 1;
                done = d.remaining == 0;
                if d.dummy_cycles > 0 {
                    d.dummy_cycles -= 1;
                    dummy = true;
                } else if d.writing {
                    phase_write = true;
                    latch = d.latch;
                } else {
                    page_addr = d.page | d.offset;
                }
            }
            None => return true,
        }
        let access = if dummy {
            Some(Access::Read(self.halt_addr))
        } else if phase_write {
            Some(Access::Write(0x2004, latch))
        } else {
            Some(Access::Read(page_addr))
        };
        let val = self.dma_cycle(access);
        if let Some(d) = self.oam_dma.as_mut() {
            if phase_write {
                d.writing = false;
                d.offset = (d.offset + 1) & 0xFF;
            } else if !dummy {
                d.writing = true;
                d.latch = val;
            }
        }
        if done {
            self.oam_dma = None;
        }
        done
    }

    // ------------------------------------------------------------- bus ---

    #[inline]
    fn bus_read(&mut self, addr: u16) -> u8 {
        match addr {
            0x0000..=0x1FFF => self.ram[(addr & 0x07FF) as usize],
            0x2000..=0x3FFF => {
                let open = self.cpu.bus_latch;
                let System { ppu, mapper, .. } = self;
                ppu.read_register(addr & 0x2007, open, mapper.as_mut())
            }
            0x4015 => {
                let open = self.cpu.bus_latch;
                self.apu.read(0x4015, open)
            }
            0x4016 => {
                let v = (self.shift[0] & 1) | (self.cpu.bus_latch & 0xE0);
                self.shift[0] >>= 1;
                v
            }
            0x4017 => {
                let v = (self.shift[1] & 1) | (self.cpu.bus_latch & 0xE0);
                self.shift[1] >>= 1;
                v
            }
            0x4000..=0x4017 => {
                let open = self.cpu.bus_latch;
                self.apu.read(addr, open)
            }
            0x4018..=0x401F => self.cpu.bus_latch,
            _ => self.mapper.prg_read(addr),
        }
    }

    #[inline]
    fn bus_write(&mut self, addr: u16, val: u8) {
        #[cfg(feature = "trace")]
        {
            if std::env::var("APU_TRACE").is_ok() && ((0x4000..=0x4017).contains(&addr)) {
                eprintln!("A {:04X} <- {:02X} @{}", addr, val, self.cycles);
            }
            if std::env::var("WRITE_TRACE").is_ok() && ((0x2000..=0x2007).contains(&addr) || addr == 0x4014) {
                if addr == 0x2007 {
                    eprintln!("W 2007 <- {:02X} @{} v={:04X} mask={:02X} sl={} dot={}", val, self.cycles, self.ppu.v, self.ppu.mask, self.ppu.scanline, self.ppu.dot);
                } else {
                    eprintln!("W {:04X} <- {:02X} @{} sl={} dot={} mask={:02X} pc={:04X}", addr, val, self.cycles, self.ppu.scanline, self.ppu.dot, self.ppu.mask, self.cpu.pc);
                }
            }
        }
        match addr {
            0x0000..=0x1FFF => self.ram[(addr & 0x07FF) as usize] = val,
            0x2000..=0x3FFF => {
                let warmup = self.cycles < 29658;
                let System { ppu, mapper, .. } = self;
                ppu.write_register(addr & 0x2007, val, mapper.as_mut(), warmup);
            }
            0x4014 => {
                // The halt happens on the next CPU cycle; if that cycle is a put
                // cycle an alignment cycle is inserted before the first get.
                let next = self.cycles + 1;
                let is_get = if GET_ON_EVEN { next & 1 == 0 } else { next & 1 == 1 };
                let dummy_cycles = 1 + if is_get { 0 } else { 1 };
                let total = dummy_cycles + 512;
                self.oam_dma = Some(OamDma {
                    remaining: total,
                    page: (val as u16) << 8,
                    offset: 0,
                    latch: 0,
                    writing: false,
                    dummy_cycles,
                });
            }
            0x4016 => {
                if val & 1 != 0 {
                    self.strobe = true;
                } else if self.strobe {
                    self.strobe = false;
                }
                if val & 1 != 0 || self.strobe == false {
                    self.shift[0] = self.keys[0];
                    self.shift[1] = self.keys[1];
                }
            }
            0x4000..=0x4017 => {
                self.apu.write(addr, val, self.cycles);
            }
            0x4018..=0x401F => {}
            _ => self.mapper.prg_write(addr, val),
        }
    }

    // ------------------------------------------------------------ running ---

    #[inline]
    pub(crate) fn rd(&mut self, addr: u16) -> u8 {
        self.cpu_cycle(Some(Access::Read(addr)))
    }

    #[inline]
    pub(crate) fn wr(&mut self, addr: u16, val: u8) {
        self.cpu_cycle(Some(Access::Write(addr, val)));
    }

    #[inline]
    pub(crate) fn tick_cycle(&mut self) {
        self.cpu_cycle(None);
    }

    #[inline]
    pub fn irq_line(&self) -> bool {
        self.apu.irq_pending() || self.apu.dmc_irq_flag() || self.mapper.irq()
    }

    /// Run one CPU instruction (or interrupt sequence, or DMA cycle).
    #[inline]
    fn sample_hist(&mut self) {
        if self.hist_enabled && self.cycles & 0x1FF == 0 {
            self.hist.push(self.cpu.pc);
        }
        if self.pcwatch != 0 && self.cycles % self.pcwatch == 0 {
            eprintln!("pcwatch cyc={} pc={:04X} a={:02X} x={:02X} y={:02X} sp={:02X}",
                self.cycles, self.cpu.pc, self.cpu.a, self.cpu.x, self.cpu.y, self.cpu.sp);
        }
    }

    pub fn step(&mut self) {
        self.sample_hist();
        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_PC").is_ok() {
                if let Ok(w) = std::env::var("TRACE_WIN") {
                    let parts: Vec<u64> = w.split('-').map(|x| x.parse().unwrap()).collect();
                    if self.cycles >= parts[0] && self.cycles < parts[1] {
                        if std::env::var("TRACE_DEC").is_ok() && (self.cpu.pc == 0xF29D || self.cpu.pc == 0xB9D0) {
                            eprintln!("DEC entry @{} PC={:04X} A={:02X} X={:02X} Y={:02X} $9E={:02X} $9F={:02X} zp00={:02X} zp04={:02X}",
                                self.cycles, self.cpu.pc, self.cpu.a, self.cpu.x, self.cpu.y, self.ram[0x9E], self.ram[0x9F], self.ram[0], self.ram[4]);
                        }
                        if std::env::var("TRACE_SCAN").is_ok() && self.cpu.pc == 0x86ED {
                            let addr = ((self.ram[5] as u16) << 8 | self.ram[4] as u16).wrapping_add(self.cpu.y as u16);
                            eprintln!("scan end: ptr=${:04X} Y={:02X} addr=${:04X} rom={:02X} cnt={:02X}{:02X}",
                                ((self.ram[5] as u16) << 8) | self.ram[4] as u16, self.cpu.y, addr,
                                self.mapper.prg_read(addr), self.ram[1], self.ram[0]);
                        }
                        eprintln!("{:6} PC={:04X} A={:02X} X={:02X} Y={:02X} S={:02X} P={:02X}", self.cycles, self.cpu.pc, self.cpu.a, self.cpu.x, self.cpu.y, self.cpu.sp, self.cpu.p);
                    }
                }
                if self.hist.len() >= 96 {
                    self.hist.remove(0);
                }
                self.hist.push(self.cpu.pc);
            }
        }
        if self.oam_dma.is_some() {
            self.oam_dma_cycle();
            return;
        }
        self.cpu_step();
    }

    pub fn run_frame(&mut self) {
        if self.first_frame {
            self.first_frame = false;
            return;
        }
        self.ppu.frame_complete = false;
        let mut guard: u64 = 0;
        while !self.ppu.frame_complete {
            self.step();
            guard += 1;
            if guard > 40_000_000 {
                break;
            }
        }
    }

    // -------------------------------------------------------------- audio ---

    #[inline]
    fn audio_tick(&mut self) {
        self.audio_acc += SAMPLE_RATE as f64 / CPU_HZ;
        if self.audio_acc >= 1.0 {
            self.audio_acc -= 1.0;
            let m = self.apu.mix() as f64;
            #[allow(unused_unsafe)]
            let (s_scale, a1, a2, a3) = unsafe {
                (
                    AUDIO_SCALE,
                    hp_coef(HP1_HZ),
                    hp_coef(HP2_HZ),
                    lp_coef(LP_HZ),
                )
            };
            #[cfg(feature = "trace")]
            {
                if std::env::var("MIXDUMP").is_ok() {
                    self.mix_dump.push(m as f32);
                }
                if std::env::var("CHDUMP").is_ok() {
                    for c in 0..5 {
                        self.ch_dump[c].push(self.apu.channel_dac(c));
                    }
                    for c in 0..4 {
                        self.len_dump[c].push(self.apu.length_counter(c));
                    }
                    self.p1_dump.push(self.apu.pulse1_debug());
                }
            }
            // DC blocking high-pass filters approximating the NES analog stages.
            let y1 = a1 * (self.hp1_y + m - self.hp1_x);
            self.hp1_x = m;
            self.hp1_y = y1;
            let y2 = a2 * (self.hp2_y + y1 - self.hp2_x);
            self.hp2_x = y1;
            self.hp2_y = y2;
            let y3 = self.lp_y + a3 * (y2 - self.lp_y);
            self.lp_y = y3;
            #[cfg(feature = "trace")]
            {
                if std::env::var("DUMP_Y3").is_ok() {
                    self.y3_dump.push(y3 as f32);
                }
            }
            // Shift the sample through the FIR history and convolve.
            for i in 0..(FIR_TAPS - 1) {
                self.fir_hist[i] = self.fir_hist[i + 1];
            }
            self.fir_hist[FIR_TAPS - 1] = y3;
            let mut acc = 0.0;
            match fir_mode() {
                1 => {
                    for i in 0..FIR_TAPS {
                        acc += self.fir_hist[i] * FIR_COEFFS[i];
                    }
                }
                2 => {
                    // Linear interpolation between the previous and next
                    // output samples (the chain runs at the CPU rate).
                    let frac = 1.0 - self.audio_acc;
                    acc = self.prev_y3 * (1.0 - frac) + y3 * frac;
                }
                _ => acc = y3,
            }
            self.prev_y3 = y3;
            let v = (acc * s_scale).clamp(-32768.0, 32767.0) as i16;
            self.out.push(v);
        }
    }
}
