//! Cartridge mappers: NROM (0), MMC1 (1), UxROM (2), CNROM (3), MMC3 (4).

use crate::ines::*;

pub trait Mapper {
    fn as_any(&self) -> Option<&dyn core::any::Any> { None }
    fn prg_read(&mut self, addr: u16) -> u8;
    fn prg_write(&mut self, addr: u16, val: u8);
    fn chr_read(&mut self, addr: u16) -> u8;
    fn chr_write(&mut self, addr: u16, val: u8);
    fn mirroring(&self) -> u8;
    /// Called once per PPU dot with the current PPU address bus value.
    fn ppu_dot(&mut self, _addr: u16) {}
    /// Level-triggered IRQ line from the cartridge.
    fn irq(&self) -> bool {
        false
    }
    /// Console reset button (not power-on).
    fn reset(&mut self) {}
    fn prg_ram(&self) -> &[u8];
}

fn mirror_from_header(m: u8) -> u8 {
    m
}

// ---------------------------------------------------------------- helpers ---

pub struct PrgRam {
    pub data: Vec<u8>,
}

impl PrgRam {
    pub fn new(size: usize) -> PrgRam {
        PrgRam {
            data: vec![0u8; size.max(8192)],
        }
    }
}

struct ChrMem {
    mem: Vec<u8>,
    ram: bool,
}

impl ChrMem {
    fn new(cart: &Cart) -> ChrMem {
        if cart.chr_rom.is_empty() {
            ChrMem {
                mem: vec![0u8; cart.chr_ram_size.max(8192)],
                ram: true,
            }
        } else {
            ChrMem {
                mem: cart.chr_rom.clone(),
                ram: false,
            }
        }
    }
    fn read(&self, bank: usize, offset: usize) -> u8 {
        let size = self.mem.len();
        let idx = (bank + offset) % size;
        self.mem[idx]
    }
    fn write(&mut self, bank: usize, offset: usize, val: u8) {
        if self.ram {
            let size = self.mem.len();
            let idx = (bank + offset) % size;
            self.mem[idx] = val;
        }
    }
}

// ------------------------------------------------------------------- NROM ---

pub struct Nrom {
    prg: Vec<u8>,
    chr: ChrMem,
    ram: PrgRam,
    mirroring: u8,
}

impl Nrom {
    pub fn new(cart: &Cart) -> Nrom {
        Nrom {
            prg: cart.prg_rom.clone(),
            chr: ChrMem::new(cart),
            ram: PrgRam::new(cart.prg_ram_size),
            mirroring: mirror_from_header(cart.mirroring),
        }
    }
}

impl Mapper for Nrom {
    fn prg_read(&mut self, addr: u16) -> u8 {
        if addr >= 0x8000 {
            let n = self.prg.len();
            if n == 0 {
                return 0;
            }
            // 16 KiB NROM mirrors $C000-$FFFF onto $8000-$BFFF.
            let a = (addr as usize - 0x8000) % n;
            self.prg[a]
        } else {
            self.ram.data[(addr as usize - 0x6000) % self.ram.data.len()]
        }
    }
    fn prg_write(&mut self, addr: u16, val: u8) {
        if (0x6000..0x8000).contains(&addr) {
            let idx = (addr as usize - 0x6000) % self.ram.data.len();
            self.ram.data[idx] = val;
        }
    }
    fn chr_read(&mut self, addr: u16) -> u8 {
        self.chr.read(0, (addr as usize) & 0x1FFF)
    }
    fn chr_write(&mut self, addr: u16, val: u8) {
        self.chr.write(0, (addr as usize) & 0x1FFF, val)
    }
    fn mirroring(&self) -> u8 {
        self.mirroring
    }
    fn prg_ram(&self) -> &[u8] {
        &self.ram.data
    }
}

// ------------------------------------------------------------------- MMC1 ---

pub struct Mmc1 {
    prg: Vec<u8>,
    chr: ChrMem,
    ram: PrgRam,
    shift: u8,
    count: u8,
    control: u8,
    chr_bank0: u8,
    chr_bank1: u8,
    prg_bank: u8,
    mirroring: u8,
    ram_enabled: bool,
}

