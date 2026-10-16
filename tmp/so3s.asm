; da65 V2.18 - Debian 2.19-1
; Created:    2026-10-16 14:56:44
; Input file: tmp/so3s.prg
; Page:       1


        .setcpu "6502"

L0120           := $0120
LE001           := $E001
LE004           := $E004
LE100           := $E100
LE10B           := $E10B
LE123           := $E123
LE15C           := $E15C
LE16E           := $E16E
LE293           := $E293
LE294           := $E294
LE295           := $E295
LE296           := $E296
        jsr     L0120
        cpx     #$E6
        sed
        tya
        and     #$20
        jsr     LE004
        rts

        jsr     LE123
        lda     #$80
        ldx     #$00
        ldy     #$09
        jsr     LE10B
        lda     #$02
        jsr     LE15C
        ldy     #$3D
        lda     #$66
        jsr     LE296
        ldy     $2002
        ldx     $2002
        jsr     LE16E
        jsr     LE100
        lda     #$00
        ldx     #$00
        ldy     #$09
        jsr     LE10B
        lda     #$00
        ldx     #$03
        ldy     #$09
        jsr     LE10B
        lda     #$04
        jsr     LE15C
        ldy     #$02
        lda     #$B8
        jsr     LE295
        ldx     $2002
        ldy     $2002
        jsr     LE16E
        lda     #$FF
        ldx     #$03
        ldy     #$09
        jsr     LE10B
        lda     #$06
        jsr     LE15C
        ldy     #$02
        lda     #$B8
        jsr     LE295
        lda     $2002
        ldx     $2002
        and     #$20
        jsr     LE001
        txa
        and     #$20
        jsr     LE004
        jsr     LE100
        lda     #$00
        ldx     #$DC
        ldy     #$09
        jsr     LE10B
        lda     #$07
        jsr     LE15C
        ldy     #$08
        lda     #$2E
        jsr     LE294
        ldx     $2002
        ldy     $2002
        jsr     LE16E
        jsr     LE100
        lda     #$EF
        ldx     #$00
        ldy     #$09
        jsr     LE10B
        lda     #$09
        jsr     LE15C
        ldy     #$1A
        lda     #$DE
        jsr     LE293
        ldx     $2002
        ldy     $2002
        jsr     LE16E
