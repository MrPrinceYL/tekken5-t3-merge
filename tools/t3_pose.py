"""Tekken 3 (PS1) pose evaluation in floating point (merge/PLAN.md): pose vector -> 18 slot
rotations (FUN_8003ad10: euler bones, two-bone IK for the limbs) -> world matrices of the model
parts (FUN_80035908 / FUN_8003afcc: part p draws 3DMK record PART_RECORD[p] with slot
PART_SLOT[p]; its parent is the part in the record's w12 (-1 = the player's base matrix), its
offset is (w9, w10, -w11); world = parent * (slot rotation, offset)).

    python t3_pose.py [model] [move] [frame]     # renders merge/png/t3_pose.png
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_anim import decode, pack  # noqa: E402
from t3_model import f, parts, prims, skin, texel, uvs, vblock, vram  # noqa: E402

PART_RECORD = [0, 1, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
               21, 22, 23, 24, 25, 26]                                             # 0x8001A05C
PART_SLOT = [0, 1, 11, 12, 13, 14, 15, 16, 17, 3, 4, 5, 6, 7, 8, 9, 10, 2,
             18, 19, 20, 21, 22, 23]                                               # 0x8001A074
# 0x8001A044: parts that also draw the next record on the same bone, right after the main one.
PART_SECOND = [0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
# Parts 18..23 are secondary parts (e.g. True Ogre's snake hand and tail); their rotations come
# from FUN_80037cbc's secondary motion, here the rest pose (identity).
EULER_SLOTS = [0, 1, 11, 2, 3, 7, 6, 10, 14, 17]
RY90 = [[0, 0, -1], [0, 1, 0], [1, 0, 0]]          # 0x80096EAC, applied to slots 2, 3, 7
# limb: (target channels, hint channel, base: 'chest' or 'hips', joint offset, upper slot, arm)
LIMBS = [(3, 15, "A", (-140, 0, 0), 4, True), (6, 16, "B", (-140, 0, 0), 8, True),
         (9, 17, "C", (-160, 0, 100), 12, False), (12, 18, "C", (-160, 0, -100), 15, False)]
LEN = {True: (302.0, 232.0), False: (449.0, 446.0)}   # from FUN_8003bca8's constants


def mmul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mvec(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def T(a):
    return [list(r) for r in zip(*a)]


def euler(x, y, z):
    """FUN_8003a338: Rz * Ry * Rx, angles in 65536 units."""
    k = 2 * math.pi / 65536
    cx, sx, cy, sy, cz, sz = math.cos(x * k), math.sin(x * k), math.cos(y * k), math.sin(y * k), math.cos(z * k), math.sin(z * k)
    return [[cy * cz, sy * sx * cz - cx * sz, sx * sz + sy * cx * cz],
            [cy * sz, cx * cz + sy * sx * sz, cx * sz * sy - sx * cz],
            [-sy, sx * cy, cy * cx]]


def compose(pm, pt, lm, lt):
    """FUN_8003b5b8 / FUN_8003b5c0: (R, t) = (Rp Rl, Rp tl + tp)."""
    return mmul(pm, lm), [a + b for a, b in zip(mvec(pm, lt), pt)]


def ik(v, hint, arm):
    """FUN_8003bca8: rotations of the upper and lower limb reaching local target v."""
    d = math.sqrt(sum(c * c for c in v))
    if d == 0:
        return None
    nx, ny, nz = (c / d for c in v)
    if 1 + nx < 1e-6:
        k = -0.5
        u, w = (0.0, -1.0, 0.0), (0.0, 0.0, -1.0)
    else:
        k = -1 / (1 + nx)
        u = (-ny, 1 + k * ny * ny, k * ny * nz)
        w = (-nz, k * ny * nz, 1 + k * nz * nz)
    h = hint * 2 * math.pi / 65536
    c, s = math.cos(h), math.sin(h)
    col1 = [c * a + s * b for a, b in zip(u, w)]
    col2 = [-s * a + c * b for a, b in zip(u, w)]
    m = [[nx, col1[0], col2[0]], [ny, col1[1], col2[1]], [nz, col1[2], col2[2]]]
    l1, l2 = LEN[arm]
    if d >= l1 + l2:
        return m, [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    ca = max(-1.0, min(1.0, (d * d + l1 * l1 - l2 * l2) / (2 * d * l1)))
    sa = math.sqrt(1 - ca * ca) * (1 if arm else -1)
    cb = max(-1.0, min(1.0, (d * d + l2 * l2 - l1 * l1) / (2 * d * l2)))
    sb = -sa * l1 / l2
    m = [[r[0] * ca + r[1] * sa, -r[0] * sa + r[1] * ca, r[2]] for r in m]
    ce, se = ca * cb + sa * sb, -sa * cb + ca * sb
    return m, [[ce, -se, 0], [se, ce, 0], [0, 0, 1]]


def slots(pose, recs):
    """18 slot rotations for a pose vector (FUN_8003ad10)."""
    rot = [[[1, 0, 0], [0, 1, 0], [0, 0, 1]] for _ in range(18)]
    for i, sl in enumerate(EULER_SLOTS):
        rot[sl] = euler(*pose[19 + 3 * i: 22 + 3 * i])
    for sl in (2, 3, 7):
        rot[sl] = mmul(rot[sl], RY90)
    m0, t0 = rot[0], list(pose[0:3])
    m1, t1 = compose(m0, t0, rot[1], [0, 0, 0])
    base = {"A": compose(m1, t1, rot[3], [350, 0, -100]), "B": compose(m1, t1, rot[7], [350, 0, 100]),
            "C": compose(m0, t0, rot[11], [0, 0, 0])}
    for ch, hint, b, off, sl, arm in LIMBS:
        bm, bt = base[b]
        local = mvec(T(bm), [p - q for p, q in zip(pose[ch:ch + 3], bt)])
        local = [a + o for a, o in zip(local, off)]
        r = ik(local, pose[hint], arm)
        if r:
            rot[sl], rot[sl + 1] = r
    return rot


def world(d, pose):
    """World (R, t) per 3DMK record of the skeleton parts (secondary parts in rest pose); the base
    matrix is the pose root."""
    recs = parts(d)
    rot = slots(pose, recs)
    out = {}

    def get(p):
        if p in out:
            return out[p]
        w = recs[PART_RECORD[p]]
        lr = rot[PART_SLOT[p]] if PART_SLOT[p] < 18 else [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        off = [w[9], w[10], -w[11]]
        par = w[12]
        pm, pt = ([[1, 0, 0], [0, 1, 0], [0, 0, 1]], list(pose[0:3])) if par < 0 else get(par)
        out[p] = compose(pm, pt, lr, off)
        return out[p]

    res = {}
    for p in range(len(PART_RECORD)):
        r = PART_RECORD[p]
        if r < len(recs):
            res[r] = get(p)
            if PART_SECOND[p] and r + 1 < len(recs) and recs[r + 1][4]:
                res[r + 1] = get(p)
    return res


def draw_order(recs):
    """Records in drawing order (FUN_80037924): each part's record, then its second record."""
    out = []
    for p, r in enumerate(PART_RECORD):
        if r < len(recs):
            out.append(r)
            if PART_SECOND[p] and r + 1 < len(recs) and recs[r + 1][4]:
                out.append(r + 1)
    return out