impl Mmc1 {
    pub fn new(cart: &Cart) -> Mmc1 {
        let mut m = Mmc1 {
            prg: cart.prg_rom.clone(),
            chr: ChrMem::new(cart),
            ram: PrgRam::new(cart.prg_ram_size),
            shift: 0,
            count: 0,
            control: 0x0C,
            chr_bank0: 0,
            chr_bank1: 0,
            prg_bank: 0,
            mirroring: mirror_from_header(cart.mirroring),
            ram_enabled: true,
        };
        m.apply_control();
        m
    }

    fn apply_control(&mut self) {
        // Control register: bits 0-1 mirroring, 2-3 PRG mode, 4 CHR mode
        self.mirroring = match self.control & 3 {
            0 => MIRROR_ONE_LOW,
            1 => MIRROR_ONE_HIGH,
            2 => MIRROR_VERTICAL,
            _ => MIRROR_HORIZONTAL,
        };
        self.ram_enabled = self.control & 0x10 == 0;
        if self.ram_enabled {
            // PRG-RAM enabled => writable
        }
    }

    fn prg_bank_for(&self, addr: u16) -> usize {
        let mode = (self.control >> 2) & 3;
        let n16 = self.prg.len() / 16384;
        let prg_bank = (self.prg_bank & 0x1F) as usize;
        let last = n16.saturating_sub(1);
        let bank = match mode {
            0 | 1 => match addr {
                // 32 KiB mode: ignore low bit
                0x8000..=0xFFFF => (prg_bank & !1) % n16.max(1),
                _ => 0,
            },
            2 => match addr {
                0x8000..=0xBFFF => 0,
                _ => prg_bank % n16.max(1),
            },
            _ => match addr {
                0x8000..=0xBFFF => prg_bank % n16.max(1),
                _ => last,
            },
        };
        if n16 == 0 {
            0
        } else {
            bank
        }
    }
}

impl Mapper for Mmc1 {
    fn prg_read(&mut self, addr: u16) -> u8 {
        if addr >= 0x8000 {
            let bank = self.prg_bank_for(addr);
            let off = (addr as usize) & 0x3FFF;
            let n = self.prg.len();
            if n == 0 {
                return 0;
            }
            let mut idx = bank * 16384 + off;
            while idx >= n {
                idx -= n;
            }
            self.prg[idx]
        } else {
            if self.ram_enabled {
                self.ram.data[(addr as usize - 0x6000) % self.ram.data.len()]
            } else {
                0xFF
            }
        }
    }

    fn prg_write(&mut self, addr: u16, val: u8) {
        if addr >= 0x8000 {
            if val & 0x80 != 0 {
                self.shift = 0;
                self.count = 0;
                self.control |= 0x0C;
                self.apply_control();
                return;
            }
            let bit = val & 1;
            self.shift = (self.shift >> 1) | (bit << 4);
            self.count += 1;
            if self.count == 5 {
                let v = self.shift & 0x1F;
                match (addr >> 13) & 3 {
                    0 => {
                        self.control = v;
                        self.apply_control();
                    }
                    1 => self.chr_bank0 = v,
                    2 => self.chr_bank1 = v,
                    _ => {
                        self.prg_bank = v;
                        if (self.control >> 2) & 3 < 2 {
                            self.prg_bank &= !1;
                        }
                    }
                }
                self.shift = 0;
                self.count = 0;
            }
        } else if self.ram_enabled {
            let idx = (addr as usize - 0x6000) % self.ram.data.len();
            self.ram.data[idx] = val;
        }
    }

    fn chr_read(&mut self, addr: u16) -> u8 {
        let a = addr as usize & 0x1FFF;
        let chr_mode = (self.control >> 4) & 1;
        let bank = if chr_mode == 0 {
            match a {
                0x0000..=0x0FFF => ((self.chr_bank0 & 0x1E) as usize) * 4096,
                _ => ((self.chr_bank1 & 0x1E) as usize) * 4096,
            }
        } else {
            match a {
                0x0000..=0x0FFF => (self.chr_bank0 as usize) * 4096,
                _ => (self.chr_bank1 as usize) * 4096,
            }
        };
        self.chr.read(bank, a & 0x0FFF)
    }

