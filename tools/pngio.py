"""Minimal PNG reader (8-bit RGB/RGBA/grey/palette, non-interlaced) -> numpy RGBA, and resampling
helpers for the portrait conversion (no PIL in this environment)."""
import struct
import zlib

import numpy as np


def read_png(path):
    """RGBA uint8 array (h, w, 4)."""
    d = open(path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", path
    p, idat, plte, trns = 8, bytearray(), None, None
    while p < len(d):
        n, = struct.unpack_from(">I", d, p)
        t, body = d[p + 4:p + 8], d[p + 8:p + 8 + n]
        if t == b"IHDR":
            w, h, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and inter == 0, "only 8-bit non-interlaced PNG"
        elif t == b"PLTE":
            plte = np.frombuffer(body, np.uint8).reshape(-1, 3)
        elif t == b"tRNS":
            trns = np.frombuffer(body, np.uint8)
        elif t == b"IDAT":
            idat += body
        p += 12 + n
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    raw = zlib.decompress(bytes(idat))
    stride = w * ch
    out = np.zeros((h, stride), np.uint8)
    prev = np.zeros(stride, np.int32)
    q = 0
    for y in range(h):
        f = raw[q]
        line = np.frombuffer(raw, np.uint8, stride, q + 1).astype(np.int32)
        q += 1 + stride
        if f == 0:
            cur = line
        elif f == 2:
            cur = (line + prev) & 255
        else:
            cur = np.zeros(stride, np.int32)
            for i in range(stride):
                a = cur[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                if f == 1:
                    pr = a
                elif f == 3:
                    pr = (a + b) >> 1
                else:
                    pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                    pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[i] = (line[i] + pr) & 255
        out[y] = cur
        prev = cur
    img = out.reshape(h, w, ch)
    if ctype == 6:
        return img.copy()
    rgba = np.full((h, w, 4), 255, np.uint8)
    if ctype == 2:
        rgba[..., :3] = img
    elif ctype == 0:
        rgba[..., :3] = img[..., :1]
    elif ctype == 4:
        rgba[..., :3] = img[..., :1]
        rgba[..., 3] = img[..., 1]
    else:
        idx = img[..., 0]
        rgba[..., :3] = plte[idx]
        if trns is not None:
            a = np.full(256, 255, np.uint8)
            a[:len(trns)] = trns
            rgba[..., 3] = a[idx]
    return rgba


def resize(img, w, h):
    """Area-average (box) resampling of an RGBA float/uint8 image to (h, w), alpha-weighted."""
    src = img.astype(np.float64)
    sh, sw = src.shape[:2]
    a = src[..., 3:4] / 255.0
    pre = np.concatenate([src[..., :3] * a, a * 255.0], axis=2)

    def axis_weights(n_src, n_dst):
        m = np.zeros((n_dst, n_src))
        scale = n_src / n_dst
        for i in range(n_dst):
            s0, s1 = i * scale, (i + 1) * scale
            for j in range(int(np.floor(s0)), min(n_src, int(np.ceil(s1)))):
                m[i, j] = max(0.0, min(s1, j + 1) - max(s0, j))
            m[i] /= m[i].sum()
        return m

    my, mx = axis_weights(sh, h), axis_weights(sw, w)
    out = np.tensordot(my, pre, axes=(1, 0))            # (h, sw, 4)
    out = np.tensordot(out, mx, axes=(1, 1)).transpose(0, 2, 1)   # (h, w, 4)
    alpha = out[..., 3:4]
    rgb = np.where(alpha > 0, out[..., :3] / np.maximum(alpha / 255.0, 1e-9), 0)
    return np.clip(np.concatenate([rgb, alpha], axis=2), 0, 255)


def write_png(path, img):
    """Write an RGBA uint8 array."""
    h, w = img.shape[:2]
    raw = b"".join(b"\0" + img[y].astype(np.uint8).tobytes() for y in range(h))

    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)

    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
