"""Tekken 3 character model -> Tekken 5 costume model (Tekken5-Tekken3-Merge, merge/PLAN.md).

First stage: the T3 mesh (3DMK, seams as weights, textures) is placed on a Tekken 5 skeleton in
its bind pose (T-pose): every T3 part is attached to a T5 node (PART_NODE), its vertices keep
their part-local coordinates, seam vertices keep their 0.5 / 0.5 weights.

    python t3_to_t5.py preview <t3 model m> <t5 costume file> <out.png>
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_model import f, parts, prims, skin, texel, uvs, vblock, vram  # noqa: E402
from t3_pose import PART_RECORD, PART_SLOT, draw_order  # noqa: E402
from t5_model import container  # noqa: E402

# T3 skeleton slot -> T5 node (merge/PLAN.md: T5 0 root, 1 pelvis, 2-3 spine, 4 lower body,
# 5 neck, 6 head, 7-10 / 11-14 arms, 15-17 / 18-20 legs)
SLOT_NODE = {0: 1, 1: 3, 2: 6, 11: 4,
             3: 7, 4: 8, 5: 9, 6: 10, 7: 11, 8: 12, 9: 13, 10: 14,
             12: 15, 13: 16, 14: 17, 15: 18, 16: 19, 17: 20}


def mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mv(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def rot_zyx(x, y, z):
    """R = Rz * Ry * Rx (radians) - the T5 skeleton's convention (checked against the mesh)."""
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    return [[cy * cz, sy * sx * cz - cx * sz, sx * sz + sy * cx * cz],
            [cy * sz, cx * cz + sy * sx * sz, cx * sz * sy - sx * cz],
            [-sy, sx * cy, cy * cx]]


def t5_skeleton(d):
    """Bind world matrices {node: (R, t)} of the costume's skeleton (container block 3)."""
    o, s = container(d)[3]
    b = d[o:o + s]
    _, cnt, _, o1, o2, o3, _ = struct.unpack_from("<HHfIIII", b, 0)
    par = [struct.unpack_from("<i", b, o1 + 4 * i)[0] for i in range(cnt)]
    tr = [struct.unpack_from("<3f", b, o2 + 12 * i) for i in range(cnt)]
    ro = [struct.unpack_from("<3f", b, o3 + 12 * i) for i in range(cnt)]
    W = {}

    def get(i):
        if i not in W:
            r = rot_zyx(*ro[i])
            if par[i] < 0:
                W[i] = (r, list(tr[i]))
            else:
                pm, pt = get(par[i])
                W[i] = (mm(pm, r), [a + b_ for a, b_ in zip(mv(pm, tr[i]), pt)])
        return W[i]

    for i in range(cnt):
        get(i)
    return W, par


def t5_skeleton_raw(d):
    """(block bytes, header, parents, translations, rotations) of the costume's skeleton."""
    o, s = container(d)[3]
    b = d[o:o + s]
    head = struct.unpack_from("<HHfIIII", b, 0)
    _, cnt, _, o1, o2, o3, _ = head
    par = [struct.unpack_from("<i", b, o1 + 4 * i)[0] for i in range(cnt)]
    tr = [list(struct.unpack_from("<3f", b, o2 + 12 * i)) for i in range(cnt)]
    ro = [list(struct.unpack_from("<3f", b, o3 + 12 * i)) for i in range(cnt)]
    return b, head, par, tr, ro


