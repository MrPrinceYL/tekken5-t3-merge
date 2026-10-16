"""Tekken 3 versus-screen portraits (BNS 12 + character): a container of Namco LZ pieces
(FUN_80031bfc, the same LZ as TK5DATA3) holding a PS1 TIM (FUN_8004c7e4 -> LoadImage).

    python t3_portraits.py <out dir>      # every portrait as PNG + an overview sheet
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_model import f as bns  # noqa: E402
from tim2png import png  # noqa: E402
from tk5data import lz_decompress  # noqa: E402

FIRST, COUNT = 12, 24


def c15(v):
    """PS1 15-bit colour -> RGBA (0x0000 = transparent, STP ignored)."""
    r, g, b = (v & 31) << 3, (v >> 5 & 31) << 3, (v >> 10 & 31) << 3
    return (r | r >> 5, g | g >> 5, b | b >> 5, 0 if v == 0 else 255)


def tim(d):
    """(width, height, rgba bytes) of a PS1 TIM (4/8/16 bit)."""
    magic, flags = struct.unpack_from("<II", d, 0)
    assert magic == 0x10, "not a TIM"
    mode, p = flags & 7, 8
    clut = []
    if flags & 8:
        n, _, _, cw, ch = struct.unpack_from("<IHHHH", d, p)
        clut = [c15(v) for v in struct.unpack_from(f"<{cw * ch}H", d, p + 12)]
        p += n
    _, _, _, w16, h = struct.unpack_from("<IHHHH", d, p)
    px = d[p + 12:]
    out = bytearray()
    if mode == 0:
        w = w16 * 4
        for y in range(h):
            for x in range(w):
                b = px[y * w16 * 2 + x // 2]
                out += bytes(clut[(b >> 4) if x & 1 else (b & 15)])
    elif mode == 1:
        w = w16 * 2
        for i in range(w * h):
            out += bytes(clut[px[i]])
    else:
        w = w16
        for i in range(w * h):
            out += bytes(c15(struct.unpack_from("<H", px, 2 * i)[0]))
    return w, h, bytes(out)


def unpack(d):
    """One Namco LZ stream, or (BNS 12/13) a container of them: u32 count, count x {u32 offset,
    u32 size}; the pieces concatenated are the file."""
    n, = struct.unpack_from("<I", d, 0)
    if n > 0x400:
        return lz_decompress(d)[0]
    return b"".join(lz_decompress(d[o:o + s])[0]
                    for o, s in (struct.unpack_from("<II", d, 4 + 8 * i) for i in range(n)))


def portrait(n):
    """Portrait of T3 character n: (w, h, rgba)."""
    return tim(unpack(bns(FIRST + n)))


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    pics = [portrait(n) for n in range(COUNT)]
    for n, (w, h, rgba) in enumerate(pics):
        png(str(out / f"t3_portrait_{n:02d}.png"), w, h, rgba)
    cols = 8
    W = max(p[0] for p in pics)
    H = max(p[1] for p in pics)
    rows = (COUNT + cols - 1) // cols
    sheet = bytearray(cols * W * rows * H * 4)
    for n, (w, h, rgba) in enumerate(pics):
        ox, oy = (n % cols) * W, (n // cols) * H
        for y in range(h):
            s = (y * w) * 4
            t = ((oy + y) * cols * W + ox) * 4
            sheet[t:t + w * 4] = rgba[s:s + w * 4]
    png(str(out / "t3_portraits.png"), cols * W, rows * H, bytes(sheet))
    print([(n, p[0], p[1]) for n, p in enumerate(pics)])
