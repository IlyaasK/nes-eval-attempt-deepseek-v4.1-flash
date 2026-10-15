//! Cycle-accurate RP2C02 PPU.
//!
//! Timing model (0-based dot indices within a 341-dot scanline):
//!  * visible scanlines 0-239, post-render 240, vblank 241-260, pre-render 261.
//!  * VBL flag set at (241, 1), cleared at (261, 1).
//!  * pixel x is produced at dot x+1 (dots 1..=256).
//!  * background fetch windows start at dots 0, 8, ... 328, 336
//!    (nametable @ +0, attribute @ +2, pattern low @ +4, pattern high @ +6).
//!  * the shift registers shift at dots 1..=256 and 320..=336, and are reloaded
//!    (low byte) at the end of every dot that is a multiple of 8.
//!  * coarse X is incremented at dots 7, 15, ... 255 and 327, 335.
//!  * sprite evaluation at dots 64..=255, sprite fetches at dots 256..=319.

use crate::ines::*;
use crate::mapper::Mapper;

#[derive(Clone, Copy, Default)]
pub struct SpriteUnit {
    pub x: u8,
    pub y: u8,
    pub attr: u8,
    pub lo: u8,
    pub hi: u8,
}

#[derive(Clone, Copy, PartialEq)]
enum EvMode {
    /// Evaluating OAM[n][0] as a Y coordinate.
    CheckY,
    /// Copying byte `m` of sprite `n` into the secondary OAM.
    CopyByte,
    /// The (buggy) sprite overflow scan.
    OverflowScan,
    /// All 64 sprites evaluated: keep failing to copy until HBlank.
    Done,
}

pub struct Ppu {
    pub fb: Box<[u16; 61440]>,

    pub vram: [u8; 4096],
    pub palette: [u8; 32],
    pub oam: [u8; 256],

    // Registers
    pub ctrl: u8,
    pub mask: u8,
    pub status: u8,
    pub oam_addr: u8,
    pub v: u16,
    pub t: u16,
    pub fine_x: u8,
    pub w: bool,
    read_buffer: u8,
    /// PPU open bus / decay register.
    pub open_bus: u8,

    // Timing
    pub scanline: u16,
    pub dot: u16,
    pub frame: u64,
    pub total_dots: u64,
    pub odd_frame: bool,
    pub frame_complete: bool,

    // Background pipeline
    bg_latch_nt: u8,
    bg_latch_at: u8,
    bg_latch_lo: u8,
    bg_latch_hi: u8,
    bg_shift_lo: u16,
    bg_shift_hi: u16,
    at_latch: u8,
    at_shift_lo: u8,
    at_shift_hi: u8,

    // Sprite pipeline
    pub sec_oam: [u8; 32],
    sprite_count: u8,
    sprites: [SpriteUnit; 8],

    // Sprite evaluation state machine
    ev_n: u8,
    ev_m: u8,
    ev_mode: EvMode,

    /// Set when a $2002 read happened exactly one dot before the VBL set.
    vbl_suppress: bool,
    /// Set when a $2002 read lands within a couple of PPU clocks of the VBL set:
    /// the NMI is not generated for that frame.
    nmi_suppress: bool,
    /// Last value written to $2007 (used for palette read back-bus bits).
    pub oam_addr_write_during_render: bool,
    /// Current value driven on the PPU address bus (for mapper A12 tracking).
    bus_addr: u16,
    /// Debug: sprite unit 0 state at the end of the last frame.
    #[cfg(feature = "trace")]
    pub dbg_sp0: SpriteUnit,
    /// Debug: number of opaque sprite pixels emitted in the last frame.
    #[cfg(feature = "trace")]
    pub dbg_sprite_px: u32,
}

impl Ppu {
    pub fn new() -> Ppu {
        Ppu {
            fb: Box::new([0u16; 61440]),
            vram: [0; 4096],
            palette: [0; 32],
            oam: [0; 256],
            ctrl: 0,
            mask: 0,
            status: 0,
            oam_addr: 0,
            v: 0,
            t: 0,
            fine_x: 0,
            w: false,
            read_buffer: 0,
            open_bus: 0,
            scanline: 0,
            dot: 0,
            frame: 0,
            total_dots: 0,
            odd_frame: true,
            frame_complete: false,
            bg_latch_nt: 0,
            bg_latch_at: 0,
            bg_latch_lo: 0,
            bg_latch_hi: 0,
            bg_shift_lo: 0,
            bg_shift_hi: 0,
            at_latch: 0,
            at_shift_lo: 0,
            at_shift_hi: 0,
            sec_oam: [0xFF; 32],
            sprite_count: 0,
            sprites: [SpriteUnit::default(); 8],
            ev_n: 0,
            ev_m: 0,
            ev_mode: EvMode::CheckY,
            vbl_suppress: false,
            nmi_suppress: false,
            oam_addr_write_during_render: false,
            bus_addr: 0,
            #[cfg(feature = "trace")]
            dbg_sp0: SpriteUnit::default(),
            #[cfg(feature = "trace")]
            dbg_sprite_px: 0,
        }
    }

