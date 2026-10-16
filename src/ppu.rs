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

#[cfg(feature = "trace")]
fn trace_scanline() -> u16 {
    std::env::var("TRACE_SL").ok().and_then(|v| v.parse().ok()).unwrap_or(18)
}

/// Delay before a register write reaches the PPU (in dots).
static mut REG_DELAY: u64 = 0;
#[cfg(feature = "trace")]
fn reg_delay() -> u64 {
    unsafe {
        if let Ok(v) = std::env::var("REG_DELAY") {
            if let Ok(n) = v.parse::<u64>() {
                REG_DELAY = n;
            }
        }
        REG_DELAY
    }
}
#[cfg(not(feature = "trace"))]
fn reg_delay() -> u64 {
    unsafe { REG_DELAY }
}

/// How long the PPU's decay register keeps its value; the reference clears it
/// between 0.4 s and 0.8 s after the last write (about 600 ms = 1.07M PPU dots).
static mut DECAY_CYCLES: u32 = 3_000_000;
#[cfg(feature = "trace")]
fn decay_cycles() -> u32 {
    unsafe {
        if let Ok(v) = std::env::var("DECAY_DOTS") {
            if let Ok(n) = v.parse::<u32>() {
                DECAY_CYCLES = n;
            }
        }
        DECAY_CYCLES
    }
}
#[cfg(not(feature = "trace"))]
fn decay_cycles() -> u32 {
    unsafe { DECAY_CYCLES }
}

/// Which PPU dot a $2002 read suppresses the vblank set on:
/// bit 0 = the dot before the set (240,340), bit 1 = the set dot (241,0).
/// Whether the attribute latch is transferred one refresh window later.
static mut ATTR_DELAY: bool = true;
#[cfg(feature = "trace")]
fn attr_delay() -> bool {
    unsafe {
        if let Ok(v) = std::env::var("ATTR_DELAY") {
            ATTR_DELAY = v != "0";
        }
        ATTR_DELAY
    }
}
#[cfg(not(feature = "trace"))]
fn attr_delay() -> bool {
    unsafe { ATTR_DELAY }
}

static mut VBL_SUPPRESS_MODE: u32 = 1;
/// Dot of scanline 241 on which the vblank flag is set (the documentation's
/// dot 1; reads on the dot before it clear and drop the flag).
static mut VBL_SET_DOT: u16 = 0;
#[cfg(feature = "trace")]
fn vbl_set_dot() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("VBL_SET_DOT") {
            if let Ok(n) = v.parse::<u16>() {
                VBL_SET_DOT = n;
            }
        }
        VBL_SET_DOT
    }
}
#[cfg(not(feature = "trace"))]
fn vbl_set_dot() -> u16 {
    unsafe { VBL_SET_DOT }
}

static mut PAL_DELAY: u64 = 4;
#[cfg(feature = "trace")]
fn pal_delay() -> u64 {
    unsafe {
        if let Ok(v) = std::env::var("PAL_DELAY") {
            if let Ok(n) = v.parse::<u64>() {
                PAL_DELAY = n;
            }
        }
        PAL_DELAY
    }
}
#[cfg(not(feature = "trace"))]
fn pal_delay() -> u64 {
    unsafe { PAL_DELAY }
}

static mut PPU_DOT_LATE: bool = true;
#[cfg(feature = "trace")]
fn ppu_dot_late() -> bool {
    unsafe {
        if let Ok(v) = std::env::var("PPU_DOT_LATE") {
            PPU_DOT_LATE = v != "0";
        }
        PPU_DOT_LATE
    }
}
#[cfg(not(feature = "trace"))]
fn ppu_dot_late() -> bool {
    unsafe { PPU_DOT_LATE }
}

/// Extra dots added to the sprite fetch phase (0 or 1).  The documented
/// sprite fetch runs at dots 257-320 with the attribute byte loaded on the
/// second tick of the second garbage nametable fetch.
static mut SPR_OFF: u16 = 0;
#[cfg(feature = "trace")]
fn spr_off() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("SPR_OFF") {
            if let Ok(n) = v.parse::<u16>() { SPR_OFF = n; }
        }
        SPR_OFF
    }
}
#[cfg(not(feature = "trace"))]
fn spr_off() -> u16 { unsafe { SPR_OFF } }