def fit_skeleton(d, m):
    """The costume's skeleton with T3 model m's proportions: every mapped node sits at the T3
    joint (offset (w9, w10, -w11) from the parent part's joint, in the parent node's frame);
    nodes between two mapped nodes (spine, neck) are scaled along. Returns the new skeleton
    block and its bind world matrices."""
    b, head, par, tr, ro = t5_skeleton_raw(d)
    t3 = parts(f(0x5F + 4 * m))
    tr = [list(t) for t in tr]
    for p in range(1, 18):
        rec = t3[PART_RECORD[p]]
        n = SLOT_NODE[PART_SLOT[p]]
        q = rec[12]
        if not 0 <= q < 18:
            continue
        mnode = SLOT_NODE[PART_SLOT[q]]
        chain = []
        k = n
        while k != mnode and k >= 0:
            chain.append(k)
            k = par[k]
        if k != mnode:
            continue
        chain.reverse()
        want = [rec[9], rec[10], -rec[11]]
        R = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        pts, Rs = [0.0, 0.0, 0.0], []
        for c in chain:
            Rs.append(R)
            pts = [a + b_ for a, b_ in zip(pts, mv(R, tr[c]))]
            R = mm(R, rot_zyx(*ro[c]))
        ln_old = math.sqrt(sum(x * x for x in pts))
        ln_new = math.sqrt(sum(x * x for x in want))
        sc = ln_new / ln_old if ln_old > 1e-6 else 1.0
        for c in chain[:-1]:
            tr[c] = [x * sc for x in tr[c]]
        partial = [0.0, 0.0, 0.0]
        for c, Rc in zip(chain[:-1], Rs[:-1]):
            partial = [a + b_ for a, b_ in zip(partial, mv(Rc, tr[c]))]
        Rl = Rs[-1]
        tr[chain[-1]] = mv([list(r) for r in zip(*Rl)], [a - b_ for a, b_ in zip(want, partial)])
    out = bytearray(b)
    o2 = head[4]
    for i, t in enumerate(tr):
        struct.pack_into("<3f", out, o2 + 12 * i, *t)
    W = {}

    def get(i):
        if i not in W:
            r = rot_zyx(*ro[i])
            if par[i] < 0:
                W[i] = (r, list(tr[i]))
            else:
                pm, pt = get(par[i])
                W[i] = (mm(pm, r), [a + b_ for a, b_ in zip(mv(pm, tr[i]), pt)])
        return W[i]

    for i in range(len(par)):
        get(i)
    return bytes(out), W


def record_nodes(recs):
    """T5 node of every drawn 3DMK record (second records share their part's node; secondary
    parts are attached rigidly to the node of their parent part for now)."""
    node = {}
    for p, r in enumerate(PART_RECORD):
        if r >= len(recs):
            continue
        sl = PART_SLOT[p]
        if sl in SLOT_NODE:
            n = SLOT_NODE[sl]
        else:
            par = recs[r][12]
            n = node.get(PART_RECORD[par], 3) if 0 <= par < len(PART_RECORD) else 3
        node[r] = n
        if r + 1 < len(recs) and r + 1 not in node and recs[r + 1][4] and p in (1, 2, 17):
            node[r + 1] = n
    return node


HANDS = (10, 14)
# Rest direction (T5 world, y up, front +z) of secondary chains not attached to a hand: hair and
# tails hang back and down (T3 swings them with secondary motion, FUN_80037cbc).
HANG = (0.0, -0.7, -0.7)


def rot_x_to(d):
    """Rotation taking +X to the unit vector d (smallest angle)."""
    x = (1.0, 0.0, 0.0)
    c = d[0]
    ax = (0.0, -d[2], d[1])                       # x cross d
    s_ = math.sqrt(ax[1] ** 2 + ax[2] ** 2)
    if s_ < 1e-9:
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]] if c > 0 else [[-1, 0, 0], [0, -1, 0], [0, 0, 1]]
    k = (0.0, ax[1] / s_, ax[2] / s_)
    K = [[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]]
    K2 = mm(K, K)
    return [[(1 if i == j else 0) + s_ * K[i][j] + (1 - c) * K2[i][j] for j in range(3)] for i in range(3)]


def record_frames(recs, node, W5):
    """Transform of every drawn record relative to its T5 node: identity for skeleton parts;
    secondary parts (parts 18..) carry their offset from the parent part, and the first part of
    each chain a rest rotation (along the hand for hand attachments, else hanging back/down)."""
    ident = ([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0.0, 0.0, 0.0])
    fr = {}
    for p, r in enumerate(PART_RECORD):
        if r >= len(recs) or r not in node:
            continue
        if p < 18:
            fr[r] = ident
            if r + 1 in node:
                fr[r + 1] = ident
            continue
        w = recs[r]
        par_rec = PART_RECORD[w[12]] if 0 <= w[12] < len(PART_RECORD) else None
        pR, pt = fr.get(par_rec, ident)
        off = [w[9], w[10], -w[11]]
        t = [a + b for a, b in zip(mv(pR, off), pt)]
        if w[12] < 18:                                 # chain start
            if node[r] in HANDS:
                R = pR
            else:
                world = mm(W5[node[r]][0], pR)
                d = mv([list(c) for c in zip(*world)], HANG)  # target in the parent frame
                ln = math.sqrt(sum(x * x for x in d))
                R = mm(pR, rot_x_to([x / ln for x in d]))
        else:
            R = pR
        fr[r] = (R, t)
    return fr


