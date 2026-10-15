//! Development harness: run a ROM natively and dump frames/audio for comparison
//! against the reference emulator's output.

use nes_emu::ines::Cart;
use nes_emu::mapper::make_mapper;
use nes_emu::system::System;
use std::io::Write;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        eprintln!("usage: nesrun <rom> <frames> [--out DIR] [--wav FILE] [--keys HEX] [--from N] [--print-frame N] [--bench]");
        std::process::exit(2);
    }
    let rom_path = &args[1];
    let frames: u64 = args[2].parse().expect("frames");
    let mut out_dir: Option<String> = None;
    let mut wav: Option<String> = None;
    let mut keys: u32 = 0;
    let mut from: u64 = 0;
    let mut bench = false;
    let mut i = 3;
    while i < args.len() {
        match args[i].as_str() {
            "--out" => {
                out_dir = Some(args[i + 1].clone());
                i += 2;
            }
            "--wav" => {
                wav = Some(args[i + 1].clone());
                i += 2;
            }
            "--keys" => {
                keys = u32::from_str_radix(&args[i + 1], 16).expect("keys");
                i += 2;
            }
            "--from" => {
                from = args[i + 1].parse().expect("from");
                i += 2;
            }
            "--state" => {
                i += 1;
            }
            "--palette" => {
                i += 1;
            }
            "--bench" => {
                bench = true;
                i += 1;
            }
            other => {
                eprintln!("unknown arg {}", other);
                std::process::exit(2);
            }
        }
    }

    let data = std::fs::read(rom_path).expect("read rom");
    let cart = Cart::parse(&data).expect("parse rom");
    let mapper = make_mapper(&cart).expect("mapper");
    let mut sys = System::new(mapper);
    sys.keys[0] = keys as u8;

    if let Some(dir) = &out_dir {
        std::fs::create_dir_all(dir).ok();
    }

    let mut all_audio: Vec<i16> = Vec::new();
    let start = std::time::Instant::now();
    for f in 0..frames {
        sys.run_frame();
        if f >= from {
            if let Some(dir) = &out_dir {
                let mut buf: Vec<u8> = Vec::with_capacity(61440 * 2);
                for v in sys.ppu.fb.iter() {
                    buf.push((v & 0xFF) as u8);
                    buf.push((v >> 8) as u8);
                }
                let path = format!("{}/frame_{:05}.idx", dir, f);
                std::fs::write(path, &buf).ok();
            }
            if wav.is_some() {
                all_audio.extend_from_slice(&sys.out);
            }
        }
        sys.out.clear();
        if std::env::args().any(|a| a == "--palette") {
            eprintln!("frame {}: pal0={:02X} {:02X} {:02X} {:02X} v={:04X} mask={:02X} fb[0]={:04X}",
                f, sys.ppu.palette[0], sys.ppu.palette[1], sys.ppu.palette[2], sys.ppu.palette[3],
                sys.ppu.v, sys.ppu.mask, sys.ppu.fb[0]);
        }
        if std::env::args().any(|a| a == "--state") {
            eprintln!("frame {}: cycles={} pc={:04X} ppu ctrl={:02X} mask={:02X} v={:04X} t={:04X} sl={} dot={}",
                f, sys.cycles, sys.cpu.pc, sys.ppu.ctrl, sys.ppu.mask, sys.ppu.v, sys.ppu.t, sys.ppu.scanline, sys.ppu.dot);
        }
    }
    let elapsed = start.elapsed();
    if bench {
        eprintln!(
            "{} frames in {:.3}s ({:.1} fps)",
            frames,
            elapsed.as_secs_f64(),
            frames as f64 / elapsed.as_secs_f64()
        );
    }

    if let Some(path) = &wav {
        let mut f = std::fs::File::create(path).expect("create wav");
        let data_len = (all_audio.len() * 2) as u32;
        f.write_all(b"RIFF").unwrap();
        f.write_all(&(36 + data_len).to_le_bytes()).unwrap();
        f.write_all(b"WAVEfmt ").unwrap();
        f.write_all(&16u32.to_le_bytes()).unwrap();
        f.write_all(&1u16.to_le_bytes()).unwrap();
        f.write_all(&1u16.to_le_bytes()).unwrap();
        f.write_all(&44100u32.to_le_bytes()).unwrap();
        f.write_all(&88200u32.to_le_bytes()).unwrap();
        f.write_all(&2u16.to_le_bytes()).unwrap();
        f.write_all(&16u16.to_le_bytes()).unwrap();
        f.write_all(b"data").unwrap();
        f.write_all(&data_len.to_le_bytes()).unwrap();
        for s in &all_audio {
            f.write_all(&s.to_le_bytes()).unwrap();
        }
    }
}
