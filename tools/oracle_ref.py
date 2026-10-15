#!/usr/bin/env python3
"""oracle_ref.py -- thin wrapper around the reference `oracle` CLI.

Three subcommands:

  frames <rom> <n> --out DIR [--replay FILE] [--from N]
      Run <rom> for <n> frames and write every frame as
      <DIR>/frame_NNNNN.idx (61440 u16 LE palette indices) plus the matching
      .ppm RGB file, exactly as `oracle run --dump-frames` does.

  audio <rom> <n> --out FILE.wav [--replay FILE] [--from N]
      Run <rom> for <n> frames and write the produced audio as a mono
      16-bit 44100 Hz WAV.

  session <rom> <n> --keys <hex> [--audio-out FILE] [--frame-out DIR]
      Drive `oracle session start / set-keys / run-frame / framebuffer /
      audio / end`: hold the given keys for the next <n> frames and capture
      the last framebuffer as <frame-out>/frame_%05d.idx plus the drained
      audio as <audio-out> (WAV, mono i16 44100 Hz).  Keys is a hex byte,
      bit order 0=A 1=B 2=Select 3=Start 4=Up 5=Down 6=Left 7=Right.

On failure the oracle's stdout/stderr is printed verbatim and its exit code
is propagated.  Requires the `oracle` binary on PATH (override with $ORACLE).
"""

import argparse
import json
import os
import subprocess
import sys
import wave

FRAME_BYTES = 256 * 240 * 2       # one .idx dump (61440 u16 LE values)
AUDIO_RATE = 44100
AUDIO_CHANNELS = 1
AUDIO_SAMPWIDTH = 2               # bytes per sample (i16)


class OracleError(Exception):
    """Raised when the oracle fails; carries the exit code to propagate."""

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


def oracle_bin():
    return os.environ.get("ORACLE", "oracle")


def run_oracle(args, capture=False):
    """Invoke the oracle.  On failure print its output and raise OracleError."""
    cmd = [oracle_bin()] + args
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise OracleError(
            "error: oracle binary not found (looked for %r); set $ORACLE" % cmd[0]
        )
    out, err = proc.stdout, proc.stderr
    if proc.returncode != 0:
        # Print the oracle's stdout/stderr verbatim, as required.
        if out:
            sys.stdout.buffer.write(out)
            sys.stdout.buffer.flush()
        if err:
            sys.stderr.buffer.write(err)
            sys.stderr.buffer.flush()
        raise OracleError(
            "oracle %s failed with exit code %d" % (args[0] if args else "?", proc.returncode),
            code=proc.returncode,
        )
    return out, err


def emit(out, err):
    """Print a successful oracle invocation's output verbatim."""
    if out:
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
    if err:
        sys.stderr.buffer.write(err)
        sys.stderr.buffer.flush()


def parse_json_or_none(data):
    try:
        return json.loads(data.decode("utf-8", "replace"))
    except Exception:
        return None


def frame_filename(directory, index):
    return os.path.join(directory, "frame_%05d.idx" % index)


# --------------------------------------------------------------------------
# subcommand: frames
# --------------------------------------------------------------------------

def cmd_frames(args):
    if args.out is None:
        raise OracleError("error: --out DIR is required for `frames`")
    if args.n < 0:
        raise OracleError("error: frame count must be >= 0")
    if args.replay is not None and not os.path.isfile(args.replay):
        raise OracleError("error: replay file not found: %s" % args.replay)

    os.makedirs(args.out, exist_ok=True)

    run_args = ["run", args.rom, str(args.n), "--dump-frames", args.out]
    if args.replay is not None:
        run_args += ["--replay", args.replay]
    if args.frm is not None:
        run_args += ["--from", str(args.frm)]

    out, err = run_oracle(run_args)
    emit(out, err)

    summary = parse_json_or_none(out) or {}
    print("frames written to %s (frame count %d)" % (args.out, args.n))

    # Sanity: verify the expected dump files exist and are the right size.
    # With --from N the emulator still runs frames 0..N-1, it just does not
    # dump them; the files written are frames N..(n-1).
    start = args.frm if args.frm is not None else 0
    missing = []
    for i in range(start, min(start + args.n, args.n)):
        path = frame_filename(args.out, i)
        if not os.path.exists(path):
            missing.append(path)
        elif os.path.getsize(path) != FRAME_BYTES:
            raise OracleError(
                "error: %s has %d bytes, expected %d"
                % (path, os.path.getsize(path), FRAME_BYTES)
            )
    if missing:
        raise OracleError(
            "error: oracle did not write expected frame dump(s): %s" % ", ".join(missing[:3])
        )
    return 0


