
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
loop:
        lda #$01
        sta $4016
        lda #$00
        sta $4016
        ldx #$08
        lda #$00
rd:     pha
        lda $4016
        and #$01
        sta $00
        pla
        asl a
        ora $00
        dex
        bne rd
        pha
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        pla
        sta $2007
        lda #$3F
        sta $2006
        lda #$00
        sta $2006
        jsr vwait
        jmp loop
vwait:  bit $2002
        bpl vwait
        rts
nmi:    rti
irq:    rti
