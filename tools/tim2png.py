"""TIM2 (PS2 texture container) to PNG, no dependencies.

    python tim2png.py <file> [offset] [out_prefix]

Writes <out_prefix>_<n>.png per picture. Supports 4/8-bit CLUT (CSM1 CLUT order) and 16/24/32-bit
images; PS2 alpha (0x80 = opaque) is scaled to 0..255.
"""
import struct, sys, zlib


def png(path, w, h, rgba):
    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    raw = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def color(b, kind):
    if kind == 1:                                   # 16-bit A1B5G5R5
        v = b[0] | b[1] << 8
        return bytes(((v & 31) * 255 // 31, (v >> 5 & 31) * 255 // 31, (v >> 10 & 31) * 255 // 31,
                      255 if v & 0x8000 else 0))
    if kind == 2:
        return bytes((b[0], b[1], b[2], 255))
    return bytes((b[0], b[1], b[2], min(255, b[3] * 2)))


def pictures(data, off=0):
    """Yield (width, height, rgba bytes) for every picture of the TIM2 at `off`."""
    assert data[off:off + 4] == b"TIM2", "not TIM2"
    count, = struct.unpack_from("<H", data, off + 6)
    p = off + 16
    for _ in range(count):
        tot, clsz, imsz, hsz, clc, _fmt, _mip, clt, imt, w, h = struct.unpack_from("<IIIHHBBBBHH", data, p)
        img = data[p + hsz:p + hsz + imsz]
        clut = data[p + hsz + imsz:p + hsz + imsz + clsz]
        ck = clt & 0x3F
        csz = {1: 2, 2: 3, 3: 4}.get(ck, 4)
        pal = [color(clut[i * csz:(i + 1) * csz], ck) for i in range(clc)]
        if clc == 256 and not clt & 0x80:           # CSM1: swap entries 8..15 and 16..23 of every 32
            for b in range(0, 256, 32):
                pal[b + 8:b + 16], pal[b + 16:b + 24] = pal[b + 16:b + 24], pal[b + 8:b + 16]
        out = bytearray()
        if imt == 4:
            for i in range(w * h):
                out += pal[img[i >> 1] >> (4 * (i & 1)) & 15]
        elif imt == 5:
            for i in range(w * h):
                out += pal[img[i]]
        else:
            bpp = {1: 2, 2: 3, 3: 4}[imt]
            for i in range(w * h):
                out += color(img[i * bpp:(i + 1) * bpp], imt)
        yield w, h, bytes(out)
        p += tot


if __name__ == "__main__":
    data = open(sys.argv[1], "rb").read()
    off = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0
    prefix = sys.argv[3] if len(sys.argv) > 3 else sys.argv[1]
    for n, (w, h, rgba) in enumerate(pictures(data, off)):
        png(f"{prefix}_{n}.png", w, h, rgba)
