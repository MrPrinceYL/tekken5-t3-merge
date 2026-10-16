"""Tekken 3 hit reactions in Tekken 5 terms (Tekken5-Tekken3-Merge, merge/PLAN.md "Moveset-Port").

T3 move +0x32 (u16) selects the reaction of an attack; T5 hit conditions point to a reaction
entry (80 B: pushbacks, directions, reaction move indices) of the own moveset. The translation is
learned from the 15 characters in both games: the T3 and T5 version of each standing attack
(same command) give pairs (T3 reaction id, T5 reaction). T5 reactions are compared across
movesets by their content: the names of the reaction moves (standing, crouching, counter hit,
left side) and the front direction. A T3 id maps to its most frequent T5 reaction; in the target
moveset that is the first reaction entry with the same content.
"""
import collections
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_moves import Moveset  # noqa: E402
from t5_com import CANCEL, HITCOND, Com  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REQ_END = 0x141
# (T3 model m, T5 slot) of the characters in both games: Paul, Law, Lei, King, Yoshimitsu, Nina,
# Hwoarang, Xiaoyu, Eddy, Jin, Julia, Kuma, Bryan, Heihachi, Anna
PAIRS = [(-6, 0), (-4, 2), (-2, 5), (0, 7), (2, 9), (4, 12), (6, 14), (8, 16), (10, 21),
         (12, 25), (14, 28), (16, 30), (18, 32), (20, 34), (30, 51)]


def com_of(slot):
    return Com((ROOT / f"merge/extracted/tk5data1_lz/{230 + 11 * slot:04d}.bin").read_bytes())


def stand_attacks(c):
    """{(direction, buttons): move} of the T5 standing move's cancels (groups expanded)."""
    alias = struct.unpack_from("<36I", c.head, 0x18)
    out = {}

    def walk(lst, i):
        while True:
            f = struct.unpack(CANCEL, c.lists[lst][i])
            i += 1
            if f[0] in (0x8000, 0x8006):              # list end, group end
                return
            if f[0] == 0x8005:                        # group: move field = start
                walk("group_cancel", f[2])
                continue
            if 0x8000 <= f[0] < 0x10000 or f[2] >= len(c.lists["move"]):
                continue
            k = (f[0] & 0xFFFF, (f[0] >> 16) & 0xFF)
            if k[1] and f[1] == 0:
                out.setdefault(k, f[2])

    walk("cancel", c.move(alias[1])["cancel"])
    return out


def normal_hit(c, h):
    """Index of the unconditional (last) entry of a hit condition list."""
    H, R = c.lists["hitcond"], c.lists["requirement"]
    while struct.unpack_from("<H", R[struct.unpack(HITCOND, H[h])[0]])[0] != REQ_END:
        h += 1
    return h


def signature(c, r):
    e = c.lists["reactions"][r]
    h = struct.unpack("<26H", e[28:80])
    n = len(c.lists["move"])
    nm = lambda i: c.name(c.move(i)["name"]) if i < n else str(i)  # noqa: E731
    return (nm(h[12]), nm(h[13]), nm(h[14]), nm(h[16]), h[0])


def t3_reaction(ms, idx):
    return struct.unpack_from("<H", ms.own.move_bytes(idx), 0x32)[0]


_TABLE = None


def table():
    """{T3 reaction id: T5 reaction signature} (most frequent pairing)."""
    global _TABLE
    if _TABLE is None:
        import t3_moveset_to_t5 as cv
        votes = collections.defaultdict(collections.Counter)
        for m, slot in PAIRS:
            ms = Moveset(m)
            c = com_of(slot)
            t5 = stand_attacks(c)
            for k, (idx, _) in cv.t3_attacks(ms).items():
                if k in t5:
                    h = normal_hit(c, c.move(t5[k])["hitcond"])
                    votes[t3_reaction(ms, idx)][signature(c, struct.unpack(HITCOND, c.lists["hitcond"][h])[2])] += 1
        _TABLE = {r: v.most_common(1)[0][0] for r, v in votes.items()}
    return _TABLE


class Mapper:
    """T3 reaction id -> reaction index of the target moveset `com` (None: keep the template's)."""

    def __init__(self, com):
        self.by_sig, self.by_stand, self.by_first = {}, {}, {}
        for r in range(len(com.lists["reactions"])):
            s = signature(com, r)
            self.by_sig.setdefault(s, r)
            self.by_stand.setdefault(s[:2], r)
            self.by_first.setdefault(s[0], r)

    def __call__(self, t3id):
        """Same reaction content, else the same standing/crouching reaction moves, else the same
        standing reaction move."""
        s = table().get(t3id)
        if not s:
            return None
        return self.by_sig.get(s, self.by_stand.get(s[:2], self.by_first.get(s[0])))


if __name__ == "__main__":
    for r, s in sorted(table().items()):
        print(f"{r:#06x}", s)
