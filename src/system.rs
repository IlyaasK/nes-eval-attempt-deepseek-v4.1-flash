//! Machine: CPU + PPU + APU + cartridge glue, DMA, controllers, audio output.

use crate::apu::Apu;
use crate::cpu::Cpu;
use crate::mapper::Mapper;
use crate::ppu::Ppu;

pub const CPU_HZ: f64 = 1789772.7272727273;
pub const SAMPLE_RATE: u32 = 44100;

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
    fn addr(&self) -> u16 {
        match *self {
            Access::Read(a) => a,
            Access::Write(a, _) => a,
        }
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
    oam_dma: Option<OamDma>,

    /// Pending access to repeat on DMA halt cycles.
    halt_addr: u16,
    /// The reference's first `emu_run_frame` call returns without emulating
    /// anything, which shifts every subsequent frame boundary by one frame.
    first_frame: bool,
    #[cfg(feature = "trace")]
    pub hist: Vec<u16>,

    // Audio output
    pub out: Vec<i16>,
    audio_acc: f64,
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
            oam_dma: None,
            halt_addr: 0,
            first_frame: true,
            #[cfg(feature = "trace")]
            hist: Vec::new(),
            out: Vec::with_capacity(8192),
            audio_acc: 0.0,
        };
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
        self.oam_dma = None;
        self.halt_addr = 0;
        self.first_frame = true;
        self.out.clear();
        self.audio_acc = 0.0;
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
        let line = self.ppu.nmi_line();
        if line && !self.prev_nmi {
            self.cpu.nmi_pending = true;
        }
        self.prev_nmi = line;
        self.ppu.advance();
        result
    }

    /// A single CPU cycle without any of the DMA handling.
    #[inline]
    fn raw_cycle(&mut self, access: Option<Access>) -> u8 {
        let v = self.clock_dot(access);
        self.apu.clock(self.cycles);
        self.clock_dot(None);
        self.clock_dot(None);
        self.cycles += 1;
        self.audio_tick();
        v
    }

    #[inline]
    fn cpu_cycle(&mut self, access: Option<Access>) -> u8 {
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
        let val = self.raw_cycle(access);
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
            if (0x2000..=0x2007).contains(&addr) || addr == 0x4014 {
                eprintln!("W {:04X} <- {:02X} @{}", addr, val, self.cycles);
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
    pub fn step(&mut self) {
        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_PC").is_ok() {
                if let Ok(w) = std::env::var("TRACE_WIN") {
                    let parts: Vec<u64> = w.split('-').map(|x| x.parse().unwrap()).collect();
                    if self.cycles >= parts[0] && self.cycles < parts[1] {
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
            let s = self.apu.mix();
            let v = (s * 32767.0 - 16384.0).clamp(-32768.0, 32767.0) as i16;
            self.out.push(v);
        }
    }
}
