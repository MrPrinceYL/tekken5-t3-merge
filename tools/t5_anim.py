"""Tekken 5 animations (format 0x64): decoder and encoder (Tekken5-Tekken3-Merge, merge/PLAN.md).

Animation bank (moveset sub-file 1/3/5, container block 0): u8 0x64, u8 0, u16 count, u16 23
(animated bones), u16 descriptor[23] (4..7 = rotation as s16 * pi/32769, else float = position),
u32 offset[count] (from the bank start), then the animations.

Animation (decoder after TKMovesets' ParseAnimation0x64): u16 frames, u8 short shift, u8 float
shift, u16 float bones, f32 factor[float bones], base pose (per bone 3 x s16 or 3 x f32), then
u32 offset[keyframes] (one per 16 frames, from that table) and per keyframe, per bone and axis a
record: byte (size << 2 | first 2 bits), MSB-first bit stream of codes: the first code is the
keyframe's value relative to the base pose, the next ones second differences for the 15 frames
after it. Frame 1 is the base pose itself.

    python t5_anim.py <bank file>     # round-trip test over every animation of a bank
"""
import math
import struct
import sys

MULT = math.pi / 32769
DESC_T5 = (11, 11, 5, 7, 7, 7, 11, 7, 7, 7, 7, 6, 7, 7, 7, 6, 7, 7, 6, 7, 7, 6, 7)
# (prefix, payload bits, offset) of the value codes, smallest range first
CODES = [(1, 2, 1), (2, 2, -4), (3, 4, 5), (4, 4, -20), (5, 6, 21), (6, 6, -84), (7, 8, 85),
         (8, 8, -340), (9, 10, 341), (10, 10, -1364), (11, 12, 1365), (12, 12, -5460)]


def is_short(desc):
    return 4 <= desc <= 7


def s16(x):
    return ((x & 0xFFFF) ^ 0x8000) - 0x8000


class BitReader:
    """sub_1407316F0: MSB-first bits, two of them already in the record's header byte."""

    def __init__(self, data, pos, rem):
        self.d, self.p, self.rem, self.avail = data, pos, rem, 2

    def read(self, n):
        if self.avail < n:
            k = (n - self.avail - 1) // 8 + 1
            for _ in range(k):
                self.rem = self.d[self.p] | (self.rem << 8)
                self.p += 1
            self.avail += 8 * k
        self.avail -= n
        v = self.rem >> self.avail
        self.rem &= (1 << self.avail) - 1
        return s16(v)


def read_code(br, state):
    """TK__Anim_64_sub_140733340. state = [repeat count, payload bits, offset]."""
    if state[0]:
        state[0] -= 1
        if state[1] == 0:
            return 0
        if state[1] == 99:
            return None
        return state[2] + br.read(state[1])
    c = br.read(4) & 15
    if c == 0:
        state[1:] = [0, 0]
        return 0
    if c == 13:
        state[1:] = [16, 0]
        return br.read(16)
    if c == 14:
        state[0] = (br.read(4) & 15) - 1
        if state[1] == 0:
            return 0
        if state[1] == 99:
            return None
        return state[2] + br.read(state[1])
    if c == 15:
        state[1:] = [99, 0]
        return None
    _, n, off = CODES[c - 1]
    state[1:] = [n, off]
    return off + br.read(n)