/// Dot of scanline 261 on which the odd frame's clock is skipped.
static mut ODD_SKIP_DOT: u16 = 340;
/// Dot of scanline 261 at which the rendering-enabled state that decides the
/// odd-frame skip is sampled.
static mut ODD_DECIDE_DOT: u16 = 337;
#[cfg(feature = "trace")]
fn odd_decide_dot() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("ODD_DECIDE_DOT") {
            if let Ok(n) = v.parse::<u16>() {
                ODD_DECIDE_DOT = n;
            }
        }
        ODD_DECIDE_DOT
    }
}
#[cfg(not(feature = "trace"))]
fn odd_decide_dot() -> u16 {
    unsafe { ODD_DECIDE_DOT }
}
#[cfg(feature = "trace")]
fn odd_skip_dot() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("ODD_SKIP_DOT") {
            if let Ok(n) = v.parse::<u16>() {
                ODD_SKIP_DOT = n;
            }
        }
        ODD_SKIP_DOT
    }
}
#[cfg(not(feature = "trace"))]
fn odd_skip_dot() -> u16 {
    unsafe { ODD_SKIP_DOT }
}

/// Dot of scanline 261 on which the vblank and sprite flags are cleared.
static mut VBL_CLEAR_DOT: u16 = 0;
#[cfg(feature = "trace")]
fn vbl_clear_dot() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("VBL_CLEAR_DOT") {
            if let Ok(n) = v.parse::<u16>() {
                VBL_CLEAR_DOT = n;
            }
        }
        VBL_CLEAR_DOT
    }
}
#[cfg(not(feature = "trace"))]
fn vbl_clear_dot() -> u16 {
    unsafe { VBL_CLEAR_DOT }
}

/// Dot of scanline 241 on which a $2002 read drops the vblank flag.
static mut VBL_DROP_DOT: u16 = 0;
#[cfg(feature = "trace")]
fn drop_dot() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("VBL_DROP_DOT") {
            if let Ok(n) = v.parse::<u16>() {
                VBL_DROP_DOT = n;
            }
        }
        VBL_DROP_DOT
    }
}
#[cfg(not(feature = "trace"))]
fn drop_dot() -> u16 {
    unsafe { VBL_DROP_DOT }
}

static mut VBL_NMI_WIN: u16 = 6;
#[cfg(feature = "trace")]
fn nmi_win() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("VBL_NMI_WIN") {
            if let Ok(n) = v.parse::<u16>() {
                VBL_NMI_WIN = n;
            }
        }
        VBL_NMI_WIN
    }
}
#[cfg(not(feature = "trace"))]
fn nmi_win() -> u16 {
    unsafe { VBL_NMI_WIN }
}

static mut VBL_DROP_SL: u16 = 241;
#[cfg(feature = "trace")]
fn drop_scanline() -> u16 {
    unsafe {
        if let Ok(v) = std::env::var("VBL_DROP_SL") {
            if let Ok(n) = v.parse::<u16>() {
                VBL_DROP_SL = n;
            }
        }
        VBL_DROP_SL
    }
}
#[cfg(not(feature = "trace"))]
fn drop_scanline() -> u16 {
    unsafe { VBL_DROP_SL }
}
fn vbl_suppress_mode() -> u32 {
    unsafe {
        #[cfg(feature = "trace")]
        {
            if let Ok(v) = std::env::var("VBL_SUPPRESS") {
                if let Ok(n) = v.parse::<u32>() {
                    VBL_SUPPRESS_MODE = n;
                }
            }
        }
        VBL_SUPPRESS_MODE
    }
}

#[derive(Clone, Copy, Default)]
pub struct SpriteUnit {
    pub x: u8,
    pub y: u8,
    pub attr: u8,
    pub lo: u8,
    pub hi: u8,
}

