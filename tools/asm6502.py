#!/usr/bin/env python3
"""asm6502.py -- tiny two-pass 6502 assembler for probe ROMs.

Supported syntax (one instruction per line, ';' comments, labels with ':'):
    lda #$10        lda $1234       lda $12         lda $1234,x
    sta $2007       jmp label       bne label       beq label
    db $00, $FF     .org $C000
Local labels: '.name' may be reused for forward jumps (resolved to the nearest).

Usage:
    from asm6502 import Assembler
    a = Assembler(origin=0xC000)
    a.line("lda #$00"); a.line("sta $2000")
    code = a.assemble()
"""

MODES = {
    "imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2,
    "abs": 3, "absx": 3, "absy": 3, "ind": 3, "indx": 2, "indy": 2,
    "rel": 2,
}

# mnemonic -> {mode: opcode}
OPS = {
    "adc": {"imm": 0x69, "zp": 0x65, "zpx": 0x75, "abs": 0x6D, "absx": 0x7D, "absy": 0x79, "indx": 0x61, "indy": 0x71},
    "and": {"imm": 0x29, "zp": 0x25, "zpx": 0x35, "abs": 0x2D, "absx": 0x3D, "absy": 0x39, "indx": 0x21, "indy": 0x31},
    "asl": {"acc": 0x0A, "zp": 0x06, "zpx": 0x16, "abs": 0x0E, "absx": 0x1E},
    "bcc": {"rel": 0x90}, "bcs": {"rel": 0xB0}, "beq": {"rel": 0xF0}, "bmi": {"rel": 0x30},
    "bne": {"rel": 0xD0}, "bpl": {"rel": 0x10}, "bvc": {"rel": 0x50}, "bvs": {"rel": 0x70},
    "bit": {"zp": 0x24, "abs": 0x2C},
    "brk": {"imp": 0x00},
    "clc": {"imp": 0x18}, "cld": {"imp": 0xD8}, "cli": {"imp": 0x58}, "clv": {"imp": 0xB8},
    "cmp": {"imm": 0xC9, "zp": 0xC5, "zpx": 0xD5, "abs": 0xCD, "absx": 0xDD, "absy": 0xD9, "indx": 0xC1, "indy": 0xD1},
    "cpx": {"imm": 0xE0, "zp": 0xE4, "abs": 0xEC},
    "cpy": {"imm": 0xC0, "zp": 0xC4, "abs": 0xCC},
    "dec": {"zp": 0xC6, "zpx": 0xD6, "abs": 0xCE, "absx": 0xDE},
    "dex": {"imp": 0xCA}, "dey": {"imp": 0x88},
    "eor": {"imm": 0x49, "zp": 0x45, "zpx": 0x55, "abs": 0x4D, "absx": 0x5D, "absy": 0x59, "indx": 0x41, "indy": 0x51},
    "inc": {"zp": 0xE6, "zpx": 0xF6, "abs": 0xEE, "absx": 0xFE},
    "inx": {"imp": 0xE8}, "iny": {"imp": 0xC8},
    "jmp": {"abs": 0x4C, "ind": 0x6C},
    "jsr": {"abs": 0x20},
    "lda": {"imm": 0xA9, "zp": 0xA5, "zpx": 0xB5, "abs": 0xAD, "absx": 0xBD, "absy": 0xB9, "indx": 0xA1, "indy": 0xB1},
    "ldx": {"imm": 0xA2, "zp": 0xA6, "zpy": 0xB6, "abs": 0xAE, "absy": 0xBE},
    "ldy": {"imm": 0xA0, "zp": 0xA4, "zpx": 0xB4, "abs": 0xAC, "absx": 0xBC},
    "lsr": {"acc": 0x4A, "zp": 0x46, "zpx": 0x56, "abs": 0x4E, "absx": 0x5E},
    "nop": {"imp": 0xEA},
    "ora": {"imm": 0x09, "zp": 0x05, "zpx": 0x15, "abs": 0x0D, "absx": 0x1D, "absy": 0x19, "indx": 0x01, "indy": 0x11},
    "pha": {"imp": 0x48}, "php": {"imp": 0x08}, "pla": {"imp": 0x68}, "plp": {"imp": 0x28},
    "rol": {"acc": 0x2A, "zp": 0x26, "zpx": 0x36, "abs": 0x2E, "absx": 0x3E},
    "ror": {"acc": 0x6A, "zp": 0x66, "zpx": 0x76, "abs": 0x6E, "absx": 0x7E},
    "rti": {"imp": 0x40}, "rts": {"imp": 0x60},
    "sbc": {"imm": 0xE9, "zp": 0xE5, "zpx": 0xF5, "abs": 0xED, "absx": 0xFD, "absy": 0xF9, "indx": 0xE1, "indy": 0xF1},
    "sec": {"imp": 0x38}, "sed": {"imp": 0xF8}, "sei": {"imp": 0x78},
    "sta": {"zp": 0x85, "zpx": 0x95, "abs": 0x8D, "absx": 0x9D, "absy": 0x99, "indx": 0x81, "indy": 0x91},
    "stx": {"zp": 0x86, "zpy": 0x96, "abs": 0x8E},
    "sty": {"zp": 0x84, "zpx": 0x94, "abs": 0x8C},
    "tax": {"imp": 0xAA}, "tay": {"imp": 0xA8}, "tsx": {"imp": 0xBA},
    "txa": {"imp": 0x8A}, "txs": {"imp": 0x9A}, "tya": {"imp": 0x98},
}

