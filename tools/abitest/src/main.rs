use std::process::exit;
use wasmtime::*;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 4 {
        eprintln!("usage: abitest <wasm> <rom> <frames>");
        exit(2);
    }
    let (wasm_path, rom_path, frames) = (&args[1], &args[2], args[3].parse::<u32>().unwrap());
    let engine = Engine::default();
    let module = Module::from_file(&engine, wasm_path).expect("load wasm");
    let mut store = Store::new(&engine, ());
    let instance = Instance::new(&mut store, &module, &[]).expect("instantiate");

    let memory = instance.get_memory(&mut store, "memory").expect("memory export");
    let emu_init = instance.get_typed_func::<(), i32>(&mut store, "emu_init").unwrap();
    let rom_buffer = instance.get_typed_func::<(), i32>(&mut store, "emu_rom_buffer").unwrap();
    let load_rom = instance.get_typed_func::<i32, i32>(&mut store, "emu_load_rom").unwrap();
    let reset = instance.get_typed_func::<(), i32>(&mut store, "emu_reset").unwrap();
    let set_keys = instance.get_typed_func::<u32, ()>(&mut store, "emu_set_keys").unwrap();
    let run_frame = instance.get_typed_func::<(), ()>(&mut store, "emu_run_frame").unwrap();
    let framebuffer = instance.get_typed_func::<(), i32>(&mut store, "emu_framebuffer").unwrap();
    let audio_buffer = instance.get_typed_func::<(), i32>(&mut store, "emu_audio_buffer").unwrap();
    let audio_samples = instance.get_typed_func::<(), i32>(&mut store, "emu_audio_samples").unwrap();
    let audio_rate = instance.get_typed_func::<(), i32>(&mut store, "emu_audio_rate").unwrap();

    assert_eq!(emu_init.call(&mut store, ()).unwrap(), 1, "emu_init");
    let rom_buf = rom_buffer.call(&mut store, ()).unwrap();
    let data = std::fs::read(rom_path).expect("read rom");
    assert!(data.len() < 8 * 1024 * 1024, "rom too large");
    {
        let mem = memory.data_mut(&mut store);
        mem[rom_buf as usize..rom_buf as usize + data.len()].copy_from_slice(&data);
    }
    assert_eq!(load_rom.call(&mut store, data.len() as i32).unwrap(), 1, "emu_load_rom");
    assert_eq!(reset.call(&mut store, ()).unwrap(), 1, "emu_reset");
    // re-load after reset check
    assert_eq!(load_rom.call(&mut store, data.len() as i32).unwrap(), 1, "emu_load_rom 2");
    assert_eq!(audio_rate.call(&mut store, ()).unwrap(), 44100, "emu_audio_rate");

    let mut total_samples = 0usize;
    let mut hashes: Vec<u64> = Vec::new();
    for f in 0..frames {
        // hold Start on frame 10..30 to exercise input
        let keys = if (10..40).contains(&f) { 0x08u32 } else { 0 };
        set_keys.call(&mut store, keys).unwrap();
        run_frame.call(&mut store, ()).unwrap();
        let n = audio_samples.call(&mut store, ()).unwrap();
        assert!(n >= 0 && n < 100000, "emu_audio_samples sanity: {}", n);
        let abuf = audio_buffer.call(&mut store, ()).unwrap();
        let _ = abuf;
        total_samples += n as usize;
        if f < 6 { println!("frame {}: samples={}", f, n); }
        let fb = framebuffer.call(&mut store, ()).unwrap();
        let mem = memory.data(&store);
        let px = &mem[fb as usize..fb as usize + 256 * 240 * 2];
        let mut h: u64 = 1469598103934665603;
        for b in px {
            h ^= *b as u64;
            h = h.wrapping_mul(1099511628211);
        }
        hashes.push(h);
    }
    println!("frames={} total_samples={} (per frame {:.2})", frames, total_samples,
             total_samples as f64 / frames as f64);
    println!("frame hashes: {:?}", &hashes[..hashes.len().min(8)]);
    let fb = framebuffer.call(&mut store, ()).unwrap();
    let mem = memory.data(&store);
    let px = &mem[fb as usize..fb as usize + 256 * 240 * 2];
    let nonzero = px.chunks(2).filter(|c| c[0] != 0 || c[1] != 0).count();
    println!("final framebuffer nonzero pixels: {} / 61440", nonzero);
    println!("ABI OK");
}