    pub fn reset(&mut self) {
        self.ctrl = 0;
        self.mask = 0;
        self.status = 0;
        self.oam_addr = 0;
        self.v = 0;
        self.t = 0;
        self.fine_x = 0;
        self.w = false;
        self.read_buffer = 0;
        self.open_bus = 0;
        self.scanline = 0;
        self.dot = 0;
        self.frame = 0;
        self.odd_frame = false;
        self.frame_complete = false;
        self.bg_latch_nt = 0;
        self.bg_latch_at = 0;
        self.bg_latch_lo = 0;
        self.bg_latch_hi = 0;
        self.bg_shift_lo = 0;
        self.bg_shift_hi = 0;
        self.at_latch = 0;
        self.at_shift_lo = 0;
        self.at_shift_hi = 0;
        self.sec_oam = [0xFF; 32];
        self.sprite_count = 0;
        self.sprites = [SpriteUnit::default(); 8];
        self.ev_mode = EvMode::CheckY;
        self.vbl_suppress = false;
        self.nmi_suppress = false;
        for p in self.fb.iter_mut() {
            *p = 0;
        }
        self.vram = [0; 4096];
        self.palette = [0; 32];
        self.oam = [0; 256];
    }

    #[inline]
    pub fn rendering_enabled(&self) -> bool {
        self.mask & 0x18 != 0
    }

    #[inline]
    pub fn nmi_line(&self) -> bool {
        self.status & 0x80 != 0 && self.ctrl & 0x80 != 0 && !self.nmi_suppress
    }

    // ------------------------------------------------------------ memory ---

    fn mirror_addr(&self, addr: u16, mapper: &dyn Mapper) -> usize {
        let a = (addr & 0x0FFF) as usize;
        let nt = a >> 10;
        let off = a & 0x03FF;
        match mapper.mirroring() {
            MIRROR_HORIZONTAL => ((nt >> 1) & 1) * 1024 + off,
            MIRROR_VERTICAL => (nt & 1) * 1024 + off,
            MIRROR_FOUR => nt * 1024 + off,
            MIRROR_ONE_LOW => off,
            _ => 1024 + off,
        }
    }

    #[inline]
    pub fn vram_read(&mut self, addr: u16, mapper: &mut dyn Mapper) -> u8 {
        self.bus_addr = addr & 0x3FFF;
        let a = addr & 0x3FFF;
        if a < 0x2000 {
            mapper.chr_read(a)
        } else if a < 0x3F00 {
            let idx = self.mirror_addr(a, mapper);
            self.vram[idx & 4095]
        } else {
            let idx = Self::pal_index(a);
            self.palette[idx] & 0x3F
        }
    }

    #[inline]
    pub fn vram_write(&mut self, addr: u16, val: u8, mapper: &mut dyn Mapper) {
        if self.rendering_enabled() && self.scanline < 240 && self.dot < 256 {
            // Writes to VRAM during rendering cannot modify nametables reliably;
            // the data is written to the address currently on the bus.
        }
        let a = addr & 0x3FFF;
        if a < 0x2000 {
            mapper.chr_write(a, val);
        } else if a < 0x3F00 {
            let idx = self.mirror_addr(a, mapper);
            self.vram[idx & 4095] = val;
        } else {
            let idx = Self::pal_index(a);
            self.palette[idx] = val & 0x3F;
        }
    }

    #[inline]
    fn pal_index(a: u16) -> usize {
        let idx = ((a - 0x3F00) & 0x1F) as usize;
        if idx >= 0x10 && idx % 4 == 0 {
            idx - 0x10
        } else {
            idx
        }
    }

    // --------------------------------------------------------- registers ---