if __name__ == "__main__":
    from tim2png import png
    m = int(sys.argv[1]) if len(sys.argv) > 1 else 22
    mv_i = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    fr = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    only = {int(x) for x in sys.argv[4].split(",")} if len(sys.argv) > 4 else None   # records to draw
    d = f(0x5F + 4 * m)
    pk, nm, mv, an = pack(m)
    o = struct.unpack_from("<I", pk, mv + 56 * mv_i)[0]
    while o >= 0x40000000:                # common pack (not loaded): take the next own animation
        mv_i += 1
        o = struct.unpack_from("<I", pk, mv + 56 * mv_i)[0]
    pose, k = decode(pk, an + o, fr)
    W = world(d, pose)
    sk = skin(d, draw_order(parts(d)))
    recs = parts(d)
    local = {r: vblock(d, recs[r][4])[1] for r in sk}
    tris = []
    for r, ws in sk.items():
        if only and r not in only:
            continue

        def P(slot):
            if slot >= len(ws) or not ws[slot]:
                return None
            acc = [0.0, 0.0, 0.0]
            for (rr, j), wt in ws[slot].items():
                R, t = W[rr]
                v = [a + b for a, b in zip(mvec(R, local[rr][j]), t)]
                acc = [x + wt * y for x, y in zip(acc, v)]
            return acc
        for (kind, L), (_, UL) in zip(prims(d, recs[r][7]), uvs(d, recs[r][8])):
            for (v, _), (a, uv) in zip(L, UL):
                sets = [(0, 1, 2), (1, 2, 3)] if len(v) == 4 else [(0, 1, 2)]
                for ids in sets:
                    pts = [P(v[i]) for i in ids]
                    if all(pts):
                        tris.append((pts, a, [uv[i] for i in ids]))
    # front view (x right, y down), z buffer
    Wd, Hd = 320, 480
    V = vram(m)
    xs = [p[0] for t, _, _ in tris for p in t]; ys = [p[1] for t, _, _ in tris for p in t]
    mnx, mxx, mny, mxy = min(xs), max(xs), min(ys), max(ys)
    s = min((Wd - 8) / (mxx - mnx + 1), (Hd - 8) / (mxy - mny + 1))
    zb = [1e18] * (Wd * Hd); img = bytearray(b"\x20\x20\x30\xff" * (Wd * Hd))
    for tri, ta, tuv in tris:
        a, b, c = tri
        n = [(b[1]-a[1])*(c[2]-a[2])-(b[2]-a[2])*(c[1]-a[1]), (b[2]-a[2])*(c[0]-a[0])-(b[0]-a[0])*(c[2]-a[2]), (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])]
        ln = math.sqrt(sum(x * x for x in n)) or 1
        sh = int(60 + 180 * abs(n[2]) / ln)
        P = [((p[0]-mnx)*s+4, (p[1]-mny)*s+4, p[2]) for p in tri]
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = P
        den = (by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
        if abs(den) < 1e-9:
            continue
        for y in range(int(max(0, min(ay, by, cy))), int(min(Hd-1, max(ay, by, cy)))+1):
            for x in range(int(max(0, min(ax, bx, cx))), int(min(Wd-1, max(ax, bx, cx)))+1):
                l1 = ((by-cy)*(x-cx)+(cx-bx)*(y-cy))/den; l2 = ((cy-ay)*(x-cx)+(ax-cx)*(y-cy))/den; l3 = 1-l1-l2
                if min(l1, l2, l3) < 0:
                    continue
                z = l1*az+l2*bz+l3*cz; q = y*Wd+x
                if z < zb[q]:
                    u = int(l1*tuv[0][0]+l2*tuv[1][0]+l3*tuv[2][0]); v = int(l1*tuv[0][1]+l2*tuv[1][1]+l3*tuv[2][1])
                    col = texel(V, ta, max(0, min(255, u)), max(0, min(255, v)))
                    if col[3] == 0:
                        continue
                    zb[q] = z; img[q*4:q*4+4] = bytes((col[0], col[1], col[2], 255))
    png(str(Path(__file__).resolve().parent.parent / "merge" / "png" / "t3_pose.png"), Wd, Hd, bytes(img))
    print("frames", k, "triangles", len(tris))