def parse(anim, desc=DESC_T5):
    nb = len(desc)
    frames, sh, fsh, fb = struct.unpack_from("<HBBH", anim, 0)
    factors = struct.unpack_from(f"<{fb}f", anim, 6)
    p = 2 * ((4 * fb + 6) // 2)
    base, base_int = [], []
    for d in desc:
        if is_short(d):
            v = struct.unpack_from("<3h", anim, p)
            base.append([x * MULT for x in v])
            base_int.append([s16(x >> sh) for x in v])
            p += 6
        else:
            base.append(list(struct.unpack_from("<3f", anim, p)))
            base_int.append([0, 0, 0])
            p += 12
    return dict(frames=frames, sh=sh, fsh=fsh, factors=factors, base=base, base_int=base_int, table=p, nb=nb)


def decode_frame(anim, frame, desc=DESC_T5, info=None):
    """Pose of `frame` (1-based): [[x, y, z] per bone] (radians / units)."""
    a = info or parse(anim, desc)
    frame = min(max(frame, 1), max(1, a["frames"] - 1))
    out = [list(b) for b in a["base"]]
    bf = frame - 1
    if bf == 0:
        return out
    sub, kf = bf & 15, bf // 16
    p = a["table"] + struct.unpack_from("<I", anim, a["table"] + 4 * kf)[0]
    fi = 0
    for j, d in enumerate(desc):
        for i in range(3):
            hdr = anim[p]
            br = BitReader(anim, p + 1, hdr & 3)
            st = [0, 0, 0]
            v = a["base_int"][j][i] + read_code(br, st)
            s = 0
            for _ in range(sub):
                r = read_code(br, st)
                if r is None:
                    break
                s += r
                v += s
            v = s16(v)
            if is_short(d):
                out[j][i] = (v << a["sh"]) * MULT
            else:
                out[j][i] = (v << a["fsh"]) * a["factors"][fi] + a["base"][j][i]
            p += hdr >> 2
        if not is_short(d):
            fi += 1
    return out


def decode_ints(anim, desc=DESC_T5):
    """All frames as the integers the game accumulates (for exact round-trip tests)."""
    a = parse(anim, desc)
    res = []
    # the last keyframe block covers frame `frames - 1` (TKMovesets' size calculation)
    for frame in range(1, max(2, a["frames"])):
        bf = frame - 1
        row = [list(x) for x in a["base_int"]]
        if bf:
            sub, kf = bf & 15, bf // 16
            p = a["table"] + struct.unpack_from("<I", anim, a["table"] + 4 * kf)[0]
            for j in range(len(desc)):
                for i in range(3):
                    hdr = anim[p]
                    br = BitReader(anim, p + 1, hdr & 3)
                    st = [0, 0, 0]
                    v = row[j][i] + read_code(br, st)
                    s = 0
                    for _ in range(sub):
                        r = read_code(br, st)
                        if r is None:
                            break
                        s += r
                        v += s
                    row[j][i] = s16(v)
                    p += hdr >> 2
        res.append(row)
    return a, res


class BitWriter:
    def __init__(self):
        self.bits = []

    def put(self, v, n):
        for k in range(n - 1, -1, -1):
            self.bits.append((v >> k) & 1)

    def record(self):
        """Header byte (size << 2 | first two bits) + the remaining bits, MSB first."""
        b = self.bits + [0] * max(0, 2 - len(self.bits))
        rest = b[2:]
        body = bytearray()
        for k in range(0, len(rest), 8):
            chunk = rest[k:k + 8] + [0] * (8 - len(rest[k:k + 8]))
            body.append(sum(bit << (7 - i) for i, bit in enumerate(chunk)))
        size = 1 + len(body)
        assert size < 64, "channel record too long"
        return bytes([(size << 2) | (b[0] << 1) | b[1]]) + bytes(body)


def put_code(bw, v):
    if v == 0:
        bw.put(0, 4)
        return
    for prefix, n, off in CODES:
        if 0 <= v - off < (1 << n):
            bw.put(prefix, 4)
            bw.put(v - off, n)
            return
    bw.put(13, 4)
    bw.put(v & 0xFFFF, 16)


def encode(values, desc=DESC_T5, sh=0, fsh=0, factors=None, base_float=None):
    """Animation from integer channel values: values[frame][bone][axis] (frame 0 = base pose;
    shorts in units of pi/32769 >> sh, floats in units of factor << fsh relative to base_float)."""
    nb = len(desc)
    floats = [j for j, d in enumerate(desc) if not is_short(d)]
    factors = factors or [1.0] * len(floats)
    base_float = base_float or [[0.0, 0.0, 0.0] for _ in floats]
    frames = len(values)
    # header frame count = values + 1: the game decodes frames 1 .. count - 1
    out = bytearray(struct.pack("<HBBH", frames + 1, sh, fsh, len(floats)))
    out += struct.pack(f"<{len(floats)}f", *factors)
    while len(out) < 2 * ((4 * len(floats) + 6) // 2):
        out += b"\0"
    fi = 0
    for j, d in enumerate(desc):
        if is_short(d):
            out += struct.pack("<3h", *[s16(x << sh) for x in values[0][j]])
        else:
            out += struct.pack("<3f", *[base_float[fi][i] + (values[0][j][i] << fsh) * factors[fi] for i in range(3)])
            fi += 1
    nk = (frames - 1) // 16 + 1 if frames > 1 else 1
    streams = []
    for k in range(nk):
        rec = bytearray()
        for j, d in enumerate(desc):
            base_v = values[0][j] if is_short(d) else [0, 0, 0]
            for i in range(3):
                bw = BitWriter()
                f0 = 16 * k
                get = lambda f: values[min(f, frames - 1)][j][i]
                put_code(bw, 0 if k == 0 else s16(get(f0) - base_v[i]))
                prev_d = 0
                for s in range(1, 16):
                    dlt = s16(get(f0 + s) - get(f0 + s - 1))
                    put_code(bw, s16(dlt - prev_d))
                    prev_d = dlt
                rec += bw.record()
        streams.append(rec)
    table_at = len(out)
    out += bytes(4 * nk)
    for k, rec in enumerate(streams):
        struct.pack_into("<I", out, table_at + 4 * k, len(out) - table_at)
        out += rec
    return bytes(out)


def bank(data):
    """(descriptors, [animation bytes]) of an animation bank."""
    cnt, nb = struct.unpack_from("<HH", data, 2)
    desc = struct.unpack_from(f"<{nb}H", data, 6)
    offs = struct.unpack_from(f"<{cnt}I", data, 6 + 2 * nb)
    starts = sorted(set(o for o in offs if o)) + [len(data)]
    end = {a: b for a, b in zip(starts, starts[1:])}
    return desc, [data[o:end[o]] if o else b"" for o in offs]


if __name__ == "__main__":
    d = open(sys.argv[1], "rb").read()
    n, = struct.unpack_from("<I", d, 0)
    o, s = struct.unpack_from("<II", d, 4)
    desc, anims = bank(d[o:o + s])
    bad = 0
    for k, an in enumerate(anims):
        if not an:
            continue
        info, ints = decode_ints(an, desc)
        # re-encode the decoded integers (frame 0 = base) and decode again
        base_ints = [list(r) for r in ints[0]]
        floats = [j for j, x in enumerate(desc) if not is_short(x)]
        re = encode(ints, desc, sh=info["sh"], fsh=info["fsh"], factors=list(info["factors"]),
                    base_float=[info["base"][j] for j in floats])
        _, ints2 = decode_ints(re, desc)
        if ints2 != ints:
            bad += 1
    print(f"{len(anims)} animations, {bad} round-trip mismatches")