    fn chr_write(&mut self, addr: u16, val: u8) {
        let a = addr as usize & 0x1FFF;
        let chr_mode = (self.control >> 4) & 1;
        let bank = if chr_mode == 0 {
            match a {
                0x0000..=0x0FFF => ((self.chr_bank0 & 0x1E) as usize) * 4096,
                _ => ((self.chr_bank1 & 0x1E) as usize) * 4096,
            }
        } else {
            match a {
                0x0000..=0x0FFF => (self.chr_bank0 as usize) * 4096,
                _ => (self.chr_bank1 as usize) * 4096,
            }
        };
        self.chr.write(bank, a & 0x0FFF, val)
    }

    fn mirroring(&self) -> u8 {
        self.mirroring
    }

    fn reset(&mut self) {
        self.shift = 0;
        self.count = 0;
        self.control |= 0x0C;
        self.apply_control();
    }

    fn prg_ram(&self) -> &[u8] {
        &self.ram.data
    }
}

// ------------------------------------------------------------------ UxROM ---

pub struct Uxrom {
    prg: Vec<u8>,
    chr: ChrMem,
    ram: PrgRam,
    mirroring: u8,
    bank: usize,
    bus_conflicts: bool,
}

impl Uxrom {
    pub fn new(cart: &Cart) -> Uxrom {
        Uxrom {
            prg: cart.prg_rom.clone(),
            chr: ChrMem::new(cart),
            ram: PrgRam::new(cart.prg_ram_size),
            mirroring: mirror_from_header(cart.mirroring),
            bank: 0,
            bus_conflicts: true,
        }
    }
}

impl Mapper for Uxrom {
    fn prg_read(&mut self, addr: u16) -> u8 {
        if addr >= 0x8000 {
            let n16 = (self.prg.len() / 16384).max(1);
            let bank = if addr < 0xC000 { self.bank } else { n16 - 1 };
            let off = (addr as usize) & 0x3FFF;
            let mut idx = (bank % n16) * 16384 + off;
            if idx >= self.prg.len() {
                idx %= self.prg.len().max(1);
            }
            self.prg[idx]
        } else {
            self.ram.data[(addr as usize - 0x6000) % self.ram.data.len()]
        }
    }
    fn prg_write(&mut self, addr: u16, val: u8) {
        if addr >= 0x8000 {
            let mut v = val;
            if self.bus_conflicts {
                let n16 = (self.prg.len() / 16384).max(1);
                let off = (addr as usize) & 0x3FFF;
                let rom_val = self.prg[((self.bank % n16) * 16384 + off) % self.prg.len()];
                v &= rom_val;
            }
            self.bank = (v & 0x0F) as usize;
        } else if (0x6000..0x8000).contains(&addr) {
            let idx = (addr as usize - 0x6000) % self.ram.data.len();
            self.ram.data[idx] = val;
        }
    }
    fn chr_read(&mut self, addr: u16) -> u8 {
        self.chr.read(0, (addr as usize) & 0x1FFF)
    }
    fn chr_write(&mut self, addr: u16, val: u8) {
        self.chr.write(0, (addr as usize) & 0x1FFF, val)
    }
    fn mirroring(&self) -> u8 {
        self.mirroring
    }
    fn prg_ram(&self) -> &[u8] {
        &self.ram.data
    }
}

// ------------------------------------------------------------------ CNROM ---

pub struct Cnrom {
    prg: Vec<u8>,
    chr: ChrMem,
    ram: PrgRam,
    mirroring: u8,
    bank: usize,
    bus_conflicts: bool,
}

impl Cnrom {
    pub fn new(cart: &Cart) -> Cnrom {
        Cnrom {
            prg: cart.prg_rom.clone(),
            chr: ChrMem::new(cart),
            ram: PrgRam::new(cart.prg_ram_size),
            mirroring: mirror_from_header(cart.mirroring),
            bank: 0,
            bus_conflicts: true,
        }
    }
}