#[derive(Clone, Copy, PartialEq, Debug)]
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
    /// Cycles remaining before the decay register clears.
    decay_timer: u32,

    // Timing
    pub scanline: u16,
    pub dot: u16,
    pub frame: u64,
    pub total_dots: u64,
    pub odd_frame: bool,
    /// Rendering-enabled state sampled at `odd_decide_dot()` on the pre-render
    /// line; the odd-frame skip at dot 340 uses this sample.
    pub render_at_skip: bool,
    pub frame_complete: bool,

    // Background pipeline
    bg_latch_nt: u8,
    bg_latch_at: u8,
    bg_latch_lo: u8,
    bg_latch_hi: u8,
    bg_shift_lo: u16,
    bg_shift_hi: u16,
    at_latch: u8,
    /// Previous attribute latch (used when the reference delays the transfer).
    at_latch_prev: u8,
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
    /// Palette writes take effect a couple of PPU dots after the CPU write;
    /// the reference shows exactly a two-dot delay on the rendered output.
    pending_pal: [(u64, u8, u8); 4],
    pending_pal_n: u8,
    /// PPU dot at which the pending $2007 address increment applies (0 = none).
    pending_v_inc: u64,
    /// Delayed register writes ($2000/$2001/$2005/$2006): they reach the PPU
    /// registers a couple of dots after the CPU write.
    reg_queue: [(u64, u8, u8); 8],
    reg_queue_n: u8,
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
            decay_timer: 0,
            pending_pal: [(0, 0, 0); 4],
            pending_pal_n: 0,
            pending_v_inc: 0,
            reg_queue: [(0, 0, 0); 8],
            reg_queue_n: 0,
            scanline: 0,
            dot: 0,
            frame: 0,
            total_dots: 0,
            odd_frame: true,
            render_at_skip: false,
            frame_complete: false,
            bg_latch_nt: 0,
            bg_latch_at: 0,
            bg_latch_lo: 0,
            bg_latch_hi: 0,
            bg_shift_lo: 0,
            bg_shift_hi: 0,
            at_latch: 0,
            at_latch_prev: 0,
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
        self.decay_timer = 0;
        self.scanline = 0;
        self.dot = 0;
        self.frame = 0;
        self.odd_frame = false;
        self.render_at_skip = false;
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
        let a = addr & 0x3FFF;
        if a < 0x2000 {
            mapper.chr_write(a, val);
        } else if a < 0x3F00 {
            let idx = self.mirror_addr(a, mapper);
            self.vram[idx & 4095] = val;
        } else {
            let idx = Self::pal_index(a);
            #[cfg(feature = "trace")]
            {
                if std::env::var("TRACE_PALW").is_ok() {
                    eprintln!("PALW f={} sl={} dot={} addr={:04X} -> idx={} val={:02X} delay={}",
                        self.frame, self.scanline, self.dot, a, idx, val, pal_delay());
                }
            }
            // The write reaches palette RAM two PPU dots later.
            let n = self.pending_pal_n as usize;
            if n < self.pending_pal.len() {
                self.pending_pal[n] = (self.total_dots + pal_delay(), idx as u8, val);
                self.pending_pal_n += 1;
            } else {
                self.palette[idx] = val & 0x3F;
            }
        }
    }

    /// Apply queued register writes whose pipeline delay has elapsed.
    fn flush_regs(&mut self, mapper: &mut dyn Mapper) {
        if self.reg_queue_n == 0 {
            return;
        }
        let now = self.total_dots;
        let mut i = 0;
        while i < self.reg_queue_n as usize {
            let (due, reg, val) = self.reg_queue[i];
            if due <= now {
                self.apply_reg(reg, val, mapper);
                let last = self.reg_queue_n as usize - 1;
                self.reg_queue[i] = self.reg_queue[last];
                self.reg_queue_n -= 1;
            } else {
                i += 1;
            }
        }
    }

    /// Apply the $2007 address increment once its pipeline delay has elapsed.
    fn flush_v_inc(&mut self) {
        if self.pending_v_inc != 0 && self.total_dots >= self.pending_v_inc {
            self.pending_v_inc = 0;
            self.increment_vram_addr();
        }
    }

    /// Apply palette writes whose two-dot pipeline delay has elapsed.
    fn flush_palette(&mut self) {
        if self.pending_pal_n == 0 {
            return;
        }
        let now = self.total_dots;
        let mut i = 0;
        while i < self.pending_pal_n as usize {
            let (due, idx, val) = self.pending_pal[i];
            if due <= now {
                self.palette[idx as usize] = val & 0x3F;
                let last = self.pending_pal_n as usize - 1;
                self.pending_pal[i] = self.pending_pal[last];
                self.pending_pal_n -= 1;
            } else {
                i += 1;
            }
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
                // The low bits come from the PPU's decay register, which sits on
                // the palette data bus; with greyscale enabled that bus is
                // masked to the two luminance bits.
                let low = if self.mask & 0x01 != 0 {
                    self.open_bus & 0x30
                } else {
                    self.open_bus & 0x1F
                };
                #[cfg(feature = "trace")]
                {
                    if std::env::var("TRACE_OB").is_ok() {
                        eprintln!("$2002 read: mask={:02X} open={:02X} low={:02X}", self.mask, self.open_bus, low);
                    }
                }
                let mut result = (self.status & 0xE0) | low;
                #[cfg(feature = "trace")]
                {
                    if std::env::var("TRACE_RD2002").is_ok() {
                        eprintln!("$2002 read f={} sl={} dot={} status={:02X}", self.frame, self.scanline, self.dot, self.status);
                    }
                }
                if vbl_suppress_mode() & 16 != 0
                    && self.scanline == drop_scanline()
                    && self.dot >= drop_dot()
                    && self.dot <= drop_dot() + nmi_win()
                {
                    // Reads just after the vblank set suppress the NMI without
                    // affecting the flag itself.
                    self.nmi_suppress = true;
                }
                // A read exactly one PPU clock before the VBL set suppresses the
                // flag for the whole frame (and the NMI is not generated).
                if self.scanline == 240 && self.dot == 340 && vbl_suppress_mode() & 1 != 0 {
                    self.vbl_suppress = true;
                    self.nmi_suppress = true;
                    result &= 0x7F;
                }
                if (vbl_suppress_mode() & 16 != 0)
                    && self.scanline == drop_scanline()
                    && self.dot == drop_dot()
                {
                    #[cfg(feature = "trace")]
                    {
                        if std::env::var("TRACE_SUPPRESS").is_ok() {
                            eprintln!("vbl suppressed at sl=241 dot={}", self.dot);
                        }
                    }
                    self.vbl_suppress = true;
                    self.nmi_suppress = true;
                    self.status &= !0x80;
                    return result & 0x7F;
                }
                if self.scanline == 241 && self.dot == 0 && vbl_suppress_mode() & 2 != 0 {
                    #[cfg(feature = "trace")]
                    {
                        if std::env::var("TRACE_SUPPRESS").is_ok() {
                            eprintln!("vbl suppressed (mode2)");
                        }
                    }
                    self.status &= !0x80;
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
                let mut v = self.oam[self.oam_addr as usize];
                // The three unimplemented bits of a sprite's attribute byte
                // always read as zero, and the decay register is refreshed with
                // whatever the read returns.
                if self.oam_addr & 3 == 2 {
                    v &= 0xE3;
                }
                self.open_bus = v;
                self.decay_timer = decay_cycles();
                v
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
                // Reading VRAM through $2007 refreshes the decay register with
                // whatever was returned to the CPU.
                self.open_bus = result;
                self.decay_timer = decay_cycles();
                self.increment_vram_addr();
                result
            }
            _ => self.open_bus,
        }
    }

    #[inline]
    /// Apply a (possibly delayed) write to one of the timing-critical
    /// registers.
    fn apply_reg(&mut self, reg: u8, val: u8, _mapper: &mut dyn Mapper) {
        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_PPW").is_ok() && (reg == 5 || reg == 6 || reg == 0 || reg == 1) {
                eprintln!("PW f={} sl={} dot={} reg={} val={:02X} w={} v={:04X} t={:04X} fx={} dots={}",
                    self.frame, self.scanline, self.dot, 2000u32 + reg as u32, val, self.w as u8, self.v, self.t,
                    self.fine_x, self.total_dots);
            }
        }
        match reg {
            0 => {
                self.ctrl = val;
                self.t = (self.t & 0xF3FF) | (((val as u16) & 0x03) << 10);
            }
            1 => {
                self.mask = val;
            }
            5 => {
                if !self.w {
                    // First write: X scroll -> fine X and coarse X.
                    self.fine_x = val & 0x07;
                    self.t = (self.t & 0x7FE0) | ((val as u16) >> 3);
                    self.w = true;
                } else {
                    // Second write: Y scroll -> coarse Y (bits 5-9) and fine Y
                    // (bits 12-14).  The X and nametable bits are preserved.
                    self.t = (self.t & 0x0C1F)
                        | (((val as u16) & 0x07) << 12)
                        | (((val as u16) & 0xF8) << 2);
                    self.w = false;
                }
            }
            6 => {
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
            _ => {}
        }
    }

    fn increment_vram_addr(&mut self) {
        let inc = if self.ctrl & 0x04 != 0 { 32 } else { 1 };
        self.v = self.v.wrapping_add(inc) & 0x7FFF;
    }

    pub fn write_register(&mut self, addr: u16, val: u8, mapper: &mut dyn Mapper, warmup: bool) {
        #[cfg(feature = "trace")]
        if !warmup && std::env::var("NMI_TRACE").is_ok() && (addr & 7) == 0 {
            eprintln!("$2000={:02X} @dot={} f={} sl={} dot={} vbl={}", val, self.total_dots, self.frame, self.scanline, self.dot, (self.status >> 7) & 1);
        }
        #[cfg(feature = "trace")]
        if !warmup && std::env::var("PPU_WLOG").is_ok() && (addr & 7) <= 7 {
            eprintln!(
                "W {:7} f={} sl={:3} dot={:3} reg{}={:02X} v={:04X} t={:04X}",
                self.total_dots, self.frame, self.scanline, self.dot, addr & 7, val, self.v, self.t
            );
        }
        // Any write to $2000-$3FFF loads the PPU's decay register with the
        // whole byte: reads of $2000-$2006 return it, $2002 its low 5 bits.
        self.open_bus = val;
        self.decay_timer = decay_cycles();
        // $2000/$2001/$2005/$2006 take effect two PPU dots after the write.
        match addr & 7 {
            0 | 1 | 5 | 6 => {
                if warmup {
                    return;
                }
                let n = self.reg_queue_n as usize;
                let reg = (addr & 7) as u8;
                if n < self.reg_queue.len() {
                    self.reg_queue[n] = (self.total_dots + reg_delay(), reg, val);
                    self.reg_queue_n += 1;
                } else {
                    self.apply_reg(reg, val, mapper);
                }
                return;
            }
            _ => {}
        }
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
                // Writes to OAMDATA during rendering do not modify OAM (only
                // the OAM address is bumped).
                let in_render = self.rendering_enabled()
                    && (self.scanline <= 239 || self.scanline == 261);
                if !in_render {
                    self.oam[self.oam_addr as usize] = val;
                }
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
                self.pending_v_inc = self.total_dots + 2;
            }
            _ => {}
        }
    }

    // ------------------------------------------------------------ timing ---

    pub fn process_dot(&mut self, mapper: &mut dyn Mapper) {
        self.flush_palette();
        self.flush_v_inc();
        self.flush_regs(mapper);
        if self.decay_timer > 0 {
            self.decay_timer -= 1;
            if self.decay_timer == 0 {
                self.open_bus = 0;
            }
        }
        let sl = self.scanline;
        let dot = self.dot;
        // The mapper sees the PPU address bus on every dot (MMC3 A12 clocking).
        if !ppu_dot_late() {
            if self.rendering_enabled() {
                let a = self.bus_addr;
                mapper.ppu_dot(a);
            } else {
                let a = self.v & 0x3FFF;
                self.bus_addr = a;
                mapper.ppu_dot(a);
            }
        }

        if sl == 241 && dot == vbl_set_dot() {
            if !self.vbl_suppress {
                self.status |= 0x80;
            }
            self.vbl_suppress = false;
        }
        if vbl_set_dot() != 0 && sl == 241 && dot == 0 {
            self.vbl_suppress = false;
        }
        if sl == 261 && dot == vbl_clear_dot() {
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
                let in_sprite_fetch = ((256 + spr_off())..=(319 + spr_off())).contains(&dot);
                if in_bg_fetch {
                    // The last fetch window of a visible scanline (dots 240-255)
                    // wraps into the next nametable; the reference keeps the
                    // previous latches for those pixels.
                    let keep_latch = dot >= 240 && dot <= 255 && sl <= 239;
                    match dot & 7 {
                        0 => {
                            let a = 0x2000 | (self.v & 0x0FFF);
                            let nt = self.vram_read(a, mapper);
                            if !keep_latch {
                                self.bg_latch_nt = nt;
                            }
                            #[cfg(feature = "trace")]
                            {
                                if std::env::var("TRACE_FETCH").is_ok() && self.scanline == 0 {
                                    eprintln!("NT fetch sl=0 dot={} v={:04X} addr={:04X} nt={:02X} cx={}", dot, self.v, a, self.bg_latch_nt, self.v & 31);
                                }
                            }
                        }
                        2 => {
                            let a = 0x23C0
                                | (self.v & 0x0C00)
                                | ((self.v >> 4) & 0x38)
                                | ((self.v >> 2) & 0x07);
                            let at = self.vram_read(a, mapper);
                            let shift = ((self.v >> 4) & 4) | (self.v & 2);
                            let latch = (at >> shift) & 3;
                            if !keep_latch {
                                self.at_latch = latch;
                            }
                        }
                        4 => {
                            let fine_y = (self.v >> 12) & 7;
                            let pt = if self.ctrl & 0x10 != 0 { 0x1000 } else { 0 };
                            let a = pt | ((self.bg_latch_nt as u16) << 4) | fine_y;
                            let lo = self.vram_read(a, mapper);
                            if !keep_latch {
                                self.bg_latch_lo = lo;
                            }
                        }
                        6 => {
                            let fine_y = (self.v >> 12) & 7;
                            let pt = if self.ctrl & 0x10 != 0 { 0x1000 } else { 0 };
                            let a = pt | ((self.bg_latch_nt as u16) << 4) | fine_y | 8;
                            let hi = self.vram_read(a, mapper);
                            if !keep_latch {
                                self.bg_latch_hi = hi;
                            }
                        }
                        7 => {
                            if dot <= 255 || dot >= 327 {
                                self.increment_x();
                            }
                        }
                        _ => {}
                    }
                } else if in_sprite_fetch {
                    let d = dot - (256 + spr_off());
                    let idx = (d / 8) as usize;
                    match d & 7 {
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
                            // The low bitplane's first fetch: the value is not
                            // used yet, but the address is on the bus (mappers
                            // like the MMC3 watch A12).
                            let (a, _) = self.sprite_pattern_addr(idx, mapper);
                            let _ = self.vram_read(a, mapper);
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
                            let _ = self.vram_read(a, mapper);
                        }
                        _ => {
                            let (a, _) = self.sprite_pattern_addr(idx, mapper);
                            // The high bitplane is 8 bytes above the low one.
                            self.sprites[idx].hi = self.vram_read(a + 8, mapper);
                        }
                    }
                }

                // --------------------------------------------------- pixel ---
                #[cfg(feature = "trace")]
                {
                    if std::env::var("TRACE_ALLPX").is_ok() && dot == 1 && sl < 2 {
                        eprintln!("procpx sl={} dot={}", sl, dot);
                    }
                    if std::env::var("TRACE_SL").is_ok() && dot == 1 && sl < 4 && self.frame == 3 {
                        eprintln!("proc sl={} dot={} rendering={}", sl, dot, rendering);
                    }
                }
                #[cfg(feature = "trace")]
                {
                    if std::env::var("TRACE_PRE").is_ok() && dot == 1 && sl < 2 {
                        eprintln!("PRE sl={} dot={}", sl, dot);
                    }
                }
                if sl <= 239 && (1..=256).contains(&dot) {
                    #[cfg(feature = "trace")]
                    {
                        if std::env::var("TRACE_SPR").is_ok() && dot == 100 && sl < 60 {
                            let s0 = &self.sprites[0];
                            eprintln!("render sl={} dot={} sp0 x={} attr={:02X} lo={:02X} hi={:02X} sec0={:02X}{:02X}{:02X}{:02X}",
                                sl, dot, s0.x, s0.attr, s0.lo, s0.hi, self.sec_oam[0], self.sec_oam[1], self.sec_oam[2], self.sec_oam[3]);
                        }
                    }
                    if std::env::var("TRACE_NOREND").is_err() { self.render_pixel(mapper); }
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
                if (sl <= 239 || sl == 261) && dot == 0 {
                    self.sprite_count = 0;
                    self.ev_n = 0;
                    self.ev_m = 0;
                    self.ev_mode = EvMode::CheckY;
                }
                if (sl <= 239) && (0..=63).contains(&dot) && dot & 1 == 1 {
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
                    let v = (emph << 6) | colour;
                    #[cfg(feature = "trace")]
                    if std::env::var("PXL_TRACE").is_ok() {
                        let prev = self.fb[(sl as usize) * 256 + x];
                        if prev != v || x == 0 {
                            eprintln!("P f={} sl={} dot={} x={} {:04X}->{:04X} off v={:04X} t={:04X} mask={:02X}",
                                self.frame, sl, dot, x, prev, v, self.v, self.t, self.mask);
                        }
                    }
                    self.fb[(sl as usize) * 256 + x] = v;
                }
            }
        }
        if ppu_dot_late() {
            let a = if self.rendering_enabled() {
                self.bus_addr
            } else {
                self.v & 0x3FFF
            };
            mapper.ppu_dot(a);
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
        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_AT").is_ok() && self.scanline == 64 && self.dot <= 48 {
                eprintln!("reload dot={} at_latch={} v={:04X}", self.dot, self.at_latch, self.v);
            }
        }
        self.bg_shift_lo = (self.bg_shift_lo & 0xFF00) | self.bg_latch_lo as u16;
        self.bg_shift_hi = (self.bg_shift_hi & 0xFF00) | self.bg_latch_hi as u16;
        let latch = if attr_delay() { self.at_latch_prev } else { self.at_latch };
        self.at_latch_prev = self.at_latch;
        self.at_shift_lo = if latch & 1 != 0 { 0xFF } else { 0 };
        self.at_shift_hi = if latch & 2 != 0 { 0xFF } else { 0 };
    }

    fn sprite_pattern_addr(&mut self, idx: usize, _mapper: &mut dyn Mapper) -> (u16, u8) {
        let tall = self.ctrl & 0x20 != 0;
        let y = self.sec_oam[idx * 4] as u16;
        let tile = self.sec_oam[idx * 4 + 1];
        let attr = self.sec_oam[idx * 4 + 2];
        // Row within the sprite for the scanline being prepared (scanline + 1).
        // The sprite was selected because it is in range, so scanline >= y here.
        let diff = self.scanline.wrapping_sub(y) & 0xFF;
        let mut row = if self.scanline >= y { diff as u8 } else { 0 };
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
        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_ALLPX").is_ok() && self.total_dots < 90000 && self.scanline < 2 {
                eprintln!("allpx sl=1 dot={} x={}", self.dot, x);
            }
        }
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
                // Row within the sprite for this scanline; the sprite window
                // does not wrap, so sprites starting at or past line 239 never
                // draw (and never set the hit flag).
                let sy = self.sprites[i].y as u16;
                let line = self.scanline;
                if line <= sy || line > sy + height {
                    continue;
                }
                let _row = line - sy - 1;
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
                        #[cfg(feature = "trace")]
                        {
                            if std::env::var("TRACE_SPRITE_EDGE").is_ok() && x >= 240 {
                                eprintln!("sprite px sl={} x={} idx={} y={:02X} attr={:02X} tile={:02X} spx={:02X}",
                                    self.scanline, x, i, self.sprites[i].y, self.sprites[i].attr,
                                    0, self.sprites[i].x);
                            }
                        }
                    }
                }
            }
        }
        if x < 8 && self.mask & 0x04 == 0 {
            sp_pixel = 0;
            sprite0_opaque = false;
        }

        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_BG").is_ok()
                && self.scanline == trace_scanline()
                && self.dot >= 80
                && self.dot < 120
            {
                eprintln!(
                    "bg sl={} dot={} x={} latch={:02X}/{:02X} nt={:02X} v={:04X} t={:04X} finex={} px={}",
                    self.scanline, self.dot, x,
                    self.bg_latch_lo, self.bg_latch_hi, self.bg_latch_nt, self.v, self.t, self.fine_x, bg_pixel
                );
            }
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

        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_SPX").is_ok() && self.scanline == 1 && (x < 12 || (x > 130 && x < 142)) {
                eprintln!("sl1 x={} sp0 x={} lo={:02X} hi={:02X} opaque={} bgpx={} sec0={:02X}{:02X}{:02X}{:02X}",
                    x, self.sprites[0].x, self.sprites[0].lo, self.sprites[0].hi, sprite0_opaque, bg_pixel,
                    self.sec_oam[0], self.sec_oam[1], self.sec_oam[2], self.sec_oam[3]);
            }
        }
        if sprite0_opaque && bg_pixel != 0 && x != 255 {
            #[cfg(feature = "trace")]
            {
                if std::env::var("TRACE_SP0HIT").is_ok() {
                    eprintln!("sprite0 hit sl={} dot={} x={} bgpx={} bgpal={} sppx={} sppal={} ctrl={:02X} mask={:02X} sp0y={:02X} sp0x={:02X} sp0lo={:02X} sp0hi={:02X}",
                        self.scanline, self.dot, x, bg_pixel, bg_pal, sp_pixel, sp_pal, self.ctrl, self.mask,
                        self.sprites[0].y, self.sprites[0].x, self.sprites[0].lo, self.sprites[0].hi);
                }
            }
            self.status |= 0x40;
        }

        let addr = if is_sprite {
            0x3F10 | ((pal as u16) << 2) | pixel as u16
        } else if pixel == 0 {
            0x3F00
        } else {
            0x3F00 | ((pal as u16) << 2) | pixel as u16
        };
        let idx = Self::pal_index(addr);
        // Greyscale masks the colour that comes out of palette RAM.
        let mut colour = self.palette[idx] as u16 & 0x3F;
        if self.mask & 0x01 != 0 {
            colour &= 0x30;
        }
        let emph = ((self.mask >> 5) & 7) as u16;
        let sl = self.scanline as usize;
        #[cfg(feature = "trace")]
        if std::env::var("PXL_TRACE").is_ok() {
            let v = (emph << 6) | colour;
            let prev = self.fb[sl * 256 + x as usize];
            if prev != v || x == 0 {
                eprintln!("P f={} sl={} dot={} x={} {:04X}->{:04X} REND v={:04X} t={:04X} mask={:02X}",
                    self.frame, sl, self.dot, x, prev, v, self.v, self.t, self.mask);
            }
        }
        self.fb[sl * 256 + x as usize] = (emph << 6) | colour;
        self.shift_registers();
    }

    fn backdrop_colour(&self) -> u16 {
        let mut idx_addr = 0x3F00u16;
        if self.v & 0x3F00 == 0x3F00 {
            idx_addr = 0x3F00 | (self.v & 0x1F);
        }
        let idx = Self::pal_index(idx_addr);
        let mut colour = self.palette[idx] as u16 & 0x3F;
        if self.mask & 0x01 != 0 {
            colour &= 0x30;
        }
        colour
    }

    // -------------------------------------------------- sprite evaluation ---

    fn ev_in_range(&self, y: u8) -> bool {
        let height: u16 = if self.ctrl & 0x20 != 0 { 16 } else { 8 };
        // Sprites with OAM Y == y are displayed on scanlines y+1 .. y+height.
        // The comparison does not wrap: a sprite whose window starts beyond the
        // visible area (Y >= 239) is never displayed.
        let line = self.scanline + 1;
        let y = y as u16;
        line > y && line <= y + height
    }

    fn evaluate_sprite_step(&mut self) {
        #[cfg(feature = "trace")]
        {
            if std::env::var("TRACE_EV").is_ok() {
                eprintln!("ev sl={} dot={} n={} m={} cnt={} mode={:?}", self.scanline, self.dot, self.ev_n, self.ev_m, self.sprite_count, self.ev_mode);
            }
        }
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
                    #[cfg(feature = "trace")]
                    {
                        if std::env::var("TRACE_OVF").is_ok() {
                            eprintln!("overflow set f={} sl={} n={} m={} addr={:02X} v={:02X} sprcnt={}", self.frame, self.scanline, self.ev_n, self.ev_m, addr, v, self.sprite_count);
                        }
                    }
                    self.status |= 0x20;
                    let m = self.ev_m as usize + 3;
                    self.ev_n = self.ev_n.wrapping_add((m / 4) as u8);
                    self.ev_m = (m % 4) as u8;
                } else {
                    self.ev_n = self.ev_n.wrapping_add(1);
                    // m is a two-bit counter: it wraps within the sprite entry
                    // rather than carrying into n.
                    self.ev_m = (self.ev_m + 1) & 3;
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
        {
            if std::env::var("SL_TRACE").is_ok()
                && self.dot == 0
                && matches!(self.scanline, 0 | 1 | 2 | 30 | 31 | 32 | 33 | 199 | 200 | 239 | 240 | 241 | 261 | 262)
            {
                eprintln!(
                    "sl={} f={} ctrl={:02X} mask={:02X} v={:04X} t={:04X} fx={} vbl={}",
                    self.scanline, self.frame, self.ctrl, self.mask, self.v, self.t, self.fine_x,
                    (self.status >> 7) & 1
                );
            }
        }
        #[cfg(feature = "trace")]
        if self.scanline == 0 && self.dot == 0 {
            self.dbg_sprite_px = 0;
        }
        #[cfg(feature = "trace")]
        if self.scanline == 239 && self.dot == 0 {
            self.dbg_sp0 = self.sprites[0];
        }
        if self.scanline == 261 && self.dot == odd_decide_dot() {
            self.render_at_skip = self.rendering_enabled();
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
            && self.odd_frame
            && self.dot == odd_skip_dot()
            && self.render_at_skip
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