    pub fn read_register(&mut self, addr: u16, open_bus: u8, mapper: &mut dyn Mapper) -> u8 {
        match addr & 7 {
            2 => {
                let mut result = (self.status & 0xE0) | (self.open_bus & 0x1F);
                #[cfg(feature = "trace")]
                {
                    if std::env::var("TRACE_RD2002").is_ok() && (self.scanline == 240 || self.scanline == 241) {
                        eprintln!("$2002 read sl={} dot={} status={:02X}", self.scanline, self.dot, self.status);
                    }
                }
                // A read exactly one PPU clock before the VBL set suppresses the
                // flag for the whole frame (and the NMI is not generated).
                if self.scanline == 240 && self.dot == 340 {
                    self.vbl_suppress = true;
                    self.nmi_suppress = true;
                    result &= 0x7F;
                }
                self.status &= !0x80;
                self.w = false;
                let _ = open_bus;
                result
            }
            4 => {
                if self.rendering_enabled()
                    && (self.scanline <= 239 || self.scanline == 261)
                    && self.dot < 64
                {
                    return 0xFF;
                }
                self.oam[self.oam_addr as usize]
            }
            7 => {
                let addr = self.v & 0x3FFF;
                self.bus_addr = addr;
                if addr & 0x3F00 == 0x3F00 {
                    let idx = Self::pal_index(addr);
                    let pal = self.palette[idx] & 0x3F;
                    self.read_buffer = self.vram_read(addr - 0x1000, mapper);
                    self.open_bus = (self.open_bus & 0xC0) | pal;
                    self.increment_vram_addr();
                    return pal | (self.open_bus & 0xC0);
                }
                let data = self.vram_read(addr, mapper);
                let result = self.read_buffer;
                self.read_buffer = data;
                self.increment_vram_addr();
                result
            }
            _ => self.open_bus,
        }
    }

    #[inline]
    fn increment_vram_addr(&mut self) {
        let inc = if self.ctrl & 0x04 != 0 { 32 } else { 1 };
        self.v = self.v.wrapping_add(inc) & 0x7FFF;
    }

    pub fn write_register(&mut self, addr: u16, val: u8, mapper: &mut dyn Mapper, warmup: bool) {
        match addr & 7 {
            0 => {
                if warmup {
                    return;
                }
                self.ctrl = val;
                self.t = (self.t & 0xF3FF) | (((val as u16) & 0x03) << 10);
            }
            1 => {
                if warmup {
                    return;
                }
                self.mask = val;
            }
            3 => {
                self.oam_addr = val;
            }
            4 => {
                self.oam[self.oam_addr as usize] = val;
                self.oam_addr = self.oam_addr.wrapping_add(1);
            }
            5 => {
                if warmup {
                    return;
                }
                if !self.w {
                    self.fine_x = val & 0x07;
                    self.t = (self.t & 0x7FE0) | ((val as u16) >> 3);
                    self.w = true;
                } else {
                    self.t = (self.t & 0x0C1F) | (((val as u16) & 0x07) << 12);
                    self.t = (self.t & 0x7FE0) | ((val as u16) >> 3);
                    self.w = false;
                }
            }
            6 => {
                if warmup {
                    return;
                }
                if !self.w {
                    self.t = (self.t & 0x00FF) | (((val as u16) & 0x3F) << 8);
                    self.t &= 0x7FFF;
                    self.w = true;
                } else {
                    self.t = (self.t & 0x7F00) | (val as u16);
                    self.v = self.t;
                    self.w = false;
                }
            }
            7 => {
                self.open_bus = val;
                let addr = self.v & 0x3FFF;
                self.vram_write(addr, val, mapper);
                self.increment_vram_addr();
            }
            _ => {}
        }
    }

    // ------------------------------------------------------------ timing ---