impl Mapper for Cnrom {
    fn prg_read(&mut self, addr: u16) -> u8 {
        if addr >= 0x8000 {
            let n = self.prg.len();
            if n == 0 {
                return 0;
            }
            let mut idx = (addr as usize - 0x8000) % n;
            if idx >= n {
                idx -= n;
            }
            self.prg[idx]
        } else {
            self.ram.data[(addr as usize - 0x6000) % self.ram.data.len()]
        }
    }
    fn prg_write(&mut self, addr: u16, val: u8) {
        if addr >= 0x8000 {
            let mut v = val;
            if self.bus_conflicts {
                let n = self.prg.len();
                let rom_val = self.prg[(addr as usize - 0x8000) % n.max(1)];
                v &= rom_val;
            }
            self.bank = (v & 0x03) as usize;
        } else if (0x6000..0x8000).contains(&addr) {
            let idx = (addr as usize - 0x6000) % self.ram.data.len();
            self.ram.data[idx] = val;
        }
    }
    fn chr_read(&mut self, addr: u16) -> u8 {
        let n = self.chr.mem.len() / 8192;
        let bank = if n == 0 { 0 } else { (self.bank % n) * 8192 };
        self.chr.read(bank, (addr as usize) & 0x1FFF)
    }
    fn chr_write(&mut self, addr: u16, val: u8) {
        let n = self.chr.mem.len() / 8192;
        let bank = if n == 0 { 0 } else { (self.bank % n) * 8192 };
        self.chr.write(bank, (addr as usize) & 0x1FFF, val)
    }
    fn mirroring(&self) -> u8 {
        self.mirroring
    }
    fn prg_ram(&self) -> &[u8] {
        &self.ram.data
    }
}

// ------------------------------------------------------------------- MMC3 ---

pub struct Mmc3 {
    prg: Vec<u8>,
    chr: ChrMem,
    ram: PrgRam,
    mirroring: u8,
    bank_select: u8,
    banks: [u8; 8],
    prg_mode: bool,
    chr_mode: bool,
    ram_enabled: bool,
    ram_writable: bool,
    pub irq_latch: u8,
    pub irq_counter: u8,
    pub irq_reload: bool,
    pub irq_enabled: bool,
    pub irq_pending: bool,
    a12_low: bool,
    low_dots: u32,
    #[cfg(feature = "trace")]
    pub dot_count: u64,
    #[cfg(feature = "trace")]
    pub clock_count: u64,
    #[cfg(feature = "trace")]
    pub rise_count: u64,
    #[cfg(feature = "trace")]
    pub rises: Vec<(u64, u32)>,
}

/// Minimum number of PPU dots A12 must stay low for a rising edge to clock the
/// IRQ counter (three M2 falling edges on real hardware).
static mut A12_LOW_DOTS: u32 = 9;
#[cfg(feature = "trace")]
fn a12_low_dots() -> u32 {
    unsafe {
        if let Ok(v) = std::env::var("A12_LOW_DOTS") {
            if let Ok(n) = v.parse::<u32>() {
                A12_LOW_DOTS = n;
            }
        }
        A12_LOW_DOTS
    }
}
#[cfg(not(feature = "trace"))]
fn a12_low_dots() -> u32 { unsafe { A12_LOW_DOTS } }

impl Mmc3 {
    pub fn new(cart: &Cart) -> Mmc3 {
        Mmc3 {
            prg: cart.prg_rom.clone(),
            chr: ChrMem::new(cart),
            ram: PrgRam::new(cart.prg_ram_size),
            mirroring: mirror_from_header(cart.mirroring),
            bank_select: 0,
            banks: [0; 8],
            prg_mode: false,
            chr_mode: false,
            ram_enabled: true,
            ram_writable: true,
            irq_latch: 0,
            irq_counter: 0,
            irq_reload: false,
            irq_enabled: false,
            irq_pending: false,
            a12_low: true,
            low_dots: 0,
            #[cfg(feature = "trace")]
            dot_count: 0,
            #[cfg(feature = "trace")]
            clock_count: 0,
            #[cfg(feature = "trace")]
            rise_count: 0,
            #[cfg(feature = "trace")]
            rises: Vec::new(),
        }
    }

