#!/usr/bin/env python3
"""dis6502.py -- minimal 6502 disassembler.

Usage: dis6502.py PRG.bin --base 0x8000 --start 0xEF80 --end 0xF000
"""
import argparse
import sys

# (mnemonic, addressing mode, size)
MODES = {
    "imp": 1, "acc": 1, "imm": 2, "zp": 2, "zpx": 2, "zpy": 2,
    "abs": 3, "absx": 3, "absy": 3, "ind": 3, "indx": 2, "indy": 2,
    "rel": 2,
}

# Canonical table: opcode -> (mnemonic, mode)
TABLE = {}


def _fill(base_ops):
    for op, (mn, mode) in base_ops.items():
        TABLE[op] = (mn, mode)


# Build from the well-known 6502 matrix (legal + illegal).
_LEGAL = """
00 BRK imp  01 ORA indx 05 ORA zp   06 ASL zp   08 PHP imp  09 ORA imm  0A ASL acc  0D ORA abs  0E ASL abs
10 BPL rel  11 ORA indy 15 ORA zpx  16 ASL zpx  18 CLC imp  19 ORA absy 1D ORA absx 1E ASL absx
20 JSR abs  21 AND indx 24 BIT zp   25 AND zp   26 ROL zp   28 PLP imp  29 AND imm  2A ROL acc  2C BIT abs  2D AND abs  2E ROL abs
30 BMI rel  31 AND indy 35 AND zpx  36 ROL zpx  38 SEC imp  39 AND absy 3D AND absx 3E ROL absx
40 RTI imp  41 EOR indx 45 EOR zp   46 LSR zp   48 PHA imp  49 EOR imm  4A LSR acc  4C JMP abs  4D EOR abs  4E LSR abs
50 BVC rel  51 EOR indy 55 EOR zpx  56 LSR zpx  58 CLI imp  59 EOR absy 5D EOR absx 5E LSR absx
60 RTS imp  61 ADC indx 65 ADC zp   66 ROR zp   68 PLA imp  69 ADC imm  6A ROR acc  6C JMP ind  6D ADC abs  6E ROR abs
70 BVS rel  71 ADC indy 75 ADC zpx  76 ROR zpx  78 SEI imp  79 ADC absy 7D ADC absx 7E ROR absx
81 STA indx 84 STY zp   85 STA zp   86 STX zp   88 DEY imp  8A TXA imp  8C STY abs  8D STA abs  8E STX abs
90 BCC rel  91 STA indy 94 STY zpx  95 STA zpx  96 STX zpy  98 TYA imp  99 STA absy 9A TXS imp  9D STA absx
A0 LDY imm  A1 LDA indx A2 LDX imm  A4 LDY zp   A5 LDA zp   A6 LDX zp   A8 TAY imp  A9 LDA imm  AA TAX imp  AC LDY abs  AD LDA abs  AE LDX abs
B0 BCS rel  B1 LDA indy B4 LDY zpx  B5 LDA zpx  B6 LDX zpy  B8 CLV imp  B9 LDA absy BA TSX imp  BC LDY absx BD LDA absx BE LDX absy
C0 CPY imm  C1 CMP indx C4 CPY zp   C5 CMP zp   C6 DEC zp   C8 INY imp  C9 CMP imm  CA DEX imp  CC CPY abs  CD CMP abs  CE DEC abs
D0 BNE rel  D1 CMP indy D5 CMP zpx  D6 DEC zpx  D8 CLD imp  D9 CMP absy DD CMP absx DE DEC absx
E0 CPX imm  E1 SBC indx E4 CPX zp   E5 SBC zp   E6 INC zp   E8 INX imp  E9 SBC imm  EA NOP imp  EC CPX abs  ED SBC abs  EE INC abs
F0 BEQ rel  F1 SBC indy F5 SBC zpx  F6 INC zpx  F8 SED imp  F9 SBC absy FD SBC absx FE INC absx
"""
_ILLEGAL = """
02 JAM imp  03 SLO indx 04 NOP zp   07 SLO zp   0B ANC imm  0C NOP abs  0F SLO abs
12 JAM imp  13 SLO indy 14 NOP zpx  17 SLO zpy  1A NOP imp  1B SLO absy 1C NOP absx 1F SLO absx
22 JAM imp  23 RLA indx 27 RLA zp   2B ANC imm  2F RLA abs  32 JAM imp  33 RLA indy 34 NOP zpx
37 RLA zpy  3A NOP imp  3B RLA absy 3C NOP absx 3F RLA absx
42 JAM imp  43 SRE indx 44 NOP zp   47 SRE zp   4B ALR imm  4F SRE abs  52 JAM imp  53 SRE indy
54 NOP zpx  57 SRE zpy  5A NOP imp  5B SRE absy 5C NOP absx 5F SRE absx
62 JAM imp  63 RRA indx 64 NOP zp   67 RRA zp   6B ARR imm  6F RRA abs  72 JAM imp  73 RRA indy
74 NOP zpx  77 RRA zpy  7A NOP imp  7B RRA absy 7C NOP absx 7F RRA absx
80 NOP imm  82 NOP imm  83 SAX indx 87 SAX zp   89 NOP imm  8B XAA imm  8F SAX abs
92 JAM imp  93 AHX indy 97 SAX zpy  9B TAS absy 9C SHY absx 9E SHX absy 9F AHX absy
A3 LAX indx A7 LAX zp   AB LAX imm  AF LAX abs  B2 JAM imp  B3 LAX indy B7 LAX zpy  BB LAS absy
BF LAX absy
C2 NOP imm  C3 DCP indx C7 DCP zp   CB AXS imm  CF DCP abs  D2 JAM imp  D3 DCP indy D4 NOP zpx
D7 DCP zpy  DA NOP imp  DB DCP absy DC NOP absx DF DCP absx
E2 NOP imm  E3 ISC indx E7 ISC zp   EB SBC imm  EF ISC abs  F2 JAM imp  F3 ISC indy F4 NOP zpx
F7 ISC zpy  FA NOP imp  FB ISC absy FC NOP absx FF ISC absx
"""