    pub fn process_dot(&mut self, mapper: &mut dyn Mapper) {
        let sl = self.scanline;
        let dot = self.dot;
        // The mapper sees the PPU address bus on every dot (MMC3 A12 clocking).
        if self.rendering_enabled() {
            let a = self.bus_addr;
            mapper.ppu_dot(a);
        } else {
            let a = self.v & 0x3FFF;
            self.bus_addr = a;
            mapper.ppu_dot(a);
        }

        if sl == 241 && dot == 0 {
            if !self.vbl_suppress {
                self.status |= 0x80;
            }
            self.vbl_suppress = false;
        }
        if sl == 261 && dot == 0 {
            // Cleared exactly 6820 PPU clocks (20 scanlines) after the set.
            self.status &= !0xE0;
            self.nmi_suppress = false;
        }

        let rendering = self.rendering_enabled();
        let active = sl <= 239 || sl == 261;

        if active {
            if rendering {
                // ------------------------------------------------ fetches ---
                let in_bg_fetch = dot <= 255 || (320..=335).contains(&dot);
                let in_sprite_fetch = (256..=319).contains(&dot);
                if in_bg_fetch {
                    match dot & 7 {
                        0 => {
                            let a = 0x2000 | (self.v & 0x0FFF);
                            self.bg_latch_nt = self.vram_read(a, mapper);
                        }
                        2 => {
                            let a = 0x23C0
                                | (self.v & 0x0C00)
                                | ((self.v >> 4) & 0x38)
                                | ((self.v >> 2) & 0x07);
                            let at = self.vram_read(a, mapper);
                            let shift = ((self.v >> 4) & 4) | (self.v & 2);
                            self.at_latch = (at >> shift) & 3;
                        }
                        4 => {
                            let fine_y = (self.v >> 12) & 7;
                            let pt = if self.ctrl & 0x10 != 0 { 0x1000 } else { 0 };
                            let a = pt | ((self.bg_latch_nt as u16) << 4) | fine_y;
                            self.bg_latch_lo = self.vram_read(a, mapper);
                        }
                        6 => {
                            let fine_y = (self.v >> 12) & 7;
                            let pt = if self.ctrl & 0x10 != 0 { 0x1000 } else { 0 };
                            let a = pt | ((self.bg_latch_nt as u16) << 4) | fine_y | 8;
                            self.bg_latch_hi = self.vram_read(a, mapper);
                        }
                        7 => {
                            if dot <= 255 || dot >= 327 {
                                self.increment_x();
                            }
                        }
                        _ => {}
                    }
                } else if in_sprite_fetch {
                    let idx = ((dot - 256) / 8) as usize;
                    match (dot - 256) & 7 {
                        0 | 1 => {
                            let a = 0x2000 | (self.v & 0x0FFF);
                            let _ = self.vram_read(a, mapper);
                        }
                        2 | 3 => {
                            let a = 0x2000 | (self.v & 0x0FFF);
                            let _ = self.vram_read(a, mapper);
                            if dot & 7 == 2 {
                                self.sprites[idx].attr = self.sec_oam[idx * 4 + 2];
                                self.sprites[idx].y = self.sec_oam[idx * 4];
                            } else {
                                self.sprites[idx].x = self.sec_oam[idx * 4 + 3];
                            }
                        }
                        4 => {
                            let (a, _) = self.sprite_pattern_addr(idx, mapper);
                            let _ = a;
                        }
                        5 => {
                            let (a, _) = self.sprite_pattern_addr(idx, mapper);
                            let v = self.vram_read(a, mapper);
                            #[cfg(feature = "trace")]
                            {
                                if std::env::var("TRACE_SPR").is_ok() && idx == 0 && self.scanline < 60 {
                                    eprintln!("fetch lo sl={} dot={} addr={:04X} val={:02X} sec0={:02X}{:02X}{:02X}{:02X}",
                                        self.scanline, dot, a, v, self.sec_oam[0], self.sec_oam[1], self.sec_oam[2], self.sec_oam[3]);
                                }
                            }
                            self.sprites[idx].lo = v;
                        }
                        6 => {
                            let (a, _) = self.sprite_pattern_addr(idx, mapper);
                            let _ = a;
                        }
                        _ => {
                            let (a, _) = self.sprite_pattern_addr(idx, mapper);
                            // The high bitplane is 8 bytes above the low one.
                            self.sprites[idx].hi = self.vram_read(a + 8, mapper);
                        }
                    }
                }

                // --------------------------------------------------- pixel ---
                if sl <= 239 && (1..=256).contains(&dot) {
                    #[cfg(feature = "trace")]
                    {
                        if std::env::var("TRACE_SPR").is_ok() && dot == 100 && sl < 60 {
                            let s0 = &self.sprites[0];
                            eprintln!("render sl={} dot={} sp0 x={} attr={:02X} lo={:02X} hi={:02X} sec0={:02X}{:02X}{:02X}{:02X}",
                                sl, dot, s0.x, s0.attr, s0.lo, s0.hi, self.sec_oam[0], self.sec_oam[1], self.sec_oam[2], self.sec_oam[3]);
                        }
                    }
                    self.render_pixel(mapper);
                }
                // The shift registers also shift during the prefetch phase.
                if (320..=336).contains(&dot) {
                    self.shift_registers();
                }

                // -------------------------------------------- reload/transfer
                if (dot & 7 == 0 && (8..=256).contains(&dot))
                    || dot == 320
                    || dot == 328
                    || dot == 336
                {
                    self.load_shifters();
                }

                // -------------------------------------------- sprite eval ----
                if sl <= 239 && (64..=255).contains(&dot) && dot & 1 == 0 {
                    self.evaluate_sprite_step();
                }
                if sl <= 239 && dot == 0 {
                    // secondary OAM clear happens on dots 0..=63 two bytes per dot
                    self.sprite_count = 0;
                }
                if sl <= 239 && (0..=63).contains(&dot) && dot & 1 == 1 {
                    let base = ((dot - 1) as usize) & 0x1F;
                    self.sec_oam[base] = 0xFF;
                    self.sec_oam[(base + 1) & 0x1F] = 0xFF;
                }

                // ------------------------------------------- vertical bits ---
                if dot == 256 && sl <= 239 || dot == 256 && sl == 261 {
                    self.increment_y();
                }
                if dot == 257 {
                    self.copy_x();
                }
                if sl == 261 && (280..=304).contains(&dot) {
                    self.copy_y();
                }
            } else {
                // Rendering disabled: output the backdrop (or palette-RAM override).
                if sl <= 239 && (1..=256).contains(&dot) {
                    let x = (dot - 1) as usize;
                    let colour = self.backdrop_colour();
                    let emph = ((self.mask >> 5) & 7) as u16;
                    self.fb[(sl as usize) * 256 + x] = (emph << 6) | colour;
                }
            }
        }
    }