    fn prg_bank(&self, addr: u16) -> usize {
        let n8 = (self.prg.len() / 8192).max(1);
        let last = n8 - 1;
        let r6 = (self.banks[6] as usize) % n8;
        let r7 = (self.banks[7] as usize) % n8;
        match (self.prg_mode, addr) {
            (false, 0x8000..=0x9FFF) => r6,
            (false, 0xA000..=0xBFFF) => r7,
            (false, 0xC000..=0xDFFF) => last - 1,
            (false, _) => last,
            (true, 0x8000..=0x9FFF) => last - 1,
            (true, 0xA000..=0xBFFF) => r7,
            (true, 0xC000..=0xDFFF) => r6,
            (true, _) => last,
        }
    }

    fn chr_bank(&self, addr: usize) -> usize {
        let a = addr & 0x1FFF;
        let r0 = ((self.banks[0] & 0xFE) as usize) * 1024;
        let r1 = ((self.banks[1] & 0xFE) as usize) * 1024;
        let b = |i: usize| (self.banks[i] as usize) * 1024;
        if !self.chr_mode {
            // 2 KiB at $0000 (R0), 2 KiB at $0800 (R1), then 1 KiB R2..R5
            match a {
                0x0000..=0x07FF => r0 + a,
                0x0800..=0x0FFF => r1 + (a - 0x0800),
                0x1000..=0x13FF => b(2) + (a - 0x1000),
                0x1400..=0x17FF => b(3) + (a - 0x1400),
                0x1800..=0x1BFF => b(4) + (a - 0x1800),
                _ => b(5) + (a - 0x1C00),
            }
        } else {
            // 1 KiB R2..R5 at $0000-$0FFF, 2 KiB R0 at $1000, 2 KiB R1 at $1800
            match a {
                0x0000..=0x03FF => b(2) + a,
                0x0400..=0x07FF => b(3) + (a - 0x0400),
                0x0800..=0x0BFF => b(4) + (a - 0x0800),
                0x0C00..=0x0FFF => b(5) + (a - 0x0C00),
                0x1000..=0x17FF => r0 + (a - 0x1000),
                _ => r1 + (a - 0x1800),
            }
        }
    }

    fn clock_irq(&mut self) {
        #[cfg(feature = "trace")]
        {
            self.clock_count += 1;
        }
        if self.irq_counter == 0 || self.irq_reload {
            self.irq_counter = self.irq_latch;
            self.irq_reload = false;
        } else {
            self.irq_counter -= 1;
        }
        // "Normal" (Sharp) revision: the IRQ is triggered while the counter is
        // zero, after the reload/decrement step.
        if self.irq_counter == 0 && self.irq_enabled {
            self.irq_pending = true;
        }
    }
}

impl Mapper for Mmc3 {
    fn as_any(&self) -> Option<&dyn core::any::Any> { Some(self) }
    fn prg_read(&mut self, addr: u16) -> u8 {
        if addr >= 0x8000 {
            let bank = self.prg_bank(addr);
            let off = (addr as usize) & 0x1FFF;
            let n = self.prg.len();
            if n == 0 {
                return 0;
            }
            let mut idx = bank * 8192 + off;
            while idx >= n {
                idx -= n;
            }
            self.prg[idx]
        } else if addr >= 0x6000 {
            if self.ram_enabled {
                self.ram.data[(addr as usize - 0x6000) % self.ram.data.len()]
            } else {
                0
            }
        } else {
            0
        }
    }

