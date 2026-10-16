"""Tekken 5 animation poses (Tekken5-Tekken3-Merge, merge/PLAN.md "Bedeutung"): rotation channel
(a, b, theta): FUN_002c7008 builds Rx(a) then turns every row by Ry(b) and takes row 2 as the
axis k = (sin b cos a, -sin a, cos b cos a), quaternion (k sin theta/2, cos theta/2). With our
column-vector matrices the node's local rotation is the rotation by -theta about k (equivalently
theta about -k) and REPLACES the bind rotation (only the bind translation stays). Animation
bone -> skeleton node MAP_A (confirmed in game with t5_anim_probe.py); bone 1 = pelvis position
(y up), bone 0 = root motion. Found by scoring all conventions on Paul's standing animations.

    python t5_pose.py <costume file> <bank file> <anim> <frame> <out.png> [sign]
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_to_t5 import mm, mv, rot_zyx  # noqa: E402

# animation bone -> skeleton node, checked against the game's local node matrices (RAM, Paul
# fighting, 13.10.): bones 2/3 do not reach the pelvis (node 1 stays identity), bone 4 = spine
# (node 2), bone 5 = lower body (node 4); the chest (node 3) has no channel (set by the game
# near its bind rotation).
MAP_A = {4: 2, 5: 4, 7: 5, 8: 6, 9: 7, 10: 8, 11: 9, 12: 10, 13: 11, 14: 12, 15: 13,
         16: 14, 17: 15, 18: 16, 19: 17, 20: 18, 21: 19, 22: 20}
SIGN = -1.0


def axis_angle(a, b, th, sign=None):
    """Rotation matrix of the channel triple (radians)."""
    s = SIGN if sign is None else sign
    k = (math.sin(b) * math.cos(a), -math.sin(a), math.cos(b) * math.cos(a))
    c, si = math.cos(s * th), math.sin(s * th)
    K = [[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]]
    K2 = mm(K, K)
    return [[(1 if i == j else 0) + si * K[i][j] + (1 - c) * K2[i][j] for j in range(3)] for i in range(3)]


def to_axis_angle(R, sign=None):
    """Channel triple (a, b, theta) of a rotation matrix; theta in [0, pi]."""
    s = SIGN if sign is None else sign
    tr = R[0][0] + R[1][1] + R[2][2]
    th = math.acos(max(-1.0, min(1.0, (tr - 1) / 2)))
    if th < 1e-6:
        return 0.0, 0.0, 0.0
    if th > math.pi - 1e-4:
        # axis from the symmetric part
        k = [math.sqrt(max(0.0, (R[i][i] + 1) / 2)) for i in range(3)]
        i = max(range(3), key=lambda j: k[j])
        for j in range(3):
            if j != i:
                k[j] = math.copysign(k[j], R[i][j] + R[j][i])
    else:
        k = [R[2][1] - R[1][2], R[0][2] - R[2][0], R[1][0] - R[0][1]]
    n = math.sqrt(sum(x * x for x in k))
    k = [x / n for x in k]
    if s < 0:
        k = [-x for x in k]
    # k = (sin b cos a, -sin a, cos b cos a)
    a = math.asin(max(-1.0, min(1.0, -k[1])))
    b = math.atan2(k[0], k[2])
    return a, b, th


def posed_world(par, tr, ro, pose):
    """World (R, t) per node for a decoded frame (list of 23 triples)."""
    W = {}
    rots = {n: pose[b] for b, n in MAP_A.items()}

    def get(i):
        if i not in W:
            R = rot_zyx(*ro[i])
            if i in rots:
                R = axis_angle(*rots[i])
            t = list(tr[i])
            if i == 1:
                t = list(pose[1])
            if par[i] < 0:
                W[i] = (R, [0.0, 0.0, 0.0] if i == 0 else t)
            elif i == 1:
                W[i] = (mm(get(0)[0], R), t)
            else:
                pm, pt = get(par[i])
                W[i] = (mm(pm, R), [a + b for a, b in zip(mv(pm, t), pt)])
        return W[i]

    for i in range(len(par)):
        get(i)
    return W


if __name__ == "__main__":
    import struct
    from t5_anim import bank, decode_frame
    from t5_posetest import render, skeleton, world
    d = open(sys.argv[1], "rb").read()
    bd = open(sys.argv[2], "rb").read()
    if len(sys.argv) > 6:
        SIGN = float(sys.argv[6])
    o, s = struct.unpack_from("<II", bd, 4)
    desc, anims = bank(bd[o:o + s])
    pose = decode_frame(anims[int(sys.argv[3])], int(sys.argv[4]), desc)
    par, tr, ro = skeleton(d)
    Wb = world(par, tr, ro, {})
    Wp = posed_world(par, tr, ro, pose)
    render(d, Wb, Wp, sys.argv[5])