# --------------------------------------------------------------------------
# subcommand: audio
# --------------------------------------------------------------------------

def cmd_audio(args):
    if args.out is None:
        raise OracleError("error: --out FILE.wav is required for `audio`")
    if args.n < 0:
        raise OracleError("error: frame count must be >= 0")
    if args.replay is not None and not os.path.isfile(args.replay):
        raise OracleError("error: replay file not found: %s" % args.replay)

    parent = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(parent, exist_ok=True)

    run_args = ["run", args.rom, str(args.n), "--dump-audio", args.out]
    if args.replay is not None:
        run_args += ["--replay", args.replay]
    if args.frm is not None:
        run_args += ["--from", str(args.frm)]

    out, err = run_oracle(run_args)
    emit(out, err)

    if not os.path.exists(args.out):
        raise OracleError("error: oracle did not write audio file %s" % args.out)

    with wave.open(args.out, "rb") as w:
        params = (w.getnchannels(), w.getsampwidth(), w.getframerate())
    if params != (AUDIO_CHANNELS, AUDIO_SAMPWIDTH, AUDIO_RATE):
        raise OracleError(
            "error: unexpected WAV format %r (want mono/16-bit/44100)" % (params,)
        )
    with wave.open(args.out, "rb") as w:
        nframes = w.getnframes()
    print("audio written to %s (%d samples @ %d Hz)" % (args.out, nframes, AUDIO_RATE))
    return 0


# --------------------------------------------------------------------------
# subcommand: session
# --------------------------------------------------------------------------

def parse_keys(text):
    """Parse a keys argument (hex string or int) into a 0..0xFF byte."""
    s = text.strip()
    if not s:
        raise OracleError("error: --keys must be a hex string or int")
    try:
        if s.lower().startswith("0x"):
            value = int(s, 16)
        elif all(c in "0123456789abcdefABCDEF" for c in s):
            # Accept a bare hex byte, e.g. "08"; fall back to decimal for
            # out-of-range strings like "10".
            try:
                value = int(s, 16)
            except ValueError:
                value = int(s, 10)
        else:
            value = int(s, 10)
    except ValueError:
        raise OracleError("error: --keys must be a hex string or int, got %r" % text)
    if not 0 <= value <= 0xFF:
        raise OracleError("error: --keys must be 0..0xFF, got 0x%X" % value)
    return value


def write_wav(path, samples_i16):
    """Write a mono 16-bit 44100 Hz WAV from a bytes object of i16 LE samples."""
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(AUDIO_CHANNELS)
        w.setsampwidth(AUDIO_SAMPWIDTH)
        w.setframerate(AUDIO_RATE)
        w.writeframes(samples_i16)


def session_call(args, allow_failure=False):
    """Run `oracle session <args>`; return (stdout_bytes, stderr_bytes, rc)."""
    cmd = [oracle_bin(), "session"] + args
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise OracleError(
            "error: oracle binary not found (looked for %r); set $ORACLE" % cmd[0]
        )
    if proc.returncode != 0 and not allow_failure:
        if proc.stdout:
            sys.stdout.buffer.write(proc.stdout)
            sys.stdout.buffer.flush()
        if proc.stderr:
            sys.stderr.buffer.write(proc.stderr)
            sys.stderr.buffer.flush()
        raise OracleError(
            "oracle session %s failed with exit code %d"
            % (args[0] if args else "?", proc.returncode),
            code=proc.returncode,
        )
    return proc.stdout, proc.stderr, proc.returncode


