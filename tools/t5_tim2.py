"""Tekken 5 TIM2 pictures with numpy: fast decode, and encode of 8-bit indexed pictures (256
colours, RGBA32 CLUT in CSM1 order, alpha 0..0x80) by colour quantisation.

The GS reads CLUT alpha 0x80 as opaque (tim2png.color: a * 2). CSM1: in every block of 32
entries, entries 8..15 and 16..23 are stored swapped.
"""
import struct

import numpy as np


def csm1(idx):
    """Storage position of CLUT entry idx (and back: the swap is its own inverse)."""
    b = idx & 7
    g = (idx >> 3) & 3
    g = {1: 2, 2: 1}.get(g, g)
    return (idx & ~31) | (g << 3) | b


PERM = np.array([csm1(i) for i in range(256)])


def decode(data, off=0, picture=0):
    """(RGBA uint8 array, header bytes of the picture) of picture `picture` of the TIM2 at `off`."""
    assert data[off:off + 4] == b"TIM2"
    count, = struct.unpack_from("<H", data, off + 6)
    p = off + 16
    for k in range(count):
        tot, clsz, imsz, hsz, clc, _f, _m, clt, imt, w, h = struct.unpack_from("<IIIHHBBBBHH", data, p)
        if k == picture:
            img = np.frombuffer(data, np.uint8, imsz, p + hsz)
            clut = np.frombuffer(data, np.uint8, clsz, p + hsz + imsz)
            assert clt & 0x3F == 3, "RGBA32 CLUT expected"
            pal = clut[:clc * 4].reshape(clc, 4).astype(np.int32)
            if clc == 256 and not clt & 0x80:
                pal = pal[PERM]
            pal[:, 3] = np.minimum(255, pal[:, 3] * 2)
            if imt == 5:
                ix = img[:w * h]
            elif imt == 4:
                ix = np.empty(w * h, np.uint8)
                ix[0::2] = img[:w * h // 2] & 15
                ix[1::2] = img[:w * h // 2] >> 4
            else:
                raise ValueError(f"image type {imt}")
            return pal[ix].reshape(h, w, 4).astype(np.uint8), bytes(data[p:p + hsz])
        p += tot
    raise IndexError(picture)


def quantise(rgba, n=256, iters=8):
    """Palette (n x 4, alpha 0..255) and indices for an RGBA image: median cut + k-means refine.
    Fully transparent pixels share one entry (0, 0, 0, 0)."""
    px = rgba.reshape(-1, 4).astype(np.float64)
    transparent = px[:, 3] < 4
    opaque = px[~transparent]
    boxes = [opaque]
    target = n - 1 if transparent.any() else n
    while len(boxes) < target:
        i = max(range(len(boxes)), key=lambda k: (np.ptp(boxes[k], axis=0).max() if len(boxes[k]) > 1 else -1))
        b = boxes[i]
        if len(b) < 2:
            break
        ch = np.ptp(b, axis=0).argmax()
        b = b[b[:, ch].argsort()]
        boxes[i:i + 1] = [b[:len(b) // 2], b[len(b) // 2:]]
    pal = np.array([b.mean(axis=0) for b in boxes if len(b)])
    for _ in range(iters):
        d = ((opaque[:, None, :] - pal[None, :, :]) ** 2 * [1, 1.2, 0.8, 2]).sum(axis=2) if len(opaque) < 60000 else None
        if d is None:
            break
        lab = d.argmin(axis=1)
        for k in range(len(pal)):
            m = lab == k
            if m.any():
                pal[k] = opaque[m].mean(axis=0)
    if transparent.any():
        pal = np.vstack([[0, 0, 0, 0], pal])
    pal = np.clip(np.round(pal), 0, 255)
    idx = np.empty(len(px), np.int64)
    w = np.array([1, 1.2, 0.8, 2])
    for s in range(0, len(px), 20000):
        blk = px[s:s + 20000]
        idx[s:s + 20000] = (((blk[:, None, :] - pal[None, :, :]) ** 2) * w).sum(axis=2).argmin(axis=1)
    if transparent.any():
        idx[transparent] = 0
    return pal.astype(np.uint8), idx.reshape(rgba.shape[:2])


def encode8(rgba, header_template):
    """One-picture TIM2 (8-bit indices, 256 x RGBA32 CLUT, CSM1) using a template picture header
    (keeps its extension chunks, e.g. GIDX; sizes are rewritten). Returns the picture bytes
    without the 16-byte file header (see `tim2_file`)."""
    h, w = rgba.shape[:2]
    pal, idx = quantise(rgba)
    full = np.zeros((256, 4), np.uint8)
    full[:len(pal)] = pal
    full[:, 3] = (full[:, 3].astype(np.int32) + 1) // 2           # 0..255 -> 0..0x80
    stored = full[PERM]                                            # CSM1 order
    hdr = bytearray(header_template)
    hsz = len(hdr)
    imsz, clsz = w * h, 256 * 4
    struct.pack_into("<IIIHH", hdr, 0, hsz + imsz + clsz, clsz, imsz, hsz, 256)
    hdr[0x12], hdr[0x13] = 0x03, 0x05                              # CLUT RGBA32 CSM1, 8-bit image
    struct.pack_into("<HH", hdr, 0x14, w, h)
    return bytes(hdr) + idx.astype(np.uint8).tobytes() + stored.tobytes()


def tim2_file(pictures):
    """TIM2 file from picture blobs (format 4, version 0 like the game's)."""
    return b"TIM2" + struct.pack("<BBH", 4, 0, len(pictures)) + bytes(8) + b"".join(pictures)
