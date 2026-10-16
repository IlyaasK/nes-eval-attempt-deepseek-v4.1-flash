//! Cycle-accurate NMOS 6502 (2A03, no decimal mode) CPU.
//!
//! The CPU is implemented as instruction microcode where every memory access and
//! every internal cycle consumes exactly one CPU cycle.  All CPU cycles of the
//! machine (including those stolen by DMA) are accounted for by `System`.

use crate::system::System;

pub const FLAG_C: u8 = 0x01;
pub const FLAG_Z: u8 = 0x02;
pub const FLAG_I: u8 = 0x04;
pub const FLAG_D: u8 = 0x08;
pub const FLAG_B: u8 = 0x10;
pub const FLAG_U: u8 = 0x20;
pub const FLAG_V: u8 = 0x40;
pub const FLAG_N: u8 = 0x80;

pub struct Cpu {
    pub a: u8,
    pub x: u8,
    pub y: u8,
    pub sp: u8,
    pub pc: u16,
    pub p: u8,
    /// Set when an illegal JAM/KIL opcode has been executed: the CPU stops.
    pub jammed: bool,
    /// NMI edge latch (set by the PPU NMI output rising edge).
    pub nmi_pending: bool,
    /// IRQ level detector output for the *current* cycle (latched at the end of
    /// the previous cycle, i.e. one cycle behind the IRQ line itself).
    pub irq_level_latched: bool,
    /// True when the interrupt lines were polled high with I clear during an
    /// instruction; consulted at the instruction boundary.
    pub irq_seen: bool,
    /// Set by CLI/PLP/RTI: the I flag change only affects interrupt polling
    /// starting with the instruction after the next one.
    pub irq_delay: bool,
    /// Number of cycles executed in the current instruction.
    pub instr_cycles: u32,
    /// Set while executing an interrupt sequence: no polling happens there.
    pub in_interrupt: bool,
    /// Last value driven on the CPU data bus (open bus behavior).
    pub bus_latch: u8,
    /// Loop counter used to detect infinite tight loops (frame safety valve).
    pub loop_guard: u32,
}

impl Cpu {
    pub fn new() -> Cpu {
        Cpu {
            a: 0,
            x: 0,
            y: 0,
            sp: 0xFD,
            pc: 0,
            p: 0x24,
            jammed: false,
            nmi_pending: false,
            irq_level_latched: false,
            irq_seen: false,
            irq_delay: false,
            instr_cycles: 0,
            in_interrupt: false,
            bus_latch: 0,
            loop_guard: 0,
        }
    }

    #[inline]
    pub fn flag(&self, f: u8) -> bool {
        self.p & f != 0
    }
    #[inline]
    pub fn set_flag(&mut self, f: u8, v: bool) {
        if v {
            self.p |= f;
        } else {
            self.p &= !f;
        }
    }
    #[inline]
    pub fn set_zn(&mut self, v: u8) {
        self.set_flag(FLAG_Z, v == 0);
        self.set_flag(FLAG_N, v & 0x80 != 0);
    }
}

impl System {
    // ----------------------------------------------------------- primitives ---

    #[inline]
    pub(crate) fn fetch(&mut self) -> u8 {
        let pc = self.cpu.pc;
        self.cpu.pc = pc.wrapping_add(1);
        self.rd(pc)
    }

    #[inline]
    pub(crate) fn fetch16(&mut self) -> u16 {
        let lo = self.fetch() as u16;
        let hi = self.fetch() as u16;
        lo | (hi << 8)
    }

    #[inline]
    pub(crate) fn push(&mut self, v: u8) {
        let sp = self.cpu.sp;
        self.wr(0x0100 + sp as u16, v);
        self.cpu.sp = sp.wrapping_sub(1);
    }

    #[inline]
    pub(crate) fn pop(&mut self) -> u8 {
        let sp = self.cpu.sp.wrapping_add(1);
        self.cpu.sp = sp;
        self.rd(0x0100 + sp as u16)
    }

    /// A read cycle that has no data dependency (dummy read / idle read).
    #[inline]
    pub(crate) fn idle_read(&mut self, addr: u16) {
        let _ = self.rd(addr);
    }

    /// The internal cycle of an implied/accumulator instruction: the CPU reads
    /// the next instruction byte (at PC) and throws it away.
    #[inline]
    fn implied(&mut self) {
        let pc = self.cpu.pc;
        self.idle_read(pc);
    }

    /// The extra cycle before a pull: the stack pointer is incremented and the
    /// stack location is read (value discarded).
    #[inline]
    fn push_pop_delay(&mut self) {
        let sp = self.cpu.sp.wrapping_add(1);
        self.idle_read(0x0100 | sp as u16);
    }

    // --------------------------------------------------------- addressing ---