    #[inline]
    fn increment_x(&mut self) {
        if (self.v & 0x001F) == 31 {
            self.v &= !0x001F;
            self.v ^= 0x0400;
        } else {
            self.v += 1;
        }
    }

    #[inline]
    fn increment_y(&mut self) {
        if (self.v & 0x7000) != 0x7000 {
            self.v += 0x1000;
        } else {
            self.v &= !0x7000;
            let mut y = (self.v & 0x03E0) >> 5;
            if y == 29 {
                y = 0;
                self.v ^= 0x0800;
            } else if y == 31 {
                y = 0;
            } else {
                y += 1;
            }
            self.v = (self.v & !0x03E0) | (y << 5);
        }
    }

    #[inline]
    fn copy_x(&mut self) {
        self.v = (self.v & !0x041F) | (self.t & 0x041F);
    }

    #[inline]
    fn copy_y(&mut self) {
        self.v = (self.v & !0x7BE0) | (self.t & 0x7BE0);
    }

    #[inline]
    fn load_shifters(&mut self) {
        self.bg_shift_lo = (self.bg_shift_lo & 0xFF00) | self.bg_latch_lo as u16;
        self.bg_shift_hi = (self.bg_shift_hi & 0xFF00) | self.bg_latch_hi as u16;
        self.at_shift_lo = if self.at_latch & 1 != 0 { 0xFF } else { 0 };
        self.at_shift_hi = if self.at_latch & 2 != 0 { 0xFF } else { 0 };
    }

    fn sprite_pattern_addr(&mut self, idx: usize, _mapper: &mut dyn Mapper) -> (u16, u8) {
        let tall = self.ctrl & 0x20 != 0;
        let y = self.sec_oam[idx * 4] as u16;
        let tile = self.sec_oam[idx * 4 + 1];
        let attr = self.sec_oam[idx * 4 + 2];
        // Row within the sprite for the scanline being prepared (scanline + 1).
        let diff = self.scanline.wrapping_sub(y) & 0xFF;
        let mut row = diff as u8;
        if tall {
            row &= 0x0F;
            if attr & 0x80 != 0 {
                row = 15 - row;
            }
            let mut t = tile;
            let base = if tile & 1 != 0 { 0x1000u16 } else { 0 };
            t &= 0xFE;
            if row >= 8 {
                t |= 1;
            }
            let a = base | ((t as u16) << 4) | ((row & 7) as u16);
            (a, attr)
        } else {
            row &= 0x07;
            if attr & 0x80 != 0 {
                row = 7 - row;
            }
            let base = if self.ctrl & 0x08 != 0 { 0x1000u16 } else { 0 };
            let a = base | ((tile as u16) << 4) | (row as u16);
            (a, attr)
        }
    }

