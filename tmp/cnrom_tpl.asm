
start:
        sei
        cld
        ldx #$FF
        txs
        lda #$00
        sta $2000
        sta $2001
        jsr vwait
        jsr vwait
        jsr vwait
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        lda #$0F
        sta $2007
        lda #$30
        sta $2007
        lda #$16
        sta $2007
        lda #$29
        sta $2007
        lda #$20
        sta $2006
        lda #$00
        sta $2006
        ldy #$04
        ldx #$00
nt:     lda #$01
        sta $2007
        inx
        bne nt
        dey
        bne nt
        lda #$00
        sta $2005
        sta $2005
        lda #$00
        sta $2000
        lda #$0A
        sta $2001
        lda #$00
        sta $11
spin:   jsr vwait
        lda $11
        and #$03
        sta $8000
        inc $11
        jmp spin
vwait:  bit $2002
        bpl vwait
        rts
nmi:    rti
irq:    rti
