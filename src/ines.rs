//! iNES / NES 2.0 ROM image parsing.

pub const MIRROR_HORIZONTAL: u8 = 0;
pub const MIRROR_VERTICAL: u8 = 1;
pub const MIRROR_FOUR: u8 = 2;
pub const MIRROR_ONE_LOW: u8 = 3;
pub const MIRROR_ONE_HIGH: u8 = 4;

pub struct Cart {
    pub prg_rom: Vec<u8>,
    pub chr_rom: Vec<u8>, // empty => CHR RAM
    pub chr_ram_size: usize,
    pub prg_ram_size: usize,
    pub mapper: u16,
    pub submapper: u8,
    pub mirroring: u8,
    pub battery: bool,
    pub version2: bool,
}

fn pow2_or_mult(size_byte: u8, unit: usize) -> usize {
    // NES 2.0 size encoding when size==0xF (exponent form) is handled by caller.
    (size_byte as usize) * unit
}

impl Cart {
    pub fn parse(buf: &[u8]) -> Option<Cart> {
        if buf.len() < 16 || &buf[0..4] != b"NES\x1a" {
            return None;
        }
        let flags6 = buf[6];
        let flags7 = buf[7];
        let version2 = (flags7 & 0x0C) == 0x08;
        let mapper = ((flags7 & 0xF0) as u16) | ((flags6 >> 4) as u16);

        let mut prg_size = pow2_or_mult(buf[4], 16384);
        let mut chr_size = pow2_or_mult(buf[5], 8192);
        let mut prg_ram_size = 8192usize;
        let mut submapper = 0u8;
        let mut mirroring = flags6 & 0x01;

        if version2 {
            submapper = (buf[8] >> 4) & 0x0F;
            // mapper high bits
            let mut m = mapper;
            m |= ((buf[8] & 0x0F) as u16) << 8;
            let _ = m;
            // PRG/CHR size
            let prg_low = buf[4];
            let chr_low = buf[5];
            if prg_low == 0x0F {
                let e = (buf[9] & 0x0F) as u32;
                prg_size = if e == 0 {
                    0
                } else {
                    let mult = (buf[9] & 0x0F) as usize;
                    let exp = ((buf[9] & 0xF0) >> 4) as u32;
                    // size = 2^exp * (mult*2 + 1) * 256
                    (1usize << (exp + 1)) * ((mult * 2 + 1) as usize) * 128
                };
            } else {
                prg_size = (prg_low as usize) * 16384;
            }
            if chr_low == 0x0F {
                let mult = (buf[9] & 0x0F) as usize;
                let exp = ((buf[9] & 0xF0) >> 4) as u32;
                chr_size = (1usize << (exp + 1)) * (mult * 2 + 1) * 128;
            } else {
                chr_size = (chr_low as usize) * 8192;
            }
            prg_ram_size = match buf[10] & 0x0F {
                0 => 0,
                n => (64usize << n) / 8,
            };
            if buf[10] & 0x0F == 0 && (buf[10] >> 4) != 0 {
                prg_ram_size = match buf[10] >> 4 {
                    n => (64usize << n) / 8,
                };
            }
            // mirroring
            let mirror_bits = flags6 & 0x0F;
            match mirror_bits & 0x08 {
                0 => mirroring = mirror_bits & 0x01,
                _ => mirroring = MIRROR_FOUR,
            }
        } else {
            if flags6 & 0x08 != 0 {
                mirroring = MIRROR_FOUR;
            }
        }

        let mut off = 16usize;
        if flags6 & 0x04 != 0 {
            // trainer present
            off += 512;
        }
        if buggy_prg_size_set(&buf[..]) {
            // nothing
        }
        if prg_size == 0 {
            // Some iNES 1.0 images rely on the file size.
            if buf.len() > off {
                prg_size = ((buf.len() - off) / 16384).max(1) * 16384;
            }
        }
        if off + prg_size > buf.len() {
            // Truncated image: clamp so we never index out of bounds.
            prg_size = prg_size.min(buf.len().saturating_sub(off));
            prg_size -= prg_size % 16384;
            if prg_size == 0 {
                return None;
            }
        }
        let prg_rom = buf[off..off + prg_size].to_vec();
        off += prg_size;

        let mut chr_rom = Vec::new();
        let mut used_chr_rom = chr_size;
        if off + chr_size > buf.len() {
            used_chr_rom = buf.len().saturating_sub(off);
        }
        if used_chr_rom >= 8192 {
            chr_rom = buf[off..off + used_chr_rom].to_vec();
        }
        let chr_ram_size = if chr_rom.is_empty() {
            if chr_size == 0 {
                8192
            } else {
                chr_size.max(8192)
            }
        } else {
            0
        };

        // Mappers 1 and 4 always have at least 8 KiB of PRG-RAM (per spec/ABI.md).
        if (mapper == 1 || mapper == 4) && prg_ram_size < 8192 {
            prg_ram_size = 8192;
        } else if prg_ram_size == 0 {
            // Base NES: $6000-$7FFF work RAM even if the header declares none.
            prg_ram_size = 8192;
        }

        Some(Cart {
            prg_rom,
            chr_rom,
            chr_ram_size,
            prg_ram_size,
            mapper,
            submapper,
            mirroring,
            battery: flags6 & 0x02 != 0,
            version2,
        })
    }
}

fn buggy_prg_size_set(_buf: &[u8]) -> bool {
    false
}
