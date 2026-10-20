"""Tekken 3 movesets (Tekken5-Tekken3-Merge, merge/PLAN.md "Movesets"): a character pack (TOC
0x62 + 4m) and the common pack (TOC 279) as the engine sees them after FUN_8002ce14.

Pack: u16 +2 move count, u32 +4 cancels (12 B), +8 moves (56 B), +0xC move pointer table (4023
u32: < 0x40000000 own move, else common move), +0x1C animations. Cancel: u16 command, u8
condition, u8 requirement, u16 -, u16 target (pointer table index), u8 option, u8 frame from,
u8 frame to, u8 start frame. Command < 0xC000: bits 0-3 buttons, bit 4 flag, bits 5-13
directions; 0xC000 = end, 0xC00C = call a group (common cancel list 0x80017C78 + s[3] * 12) that
returns with 0xC00D (FUN_8002de24).

    python t3_moves.py <model> [move]      # print a move's cancel list (default: move 0)
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_anim import _ram  # noqa: E402
from t3_model import f  # noqa: E402

COMMON_TOC = 279
GROUPS = 0x80017C78
DIRS = {0x20: "d/b", 0x40: "d", 0x80: "d/f", 0x100: "b", 0x200: "n", 0x400: "f", 0x800: "u/b",
        0x1000: "u", 0x2000: "u/f"}


class Pack:
    def __init__(self, data):
        self.d = data
        self.count, = struct.unpack_from("<H", data, 2)
        (self.cancels, self.moves, self.table, self.l10, self.l14, self.l18,
         self.anims) = struct.unpack_from("<7I", data, 4)

    def move(self, i):
        return struct.unpack_from("<14I", self.d, self.moves + 56 * i)

    def move_bytes(self, i):
        return self.d[self.moves + 56 * i:self.moves + 56 * i + 56]

    def anim_frames(self, i, common=None):
        """Animation length of move i (the loader copies the animation's first byte to +0x18)."""
        a, = struct.unpack_from("<I", self.d, self.moves + 56 * i)
        if a >= 0x40000000:
            return common.d[common.anims + a - 0x40000000]
        return self.d[self.anims + a]


class Moveset:
    def __init__(self, m):
        self.m = m
        self.own = Pack(f(0x62 + 4 * m))
        self.common = Pack(f(COMMON_TOC))

    def resolve(self, target):
        """(pack, move index) of a pointer table entry."""
        v, = struct.unpack_from("<I", self.own.d, self.own.table + 4 * target)
        return (self.own, v) if v < 0x40000000 else (self.common, v - 0x40000000)

    def cancels_grouped(self, pack, start):
        """As cancels(), with the group each entry comes from: (kind, entry, group start or None)
        (a 0xC00C call names the common list 0x80017C78 + s[3] * 12)."""
        out = []
        p = pack.cancels + 12 * start
        while True:
            e = struct.unpack("<HBBHHBBBB", pack.d[p:p + 12])
            if e[0] == 0xC000:
                return out
            if e[0] == 0xC00C:
                g = GROUPS + 12 * e[4]
                while True:
                    ge = struct.unpack("<HBBHHBBBB", _ram(g, 12))
                    if ge[0] in (0xC000, 0xC00D):
                        break
                    out.append(("group", ge, e[4]))
                    g += 12
            else:
                out.append(("own", e, None))
            p += 12

    def cancels(self, pack, start):
        """Cancel entries from index `start` of `pack` (group references expanded, in order)."""
        out = []
        p = pack.cancels + 12 * start
        src = pack.d
        while True:
            e = struct.unpack_from("<HBBHHBBBB", src, p)
            cmd = e[0]
            if cmd == 0xC000:
                break
            if cmd == 0xC00C:
                g = GROUPS + 12 * e[4]
                while True:
                    ge = struct.unpack("<HBBHHBBBB", _ram(g, 12))
                    if ge[0] in (0xC000, 0xC00D):          # 0xC00D returns from the group
                        break
                    out.append(("group", ge))
                    g += 12
            else:
                out.append(("own", e))
            p += 12
        return out


def describe(cmd):
    if cmd >= 0xC000:
        return f"special {cmd:#x}"
    btn = "+".join(n for b, n in ((1, "1"), (2, "2"), (4, "3"), (8, "4")) if cmd & b) or "-"
    dirs = "/".join(n for b, n in DIRS.items() if cmd & b) or "any"
    return f"{dirs} {btn}{' (flag)' if cmd & 0x10 else ''}"


if __name__ == "__main__":
    m = int(sys.argv[1])
    mi = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    ms = Moveset(m)
    w = ms.own.move(mi)
    print(f"move {mi}: anim {w[0]:#x} vuln {w[1]:#x} cancel {w[3]} next {w[4] & 0xFFFF}")
    for src, e in ms.cancels(ms.own, w[3]):
        cmd, cond, req, _, tgt, opt, fr0, fr1, st = e
        pk, idx = ms.resolve(tgt)
        kind = "own" if pk is ms.own else "common"
        if idx >= pk.count:
            print(f"  {src:5} {describe(cmd):22} cond {cond:3} req {req:3} -> {kind} {idx:#x} (out of range, target {tgt})")
            continue
        mv = pk.move_bytes(idx)
        ln, dmg, a0, a1 = pk.anim_frames(idx, ms.common), mv[0x2C], mv[0x2D], mv[0x2E]
        print(f"  {src:5} {describe(cmd):22} cond {cond:3} req {req:3} -> {kind} {idx:4} "
              f"len {ln:3} dmg {dmg:3} active {a0}-{a1} frames {fr0}-{fr1} opt {opt:#x}")
