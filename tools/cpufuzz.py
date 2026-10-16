import os, sys
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import numpy as np
sys.argv=['x']
sys.argv=['cpufuzz']
from probe import build, run_both
from hexfont import chr_ram_font

OPS = [
 (0x69,'imm'),(0x65,'zp'),(0x75,'zpx'),(0x6D,'abs'),(0x7D,'absx'),(0x79,'absy'),(0x61,'izx'),(0x71,'izy'),
 (0x29,'imm'),(0x25,'zp'),(0x35,'zpx'),(0x2D,'abs'),(0x3D,'absx'),(0x39,'absy'),(0x21,'izx'),(0x31,'izy'),
 (0x0A,'acc'),(0x06,'zp'),(0x16,'zpx'),(0x0E,'abs'),(0x1E,'absx'),
 (0x24,'zp'),(0x2C,'abs'),
 (0xC9,'imm'),(0xC5,'zp'),(0xD5,'zpx'),(0xCD,'abs'),(0xDD,'absx'),(0xD9,'absy'),(0xC1,'izx'),(0xD1,'izy'),
 (0xE0,'imm'),(0xE4,'zp'),(0xEC,'abs'),(0xC0,'imm'),(0xC4,'zp'),(0xCC,'abs'),
 (0xC6,'zp'),(0xD6,'zpx'),(0xCE,'abs'),(0xDE,'absx'),
 (0xCA,'acc'),(0x88,'acc'),(0xE6,'zp'),(0xF6,'zpx'),(0xEE,'abs'),(0xFE,'absx'),(0xE8,'acc'),(0xC8,'acc'),
 (0x49,'imm'),(0x45,'zp'),(0x55,'zpx'),(0x4D,'abs'),(0x5D,'absx'),(0x59,'absy'),(0x41,'izx'),(0x51,'izy'),
 (0x4A,'acc'),(0x46,'zp'),(0x56,'zpx'),(0x4E,'abs'),(0x5E,'absx'),
 (0x09,'imm'),(0x05,'zp'),(0x15,'zpx'),(0x0D,'abs'),(0x1D,'absx'),(0x19,'absy'),(0x01,'izx'),(0x11,'izy'),
 (0x2A,'acc'),(0x26,'zp'),(0x36,'zpx'),(0x2E,'abs'),(0x3E,'absx'),
 (0x6A,'acc'),(0x66,'zp'),(0x76,'zpx'),(0x6E,'abs'),(0x7E,'absx'),
 (0xE9,'imm'),(0xE5,'zp'),(0xF5,'zpx'),(0xED,'abs'),(0xFD,'absx'),(0xF9,'absy'),(0xE1,'izx'),(0xF1,'izy'),
 (0x85,'zp'),(0x95,'zpx'),(0x8D,'abs'),(0x9D,'absx'),(0x99,'absy'),(0x81,'izx'),(0x91,'izy'),
 (0x86,'zp'),(0x96,'zpy'),(0x8E,'abs'),(0x84,'zp'),(0x94,'zpx'),(0x8C,'abs'),
 (0xAA,'acc'),(0x8A,'acc'),(0xA8,'acc'),(0x98,'acc'),(0xBA,'acc'),
 (0x48,'acc'),(0x08,'acc'),(0x68,'acc'),(0x28,'acc'),
 (0x18,'acc'),(0x38,'acc'),(0xB8,'acc'),
 (0xA7,'zp'),(0xB7,'zpy'),(0xAF,'abs'),(0xBF,'absy'),(0xA3,'izx'),(0xB3,'izy'),
 (0x87,'zp'),(0x97,'zpy'),(0x8F,'abs'),(0x83,'izx'),
 (0xC7,'zp'),(0xD7,'zpx'),(0xCF,'abs'),(0xDF,'absx'),(0xDB,'absy'),(0xC3,'izx'),(0xD3,'izy'),
 (0xE7,'zp'),(0xF7,'zpx'),(0xEF,'abs'),(0xFF,'absx'),(0xFB,'absy'),(0xE3,'izx'),(0xF3,'izy'),
 (0x07,'zp'),(0x17,'zpx'),(0x0F,'abs'),(0x1F,'absx'),(0x1B,'absy'),(0x03,'izx'),(0x13,'izy'),
 (0x27,'zp'),(0x37,'zpx'),(0x2F,'abs'),(0x3F,'absx'),(0x3B,'absy'),(0x23,'izx'),(0x33,'izy'),
 (0x47,'zp'),(0x57,'zpx'),(0x4F,'abs'),(0x5F,'absx'),(0x5B,'absy'),(0x43,'izx'),(0x53,'izy'),
 (0x67,'zp'),(0x77,'zpx'),(0x6F,'abs'),(0x7F,'absx'),(0x7B,'absy'),(0x63,'izx'),(0x73,'izy'),
 (0x0B,'imm'),(0x2B,'imm'),(0x4B,'imm'),(0x6B,'imm'),(0x8B,'imm'),(0xCB,'imm'),(0xEB,'imm'),
 (0x1A,'acc'),(0x3A,'acc'),(0x5A,'acc'),(0x7A,'acc'),(0xDA,'acc'),(0xFA,'acc'),
 (0x04,'zp'),(0x44,'zp'),(0x64,'zp'),(0x14,'zpx'),(0x34,'zpx'),(0x54,'zpx'),(0x74,'zpx'),(0xD4,'zpx'),(0xF4,'zpx'),
 (0x0C,'abs'),(0x1C,'absx'),(0x3C,'absx'),(0x5C,'absx'),(0x7C,'absx'),(0xDC,'absx'),(0xFC,'absx'),
 (0x80,'imm'),(0x82,'imm'),(0x89,'imm'),(0xC2,'imm'),(0xE2,'imm'),
 (0x93,'izy'),(0x9F,'absy'),(0x9C,'absx'),(0x9E,'absy'),(0x9B,'absy'),(0xBB,'absy'),
]
def enc(op, mode, seed):
    a = 0x10  # zero-page operand byte: fixed, page 0 is known-zero
    if mode=='imm':  return [op, (seed*37+0x5A)&0xFF]
    if mode=='acc':  return [op]
    if mode=='zp':   return [op, 0x10]
    if mode=='zpx':  return [op, 0x0E]
    if mode=='zpy':  return [op, 0x0E]
    if mode=='abs':  return [op, ((seed*64)&0xFF), 0x03]
    if mode=='absx': return [op, 0x00, 0x03]
    if mode=='absy': return [op, 0x00, 0x03]
    if mode=='izx':  return [op, 0x00]
    if mode=='izy':  return [op, 0x00]
    raise Exception(mode)
