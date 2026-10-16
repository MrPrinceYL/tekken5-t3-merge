"""Tekken 5 costume model (slot sub-file 10, container of 19 blocks): mesh block "NUDP".

NUDP: "NUDP", u32 size, u32 counts, u32 0, then 0x40-byte batch records (bounding sphere,
vertex count, data offset, bone palette) and VIF packets for VU1 per batch:
STCYCL 1/5, UNPACK V1-32 @0 (vertex count), V3-32 @1 positions, V3-32 @2 normals, V2-32 @4 UVs
(stride 5 qwords), STCYCL 1/2, V4-32 @0xCC weights, V4-8 @0xCD bone indices (x7), control
words, MSCAL.

    python t5_model.py [file]    # batches of merge/extracted/tk5data1/0240.bin
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def container(d):
    n, = struct.unpack_from("<I", d, 0)
    return [struct.unpack_from("<II", d, 4 + 8 * i) for i in range(n)]


def vif_batches(b, start=0, end=None):
    """Walk the VIF stream; yield one dict per MSCAL with the unpacked arrays. STCYCL is tracked:
    in filling mode (CL < WL) an UNPACK reads only CL of every WL elements; with CL = 0 it reads
    nothing and only writes the masked row value - Tekken 5 uses that to set the ADC bit (no
    triangle) on vertex positions: `adc` = flagged vertex indices ((address - 1) / 5, stride 5)."""
    p = start
    end = len(b) if end is None else end
    cl, wl = 1, 1
    cur = {}
    while p + 4 <= end:
        w, = struct.unpack_from("<I", b, p)
        cmd, num, imm = (w >> 24) & 0x7F, (w >> 16) & 0xFF, w & 0xFFFF
        if cmd >= 0x60:
            vn, vl = (cmd >> 2) & 3, cmd & 3
            comp, size = vn + 1, [32, 16, 8, 5][vl]
            n = num or 256
            reads = n if cl >= wl else (n // wl) * cl + min(n % wl, cl)
            nbytes = ((size * comp * reads + 31) // 32) * 4
            data = b[p + 4:p + 4 + nbytes]
            addr = imm & 0x3FF
            if reads == 0:
                # ADC: positions written are at addr + i for i < n; a vertex occupies 5 qwords
                first = (addr - 1) // 5
                cur.setdefault("adc", set()).update(range(first, first + (n - 1) // 5 + 1))
            elif (comp, size) == (3, 32):
                cur.setdefault("v3", {})[addr] = [struct.unpack_from("<3f", data, 12 * i) for i in range(reads)]
            elif (comp, size) == (2, 32):
                cur["uv"] = [struct.unpack_from("<2f", data, 8 * i) for i in range(reads)]
            elif (comp, size) == (4, 32):
                cur["w"] = [struct.unpack_from("<4f", data, 16 * i) for i in range(reads)]
            elif (comp, size) == (4, 8):
                cur["j"] = [tuple(data[4 * i:4 * i + 4]) for i in range(reads)]
            elif (comp, size) == (1, 32):
                vals = struct.unpack_from(f"<{reads}I", data, 0)
                if addr == 0 and reads == 1:
                    cur["n"] = vals[0]
                else:
                    cur.setdefault("other", []).append((addr, vals))
            p += 4 + nbytes
            continue
        p += 4
        if cmd == 0x01:
            cl, wl = imm & 0xFF, imm >> 8
        elif cmd == 0x20:
            p += 4
        elif cmd in (0x30, 0x31):
            p += 16
        elif cmd in (0x50, 0x51):
            p += (imm or 65536) * 16
        elif cmd == 0x4A:
            p += (num or 256) * 8
        elif cmd in (0x14, 0x15, 0x17):
            if cur:
                yield cur
            cur = {}
        elif cmd not in (0x00, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x10, 0x11, 0x13):
            raise ValueError(f"unknown VIF code {w:#010x} at {p - 4:#x}")


def strip_triangles(bt):
    """Triangles of a batch: one strip, winding alternating with the vertex index, no triangle
    ends at an ADC-flagged vertex."""
    P = bt["v3"][1]
    adc = bt.get("adc", set())
    out = []
    for i in range(2, len(P)):
        if i in adc:
            continue
        out.append((i - 2, i - 1, i) if i % 2 == 0 else (i - 2, i, i - 1))
    return out


def groups(b):
    """Groups of an NUDP block b: header byte 10 = group count; group = u8 flags (0x20/0x24),
    u8 0, u8 0, u8 main node, u16 batches, u16 vertices, f32 sphere[4]; then per batch 0x28 bytes:
    4 render-state words (word 0 low 16 bits = material = TIM2 picture), u32 data offset, u16
    qwords, u16 VIF packets, u32 0, u16 0, u8 palette[10] (node indices, 0xFF = unused)."""
    out = []
    p = 0x20
    for _ in range(b[10]):
        nb, nv = struct.unpack_from("<HH", b, p + 4)
        g = {"flags": b[p], "main": b[p + 3], "verts": nv, "sphere": struct.unpack_from("<4f", b, p + 8), "batches": []}
        q = p + 0x18
        for _ in range(nb):
            st = struct.unpack_from("<4I", b, q)
            off, qwc, npk = struct.unpack_from("<IHH", b, q + 0x10)
            pal = [x for x in b[q + 0x1E:q + 0x28] if x != 0xFF]
            g["batches"].append({"state": st, "material": st[0] & 0xFFFF, "offset": off, "qwc": qwc,
                                 "packets": npk, "palette": pal})
            q += 0x28
        out.append(g)
        p = q
    return out


def nudp_blocks(d):
    return [(o, s) for o, s in container(d) if d[o:o + 4] == b"NUDP"]


def batches(d):
    out = []
    for o, s in nudp_blocks(d):
        b = d[o:o + s]
        first = min(struct.unpack_from("<I", b, 0x48 + 0x40 * i)[0] for i in range(1))
        out.append(list(vif_batches(b, first)))
    return out


if __name__ == "__main__":
    fn = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "merge/extracted/tk5data1/0240.bin")
    d = open(fn, "rb").read()
    for k, bl in enumerate(batches(d)):
        nv = sum(len(x.get("v3", {}).get(1, [])) for x in bl)
        js = sorted({j for x in bl for t in x.get("j", []) for j in t})
        print(f"NUDP {k}: {len(bl)} batches, {nv} vertices, bone indices {js[:20]}")
