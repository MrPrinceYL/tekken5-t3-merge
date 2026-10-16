"""Tekken 3 (PS1) animations: exact port of the decoder (merge/PLAN.md).

A character pack (BNS 0x62+4m) holds the moveset: u16 +2 = move count, +8 = moves (56 bytes,
word 0 = animation offset in section +0x1C; >= 0x40000000 = common pack). An animation
(FUN_80038b4c) decodes to a pose vector of 49 s16 channels per frame: root position (0-2), four
IK targets (3-14: hands / feet), four bend hints (15-18), ten euler triples (19-48, 12-bit
angles) - FUN_8003ad10 turns it into bone matrices (two-bone IK for the limbs).

    python t3_anim.py [model]      # decode the first animations of a model (default Ogre 22)
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_model import f  # noqa: E402

ELF = r"E:/Decompilation/Decomps/Tekken3/extracted/resident.elf"
_elf = None


def _ram(addr, n):
    global _elf
    if _elf is None:
        d = open(ELF, "rb").read()
        phoff, = struct.unpack_from("<I", d, 0x1C)
        phnum, = struct.unpack_from("<H", d, 0x2C)
        _elf = (d, [struct.unpack_from("<8I", d, phoff + i * 32) for i in range(phnum)])
    d, segs = _elf
    for _, off, va, _, fsz, *_ in segs:
        if va <= addr < va + fsz:
            return d[off + addr - va: off + addr - va + n]
    raise ValueError(hex(addr))


def u8(a): return _ram(a, 1)[0]
def u16(a): return struct.unpack("<H", _ram(a, 2))[0]
def s32(x): return ((x & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000
def s16(x): return ((x & 0xFFFF) ^ 0x8000) - 0x8000


SHIFT = None


def curve(data, p, t, k, shift):
    """FUN_800387c8: value at frame t of a key list at data[p] (s16 words)."""
    def w(i): return struct.unpack_from("<h", data, p + 2 * i)[0]
    k -= 1
    v3 = w(0)
    u8_ = w(1) & 0xFFFFFFFF
    i = 2
    v2 = v3
    v7 = s32(((s32(u8_) >> 5) << shift) + v3)
    v10 = 0
    while True:
        v9, v6, v5, v4 = v10, v7, v2, v3
        v10 = v9 + (u8_ & 0x1F) + 1
        v7 = v6
        if v10 == k:
            break
        u8_ = w(i) & 0xFFFFFFFF
        i += 1
        v7 = s32(v6 + ((s32(u8_) >> 5) << shift))
        v3, v2 = v5, v6
        if not (0 < t - v10):
            break
    t -= v9
    seg = v10 - v9
    b = 0
    if t != 0:
        if seg - 0x10 < 1:
            b = u8(0x800966F8 + seg * 0x20 + t + 3)
        else:
            b = u8((0x80096B3C - seg * 0x20 - t) & 0xFFFFFFFF)
        b <<= 1
    in_v1 = 0
    if v9 == 0:
        uv = u16(0x80096C20 - b)
        r = u16(0x80096A1C - b) * (v7 - v5)
    else:
        a4 = u16(0x8009691C + b) * (v4 - v5)
        if v10 == k:
            uv = u16(0x80096C20 - b) + u16(0x80096A1C - b) + 0x2AAB
            r = a4
        else:
            r = u16(0x80096A1C - b) * (v7 - v5)
            uv = u16(0x80096B1E - b)
            in_v1 = a4
    if v9 != 0 and v10 != k:
        r += in_v1
    return (s32(r + uv * (v6 - v5)) >> 16) + v5


def decode(data, a, frame):
    """FUN_80038b4c: the 49-channel pose of the animation at data[a] for `frame`."""
    head, = struct.unpack_from("<H", data, a)
    k = head & 0xFF
    frame = max(0, min(frame, k - 1))
    n = head >> 8
    counts = data[a + 2: a + 50]
    p = a + 50
    out = []
    for c in range(49):
        t = k - (frame + 1) if c & 1 else frame
        if n == 0:
            v = 0
        elif n == 1:
            v = struct.unpack_from("<H", data, p)[0] << 1
        elif n == 2:
            x = struct.unpack_from("<h", data, p + 2)[0] * t
            if k > 9:
                x >>= 5
            v = (struct.unpack_from("<H", data, p)[0] + x) << 1
        elif n == k:
            v = struct.unpack_from("<H", data, p + 2 * t)[0] << 1
        else:
            v = curve(data, p, t, k, u8(0x80096C24 + c)) << 1
        out.append(s16(v))
        p += 2 * n
        if c < 48:
            n = counts[c]
    return out, k


def pack(m):
    """Character pack of model m: (data, move count, moves offset, animation section offset)."""
    d = f(0x62 + 4 * m)
    return d, struct.unpack_from("<H", d, 2)[0], struct.unpack_from("<I", d, 8)[0], struct.unpack_from("<I", d, 0x1C)[0]


if __name__ == "__main__":
    m = int(sys.argv[1]) if len(sys.argv) > 1 else 22
    d, nm, mv, an = pack(m)
    for i in range(3):
        o = struct.unpack_from("<I", d, mv + 56 * i)[0]
        if o >= 0x40000000:
            continue
        _, k = decode(d, an + o, 0)
        for fr in (0, k // 2, k - 1):
            pose, _ = decode(d, an + o, fr)
            print(f"move {i} anim {o:#x} frames {k} frame {fr}: {pose[:19]} | rot {pose[19:31]}")