    #[inline]
    fn am_imm(&mut self) -> u16 {
        let pc = self.cpu.pc;
        self.cpu.pc = pc.wrapping_add(1);
        pc
    }
    #[inline]
    fn am_zp(&mut self) -> u16 {
        self.fetch() as u16
    }
    /// zp,X (4 cycles: dummy read of the un-indexed address first).
    #[inline]
    fn am_zpx(&mut self) -> u16 {
        let b = self.fetch();
        self.idle_read(b as u16);
        b.wrapping_add(self.cpu.x) as u16
    }
    /// zp,Y (4 cycles: dummy read of the un-indexed address first).
    #[inline]
    fn am_zpy(&mut self) -> u16 {
        let b = self.fetch();
        self.idle_read(b as u16);
        b.wrapping_add(self.cpu.y) as u16
    }
    #[inline]
    fn am_abs(&mut self) -> u16 {
        self.fetch16()
    }
    #[inline]
    fn am_absx(&mut self) -> u16 {
        let base = self.fetch16();
        let addr = base.wrapping_add(self.cpu.x as u16);
        if base & 0xFF00 != addr & 0xFF00 {
            self.idle_read((base & 0xFF00) | (addr & 0x00FF));
        }
        addr
    }
    #[inline]
    fn am_absy(&mut self) -> u16 {
        let base = self.fetch16();
        let addr = base.wrapping_add(self.cpu.y as u16);
        if base & 0xFF00 != addr & 0xFF00 {
            self.idle_read((base & 0xFF00) | (addr & 0x00FF));
        }
        addr
    }
    /// Indexed with an unconditional dummy read at the unfixed address
    /// (RMW ops and indexed stores).
    #[inline]
    fn am_absx_rmw(&mut self) -> u16 {
        let base = self.fetch16();
        let addr = base.wrapping_add(self.cpu.x as u16);
        self.idle_read((base & 0xFF00) | (addr & 0x00FF));
        addr
    }
    #[inline]
    fn am_absy_rmw(&mut self) -> u16 {
        let base = self.fetch16();
        let addr = base.wrapping_add(self.cpu.y as u16);
        self.idle_read((base & 0xFF00) | (addr & 0x00FF));
        addr
    }
    /// (zp,X): 4 cycles (dummy read of the un-indexed pointer address first).
    #[inline]
    fn am_indx(&mut self) -> u16 {
        let b = self.fetch();
        self.idle_read(b as u16);
        let p = b.wrapping_add(self.cpu.x);
        let lo = self.rd(p as u16) as u16;
        let hi = self.rd(p.wrapping_add(1) as u16) as u16;
        (hi << 8) | lo
    }

    #[inline]
    fn am_zpx_rmw(&mut self) -> u16 {
        self.am_zpx()
    }
    #[inline]
    fn am_indy(&mut self) -> u16 {
        let b = self.fetch();
        let lo = self.rd(b as u16) as u16;
        let hi = self.rd(b.wrapping_add(1) as u16) as u16;
        let base = (hi << 8) | lo;
        let addr = base.wrapping_add(self.cpu.y as u16);
        if base & 0xFF00 != addr & 0xFF00 {
            self.idle_read((base & 0xFF00) | (addr & 0x00FF));
        }
        addr
    }
    #[inline]
    fn am_indy_rmw(&mut self) -> u16 {
        let b = self.fetch();
        let lo = self.rd(b as u16) as u16;
        let hi = self.rd(b.wrapping_add(1) as u16) as u16;
        let base = (hi << 8) | lo;
        let addr = base.wrapping_add(self.cpu.y as u16);
        self.idle_read((base & 0xFF00) | (addr & 0x00FF));
        addr
    }

    // ---------------------------------------------------------- operations ---

    fn adc(&mut self, v: u8) {
        // The 2A03 has no decimal mode: the D flag is stored but the ALU always
        // adds in binary.
        let a = self.cpu.a;
        let carry = self.cpu.flag(FLAG_C) as u16;
        let sum = a as u16 + v as u16 + carry;
        let r = sum as u8;
        self.cpu.set_flag(FLAG_C, sum > 0xFF);
        let overflow = (!(a ^ v) & (a ^ r) & 0x80) != 0;
        self.cpu.set_flag(FLAG_V, overflow);
        self.cpu.a = r;
        self.cpu.set_zn(r);
    }

    fn sbc(&mut self, v: u8) {
        // As with ADC, decimal mode does not exist on the 2A03.
        let a = self.cpu.a;
        let carry = self.cpu.flag(FLAG_C) as u16;
        let diff = (a as u16).wrapping_sub(v as u16).wrapping_sub(1 - carry);
        let r = diff as u8;
        self.cpu.set_flag(FLAG_C, diff < 0x100);
        let overflow = ((a ^ v) & (a ^ r) & 0x80) != 0;
        self.cpu.set_flag(FLAG_V, overflow);
        self.cpu.a = r;
        self.cpu.set_zn(r);
    }

    fn cmp(&mut self, reg: u8, v: u8) {
        let r = reg.wrapping_sub(v);
        self.cpu.set_flag(FLAG_C, reg >= v);
        self.cpu.set_zn(r);
    }

    fn asl_value(&mut self, v: u8) -> u8 {
        self.cpu.set_flag(FLAG_C, v & 0x80 != 0);
        let r = v << 1;
        self.cpu.set_zn(r);
        r
    }
    fn lsr_value(&mut self, v: u8) -> u8 {
        self.cpu.set_flag(FLAG_C, v & 1 != 0);
        let r = v >> 1;
        self.cpu.set_zn(r);
        r
    }
    fn rol_value(&mut self, v: u8) -> u8 {
        let c = self.cpu.flag(FLAG_C) as u8;
        self.cpu.set_flag(FLAG_C, v & 0x80 != 0);
        let r = (v << 1) | c;
        self.cpu.set_zn(r);
        r
    }
    fn ror_value(&mut self, v: u8) -> u8 {
        let c = self.cpu.flag(FLAG_C) as u8;
        self.cpu.set_flag(FLAG_C, v & 1 != 0);
        let r = (v >> 1) | (c << 7);
        self.cpu.set_zn(r);
        r
    }
    fn inc_value(&mut self, v: u8) -> u8 {
        let r = v.wrapping_add(1);
        self.cpu.set_zn(r);
        r
    }
    fn dec_value(&mut self, v: u8) -> u8 {
        let r = v.wrapping_sub(1);
        self.cpu.set_zn(r);
        r
    }

