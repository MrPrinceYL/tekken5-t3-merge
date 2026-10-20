"""Learn T3 cancel conditions -> T5 requirements from the 15 characters both games have
(Tekken5-Tekken3-Merge, merge/PLAN.md "Moveset-Port"). Both movesets are walked in parallel from
standing: a T3 cancel entry and a T5 cancel entry with the same command (t5_key) lead to a pair
of moves that is walked further. For every aligned pair of entries the T3 (condition,
requirement) is counted against the first T5 requirement of the entry's list.

    python t3_req_learn.py            # prints {T3 (cond, req): [(T5 requirement, count), ...]}
"""
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_moves import Moveset  # noqa: E402
from t3_reactions import PAIRS  # noqa: E402
from t5_com import CANCEL, Com  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REQ_END = 0x141


def t5_entries(com, start):
    """(command key, first requirement, target move) of a T5 cancel list, groups inlined."""
    R = com.lists["requirement"]
    out, k = [], start
    while True:
        f = struct.unpack(CANCEL, com.lists["cancel"][k])
        if f[0] == 0x8000:
            return out
        fs = [f]
        if f[0] == 0x8005:
            fs, g = [], f[2]
            while struct.unpack(CANCEL, com.lists["group_cancel"][g])[0] != 0x8006:
                fs.append(struct.unpack(CANCEL, com.lists["group_cancel"][g]))
                g += 1
        for c in fs:
            if c[0] < 0x8000 or c[0] >= 0x10000:
                req = struct.unpack_from("<H", R[c[1]])[0]
                out.append(((c[0] & 0xFFFF, (c[0] >> 16) & 0xFF), req, c[2]))
        k += 1


def learn():
    stats = defaultdict(Counter)
    for m, slot in PAIRS:
        ms = Moveset(m)
        com = Com((ROOT / f"merge/extracted/tk5data1_lz/{230 + 11 * slot:04d}.bin").read_bytes())
        aliases = struct.unpack_from("<36I", com.head, 0x18)
        n5 = len(com.lists["move"])
        seen, todo = set(), [(0, aliases[1])]
        while todo:
            t3, t5 = todo.pop()
            if (t3, t5) in seen or len(seen) > 4000:
                continue
            seen.add((t3, t5))
            e5 = t5_entries(com, com.move(t5)["cancel"])
            for _, e in ms.cancels(ms.own, ms.own.move(t3)[3]):
                cmd, cond, req, _, tgt, *_ = e
                if cmd >= 0xC000 or not cmd & 0xF:
                    continue
                key = ((cmd >> 4) & 0x3FE, cmd & 0xF)
                pk, idx = ms.resolve(tgt)
                for k5, r5, mv5 in e5:
                    if k5 == key or (k5[1] == key[1] and k5[0] in (0, 0x20) and key[0] in (0, 0x20)):
                        if cond or req:
                            stats[(cond, req)][r5] += 1
                        if pk is ms.own and idx < pk.count and mv5 < n5:
                            todo.append((idx, mv5))
                        break
    return stats


if __name__ == "__main__":
    for k, c in sorted(learn().items(), key=lambda kv: -sum(kv[1].values())):
        print(k, c.most_common(4))
