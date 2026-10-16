"""Animation bone probe (Tekken5-Tekken3-Merge, merge/PLAN.md "Zuordnung Anim-Knochen"): a copy of
an animation bank with one rotation bone turned by a quarter turn in the base pose of every
animation (keyframes are relative to it), so a fight shows which body part that bone moves.

    python t5_anim_probe.py <bank file> <bone> <component, -1 = all> <out file>
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t5_anim import is_short, s16  # noqa: E402


def probe(data, bone, comp, delta=0x4000):
    d = bytearray(data)
    n, = struct.unpack_from("<I", d, 0)
    o, s = struct.unpack_from("<II", d, 4)
    cnt, nb = struct.unpack_from("<HH", d, o + 2)
    desc = struct.unpack_from(f"<{nb}H", d, o + 6)
    offs = struct.unpack_from(f"<{cnt}I", d, o + 6 + 2 * nb)
    assert is_short(desc[bone]), f"bone {bone} is a position"
    for a in sorted(set(x for x in offs if x)):
        p = o + a
        frames, sh, fsh, fb = struct.unpack_from("<HBBH", d, p)
        q = p + 2 * ((4 * fb + 6) // 2)
        for j, dsc in enumerate(desc):
            if j == bone:
                for c in (range(3) if comp < 0 else (comp,)):
                    v, = struct.unpack_from("<h", d, q + 2 * c)
                    struct.pack_into("<h", d, q + 2 * c, s16(v + delta))
            q += 6 if is_short(dsc) else 12
    return bytes(d)


if __name__ == "__main__":
    data = Path(sys.argv[1]).read_bytes()
    Path(sys.argv[4]).write_bytes(probe(data, int(sys.argv[2]), int(sys.argv[3])))
