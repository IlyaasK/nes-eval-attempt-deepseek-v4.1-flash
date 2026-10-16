; da65 V2.18 - Debian 2.19-1
; Created:    2026-10-16 13:54:55
; Input file: tmp/s5.prg
; Page:       1


        .setcpu "6502"

LA417           := $A417
LA455           := $A455
LA4EA           := $A4EA
LAC7A           := $AC7A
LDD8F           := $DD8F
LF4D4           := $F4D4
LF9B0           := $F9B0
        and     $38C6,y
        lda     $38
        ora     $39
        bne     LF9B0
        rts

        tax
        lda     $49
        pha
        lda     #$04
        jsr     LF4D4
        txa
        jsr     LA455
        pla
        sta     $49
        jmp     LF4D4

        lda     $49
        pha
        lda     #$04
        jsr     LF4D4
        jsr     LA417
        pla
        sta     $49
        jmp     LF4D4

        tax
        lda     $49
        pha
        lda     #$04
        jsr     LF4D4
        txa
        jsr     LA4EA
        pla
        sta     $49
        jmp     LF4D4

        and     #$03
        tax
        lda     LFA1C,x
        tax
        lda     $49
        pha
        lda     #$04
        jsr     LF4D4
        jsr     LDD8F
        jsr     LAC7A
        pla
        sta     $49
        jmp     LF4D4

LFA1C:  brk
        .byte   $0F
        asl     $602D,x
LFA21:  tay
        ldx     #$03
LFA24:  lda     #$01
        sta     $4016
        sta     $38,x
        lda     #$00
        sta     $4016
        lda     #$08
        sta     $38
LFA34:  lda     $4016,y
        lsr     a
        rol     $38,x
        bcc     LFA34
        dex
        bne     LFA24
        lda     $39
        cmp     $3A
        beq     LFA4B
        cmp     $3B
        beq     LFA4B
        lda     $3A
LFA4B:  sta     $2A,y
        tax
        eor     $2C,y
        and     $2A,y
        sta     $2E,y
        txa
        sta     $2C,y
        ldx     #$00
        rts

        pha
        jsr     LFA21
        pla
        tax
        lda     $2E,x
        ldx     #$00
        rts

        tax
        lda     $2A,x
        ldx     #$00
        rts

        jsr     LFA76
        ldx     #$00
        rts

LFA76:  lda     $34
        tax
        lsr     a
        lsr     a
        lsr     a
        sta     $34
        lsr     a
        .byte   $45
