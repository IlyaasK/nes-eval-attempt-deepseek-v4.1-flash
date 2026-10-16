; da65 V2.18 - Debian 2.19-1
; Created:    2026-10-16 13:38:31
; Input file: tmp/s4.prg
; Page:       1


        .setcpu "6502"

LEB83           := $EB83
LEB88           := $EB88
        php
        ldy     $02
        lda     $800A,y
        jmp     LEB30

        lda     $89
        and     #$04
        beq     LEB17
        ldy     $02
        lda     $800F,y
        jmp     LEB30

LEB17:  lda     $89
        and     #$02
        beq     LEB25
        ldy     $02
        lda     $8014,y
        jmp     LEB30

LEB25:  lda     $89
        and     #$01
        beq     LEB51
        ldy     $02
        lda     $8019,y
LEB30:  sta     $02
        ldy     #$01
        lda     ($97),y
        clc
        ldy     $02
        adc     $8000,y
        sta     $09
        lda     #$00
        sta     $08
        tay
        lda     ($97),y
        clc
        ldy     $02
        adc     $8005,y
        sta     $0B
        lda     #$00
        sta     $0A
LEB51:  lda     $04
        ldx     $05
        cpx     $09
        bne     LEB69
        cmp     $08
        bne     LEB69
        lda     $06
        ldx     $07
        cpx     $0B
        bne     LEB69
        cmp     $0A
        beq     LEB6E
LEB69:  lda     #$00
        jmp     LEB83

LEB6E:  lda     $89
        and     #$80
        beq     LEB88
        lda     $18
        bne     LEB88
        lda     #$01
        sta     $18
        lda     #$10
        sta     $03