    fn rmw_asl(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.asl_value(v);
        self.wr(addr, nv);
    }
    fn rmw_lsr(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.lsr_value(v);
        self.wr(addr, nv);
    }
    fn rmw_rol(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.rol_value(v);
        self.wr(addr, nv);
    }
    fn rmw_ror(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.ror_value(v);
        self.wr(addr, nv);
    }
    fn rmw_inc(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.inc_value(v);
        self.wr(addr, nv);
    }
    fn rmw_dec(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.dec_value(v);
        self.wr(addr, nv);
    }
    // Undocumented read-modify-write combinations.
    fn rmw_slo(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.asl_value(v);
        self.wr(addr, nv);
        let a = self.cpu.a;
        self.cpu.a = a | nv;
        self.cpu.set_zn(self.cpu.a);
    }
    fn rmw_rla(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.rol_value(v);
        self.wr(addr, nv);
        let a = self.cpu.a;
        self.cpu.a = a & nv;
        self.cpu.set_zn(self.cpu.a);
    }
    fn rmw_sre(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.lsr_value(v);
        self.wr(addr, nv);
        let a = self.cpu.a;
        self.cpu.a = a ^ nv;
        self.cpu.set_zn(self.cpu.a);
    }
    fn rmw_rra(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.ror_value(v);
        self.wr(addr, nv);
        self.adc(nv);
    }
    fn rmw_dcp(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.dec_value(v);
        self.wr(addr, nv);
        let a = self.cpu.a;
        self.cmp(a, nv);
    }
    fn rmw_isb(&mut self, addr: u16) {
        let v = self.rd(addr);
        self.wr(addr, v);
        let nv = self.inc_value(v);
        self.wr(addr, nv);
        self.sbc(nv);
    }

    // ------------------------------------------------------- interrupt ops ---

    /// IRQ/NMI/BRK sequence. `vector` is the target vector address.
    fn interrupt_sequence(&mut self, vector: u16, brk: bool) {
        self.cpu.in_interrupt = true;
        // BRK fetches its opcode first, so it only has one dummy read here.
        let pc = self.cpu.pc;
        if !brk {
            self.idle_read(pc);
        }
        self.idle_read(pc);
        let pc = self.cpu.pc;
        self.push((pc >> 8) as u8);
        self.push((pc & 0xFF) as u8);
        let pushed = if brk {
            self.cpu.p | FLAG_B | FLAG_U
        } else {
            (self.cpu.p & !FLAG_B) | FLAG_U
        };
        self.push(pushed);
        // NMI hijacking: if the NMI line is asserted before the vector is read,
        // the NMI vector is used instead.
        let mut vec = vector;
        if self.cpu.nmi_pending {
            vec = 0xFFFA;
            self.cpu.nmi_pending = false;
        }
        let lo = self.rd(vec) as u16;
        self.cpu.set_flag(FLAG_I, true);
        let hi = self.rd(vec + 1) as u16;
        self.cpu.pc = (hi << 8) | lo;
        self.cpu.in_interrupt = false;
        self.cpu.irq_seen = false;
    }

    pub(crate) fn reset_sequence(&mut self) {
        // 7 cycles: two dummy reads, three suppressed pushes, two vector reads.
        self.idle_read(self.cpu.pc);
        self.idle_read(self.cpu.pc);
        self.cpu.sp = self.cpu.sp.wrapping_sub(1);
        self.idle_read(0x0100 | self.cpu.sp as u16);
        self.cpu.sp = self.cpu.sp.wrapping_sub(1);
        self.idle_read(0x0100 | self.cpu.sp as u16);
        self.cpu.sp = self.cpu.sp.wrapping_sub(1);
        self.idle_read(0x0100 | self.cpu.sp as u16);
        let lo = self.rd(0xFFFC) as u16;
        let hi = self.rd(0xFFFD) as u16;
        self.cpu.pc = (hi << 8) | lo;
        // One extra cycle of PPU/APU warm-up: this reproduces the documented
        // power-on alignment (PPU at scanline 0, dot 25 at the first opcode fetch).
        self.idle_read(self.cpu.pc);
    }

    // ------------------------------------------------------------- stepping ---

    /// Execute one instruction (or service a pending interrupt).
    pub fn cpu_step(&mut self) {
        self.cpu.instr_cycles = 0;
        if self.cpu.jammed {
            // The CPU is frozen; the PPU/APU keep running.
            self.tick_cycle();
            return;
        }
        if self.cpu.nmi_pending {
            self.interrupt_sequence(0xFFFA, false);
            return;
        }
        if self.cpu.irq_seen {
            let line = self.irq_line();
            if line {
                self.interrupt_sequence(0xFFFE, false);
                return;
            }
            self.cpu.irq_seen = false;
        }
        self.cpu.irq_seen = false;
        self.cpu.irq_delay = false;
        let op = self.fetch();
        self.execute(op);
    }

