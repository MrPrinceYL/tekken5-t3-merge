"""Tekken 3 animations retargeted to Tekken 5 animation banks (Tekken5-Tekken3-Merge).

A T3 frame (t3_anim.decode -> t3_pose.world) gives every body part's world rotation R3 in T3
space; the costume mesh was built so that a T5 node carries its T3 part's local frame
(t3_to_t5.convert_mesh), so the node's wanted world rotation is A * R3 with A = T3 -> T5 axes
(y and z flipped, measured on standing poses). T5 local rotation = parent world^T * wanted
(t5_pose: the animation rotation replaces the bind rotation). Nodes without a T3 part keep their
bind rotation relative to the T3 part above them: the spine (node 2) carries the T3 root
rotation... except that the game has no pelvis and no chest channel (t5_pose.MAP_A, measured
in RAM): the pelvis stays identity and the spine (whose child, the chest, keeps its bind
rotation) takes the T3 chest rotation. Elbows and knees
(descriptor 6) are hinges about local z. Bone 1 = pelvis position = A * T3 root, bone 0 (root
motion) = horizontal root displacement since frame 0, bone 6 = (-400, 0, 0) like the game's.

    python t3_anim_to_t5.py <t3 model> <t3 move> <out.png>     # preview: T3 frames vs T5 decode
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_anim import decode, pack  # noqa: E402
from t3_model import f  # noqa: E402
from t3_pose import PART_RECORD, PART_SLOT, world as t3_world  # noqa: E402
from t3_to_t5 import SLOT_NODE, mm, mv, rot_zyx, t5_skeleton_raw  # noqa: E402
from t5_anim import DESC_T5, decode_frame, encode, is_short  # noqa: E402
import t5_pose as tp  # noqa: E402

A = [[1, 0, 0], [0, -1, 0], [0, 0, -1]]
NODE_BONE = {n: b for b, n in tp.MAP_A.items()}
MULT = math.pi / 32769
FLOAT_FACTOR = 0.25


def T(m):
    return [list(r) for r in zip(*m)]


def node_parts():
    """T5 node -> T3 part (the body parts of the skeleton)."""
    out = {}
    for p in range(18):
        sl = PART_SLOT[p]
        if sl in SLOT_NODE:
            out[SLOT_NODE[sl]] = p
    return out


NODE_PART = node_parts()


def frame_channels(model, skel, pose):
    """23 channel triples (radians / units) for one T3 pose vector."""
    par, tr, ro = skel
    W3 = t3_world(model, pose)
    want = {n: mm(A, W3[PART_RECORD[p]][0]) for n, p in NODE_PART.items() if PART_RECORD[p] in W3}
    root = mm(A, W3[PART_RECORD[0]][0])
    world = {0: [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}
    ch = [[0.0, 0.0, 0.0] for _ in range(23)]
    ch[6] = [-400.0, 0.0, 0.0]
    ch[1] = mv(A, pose[0:3])
    for n in range(1, 21):
        pw = world[par[n]]
        if n in (1, 3):                                    # no channel: pelvis identity,
            world[n] = mm(pw, rot_zyx(*ro[n]))             # chest at its bind rotation
            continue
        if n == 2:
            Q = mm(T(pw), want[3])                         # the spine carries the T3 chest
        elif n in want:
            Q = mm(T(pw), want[n])
        else:
            Q = rot_zyx(*ro[n])                            # bind rotation (neck)
        b = NODE_BONE[n]
        if DESC_T5[b] == 6:                                # hinge about local z
            th = math.atan2(Q[1][0], Q[0][0])
            ch[b] = [0.0, 0.0, -th]
            Q = tp.axis_angle(0.0, 0.0, -th)
        else:
            ch[b] = list(tp.to_axis_angle(Q))
        world[n] = mm(pw, Q)
    return ch


def continuous(frames):
    """Keep (a, b, theta) continuous over frames: undefined axes (theta ~ 0) copy the previous
    one, and b is unwrapped."""
    for b in range(23):
        if not is_short(DESC_T5[b]) or DESC_T5[b] == 6:
            continue
        prev = None
        for fr in frames:
            a, bb, th = fr[b]
            if prev is not None:
                if th < 1e-3:
                    a, bb = prev[0], prev[1]
                while bb - prev[1] > math.pi:
                    bb -= 2 * math.pi
                while bb - prev[1] < -math.pi:
                    bb += 2 * math.pi
            fr[b] = [a, bb, th]
            prev = fr[b]
    return frames


def anim_source(m, move):
    """(data, offset) of the animation of T3 model m's move `move`: the own pack, or the common
    pack (TOC 279, same layout: animations at +0x1C) for values >= 0x40000000."""
    d, nm, mvo, an = pack(m)
    o, = struct.unpack_from("<I", d, mvo + 56 * move)
    if o >= 0x40000000:
        d = f(279)
        an, = struct.unpack_from("<I", d, 0x1C)
        o -= 0x40000000
    return d, an + o


def convert(m, move, skel):
    """T5 animation bytes (format 0x64) of T3 model m's move `move`; None for animations from the
    common pack (TOC 279 decoded for Gon's stand gave a torn-apart body in the game: unclear
    whether all characters' common values refer to that pack - not converted)."""
    if struct.unpack_from("<I", pack(m)[0], pack(m)[2] + 56 * move)[0] >= 0x40000000:
        return None
    d, a = anim_source(m, move)
    an, o = a, 0
    model = f(0x5F + 4 * m)
    _, k = decode(d, an + o, 0)
    frames = continuous([frame_channels(model, skel, decode(d, an + o, i)[0]) for i in range(k)])
    # root motion like the game's animations (measured on Paul's): bone 0 = horizontal (x, z)
    # displacement since frame 0, bone 1 = pelvis (height + its frame-0 horizontal offset)
    x0, z0 = frames[0][1][0], frames[0][1][2]
    for fr in frames:
        dx, dz = fr[1][0] - x0, fr[1][2] - z0
        fr[0] = [dx, 0.0, dz]
        fr[1] = [x0, fr[1][1], z0]
    floats = [j for j, x in enumerate(DESC_T5) if not is_short(x)]
    base_float = [frames[0][j] for j in floats]
    vals = []
    for fr in frames:
        row = []
        fi = 0
        for j, x in enumerate(DESC_T5):
            if is_short(x):
                row.append([max(-32767, min(32767, round(v / MULT))) for v in fr[j]])
            else:
                row.append([round((v - bf) / FLOAT_FACTOR) for v, bf in zip(fr[j], base_float[fi])])
                fi += 1
        vals.append(row)
    return encode(vals, DESC_T5, sh=0, fsh=0, factors=[FLOAT_FACTOR] * len(floats), base_float=base_float)


def pelvis_height(ms, move, skel, frame):
    """T5 pelvis height (bone 1 y) of T3 move `move` at `frame` (ms: t3_moves.Moveset)."""
    d, a = anim_source(ms.m, move)
    pose, k = decode(d, a, min(frame, max(0, decode(d, a, 0)[1] - 1)))
    return mv(A, pose[0:3])[1]


def skeleton_of(costume):
    _, _, par, tr, ro = t5_skeleton_raw(costume)
    return par, tr, ro


if __name__ == "__main__":
    m, move, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    from t3_to_t5 import fit_skeleton
    from t5_posetest import render, world
    t5 = open(Path(__file__).resolve().parent.parent / "merge/extracted/tk5data1/0240.bin", "rb").read()
    blk, _ = fit_skeleton(t5, m)
    costume = Path(__file__).resolve().parent.parent / {22: "merge/data/ogre/model.bin"}.get(m, "merge/data/ogre/model.bin")
    cd = open(costume, "rb").read()
    skel = skeleton_of(cd)
    anim = convert(m, move, skel)
    par, tr, ro = skel
    Wb = world(par, tr, ro, {})
    p = decode_frame(anim, 10)
    Wp = tp.posed_world(par, tr, ro, p)
    render(cd, Wb, Wp, out)
    print(len(anim), "bytes")