def convert_mesh(m, W5, scale=1.0):
    """Triangles of T3 model m in the T5 bind pose: list of
    (corners[(pos, {node: weight})], (uv entry a, [(u, v)]), double_sided)."""
    d = f(0x5F + 4 * m)
    recs = parts(d)
    order = draw_order(recs)
    sk = skin(d, order)
    local = {r: vblock(d, recs[r][4])[1] for r in sk}
    node = record_nodes(recs)
    frames = record_frames(recs, node, W5)
    tris = []
    for r, ws in sk.items():
        def corner(slot):
            if slot >= len(ws) or not ws[slot]:
                return None
            pos = [0.0, 0.0, 0.0]
            wts = {}
            for (rr, j), wt in ws[slot].items():
                R, t = W5[node[rr]]
                fR, ft = frames.get(rr, ([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0.0, 0.0, 0.0]))
                v = [a + b for a, b in zip(mv(fR, [c * scale for c in local[rr][j]]), ft)]
                p = [a + b for a, b in zip(mv(R, v), t)]
                pos = [x + wt * y for x, y in zip(pos, p)]
                wts[node[rr]] = wts.get(node[rr], 0) + wt
            return pos, wts

        for (kind, L), (_, UL) in zip(prims(d, recs[r][7]), uvs(d, recs[r][8])):
            for (v, ws_), (a, uv) in zip(L, UL):
                flags = ws_[1] if kind in ("ft4", "gt4") else ws_[0]
                double = bool(flags & 0x1000000)
                sets = [(0, 1, 2), (1, 2, 3)] if len(v) == 4 else [(0, 1, 2)]
                for ids in sets:
                    cs = [corner(v[i]) for i in ids]
                    if all(cs):
                        tris.append((cs, (a, [uv[i] for i in ids]), double))
    return tris


def preview(tris, V, out, W=360, H=480):
    from tim2png import png
    xs = [c[0][0] for t, _, _ in tris for c in t]
    ys = [c[0][1] for t, _, _ in tris for c in t]
    mnx, mxx, mny, mxy = min(xs), max(xs), min(ys), max(ys)
    s = min((W - 8) / (mxx - mnx), (H - 8) / (mxy - mny))
    zb = [-1e18] * (W * H)
    img = bytearray(b"\x20\x20\x30\xff" * (W * H))
    for t, (a, uv), _ in tris:
        P = [((c[0][0] - mnx) * s + 4, (mxy - c[0][1]) * s + 4, c[0][2]) for c in t]
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = P
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        for y in range(int(max(0, min(ay, by, cy))), int(min(H - 1, max(ay, by, cy))) + 1):
            for x in range(int(max(0, min(ax, bx, cx))), int(min(W - 1, max(ax, bx, cx))) + 1):
                l1 = ((by - cy) * (x - cx) + (cx - bx) * (y - cy)) / den
                l2 = ((cy - ay) * (x - cx) + (ax - cx) * (y - cy)) / den
                l3 = 1 - l1 - l2
                if min(l1, l2, l3) < 0:
                    continue
                z = l1 * az + l2 * bz + l3 * cz
                q = y * W + x
                if z > zb[q]:
                    u = int(l1 * uv[0][0] + l2 * uv[1][0] + l3 * uv[2][0])
                    v = int(l1 * uv[0][1] + l2 * uv[1][1] + l3 * uv[2][1])
                    col = texel(V, a, max(0, min(255, u)), max(0, min(255, v)))
                    if col[3] == 0:
                        continue
                    zb[q] = z
                    img[q * 4:q * 4 + 4] = bytes(col[:3]) + b"\xff"
    png(out, W, H, bytes(img))


if __name__ == "__main__":
    if sys.argv[1] == "preview":
        m = int(sys.argv[2])
        d5 = open(sys.argv[3], "rb").read()
        W5 = fit_skeleton(d5, m)[1] if "--fit" in sys.argv else t5_skeleton(d5)[0]
        tris = convert_mesh(m, W5)
        preview(tris, vram(m), sys.argv[4])
        print(len(tris), "triangles")