def _parse(spec):
    toks = spec.split()
    i = 0
    while i < len(toks):
        op = int(toks[i], 16)
        TABLE[op] = (toks[i + 1], toks[i + 2])
        i += 3


_parse(_LEGAL)
_parse(_ILLEGAL)

EXTRA = {
    0x0A: ("ASL", "acc"), 0x2A: ("ROL", "acc"), 0x4A: ("LSR", "acc"),
    0x6A: ("ROR", "acc"),
}


def fmt_operand(mode, pos, data, pc):
    if mode == "imp":
        return ""
    if mode == "acc":
        return "A"
    if mode == "rel":
        off = data[pos + 1]
        if off >= 0x80:
            off -= 0x100
        return "$%04X" % ((pc + 2 + off) & 0xFFFF)
    lo = data[pos + 1] if pos + 1 < len(data) else 0
    if mode == "imm":
        return "#$%02X" % lo
    if mode == "zp":
        return "$%02X" % lo
    if mode == "zpx":
        return "$%02X,X" % lo
    if mode == "zpy":
        return "$%02X,Y" % lo
    hi = data[pos + 2] if pos + 2 < len(data) else 0
    a = lo | (hi << 8)
    return {
        "abs": "$%04X",
        "absx": "$%04X,X",
        "absy": "$%04X,Y",
        "ind": "($%04X)",
        "indx": "($%02X,X)",
        "indy": "($%02X),Y",
    }[mode] % (a if mode in ("abs", "absx", "absy", "ind") else lo)


def disassemble(data, base, start, end):
    out = []
    pc = start
    while pc < end:
        off = pc - base
        if off < 0 or off >= len(data):
            break
        op = data[off]
        mn, mode = TABLE.get(op, ("???", "imp"))
        size = MODES[mode]
        text = "%04X  %-4s %s" % (pc, mn, fmt_operand(mode, off, data, pc))
        out.append(text)
        pc += size
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0x8000)
    ap.add_argument("--start", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--end", type=lambda s: int(s, 0), required=True)
    args = ap.parse_args()
    data = open(args.file, "rb").read()
    for line in disassemble(data, args.base, args.start, args.end):
        print(line)


if __name__ == "__main__":
    main()