PRE = {'zpx':'ldx #$01','zpy':'ldy #$01','absx':'ldx #$00','absy':'ldy #$00','izx':'ldx #$00','izy':'ldy #$00'}
PASSES = [('clc','cld'),('sec','sed')]
def gen():
    L=[ """
start:  sei
        cld
        ldx #$FF
        txs
        lda #$40
        sta $4017
        lda #$00
        sta $2000
        sta $2001
        jsr vwait
        jsr vwait
        lda #$00
        sta $0300
        lda #$11
        sta $0301
        lda #$22
        sta $02FF
        lda #$33
        sta $0350
        lda #$44
        sta $10
        lda #$55
        sta $0E
        lda #$66
        sta $0100
        lda #$03
        sta $0101
        lda #$00
        sta $00
"""]
    for i,(op,mode) in enumerate(OPS):
        for (cflag,dflag) in PASSES:
            by = enc(op, mode, i)
            pre = PRE.get(mode,'')
            L.append("""
        lda #$5A
        ldx #$03
        ldy #$FE
        %s
        %s
        %s
        .byte %s
        cld
        eor $00
        sta $00
        txa
        eor $00
        sta $00
        tya
        eor $00
        sta $00
        php
        pla
        eor $00
        sta $00
        lda $0300
        eor $00
        sta $00
        lda $0301
        eor $00
        sta $00
        lda $02FF
        eor $00
        sta $00
""" % (cflag, dflag, pre, ', '.join('$%02X'%b for b in by)))
    L.append("""
        jmp done
vwait:  bit $2002
        bpl vwait
        rts
nmi:    rti
irq:    rti
done:   lda $00
        lsr a
        lsr a
        lsr a
        lsr a
        jsr nib2ascii
        sta $0400
        lda $00
        and #$0F
        jsr nib2ascii
        sta $0401
        lda $00
        lsr a
        lsr a
        sta $0402
        lda $2002
        lda #$20
        sta $2006
        lda #$00
        sta $2006
        lda $0400
        sta $2007
        lda $0401
        sta $2007
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        lda #$0F
        sta $2007
        lda #$30
        sta $2007
        sta $2007
        sta $2007
        lda #$00
        sta $2005
        sta $2005
        lda #$0A
        sta $2001
spin:   jmp spin
nib2ascii:
        cmp #$0A
        bcc low
        clc
        adc #$07
low:    clc
        adc #$30
        rts
""")
    return '\n'.join(L)
TPL=gen()
rom=build(TPL, chr_bytes=chr_ram_font(), vectors=("nmi","start","irq"), origin=0x8000, bank_size=0x8000, prg_banks=1)
print('rom', len(rom), file=sys.stderr)
ref, mine = run_both(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'tmp/cpufuzz.nes'), rom, frames=6)
bad=[]
for i,(a,b) in enumerate(zip(ref,mine)):
    if not (a==b).all():
        d=np.argwhere(a!=b)
        bad.append((i,len(d), d[:3].tolist()))
print('frames differing:', bad if bad else 'NONE - identical')