def cmd_session(args):
    keys = parse_keys(args.keys)
    if args.n < 0:
        raise OracleError("error: frame count must be >= 0")
    if args.audio_out is None and args.frame_out is None:
        raise OracleError(
            "error: nothing to capture; pass --audio-out FILE and/or --frame-out DIR"
        )

    # 1. start
    out, err, _ = session_call(["start", args.rom])
    emit(err, b"")
    info = parse_json_or_none(out)
    if not info or "id" not in info:
        raise OracleError("error: could not parse session start output: %r" % out[:200])
    sid = info["id"]

    try:
        # 2. hold keys from the next frame run onwards
        out, err, _ = session_call(["set-keys", sid, "%02x" % keys])
        emit(out, err)

        # 3. run n frames
        out, err, _ = session_call(["run-frame", sid, str(args.n)])
        emit(out, err)

        # 4. last framebuffer -> .idx
        if args.frame_out is not None:
            os.makedirs(args.frame_out, exist_ok=True)
            fb, fberr, _ = session_call(["framebuffer", sid])
            emit(b"", fberr)
            if len(fb) != FRAME_BYTES:
                raise OracleError(
                    "error: framebuffer is %d bytes, expected %d"
                    % (len(fb), FRAME_BYTES)
                )
            # Last completed frame index.  run-frame N leaves cur_frame == N,
            # and frame N-1 is the last one completed; name dumps accordingly.
            frame_index = max(args.n - 1, 0)
            path = frame_filename(args.frame_out, frame_index)
            with open(path, "wb") as fh:
                fh.write(fb)
            print("wrote framebuffer to %s (%d bytes)" % (path, len(fb)))

        # 5. drained audio -> WAV
        if args.audio_out is not None:
            raw, aerr, _ = session_call(["audio", sid])
            emit(b"", aerr)
            if len(raw) % 2 != 0:
                raise OracleError(
                    "error: audio payload is %d bytes, not a multiple of 2" % len(raw)
                )
            # `oracle session audio` drains everything produced since the
            # session started; --audio-from drops whole frames worth of
            # samples (floor(44100/60.0988) per NTSC frame) from the front,
            # mirroring `oracle run --from N` for the audio stream.
            if args.audio_from:
                skip = min(args.audio_from, args.n) * (AUDIO_RATE // 60)
                raw = raw[skip * 2:]
            write_wav(args.audio_out, raw)
            print(
                "wrote audio to %s (%d samples @ %d Hz)"
                % (args.audio_out, len(raw) // 2, AUDIO_RATE)
            )
    finally:
        # 6. always end the session, even if something above failed
        try:
            session_call(["end", sid], allow_failure=True)
        except OracleError:
            pass

    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="oracle_ref.py",
        description="Thin wrapper around the reference `oracle` CLI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Requires")[0],
    )
    sub = p.add_subparsers(dest="command")

    pf = sub.add_parser(
        "frames",
        help="run a ROM and dump every frame (.idx + .ppm) into a directory",
        description="Run <rom> for <n> frames and write frame dumps into DIR.",
    )
    pf.add_argument("rom", help="path to the .nes ROM")
    pf.add_argument("n", type=int, help="number of frames to run")
    pf.add_argument("--out", metavar="DIR", help="output directory for frame dumps")
    pf.add_argument("--replay", metavar="FILE", default=None, help="input replay file")
    pf.add_argument(
        "--from",
        dest="frm",
        type=int,
        default=None,
        metavar="N",
        help="dump only frames >= N (the emulator still runs from power-on)",
    )
    pf.set_defaults(func=cmd_frames)

    pa = sub.add_parser(
        "audio",
        help="run a ROM and dump its audio to a mono WAV",
        description="Run <rom> for <n> frames and write audio to FILE.wav.",
    )
    pa.add_argument("rom", help="path to the .nes ROM")
    pa.add_argument("n", type=int, help="number of frames to run")
    pa.add_argument("--out", metavar="FILE.wav", help="output WAV path")
    pa.add_argument("--replay", metavar="FILE", default=None, help="input replay file")
    pa.add_argument(
        "--from",
        dest="frm",
        type=int,
        default=None,
        metavar="N",
        help="dump only audio produced by frames >= N",
    )
    pa.set_defaults(func=cmd_audio)

    ps = sub.add_parser(
        "session",
        help="hold keys for N frames and capture the last framebuffer + audio",
        description="Drive `oracle session` to run a ROM with held keys.",
    )
    ps.add_argument("rom", help="path to the .nes ROM")
    ps.add_argument("n", type=int, help="number of frames to run with keys held")
    ps.add_argument(
        "--keys",
        required=True,
        metavar="HEX",
        help="held keys, hex byte (bit0=A bit1=B bit2=Select bit3=Start "
        "bit4=Up bit5=Down bit6=Left bit7=Right)",
    )
    ps.add_argument("--audio-out", metavar="FILE", default=None, help="output WAV path")
    ps.add_argument("--frame-out", metavar="DIR", default=None, help="output frame dump dir")
    ps.add_argument(
        "--audio-from",
        dest="audio_from",
        type=int,
        default=None,
        metavar="N",
        help="keep only audio samples produced by frames >= N "
        "(`oracle session audio` drains everything; default 0)",
    )
    ps.set_defaults(func=cmd_session)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except OracleError as exc:
        print("%s" % exc, file=sys.stderr)
        return exc.code if exc.code else 1


if __name__ == "__main__":
    sys.exit(main())
