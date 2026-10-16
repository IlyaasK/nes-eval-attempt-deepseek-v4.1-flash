"""Shared helpers: a probe ROM that shows a byte as two hex digits on screen."""
import numpy as np

GLYPHS = {
 0:"0110010101100101011001010110010101100101011001010110011000000000",
}
DIGITS = {
 '0':'01111100'+'11000110'+'11000110'+'11000110'+'11000110'+'11000110'+'01111100'+'00000000',
 '1':'00110000'+'01110000'+'00110000'+'00110000'+'00110000'+'00110000'+'11111100'+'00000000',
 '2':'01111000'+'11001100'+'00001100'+'00011000'+'00110000'+'01100000'+'11111100'+'00000000',
 '3':'01111000'+'11001100'+'00001100'+'00111000'+'00001100'+'11001100'+'01111000'+'00000000',
 '4':'00011000'+'00111000'+'01111000'+'11011000'+'11111110'+'00011000'+'00011000'+'00000000',
 '5':'11111100'+'11000000'+'11111000'+'00001100'+'00001100'+'11001100'+'01111000'+'00000000',
 '6':'00111000'+'01100000'+'11000000'+'11111000'+'11001100'+'11001100'+'01111000'+'00000000',
 '7':'11111100'+'11001100'+'00001100'+'00011000'+'00110000'+'00110000'+'00110000'+'00000000',
 '8':'01111000'+'11001100'+'11001100'+'01111000'+'11001100'+'11001100'+'01111000'+'00000000',
 '9':'01111000'+'11001100'+'11001100'+'01111100'+'00001100'+'00011000'+'01110000'+'00000000',
 'A':'00110000'+'01111000'+'11001100'+'11001100'+'11111100'+'11001100'+'11001100'+'00000000',
 'B':'11111000'+'11001100'+'11001100'+'11111000'+'11001100'+'11001100'+'11111000'+'00000000',
 'C':'01111000'+'11001100'+'11000000'+'11000000'+'11000000'+'11001100'+'01111000'+'00000000',
 'D':'11110000'+'11011000'+'11001100'+'11001100'+'11001100'+'11011000'+'11110000'+'00000000',
 'E':'11111100'+'11000000'+'11000000'+'11111000'+'11000000'+'11000000'+'11111100'+'00000000',
 'F':'11111100'+'11000000'+'11000000'+'11111000'+'11000000'+'11000000'+'11000000'+'00000000',
}
def chr_ram_font():
    """Return an 8 KiB CHR image with ASCII-hex tiles at indices 0..15."""
    chr_ = bytearray(8192)
    for i in range(16):
        pat = DIGITS['0123456789ABCDEF'[i]]
        for row in range(8):
            bits = pat[row*8:(row+1)*8]
            lo = 0
            for c, b in enumerate(bits):
                if b == '1':
                    lo |= 0x80 >> c
            chr_[i*16 + row] = lo
            chr_[i*16 + 8 + row] = lo      # both bitplanes -> colour 3
    return bytes(chr_)

def hextext(chr_path=None):
    """Return a texture dict for readtext: tile index -> character."""
    return {'chr': chr_ram_font() if chr_path is None else None,
            'map': {i: '0123456789ABCDEF'[i] for i in range(16)}}


def decode_screen(frame):
    """Decode a 256x240 index framebuffer rendered with the hex font into a
    list of 960 characters (32 tiles per row, values from chr_ram_font)."""
    font = chr_ram_font()
    # build glyph bitmaps for every tile index
    def bits(t):
        return [[(font[t * 16 + r] >> (7 - c)) & 1 for c in range(8)] for r in range(8)]
    cands = list(range(256))
    out = []
    for ty in range(30):
        for tx in range(32):
            cell = frame[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8]
            on = [[1 if cell[r, c] == 0x30 else 0 for c in range(8)] for r in range(8)]
            best, bs = '?', -1
            for t in cands:
                p = bits(t)
                s = sum(1 for r in range(8) for c in range(8) if p[r][c] == on[r][c])
                if s > bs:
                    bs, best = s, t
            if 0 <= best <= 15:
                out.append('0123456789ABCDEF'[best])
            else:
                out.append('.')
    return out