BRANCHES = {"bcc", "bcs", "beq", "bmi", "bne", "bpl", "bvc", "bvs"}


class AsmError(Exception):
    pass


class Assembler:
    def __init__(self, origin=0xC000):
        self.origin = origin
        self.items = []  # (addr_or_None, bytes_or_label_marker)
        self.pc = origin
        self.labels = {}
        self.locals = 0

    # ---------------------------------------------------------------- internals
    def _parse_operand(self, mn, raw):
        raw = raw.strip()
        if raw == "":
            return "imp", 0, None
        if raw.upper() == "A":
            return "acc", 0, None
        if raw.startswith("#"):
            v = raw[1:].strip()
            return "imm", self._value(v), None
        if raw.startswith("("):
            if raw.endswith(",X)") or raw.endswith(",x)"):
                return "indx", self._value(raw[1:-3]), None
            if raw.endswith("),Y") or raw.endswith("),y"):
                return "indy", self._value(raw[1:-3]), None
            if raw.endswith(")"):
                return "ind", self._value(raw[1:-1]), None
            raise AsmError("bad indirect operand: " + raw)
        if raw.endswith(",X") or raw.endswith(",x"):
            v = self._value(raw[:-2])
            if isinstance(v, str):
                return "absx", v, None
            return ("zpx" if v < 0x100 else "absx"), v, None
        if raw.endswith(",Y") or raw.endswith(",y"):
            v = self._value(raw[:-2])
            if isinstance(v, str):
                return "absy", v, None
            return ("zpy" if v < 0x100 else "absy"), v, None
        v = self._value(raw)
        if mn in BRANCHES:
            return "rel", v, None
        if isinstance(v, str):
            return "abs", v, None
        if v < 0x100:
            return "zp", v, None
        return "abs", v, None

    def _value(self, tok):
        tok = tok.strip()
        if tok.startswith("$"):
            return int(tok[1:], 16)
        if tok.startswith("%"):
            return int(tok[1:], 2)
        if tok.lower().startswith("0x"):
            return int(tok, 16)
        if tok.startswith("'"):
            return ord(tok[1])
        try:
            return int(tok, 10)
        except ValueError:
            return tok  # label

    # ------------------------------------------------------------------ public
    def line(self, text):
        text = text.split(";")[0].strip()
        if not text:
            return
        if text.startswith("."):
            parts = text.split(None, 1)
            if parts[0] == ".org":
                self.pc = self._value(parts[1])
                return
            if parts[0] == ".byte":
                self.items.append((self.pc, bytes(self._value(x) for x in parts[1].split(","))))
                self.pc += len(self.items[-1][1])
                return
            raise AsmError("unknown directive " + parts[0])
        if ":" in text.split()[0] and text.split()[0].endswith(":"):
            label = text.split()[0][:-1]
            self.labels[label] = self.pc
            text = text[len(label) + 1:].strip()
            if not text:
                return
        parts = text.split(None, 1)
        mn = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""
        if mn == "db":
            vals = [self._value(x) for x in rest.split(",")]
            b = bytes(vals)
            self.items.append((self.pc, b))
            self.pc += len(b)
            return
        if mn not in OPS:
            raise AsmError("unknown mnemonic " + mn)
        mode, value, _ = self._parse_operand(mn, rest)
        if mode not in OPS[mn]:
            # widen zp to abs when needed
            if mode == "zp" and "abs" in OPS[mn]:
                mode = "abs"
            elif mode == "zpx" and "absx" in OPS[mn]:
                mode = "absx"
            elif mode == "zpy" and "absy" in OPS[mn]:
                mode = "absy"
            else:
                raise AsmError("%s does not support mode %s" % (mn, mode))
        op = OPS[mn][mode]
        size = MODES[mode]
        if mode == "rel":
            self.items.append((self.pc, ("branch", op, value)))
            self.pc += 2
            return
        if isinstance(value, str):
            # forward reference: emit a marker, patch later
            self.items.append((self.pc, ("ref", op, mode, value)))
            self.pc += size
            return
        if size == 1:
            b = bytes([op])
        elif size == 2:
            b = bytes([op, value & 0xFF])
        else:
            b = bytes([op, value & 0xFF, (value >> 8) & 0xFF])
        self.items.append((self.pc, b))
        self.pc += size

    def label(self, name):
        self.labels[name] = self.pc

    def assemble(self):
        # first pass done; resolve
        out = bytearray()
        start = self.origin
        for addr, item in self.items:
            if addr > start + len(out):
                out.extend(b"\x00" * (addr - start - len(out)))
            if isinstance(item, tuple):
                kind = item[0]
                if kind == "branch":
                    _, op, target = item
                    if isinstance(target, str):
                        target = self.labels[target]
                    off = target - (addr + 2)
                    if off < -128 or off > 127:
                        raise AsmError("branch out of range at %04X" % addr)
                    out.extend(bytes([op, off & 0xFF]))
                elif kind == "ref":
                    _, op, mode, name = item
                    if name not in self.labels:
                        raise AsmError("undefined label " + name)
                    v = self.labels[name]
                    size = MODES[mode]
                    if size == 2:
                        out.extend(bytes([op, v & 0xFF]))
                    else:
                        out.extend(bytes([op, v & 0xFF, (v >> 8) & 0xFF]))
                else:
                    raise AsmError("bad item")
            else:
                out.extend(item)
        return bytes(out)


if __name__ == "__main__":
    import sys
    src = sys.stdin.read()
    a = Assembler(origin=0xC000)
    for l in src.splitlines():
        a.line(l)
    print(a.assemble().hex())