    fn prg_write(&mut self, addr: u16, val: u8) {
        match addr {
            0x8000..=0x9FFE if addr & 1 == 0 => {
                self.bank_select = val;
                self.prg_mode = val & 0x40 != 0;
                self.chr_mode = val & 0x80 != 0;
            }
            0x8001..=0x9FFF if addr & 1 == 1 => {
                let r = (self.bank_select & 7) as usize;
                self.banks[r] = val;
            }
            0xA000..=0xBFFE if addr & 1 == 0 => {
                self.mirroring = if val & 1 != 0 {
                    MIRROR_HORIZONTAL
                } else {
                    MIRROR_VERTICAL
                };
            }
            0xA001..=0xBFFF if addr & 1 == 1 => {
                self.ram_enabled = val & 0x80 != 0;
                self.ram_writable = val & 0x40 != 0;
            }
            0xC000..=0xDFFE if addr & 1 == 0 => {
                self.irq_latch = val;
            }
            0xC001..=0xDFFF if addr & 1 == 1 => {
                self.irq_reload = true;
            }
            0xE000..=0xFFFE if addr & 1 == 0 => {
                self.irq_enabled = false;
                self.irq_pending = false;
            }
            0xE001..=0xFFFF if addr & 1 == 1 => {
                self.irq_enabled = true;
            }
            _ => {}
        }
        if (0x6000..0x8000).contains(&addr) && self.ram_writable {
            let idx = (addr as usize - 0x6000) % self.ram.data.len();
            self.ram.data[idx] = val;
        }
    }

    fn chr_read(&mut self, addr: u16) -> u8 {
        let idx = self.chr_bank(addr as usize);
        let n = self.chr.mem.len();
        self.chr.mem[idx % n.max(1)]
    }

    fn chr_write(&mut self, addr: u16, val: u8) {
        let idx = self.chr_bank(addr as usize);
        let n = self.chr.mem.len();
        if self.chr.ram && n > 0 {
            self.chr.mem[idx % n] = val;
        }
    }

    fn mirroring(&self) -> u8 {
        self.mirroring
    }

    fn ppu_dot(&mut self, addr: u16) {
        #[cfg(feature = "trace")]
        {
            self.dot_count += 1;
        }
        let a12 = (addr & 0x1000) != 0;
        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_MMC3").is_ok() && self.dot_count > 89000 && self.dot_count < 89060 {
                eprintln!("dot {} addr={:04X} a12={} low_dots={}", self.dot_count, addr, a12 as u8, self.low_dots);
            }
        }
        if a12 {
            #[cfg(feature = "trace")]
            {
                if std::env::var("TRACE_A12").is_ok() {
                    eprintln!("A12RISE dots={} low={} line={} irq={}", self.dot_count, self.low_dots,
                        self.dot_count / 341, self.irq_pending);
                }
            }
            if self.a12_low && self.low_dots >= a12_low_dots() {
                #[cfg(feature = "trace")]
                {
                    if std::env::var("TRACE_A12").is_ok() {
                        self.rises.push((self.dot_count, self.low_dots));
                    }
                    self.rise_count += 1;
                }
                self.clock_irq();
            }
            self.a12_low = false;
            self.low_dots = 0;
        } else {
            self.a12_low = true;
            self.low_dots = self.low_dots.saturating_add(1);
        }
    }

    fn irq(&self) -> bool {
        self.irq_pending
    }

    fn reset(&mut self) {
        self.irq_pending = false;
        self.irq_enabled = false;
        self.irq_reload = true;
    }

    fn prg_ram(&self) -> &[u8] {
        &self.ram.data
    }
}

pub fn make_mapper(cart: &Cart) -> Option<Box<dyn Mapper>> {
    Some(match cart.mapper {
        0 => Box::new(Nrom::new(cart)),
        1 => Box::new(Mmc1::new(cart)),
        2 => Box::new(Uxrom::new(cart)),
        3 => Box::new(Cnrom::new(cart)),
        4 => Box::new(Mmc3::new(cart)),
        _ => return None,
    })
}

// ------------------------------------------------------------- null map ---

pub struct Null;

impl Mapper for Null {
    fn prg_read(&mut self, _addr: u16) -> u8 {
        0
    }
    fn prg_write(&mut self, _addr: u16, _val: u8) {}
    fn chr_read(&mut self, _addr: u16) -> u8 {
        0
    }
    fn chr_write(&mut self, _addr: u16, _val: u8) {}
    fn mirroring(&self) -> u8 {
        MIRROR_HORIZONTAL
    }
    fn prg_ram(&self) -> &[u8] {
        &[]
    }
}
