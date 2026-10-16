"""Textured front-view render of a Tekken 5 costume model (sub-file 10) in bind pose, to check
the NUDP reading: groups/batches (t5_model.groups), strip triangles, material = TIM2 picture.

    python t5_render.py <model file> <out.png>
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t5_model import container, groups, strip_triangles, vif_batches  # noqa: E402
from tim2png import pictures, png  # noqa: E402

if __name__ == "__main__":
    d = open(sys.argv[1], "rb").read()
    E = container(d)
    allpics = list(pictures(d, E[1][0]))
    # material = texture id (GIDX chunk of the picture header), like the game (merge/PLAN.md)
    from t5_costume import gidx
    t = d[E[1][0]:]
    cnt, = struct.unpack_from("<H", t, 6)
    q, ids = 16, []
    for _ in range(cnt):
        tot, = struct.unpack_from("<I", t, q)
        ids.append(gidx(t[q:q + 0x50]))
        q += tot
    by_id = {i: allpics[k] for k, i in enumerate(ids) if i is not None}
    tris = []
    skip_body = "--costume-only" in sys.argv
    for k, (o, s) in enumerate(E):
        if d[o:o + 4] != b"NUDP" or (skip_body and k != 2):
            continue
        b = d[o:o + s]
        for g in groups(b):
            for bt in g["batches"]:
                tex = bt["material"]
                for vb in vif_batches(b, bt["offset"], bt["offset"] + bt["qwc"] * 16):
                    if 1 not in vb.get("v3", {}):
                        continue
                    P, UV = vb["v3"][1], vb.get("uv")
                    for t in strip_triangles(vb):
                        tris.append(([P[i] for i in t], [UV[i] for i in t] if UV else None, tex))
    W, H = 360, 480
    xs = [p[0] for t, _, _ in tris for p in t]; ys = [p[1] for t, _, _ in tris for p in t]
    mnx, mxx, mny, mxy = min(xs), max(xs), min(ys), max(ys)
    s = min((W - 8) / (mxx - mnx), (H - 8) / (mxy - mny))
    zb = [-1e18] * (W * H); img = bytearray(b"\x20\x20\x30\xff" * (W * H))
    for t, uv, tex in tris:
        P = [((p[0] - mnx) * s + 4, (mxy - p[1]) * s + 4, p[2]) for p in t]
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = P
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        pw, ph, prgba = by_id.get(tex, (1, 1, b"\xff\x00\xff\xff"))
        for y in range(int(max(0, min(ay, by, cy))), int(min(H - 1, max(ay, by, cy))) + 1):
            for x in range(int(max(0, min(ax, bx, cx))), int(min(W - 1, max(ax, bx, cx))) + 1):
                l1 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / den
                l2 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / den
                l3 = 1 - l1 - l2
                if min(l1, l2, l3) < 0:
                    continue
                z = l1 * az + l2 * bz + l3 * cz; q = y * W + x
                if z > zb[q]:
                    if uv:
                        u = (l1 * uv[0][0] + l2 * uv[1][0] + l3 * uv[2][0]) % 1.0
                        v = (1.0 - (l1 * uv[0][1] + l2 * uv[1][1] + l3 * uv[2][1])) % 1.0
                        k = (int(v * ph) * pw + int(u * pw)) * 4
                        col = prgba[k:k + 3]
                    else:
                        col = b"\xc0\xc0\xc0"
                    zb[q] = z; img[q * 4:q * 4 + 4] = bytes(col) + b"\xff"
    png(sys.argv[2], W, H, bytes(img))
    print(len(tris), "triangles")