    fn branch(&mut self, cond: bool) {
        let offset = self.fetch() as i8;
        if cond {
            let pc = self.cpu.pc;
            let addr = pc.wrapping_add(offset as u16);
            // Dummy read of the unfixed target address.
            self.idle_read((pc & 0xFF00) | (addr & 0x00FF));
            if addr & 0xFF00 != pc & 0xFF00 {
                // Crossed a page: one more cycle, reading the fixed address.
                self.idle_read(addr);
            }
            self.cpu.pc = addr;
        }
    }

    // ------------------------------------------------------- the opcode map ---

    fn execute(&mut self, op: u8) {
        match op {
            // ---- 0x00 BRK
            0x00 => {
                let pc = self.cpu.pc.wrapping_add(1);
                self.cpu.pc = pc;
                self.interrupt_sequence(0xFFFE, true);
            }
            // ---- ORA
            0x09 => {
                let a = self.am_imm();
                let v = self.rd(a);
                let r = self.cpu.a | v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x05 => {
                let a = self.am_zp();
                let v = self.rd(a);
                let r = self.cpu.a | v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x15 => {
                let a = self.am_zpx();
                let v = self.rd(a);
                let r = self.cpu.a | v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x0D => {
                let a = self.am_abs();
                let v = self.rd(a);
                let r = self.cpu.a | v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x1D => {
                let a = self.am_absx();
                let v = self.rd(a);
                let r = self.cpu.a | v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x19 => {
                let a = self.am_absy();
                let v = self.rd(a);
                let r = self.cpu.a | v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x01 => {
                let a = self.am_indx();
                let v = self.rd(a);
                let r = self.cpu.a | v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x11 => {
                let a = self.am_indy();
                let v = self.rd(a);
                let r = self.cpu.a | v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            // ---- AND
            0x29 => {
                let a = self.am_imm();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x25 => {
                let a = self.am_zp();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x35 => {
                let a = self.am_zpx();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x2D => {
                let a = self.am_abs();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x3D => {
                let a = self.am_absx();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x39 => {
                let a = self.am_absy();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x21 => {
                let a = self.am_indx();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x31 => {
                let a = self.am_indy();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            // ---- EOR
            0x49 => {
                let a = self.am_imm();
                let v = self.rd(a);
                let r = self.cpu.a ^ v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x45 => {
                let a = self.am_zp();
                let v = self.rd(a);
                let r = self.cpu.a ^ v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x55 => {
                let a = self.am_zpx();
                let v = self.rd(a);
                let r = self.cpu.a ^ v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x4D => {
                let a = self.am_abs();
                let v = self.rd(a);
                let r = self.cpu.a ^ v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x5D => {
                let a = self.am_absx();
                let v = self.rd(a);
                let r = self.cpu.a ^ v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x59 => {
                let a = self.am_absy();
                let v = self.rd(a);
                let r = self.cpu.a ^ v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x41 => {
                let a = self.am_indx();
                let v = self.rd(a);
                let r = self.cpu.a ^ v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0x51 => {
                let a = self.am_indy();
                let v = self.rd(a);
                let r = self.cpu.a ^ v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            // ---- ADC
            0x69 => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.adc(v);
            }
            0x65 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.adc(v);
            }
            0x75 => {
                let a = self.am_zpx();
                let v = self.rd(a);
                self.adc(v);
            }
            0x6D => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.adc(v);
            }
            0x7D => {
                let a = self.am_absx();
                let v = self.rd(a);
                self.adc(v);
            }
            0x79 => {
                let a = self.am_absy();
                let v = self.rd(a);
                self.adc(v);
            }
            0x61 => {
                let a = self.am_indx();
                let v = self.rd(a);
                self.adc(v);
            }
            0x71 => {
                let a = self.am_indy();
                let v = self.rd(a);
                self.adc(v);
            }
            // ---- SBC
            0xE9 => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.sbc(v);
            }
            0xEB => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.sbc(v);
            }
            0xE5 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.sbc(v);
            }
            0xF5 => {
                let a = self.am_zpx();
                let v = self.rd(a);
                self.sbc(v);
            }
            0xED => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.sbc(v);
            }
            0xFD => {
                let a = self.am_absx();
                let v = self.rd(a);
                self.sbc(v);
            }
            0xF9 => {
                let a = self.am_absy();
                let v = self.rd(a);
                self.sbc(v);
            }
            0xE1 => {
                let a = self.am_indx();
                let v = self.rd(a);
                self.sbc(v);
            }
            0xF1 => {
                let a = self.am_indy();
                let v = self.rd(a);
                self.sbc(v);
            }
            // ---- CMP / CPX / CPY
            0xC9 => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.cmp(self.cpu.a, v);
            }
            0xC5 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.cmp(self.cpu.a, v);
            }
            0xD5 => {
                let a = self.am_zpx();
                let v = self.rd(a);
                self.cmp(self.cpu.a, v);
            }
            0xCD => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.cmp(self.cpu.a, v);
            }
            0xDD => {
                let a = self.am_absx();
                let v = self.rd(a);
                self.cmp(self.cpu.a, v);
            }
            0xD9 => {
                let a = self.am_absy();
                let v = self.rd(a);
                self.cmp(self.cpu.a, v);
            }
            0xC1 => {
                let a = self.am_indx();
                let v = self.rd(a);
                self.cmp(self.cpu.a, v);
            }
            0xD1 => {
                let a = self.am_indy();
                let v = self.rd(a);
                self.cmp(self.cpu.a, v);
            }
            0xE0 => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.cmp(self.cpu.x, v);
            }
            0xE4 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.cmp(self.cpu.x, v);
            }
            0xEC => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.cmp(self.cpu.x, v);
            }
            0xC0 => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.cmp(self.cpu.y, v);
            }
            0xC4 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.cmp(self.cpu.y, v);
            }
            0xCC => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.cmp(self.cpu.y, v);
            }
            // ---- LDA
            0xA9 => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            0xA5 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            0xB5 => {
                let a = self.am_zpx();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            0xAD => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            0xBD => {
                let a = self.am_absx();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            0xB9 => {
                let a = self.am_absy();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            0xA1 => {
                let a = self.am_indx();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            0xB1 => {
                let a = self.am_indy();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            // ---- LDX
            0xA2 => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xA6 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xB6 => {
                let a = self.am_zpy();
                let v = self.rd(a);
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xAE => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xBE => {
                let a = self.am_absy();
                let v = self.rd(a);
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            // ---- LDY
            0xA0 => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.cpu.y = v;
                self.cpu.set_zn(v);
            }
            0xA4 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.cpu.y = v;
                self.cpu.set_zn(v);
            }
            0xB4 => {
                let a = self.am_zpx();
                let v = self.rd(a);
                self.cpu.y = v;
                self.cpu.set_zn(v);
            }
            0xAC => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.cpu.y = v;
                self.cpu.set_zn(v);
            }
            0xBC => {
                let a = self.am_absx();
                let v = self.rd(a);
                self.cpu.y = v;
                self.cpu.set_zn(v);
            }
            // ---- STA
            0x85 => {
                let a = self.am_zp();
                self.wr(a, self.cpu.a);
            }
            0x95 => {
                let a = self.am_zpx();
                self.wr(a, self.cpu.a);
            }
            0x8D => {
                let a = self.am_abs();
                self.wr(a, self.cpu.a);
            }
            0x9D => {
                let a = self.am_absx_rmw();
                self.wr(a, self.cpu.a);
            }
            0x99 => {
                let a = self.am_absy_rmw();
                self.wr(a, self.cpu.a);
            }
            0x81 => {
                let a = self.am_indx();
                self.wr(a, self.cpu.a);
            }
            0x91 => {
                let a = self.am_indy_rmw();
                self.wr(a, self.cpu.a);
            }
            // ---- STX / STY
            0x86 => {
                let a = self.am_zp();
                self.wr(a, self.cpu.x);
            }
            0x96 => {
                let a = self.am_zpy();
                self.wr(a, self.cpu.x);
            }
            0x8E => {
                let a = self.am_abs();
                self.wr(a, self.cpu.x);
            }
            0x84 => {
                let a = self.am_zp();
                self.wr(a, self.cpu.y);
            }
            0x94 => {
                let a = self.am_zpx();
                self.wr(a, self.cpu.y);
            }
            0x8C => {
                let a = self.am_abs();
                self.wr(a, self.cpu.y);
            }
            // ---- RMW
            0x0A => {
                self.implied();
                let a = self.cpu.a;
                let r = self.asl_value(a);
                self.cpu.a = r;
            }
            0x06 => {
                let a = self.am_zp();
                self.rmw_asl(a);
            }
            0x16 => {
                let a = self.am_zpx_rmw();
                self.rmw_asl(a);
            }
            0x0E => {
                let a = self.am_abs();
                self.rmw_asl(a);
            }
            0x1E => {
                let a = self.am_absx_rmw();
                self.rmw_asl(a);
            }
            0x4A => {
                self.implied();
                let a = self.cpu.a;
                let r = self.lsr_value(a);
                self.cpu.a = r;
            }
            0x46 => {
                let a = self.am_zp();
                self.rmw_lsr(a);
            }
            0x56 => {
                let a = self.am_zpx_rmw();
                self.rmw_lsr(a);
            }
            0x4E => {
                let a = self.am_abs();
                self.rmw_lsr(a);
            }
            0x5E => {
                let a = self.am_absx_rmw();
                self.rmw_lsr(a);
            }
            0x2A => {
                self.implied();
                let a = self.cpu.a;
                let r = self.rol_value(a);
                self.cpu.a = r;
            }
            0x26 => {
                let a = self.am_zp();
                self.rmw_rol(a);
            }
            0x36 => {
                let a = self.am_zpx_rmw();
                self.rmw_rol(a);
            }
            0x2E => {
                let a = self.am_abs();
                self.rmw_rol(a);
            }
            0x3E => {
                let a = self.am_absx_rmw();
                self.rmw_rol(a);
            }
            0x6A => {
                self.implied();
                let a = self.cpu.a;
                let r = self.ror_value(a);
                self.cpu.a = r;
            }
            0x66 => {
                let a = self.am_zp();
                self.rmw_ror(a);
            }
            0x76 => {
                let a = self.am_zpx_rmw();
                self.rmw_ror(a);
            }
            0x6E => {
                let a = self.am_abs();
                self.rmw_ror(a);
            }
            0x7E => {
                let a = self.am_absx_rmw();
                self.rmw_ror(a);
            }
            0xE6 => {
                let a = self.am_zp();
                self.rmw_inc(a);
            }
            0xF6 => {
                let a = self.am_zpx_rmw();
                self.rmw_inc(a);
            }
            0xEE => {
                let a = self.am_abs();
                self.rmw_inc(a);
            }
            0xFE => {
                let a = self.am_absx_rmw();
                self.rmw_inc(a);
            }
            0xC6 => {
                let a = self.am_zp();
                self.rmw_dec(a);
            }
            0xD6 => {
                let a = self.am_zpx_rmw();
                self.rmw_dec(a);
            }
            0xCE => {
                let a = self.am_abs();
                self.rmw_dec(a);
            }
            0xDE => {
                let a = self.am_absx_rmw();
                self.rmw_dec(a);
            }
            // ---- BIT
            0x24 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.bit(v);
            }
            0x2C => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.bit(v);
            }
            // ---- JMP / JSR / RTS / RTI
            0x4C => {
                self.cpu.pc = self.fetch16();
            }
            0x6C => {
                let ptr = self.fetch16();
                let lo = self.rd(ptr) as u16;
                let hi_addr = (ptr & 0xFF00) | ((ptr.wrapping_add(1)) & 0x00FF);
                let hi = self.rd(hi_addr) as u16;
                self.cpu.pc = (hi << 8) | lo;
            }
            0x20 => {
                let lo = self.fetch();
                let sp = self.cpu.sp;
                self.idle_read(0x0100 | sp as u16);
                let ret = self.cpu.pc;
                self.push((ret >> 8) as u8);
                self.push((ret & 0xFF) as u8);
                let hi = self.fetch();
                self.cpu.pc = ((hi as u16) << 8) | lo as u16;
            }
            0x60 => {
                self.implied();
                self.push_pop_delay();
                let lo = self.pop() as u16;
                let hi = self.pop() as u16;
                let pc = ((hi << 8) | lo).wrapping_add(1);
                self.cpu.pc = pc;
                self.idle_read(pc);
            }
            0x40 => {
                self.implied();
                self.push_pop_delay();
                let p = self.pop();
                self.cpu.p = (p & !FLAG_B) | FLAG_U;
                let lo = self.pop() as u16;
                let hi = self.pop() as u16;
                self.cpu.pc = (hi << 8) | lo;

            }
            // ---- Branches
            0x10 => self.branch(!self.cpu.flag(FLAG_N)),
            0x30 => self.branch(self.cpu.flag(FLAG_N)),
            0x50 => self.branch(!self.cpu.flag(FLAG_V)),
            0x70 => self.branch(self.cpu.flag(FLAG_V)),
            0x90 => self.branch(!self.cpu.flag(FLAG_C)),
            0xB0 => self.branch(self.cpu.flag(FLAG_C)),
            0xD0 => self.branch(!self.cpu.flag(FLAG_Z)),
            0xF0 => self.branch(self.cpu.flag(FLAG_Z)),
            // ---- Flags
            0x18 => {
                self.implied();
                self.cpu.set_flag(FLAG_C, false);
            }
            0x38 => {
                self.implied();
                self.cpu.set_flag(FLAG_C, true);
            }
            0x58 => {
                self.implied();
                self.cpu.set_flag(FLAG_I, false);
            }
            0x78 => {
                self.implied();
                self.cpu.set_flag(FLAG_I, true);
            }
            0xB8 => {
                self.implied();
                self.cpu.set_flag(FLAG_V, false);
            }
            0xD8 => {
                self.implied();
                self.cpu.set_flag(FLAG_D, false);
            }
            0xF8 => {
                self.implied();
                self.cpu.set_flag(FLAG_D, true);
            }
            0xEA => self.implied(),
            // ---- Transfers / stack
            0xAA => {
                self.implied();
                self.cpu.x = self.cpu.a;
                let v = self.cpu.x;
                self.cpu.set_zn(v);
            }
            0xA8 => {
                self.implied();
                self.cpu.y = self.cpu.a;
                let v = self.cpu.y;
                self.cpu.set_zn(v);
            }
            0x8A => {
                self.implied();
                self.cpu.a = self.cpu.x;
                let v = self.cpu.a;
                self.cpu.set_zn(v);
            }
            0x98 => {
                self.implied();
                self.cpu.a = self.cpu.y;
                let v = self.cpu.a;
                self.cpu.set_zn(v);
            }
            0xBA => {
                self.implied();
                self.cpu.x = self.cpu.sp;
                let v = self.cpu.x;
                self.cpu.set_zn(v);
            }
            0x9A => {
                self.implied();
                self.cpu.sp = self.cpu.x;
            }
            0xE8 => {
                self.implied();
                let v = self.cpu.x.wrapping_add(1);
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xCA => {
                self.implied();
                let v = self.cpu.x.wrapping_sub(1);
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xC8 => {
                self.implied();
                let v = self.cpu.y.wrapping_add(1);
                self.cpu.y = v;
                self.cpu.set_zn(v);
            }
            0x88 => {
                self.implied();
                let v = self.cpu.y.wrapping_sub(1);
                self.cpu.y = v;
                self.cpu.set_zn(v);
            }
            0x08 => {
                self.implied();
                let p = self.cpu.p | FLAG_B | FLAG_U;
                self.push(p);
            }
            0x28 => {
                self.implied();
                self.push_pop_delay();
                let p = self.pop();
                self.cpu.p = (p & !FLAG_B) | FLAG_U;
            }
            0x48 => {
                self.implied();
                let a = self.cpu.a;
                self.push(a);
            }
            0x68 => {
                self.implied();
                self.push_pop_delay();
                let v = self.pop();
                self.cpu.a = v;
                self.cpu.set_zn(v);
            }
            // ---- Illegal NOPs (implied / immediate)
            0x1A | 0x3A | 0x5A | 0x7A | 0xDA | 0xFA => self.implied(),
            0x80 | 0x82 | 0x89 | 0xC2 | 0xE2 => {
                // NOP #imm: four variants, each 2 cycles (the operand read).
                let a = self.am_imm();
                let _ = self.rd(a);
            }
            0x04 | 0x44 | 0x64 => {
                let a = self.am_zp();
                let _ = self.rd(a);
            }
            0x14 | 0x34 | 0x54 | 0x74 | 0xD4 | 0xF4 => {
                let a = self.am_zpx();
                let _ = self.rd(a);
            }
            0x0C => {
                let a = self.am_abs();
                let _ = self.rd(a);
            }
            0x1C | 0x3C | 0x5C | 0x7C | 0xDC | 0xFC => {
                let a = self.am_absx();
                let _ = self.rd(a);
            }
            // ---- LAX
            0xA7 => {
                let a = self.am_zp();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xB7 => {
                let a = self.am_zpy();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xAF => {
                let a = self.am_abs();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xBF => {
                let a = self.am_absy();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xA3 => {
                let a = self.am_indx();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xB3 => {
                let a = self.am_indy();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            0xAB => {
                let a = self.am_imm();
                let v = self.rd(a);
                self.cpu.a = v;
                self.cpu.x = v;
                self.cpu.set_zn(v);
            }
            // ---- SAX
            0x87 => {
                let a = self.am_zp();
                let v = self.cpu.a & self.cpu.x;
                self.wr(a, v);
            }
            0x97 => {
                let a = self.am_zpy();
                let v = self.cpu.a & self.cpu.x;
                self.wr(a, v);
            }
            0x8F => {
                let a = self.am_abs();
                let v = self.cpu.a & self.cpu.x;
                self.wr(a, v);
            }
            0x83 => {
                let a = self.am_indx();
                let v = self.cpu.a & self.cpu.x;
                self.wr(a, v);
            }
            // ---- SLO
            0x07 => {
                let a = self.am_zp();
                self.rmw_slo(a);
            }
            0x17 => {
                let a = self.am_zpx_rmw();
                self.rmw_slo(a);
            }
            0x0F => {
                let a = self.am_abs();
                self.rmw_slo(a);
            }
            0x1F => {
                let a = self.am_absx_rmw();
                self.rmw_slo(a);
            }
            0x1B => {
                let a = self.am_absy_rmw();
                self.rmw_slo(a);
            }
            0x03 => {
                let a = self.am_indx();
                self.rmw_slo(a);
            }
            0x13 => {
                let a = self.am_indy_rmw();
                self.rmw_slo(a);
            }
            // ---- RLA
            0x27 => {
                let a = self.am_zp();
                self.rmw_rla(a);
            }
            0x37 => {
                let a = self.am_zpx_rmw();
                self.rmw_rla(a);
            }
            0x2F => {
                let a = self.am_abs();
                self.rmw_rla(a);
            }
            0x3F => {
                let a = self.am_absx_rmw();
                self.rmw_rla(a);
            }
            0x3B => {
                let a = self.am_absy_rmw();
                self.rmw_rla(a);
            }
            0x23 => {
                let a = self.am_indx();
                self.rmw_rla(a);
            }
            0x33 => {
                let a = self.am_indy_rmw();
                self.rmw_rla(a);
            }
            // ---- SRE
            0x47 => {
                let a = self.am_zp();
                self.rmw_sre(a);
            }
            0x57 => {
                let a = self.am_zpx_rmw();
                self.rmw_sre(a);
            }
            0x4F => {
                let a = self.am_abs();
                self.rmw_sre(a);
            }
            0x5F => {
                let a = self.am_absx_rmw();
                self.rmw_sre(a);
            }
            0x5B => {
                let a = self.am_absy_rmw();
                self.rmw_sre(a);
            }
            0x43 => {
                let a = self.am_indx();
                self.rmw_sre(a);
            }
            0x53 => {
                let a = self.am_indy_rmw();
                self.rmw_sre(a);
            }
            // ---- RRA
            0x67 => {
                let a = self.am_zp();
                self.rmw_rra(a);
            }
            0x77 => {
                let a = self.am_zpx_rmw();
                self.rmw_rra(a);
            }
            0x6F => {
                let a = self.am_abs();
                self.rmw_rra(a);
            }
            0x7F => {
                let a = self.am_absx_rmw();
                self.rmw_rra(a);
            }
            0x7B => {
                let a = self.am_absy_rmw();
                self.rmw_rra(a);
            }
            0x63 => {
                let a = self.am_indx();
                self.rmw_rra(a);
            }
            0x73 => {
                let a = self.am_indy_rmw();
                self.rmw_rra(a);
            }
            // ---- DCP
            0xC7 => {
                let a = self.am_zp();
                self.rmw_dcp(a);
            }
            0xD7 => {
                let a = self.am_zpx_rmw();
                self.rmw_dcp(a);
            }
            0xCF => {
                let a = self.am_abs();
                self.rmw_dcp(a);
            }
            0xDF => {
                let a = self.am_absx_rmw();
                self.rmw_dcp(a);
            }
            0xDB => {
                let a = self.am_absy_rmw();
                self.rmw_dcp(a);
            }
            0xC3 => {
                let a = self.am_indx();
                self.rmw_dcp(a);
            }
            0xD3 => {
                let a = self.am_indy_rmw();
                self.rmw_dcp(a);
            }
            // ---- ISB / ISC
            0xE7 => {
                let a = self.am_zp();
                self.rmw_isb(a);
            }
            0xF7 => {
                let a = self.am_zpx_rmw();
                self.rmw_isb(a);
            }
            0xEF => {
                let a = self.am_abs();
                self.rmw_isb(a);
            }
            0xFF => {
                let a = self.am_absx_rmw();
                self.rmw_isb(a);
            }
            0xFB => {
                let a = self.am_absy_rmw();
                self.rmw_isb(a);
            }
            0xE3 => {
                let a = self.am_indx();
                self.rmw_isb(a);
            }
            0xF3 => {
                let a = self.am_indy_rmw();
                self.rmw_isb(a);
            }
            // ---- ANC / ALR / ARR / ANE / SBX / LAS / TAS / SHY / SHX / SHA
            0x0B | 0x2B => {
                let a = self.am_imm();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
                self.cpu.set_flag(FLAG_C, r & 0x80 != 0);
            }
            0x4B => {
                let a = self.am_imm();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                let r = self.lsr_value(r);
                self.cpu.a = r;
            }
            0x6B => {
                let a = self.am_imm();
                let v = self.rd(a);
                let r = self.cpu.a & v;
                let c = self.cpu.flag(FLAG_C) as u8;
                let r = (r >> 1) | (c << 7);
                self.cpu.a = r;
                self.cpu.set_zn(r);
                self.cpu.set_flag(FLAG_C, r & 0x40 != 0);
                self.cpu
                    .set_flag(FLAG_V, ((r & 0x40) >> 6) ^ ((r & 0x20) >> 5) != 0);
            }
            0x8B => {
                let a = self.am_imm();
                let v = self.rd(a);
                let r = (self.cpu.a | 0xEE) & self.cpu.x & v;
                self.cpu.a = r;
                self.cpu.set_zn(r);
            }
            0xCB => {
                let a = self.am_imm();
                let v = self.rd(a);
                let t = self.cpu.a & self.cpu.x;
                self.cpu.set_flag(FLAG_C, t >= v);
                let r = t.wrapping_sub(v);
                self.cpu.x = r;
                self.cpu.set_zn(r);
            }
            0xBB => {
                let a = self.am_absy();
                let v = self.rd(a);
                let r = v & self.cpu.sp;
                self.cpu.a = r;
                self.cpu.x = r;
                self.cpu.sp = r;
                self.cpu.set_zn(r);
            }
            0x9B => {
                let a = self.am_absy_rmw();
                let r = self.cpu.a & self.cpu.x & ((a >> 8) as u8).wrapping_add(1);
                let sp = self.cpu.sp;
                self.wr(a, r);
                self.cpu.sp = r & self.cpu.a & self.cpu.x;
                let _ = sp;
            }
            0x9C => {
                let a = self.am_absx_rmw();
                let r = self.cpu.y & ((a >> 8) as u8).wrapping_add(1);
                self.wr(a, r);
            }
            0x9E => {
                let a = self.am_absy_rmw();
                let r = self.cpu.x & ((a >> 8) as u8).wrapping_add(1);
                self.wr(a, r);
            }
            0x9F => {
                let a = self.am_absy_rmw();
                let hi = ((a >> 8) as u8).wrapping_add(1);
                let r = self.cpu.a & self.cpu.x & hi;
                self.wr(a, r);
            }
            0x93 => {
                let a = self.am_indy_rmw();
                let hi = ((a >> 8) as u8).wrapping_add(1);
                let r = self.cpu.a & self.cpu.x & hi;
                self.wr(a, r);
            }
            // ---- JAM / KIL
            0x02 | 0x12 | 0x22 | 0x32 | 0x42 | 0x52 | 0x62 | 0x72 | 0x92 | 0xB2 | 0xD2 | 0xF2 => {
                #[cfg(feature = "trace")]
                {
                    if std::env::var("TRACE_JAM").is_ok() {
                        eprintln!("JAM at {:04X} cycle {}", self.cpu.pc.wrapping_sub(1), self.cycles);
                        eprintln!("history: {}", self.hist.iter().map(|x| format!("{:04X}", x)).collect::<Vec<_>>().join(" "));
                    }
                }
                self.cpu.jammed = true;
            }
        }
    }

    fn bit(&mut self, v: u8) {
        let a = self.cpu.a;
        self.cpu.set_flag(FLAG_Z, a & v == 0);
        self.cpu.set_flag(FLAG_V, v & 0x40 != 0);
        self.cpu.set_flag(FLAG_N, v & 0x80 != 0);
    }
}