    #[inline]
    fn shift_registers(&mut self) {
        self.bg_shift_lo <<= 1;
        self.bg_shift_hi = (self.bg_shift_hi << 1) | 1;
        self.at_shift_lo <<= 1;
        self.at_shift_hi <<= 1;
    }

    fn render_pixel(&mut self, _mapper: &mut dyn Mapper) {
        let x = (self.dot - 1) as u8;
        let bg_enabled = self.mask & 0x08 != 0;
        let sp_enabled = self.mask & 0x10 != 0;

        // ------------------------------------------------ background pixel ---
        let mut bg_pixel = 0u8;
        let mut bg_pal = 0u8;
        if bg_enabled && (x >= 8 || self.mask & 0x02 != 0) {
            let shift = 15 - self.fine_x as u16;
            bg_pixel = ((self.bg_shift_lo >> shift) & 1) as u8
                | ((((self.bg_shift_hi >> shift) & 1) as u8) << 1);
            let ashift = 7 - self.fine_x;
            bg_pal = ((self.at_shift_lo >> ashift) & 1) | (((self.at_shift_hi >> ashift) & 1) << 1);
        }

        // ---------------------------------------------------- sprite pixels ---
        let mut sp_pixel = 0u8;
        let mut sp_pal = 0u8;
        let mut sp_prio = 0u8;
        let mut sprite0_opaque = false;
        if sp_enabled {
            let height: u16 = if self.ctrl & 0x20 != 0 { 16 } else { 8 };
            for i in 0..8 {
                // Row index within the sprite for this scanline (a sprite with
                // OAM Y == y occupies scanlines y+1 .. y+height).
                let row = self
                    .scanline
                    .wrapping_sub(self.sprites[i].y as u16)
                    .wrapping_sub(1)
                    & 0xFF;
                if row >= height {
                    continue;
                }
                if self.sprites[i].x > 0 {
                    self.sprites[i].x -= 1;
                    continue;
                }
                let flip = self.sprites[i].attr & 0x40 != 0;
                let (blo, bhi) = if !flip {
                    let lo = (self.sprites[i].lo >> 7) & 1;
                    let hi = (self.sprites[i].hi >> 7) & 1;
                    self.sprites[i].lo <<= 1;
                    self.sprites[i].hi <<= 1;
                    (lo, hi)
                } else {
                    let lo = self.sprites[i].lo & 1;
                    let hi = self.sprites[i].hi & 1;
                    self.sprites[i].lo >>= 1;
                    self.sprites[i].hi >>= 1;
                    (lo, hi)
                };
                let pix = blo | (bhi << 1);
                if pix != 0 {
                    if i == 0 {
                        sprite0_opaque = true;
                    }
                    if sp_pixel == 0 {
                        sp_pixel = pix;
                        sp_pal = self.sprites[i].attr & 3;
                        sp_prio = (self.sprites[i].attr >> 5) & 1;
                    }
                }
            }
        }
        if x < 8 && self.mask & 0x04 == 0 {
            sp_pixel = 0;
            sprite0_opaque = false;
        }

        // ------------------------------------------------------- compose ---
        #[cfg(feature = "trace")]
        if sp_pixel != 0 {
            self.dbg_sprite_px += 1;
        }
        let (pixel, pal, is_sprite) = if bg_pixel == 0 && sp_pixel == 0 {
            (0u8, 0u8, false)
        } else if bg_pixel == 0 {
            (sp_pixel, sp_pal, true)
        } else if sp_pixel == 0 {
            (bg_pixel, bg_pal, false)
        } else if sp_prio == 0 {
            (sp_pixel, sp_pal, true)
        } else {
            (bg_pixel, bg_pal, false)
        };

        if sprite0_opaque && bg_pixel != 0 && x != 255 {
            self.status |= 0x40;
        }

        let mut addr = if is_sprite {
            0x3F10 | ((pal as u16) << 2) | pixel as u16
        } else if pixel == 0 {
            0x3F00
        } else {
            0x3F00 | ((pal as u16) << 2) | pixel as u16
        };
        if self.mask & 0x01 != 0 {
            addr &= 0x3F30;
        }
        let idx = Self::pal_index(addr);
        let colour = self.palette[idx] as u16 & 0x3F;
        let emph = ((self.mask >> 5) & 7) as u16;
        let sl = self.scanline as usize;
        self.fb[sl * 256 + x as usize] = (emph << 6) | colour;
        self.shift_registers();
    }

