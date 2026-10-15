//! NES emulator wasm ABI (see spec/ABI.md).

#![allow(clippy::missing_safety_doc)]

pub mod apu;
pub mod cpu;
pub mod ines;
pub mod mapper;
pub mod ppu;
pub mod system;

use core::ffi::c_int;
use system::System;

const ROM_BUFFER_SIZE: usize = 8 * 1024 * 1024;

pub struct Emu {
    pub system: System,
    pub rom: Vec<u8>,
    pub audio: Vec<i16>,
}

static mut EMU: *mut Emu = core::ptr::null_mut();

#[inline]
fn emu() -> &'static mut Emu {
    unsafe {
        if EMU.is_null() {
            let mut rom = Vec::new();
            rom.resize(ROM_BUFFER_SIZE, 0);
            let e = Box::new(Emu {
                system: System::new(Box::new(mapper::Null)),
                rom,
                audio: Vec::with_capacity(16384),
            });
            EMU = Box::into_raw(e);
        }
        &mut *EMU
    }
}

#[no_mangle]
pub extern "C" fn emu_init() -> c_int {
    let _ = emu();
    1
}

#[no_mangle]
pub extern "C" fn emu_rom_buffer() -> *mut u8 {
    emu().rom.as_mut_ptr()
}

#[no_mangle]
pub extern "C" fn emu_load_rom(len: c_int) -> c_int {
    let e = emu();
    if len <= 0 || len as usize > ROM_BUFFER_SIZE {
        return 0;
    }
    let bytes = &e.rom[..len as usize];
    match ines::Cart::parse(bytes) {
        Some(cart) => match mapper::make_mapper(&cart) {
            Some(m) => {
                e.system = System::new(m);
                e.audio.clear();
                1
            }
            None => 0,
        },
        None => 0,
    }
}

#[no_mangle]
pub extern "C" fn emu_reset() -> c_int {
    let e = emu();
    e.system.power_on();
    e.audio.clear();
    1
}

#[no_mangle]
pub extern "C" fn emu_set_keys(k: u32) {
    let e = emu();
    e.system.keys[0] = k as u8;
    e.system.keys[1] = (k >> 8) as u8;
}

#[no_mangle]
pub extern "C" fn emu_run_frame() {
    let e = emu();
    e.system.run_frame();
    e.audio.extend_from_slice(&e.system.out);
    e.system.out.clear();
}

#[no_mangle]
pub extern "C" fn emu_framebuffer() -> *mut u16 {
    emu().system.ppu.fb.as_mut_ptr()
}

#[no_mangle]
pub extern "C" fn emu_audio_buffer() -> *mut i16 {
    let e = emu();
    if e.audio.capacity() == 0 {
        e.audio.reserve(16384);
    }
    e.audio.as_mut_ptr()
}

#[no_mangle]
pub extern "C" fn emu_audio_samples() -> c_int {
    let e = emu();
    let n = e.audio.len() as c_int;
    e.audio.clear();
    n
}

#[no_mangle]
pub extern "C" fn emu_audio_rate() -> c_int {
    44100
}
