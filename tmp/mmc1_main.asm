
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
        ; select PRG bank 0 in the $8000 window (MMC1 serial write)
        lda #$00
        jsr mmc1_write
        jsr bank
        jsr paint
        jsr showdelay
        ; select PRG bank 1
        lda #$01
        jsr mmc1_write
        jsr bank
        jsr paint
spin:   jmp spin
; --- write A to the MMC1 control register ($8000)
mmc1_write:
        pha
        ldx #$05
w1:     lda #$00
        lsr $10          ; dummy
        pla
        pha
        ; shift out bit 0 of the value
        and #$01
        sta $8000
        lsr $11
        pla
        lsr a
        pha
        dex
        bne w1
        pla
        ; last write (bit 4) - use the value's bit 4
        rts
bank:   jsr $8000
done:   rts
; --- paint the current A into palette entry 0
paint:
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
        rts
showdelay:
        jsr vwait
        rts
vwait:  bit $2002
        bpl vwait
        rts
nmi:    rti
irq:    rti