    fn backdrop_colour(&self) -> u16 {
        let mut idx_addr = 0x3F00u16;
        if self.v & 0x3F00 == 0x3F00 {
            idx_addr = 0x3F00 | (self.v & 0x1F);
        }
        let idx = Self::pal_index(idx_addr);
        let mut addr = idx as u16;
        if self.mask & 0x01 != 0 {
            addr &= 0x30;
        }
        self.palette[addr as usize] as u16 & 0x3F
    }

    // -------------------------------------------------- sprite evaluation ---

    fn ev_in_range(&self, y: u8) -> bool {
        let height: u16 = if self.ctrl & 0x20 != 0 { 16 } else { 8 };
        // Sprites with OAM Y == y are displayed on scanlines y+1 .. y+height, so
        // the evaluation on scanline L selects them when L - y < height.
        let diff = self.scanline.wrapping_sub(y as u16) & 0xFF;
        diff < height
    }

    fn evaluate_sprite_step(&mut self) {
        match self.ev_mode {
            EvMode::CheckY => {
                let y = self.oam[(self.ev_n as usize) * 4];
                if self.ev_in_range(y) {
                    if self.sprite_count < 8 {
                        self.sec_oam[(self.sprite_count as usize) * 4] = y;
                        self.ev_m = 1;
                        self.ev_mode = EvMode::CopyByte;
                    } else {
                        self.ev_mode = EvMode::OverflowScan;
                        self.ev_m = 0;
                    }
                } else {
                    self.ev_n += 1;
                    if self.ev_n >= 64 {
                        self.ev_mode = EvMode::Done;
                    } else if self.sprite_count >= 8 {
                        self.ev_mode = EvMode::OverflowScan;
                        self.ev_m = 0;
                    }
                }
            }
            EvMode::CopyByte => {
                let v = self.oam[(self.ev_n as usize) * 4 + self.ev_m as usize];
                self.sec_oam[(self.sprite_count as usize) * 4 + self.ev_m as usize] = v;
                self.ev_m += 1;
                if self.ev_m >= 4 {
                    self.sprite_count += 1;
                    self.ev_n += 1;
                    self.ev_m = 0;
                    if self.sprite_count >= 8 {
                        self.ev_mode = EvMode::OverflowScan;
                    } else if self.ev_n >= 64 {
                        self.ev_mode = EvMode::Done;
                    } else {
                        self.ev_mode = EvMode::CheckY;
                    }
                }
            }
            EvMode::OverflowScan => {
                let addr = (self.ev_n as usize * 4 + self.ev_m as usize) & 0xFF;
                let v = self.oam[addr];
                if self.ev_in_range(v) {
                    self.status |= 0x20;
                    let m = self.ev_m as usize + 3;
                    self.ev_n = self.ev_n.wrapping_add((m / 4) as u8);
                    self.ev_m = (m % 4) as u8;
                } else {
                    self.ev_n = self.ev_n.wrapping_add(1);
                    self.ev_m = self.ev_m.wrapping_add(1);
                }
                if self.ev_n >= 64 {
                    self.ev_mode = EvMode::Done;
                }
            }
            EvMode::Done => {}
        }
    }

    /// Advance to the next dot; handles scanline/frame boundaries.
    pub fn advance(&mut self) {
        #[cfg(feature = "trace")]
        if self.scanline == 0 && self.dot == 0 {
            self.dbg_sprite_px = 0;
        }
        #[cfg(feature = "trace")]
        if self.scanline == 239 && self.dot == 0 {
            self.dbg_sp0 = self.sprites[0];
        }
        self.dot += 1;
        self.total_dots += 1;
        let line_len: u16 = 341;
        if self.dot >= line_len {
            self.dot = 0;
            self.scanline += 1;
            if self.scanline > 261 {
                self.scanline = 0;
                self.frame += 1;
                self.odd_frame = !self.odd_frame;
                self.frame_complete = true;
            }
        } else if self.scanline == 261
            && self.rendering_enabled()
            && self.odd_frame
            && self.dot == 340
        {
            // Odd frames skip the last dot of the pre-render scanline.
            self.dot = 0;
            self.scanline = 0;
            self.frame += 1;
            self.odd_frame = !self.odd_frame;
            self.frame_complete = true;
        }
    }
}
