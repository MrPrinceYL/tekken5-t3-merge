"""Experiment: apply a Tekken 5 animation frame to a costume's skeleton and render the skinned
costume mesh (front + side view), to find how the 23 animation bones map onto skeleton nodes.

    python t5_posetest.py <costume file> <bank file> <anim> <frame> <out.png> [variant]
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_to_t5 import mm, mv, rot_zyx  # noqa: E402
from t5_anim import bank, decode_frame  # noqa: E402
from t5_model import container, groups, strip_triangles, vif_batches  # noqa: E402
from tim2png import png, pictures  # noqa: E402

# animation bone -> skeleton node (hypothesis A)
MAP_A = {2: 1, 3: 2, 4: 3, 5: 4, 7: 5, 8: 6,
         9: 7, 10: 8, 11: 9, 12: 10, 13: 11, 14: 12, 15: 13, 16: 14,
         17: 15, 18: 16, 19: 17, 20: 18, 21: 19, 22: 20}


def skeleton(d):
    o, s = container(d)[3]
    b = d[o:o + s]
    _, cnt, _, o1, o2, o3, _ = struct.unpack_from("<HHfIIII", b, 0)
    par = [struct.unpack_from("<i", b, o1 + 4 * i)[0] for i in range(cnt)]
    tr = [list(struct.unpack_from("<3f", b, o2 + 12 * i)) for i in range(cnt)]
    ro = [list(struct.unpack_from("<3f", b, o3 + 12 * i)) for i in range(cnt)]
    return par, tr, ro


def world(par, tr, ro, override):
    W = {}

    def get(i):
        if i not in W:
            R = override.get(i, rot_zyx(*ro[i]))
            if par[i] < 0:
                W[i] = (R, tr[i])
            else:
                pm, pt = get(par[i])
                W[i] = (mm(pm, R), [a + b for a, b in zip(mv(pm, tr[i]), pt)])
        return W[i]

    for i in range(len(par)):
        get(i)
    return W


def inv(R, t):
    Rt = [list(r) for r in zip(*R)]
    return Rt, [-x for x in mv(Rt, t)]


def render(d, Wb, Wp, out, W=320, H=480):
    E = container(d)
    pics = [p for p in pictures(d, E[1][0]) if (p[0], p[1]) != (8, 2)]
    skin = {n: (mm(Wp[n][0], inv(*Wb[n])[0]), None) for n in Wp}
    M = {}
    for n in Wp:
        iR, it = inv(*Wb[n])
        R = mm(Wp[n][0], iR)
        t = [a + b for a, b in zip(mv(Wp[n][0], it), Wp[n][1])]
        M[n] = (R, t)
    tris = []
    o, s = E[2]
    b = d[o:o + s]
    for g in groups(b):
        for bt in g["batches"]:
            pal = bt["palette"]
            for v in vif_batches(b, bt["offset"], bt["offset"] + bt["qwc"] * 16):
                if 1 not in v.get("v3", {}):
                    continue
                P = []
                for k, p in enumerate(v["v3"][1]):
                    acc = [0.0, 0.0, 0.0]
                    for jj, ww in zip(v["j"][k], v["w"][k]):
                        if ww == 0:
                            continue
                        R, t = M[pal[jj // 7]]
                        q = [a + c for a, c in zip(mv(R, p), t)]
                        acc = [x + ww * y for x, y in zip(acc, q)]
                    P.append(acc)
                for t in strip_triangles(v):
                    tris.append([P[i] for i in t])
    img = bytearray(b"\x20\x20\x30\xff" * (2 * W * H))
    for view in (0, 1):
        pts = [[(p[0], p[1], p[2]) if view == 0 else (p[2], p[1], -p[0]) for p in t] for t in tris]
        xs = [p[0] for t in pts for p in t]; ys = [p[1] for t in pts for p in t]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        s_ = min((W - 8) / (max(xs) - min(xs) + 1), (H - 8) / (max(ys) - min(ys) + 1))
        zb = [-1e18] * (W * H)
        for t in pts:
            u = [b - a for a, b in zip(t[0], t[1])]; w = [b - a for a, b in zip(t[0], t[2])]
            n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
            ln = math.sqrt(sum(x * x for x in n)) or 1
            sh = int(60 + 180 * abs(n[2]) / ln)
            P = [((p[0] - cx) * s_ + W / 2, (cy - p[1]) * s_ + H / 2, p[2]) for p in t]
            (ax, ay, az), (bx, by, bz), (qx, qy, qz) = P
            den = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy)
            if abs(den) < 1e-9:
                continue
            for y in range(int(max(0, min(ay, by, qy))), int(min(H - 1, max(ay, by, qy))) + 1):
                for x in range(int(max(0, min(ax, bx, qx))), int(min(W - 1, max(ax, bx, qx))) + 1):
                    l1 = ((by - qy) * (x - qx) + (qx - bx) * (y - qy)) / den
                    l2 = ((qy - ay) * (x - qx) + (ax - qx) * (y - qy)) / den
                    l3 = 1 - l1 - l2
                    if min(l1, l2, l3) < 0:
                        continue
                    z = l1 * az + l2 * bz + l3 * qz
                    if z > zb[y * W + x]:
                        zb[y * W + x] = z
                        k = (y * 2 * W + x + view * W) * 4
                        img[k:k + 4] = bytes((sh, sh, sh, 255))
    png(out, 2 * W, H, bytes(img))


def pose_override(anim_pose, mapping, order="zyx"):
    ov = {}
    for ab, node in mapping.items():
        x, y, z = anim_pose[ab]
        ov[node] = rot_zyx(x, y, z) if order == "zyx" else xyz(x, y, z)
    return ov


def xyz(x, y, z):
    """Rx * Ry * Rz."""
    Rz = rot_zyx(0, 0, z); Ry = rot_zyx(0, y, 0); Rx = rot_zyx(x, 0, 0)
    return mm(mm(Rx, Ry), Rz)


if __name__ == "__main__":
    d = open(sys.argv[1], "rb").read()
    bd = open(sys.argv[2], "rb").read()
    o, s = struct.unpack_from("<II", bd, 4)
    desc, anims = bank(bd[o:o + s])
    pose = decode_frame(anims[int(sys.argv[3])], int(sys.argv[4]), desc)
    order = sys.argv[6] if len(sys.argv) > 6 else "zyx"
    par, tr, ro = skeleton(d)
    Wb = world(par, tr, ro, {})
    Wp = world(par, tr, ro, pose_override(pose, MAP_A, order))
    render(d, Wb, Wp, sys.argv[5])
