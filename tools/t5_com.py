"""Tekken 5 movesets ("COM", slot sub-file 0, LZ; Tekken5-Tekken3-Merge, merge/PLAN.md
"Movesets"): parse into lists of fixed-size entries and write back.

File: header 0x26C bytes (MovesetInfo with the list table at 0x180: 23 x {u32 pointer, u32
count}), then a string block (move / animation names), then the 23 lists in table order. List
pointers are file offsets - 0x26C; entries refer to each other by index, so lists can grow at
their ends as long as the table is rewritten.

    python t5_com.py <decompressed COM>      # round trip test
"""
import struct
import sys

HEAD = 0x26C
TABLE = 0x180
NAMES = ["reactions", "requirement", "hitcond", "pushback", "pushback_extra", "cancel",
         "group_cancel", "cancel_extra", "extraprop", "move_begin", "move_end", "move",
         "voiceclip", "input_seq", "input", "a1", "mvl_playable", "mvl_input", "mvl_display",
         "a2", "a3", "a4", "a5"]
SIZE = {"reactions": 80, "requirement": 4, "hitcond": 12, "pushback": 12, "pushback_extra": 2,
        "cancel": 24, "group_cancel": 24, "cancel_extra": 4, "extraprop": 8, "move_begin": 8,
        "move_end": 8, "move": 76, "voiceclip": 2, "input_seq": 8, "input": 4, "a1": 2,
        "mvl_playable": 20, "mvl_input": 4, "mvl_display": 44, "a2": 8, "a3": 8, "a4": 8, "a5": 8}

CANCEL = "<IIIIHHHH"        # command, requirement, move, extradata, from, to, start, option
HITCOND = "<III"            # requirement, damage, reactions
MOVE = "<IIIIIIHHHhIhHHHIIIIiIHHhH"
MOVE_FIELDS = ["name", "anim_name", "anim", "vuln", "hitlevel", "cancel", "transition", "val2",
               "val1", "x1e", "hitcond", "anim_len", "air_start", "air_end", "ground_fall",
               "voiceclip", "extraprop", "begin", "end", "x3c", "hitbox", "active_start",
               "active_end", "x48", "distance"]


class Com:
    def __init__(self, data):
        self.head = bytearray(data[:HEAD])
        tab = [struct.unpack_from("<II", data, TABLE + 8 * k) for k in range(23)]
        first = min(p for p, _ in tab) + HEAD
        self.strings = bytearray(data[HEAD:first])
        self.lists = {}
        self.order = sorted(range(23), key=lambda k: (tab[k][0], k))
        for k in range(23):
            p, c = tab[k]
            sz = SIZE[NAMES[k]]
            o = p + HEAD
            self.lists[NAMES[k]] = [bytes(data[o + sz * i:o + sz * (i + 1)]) for i in range(c)]
        last = max(tab[k][0] + SIZE[NAMES[k]] * tab[k][1] for k in range(23)) + HEAD
        self.tail = bytes(data[last:])
        # padding bytes after each list (kept as in the original)
        self.gap = {}
        for i, k in enumerate(self.order):
            end = tab[k][0] + SIZE[NAMES[k]] * tab[k][1] + HEAD
            nxt = tab[self.order[i + 1]][0] + HEAD if i + 1 < len(self.order) else last
            self.gap[k] = bytes(data[end:max(end, nxt)])

    def add(self, name, entry):
        self.lists[name].append(bytes(entry))
        return len(self.lists[name]) - 1

    def string(self, s):
        """Offset (pointer value) of a new string in the string block."""
        o = len(self.strings)
        self.strings += s.encode("latin1") + b"\0"
        while len(self.strings) % 4:
            self.strings += b"\0"
        return o

    def move(self, i):
        return dict(zip(MOVE_FIELDS, struct.unpack(MOVE, self.lists["move"][i])))

    @staticmethod
    def pack_move(m):
        return struct.pack(MOVE, *[m[f] for f in MOVE_FIELDS])

    def name(self, ptr):
        o = ptr
        if not 0 <= o < len(self.strings):
            return "?"
        return self.strings[o:self.strings.index(b"\0", o)].decode("latin1")

    def reachable_moves(self):
        """Moves the game can reach: the 36 aliases, cancel and group-cancel targets, transitions
        and reaction moves (ids 0x8000 + n are aliases), followed transitively."""
        n = len(self.lists["move"])
        aliases = struct.unpack_from("<36I", self.head, 0x18)

        def real(x):
            x = aliases[x - 0x8000] if 0x8000 <= x < 0x8000 + 36 else x
            return x if x < n else None

        group = [struct.unpack(CANCEL, e) for e in self.lists["group_cancel"]]
        seen = set()
        todo = [real(a) for a in aliases]
        for e in self.lists["reactions"]:
            todo += [real(x) for x in struct.unpack_from("<14H", e, 52)]
        while todo:
            i = todo.pop()
            if i is None or i in seen:
                continue
            seen.add(i)
            m = self.move(i)
            todo.append(real(m["transition"]))
            k = m["cancel"]
            while True:
                f = struct.unpack(CANCEL, self.lists["cancel"][k])
                if f[0] == 0x8005:
                    g = f[2]
                    while group[g][0] != 0x8006:
                        todo.append(real(group[g][2]))
                        g += 1
                else:
                    todo.append(real(f[2]))
                if f[0] == 0x8000:
                    break
                k += 1
        return seen

    def drop_dead_cancel_lists(self):
        """Unreachable moves keep their index but share the list of alias 1 (standing): their own
        cancel lists can then be compacted away."""
        live = self.reachable_moves()
        stand = self.move(struct.unpack_from("<I", self.head, 0x18 + 4)[0])["cancel"]
        for i in range(len(self.lists["move"])):
            if i not in live:
                m = self.move(i)
                m["cancel"] = stand
                self.lists["move"][i] = self.pack_move(m)
        return len(self.lists["move"]) - len(live)

    def remove_dead_moves(self):
        """Drop the moves the game cannot reach (reachable_moves) and renumber every move
        reference: both alias blocks of the header, cancel / group-cancel targets (not the group
        index of 0x8005), end-entry targets, transitions, reaction moves. A leftover reference to
        a dropped move (only from unreachable lists) goes to standing (alias 1)."""
        n = len(self.lists["move"])
        live = sorted(self.reachable_moves())
        new = {old: k for k, old in enumerate(live)}
        stand = new[struct.unpack_from("<I", self.head, 0x18 + 4)[0]]

        def ren(x):
            return new.get(x, stand) if x < n else x            # 0x8000 + n: aliases stay

        for blk in (0x18, 0x18 + 36 * 4):
            al = list(struct.unpack_from("<36I", self.head, blk))
            struct.pack_into("<36I", self.head, blk, *[ren(x) for x in al])
        for name in ("cancel", "group_cancel"):
            out = []
            for e in self.lists[name]:
                f = list(struct.unpack(CANCEL, e))
                if f[0] != 0x8005:
                    f[2] = ren(f[2])
                out.append(struct.pack(CANCEL, *f))
            self.lists[name] = out
        for k, e in enumerate(self.lists["reactions"]):
            b = bytearray(e)
            mv = struct.unpack_from("<14H", b, 52)
            struct.pack_into("<14H", b, 52, *[ren(x) for x in mv])
            self.lists["reactions"][k] = bytes(b)
        moves = []
        for old in live:
            m = self.move(old)
            m["transition"] = ren(m["transition"])
            moves.append(self.pack_move(m))
        self.lists["move"] = moves
        return n - len(live)

    def drop_group_entries(self, drop):
        """Remove the group-cancel entries for which drop(fields) is true and renumber every
        group call (0x8005: move field = group start, start-frame field = entry count)."""
        old = [struct.unpack(CANCEL, e) for e in self.lists["group_cancel"]]
        new, at = [], {}
        for k, f in enumerate(old):
            at[k] = len(new)
            if f[0] == 0x8006 or not drop(f):
                new.append(f)
        at[len(old)] = len(new)

        def count(g):
            n = 0
            while new[g + n][0] != 0x8006:
                n += 1
            return n

        for name in ("cancel", "group_cancel"):
            src = [struct.unpack(CANCEL, e) for e in self.lists[name]] if name == "cancel" else new
            out = []
            for f in src:
                f = list(f)
                if f[0] == 0x8005:
                    f[2] = at[f[2]]
                    f[6] = count(f[2])
                out.append(struct.pack(CANCEL, *f))
            self.lists[name] = out
        return len(old) - len(new)

    def compact_cancels(self):
        """Keep only the cancel lists moves start (each up to its 0x8000 end entry) and share
        identical ones; the converter's clones leave the replaced template lists behind. Moves
        are the only references into the cancel list (groups have their own list)."""
        lists, at, out = {}, {}, []
        for i in range(len(self.lists["move"])):
            m = self.move(i)
            s = m["cancel"]
            if s not in at:
                k = s
                while struct.unpack_from("<I", self.lists["cancel"][k])[0] != 0x8000:
                    k += 1
                body = tuple(self.lists["cancel"][s:k + 1])
                if body not in lists:
                    lists[body] = len(out)
                    out.extend(body)
                at[s] = lists[body]
            if m["cancel"] != at[s]:
                m["cancel"] = at[s]
                self.lists["move"][i] = self.pack_move(m)
        self.lists["cancel"] = out

    def build(self):
        out = bytearray(self.head) + self.strings
        tab = {}
        for k in self.order:
            n = NAMES[k]
            while len(out) % 4:
                out += b"\0"
            tab[k] = (len(out) - HEAD, len(self.lists[n]))
            for e in self.lists[n]:
                out += e
            if self.gap[k] and (len(out) + len(self.gap[k])) % 4 == 0:
                out += self.gap[k]
        out += self.tail
        for k in range(23):
            struct.pack_into("<II", out, TABLE + 8 * k, *tab[k])
        return bytes(out)


if __name__ == "__main__":
    d = open(sys.argv[1], "rb").read()
    c = Com(d)
    b = c.build()
    print(len(d), len(b), "identical" if b == d else "DIFFERENT")
    if b != d:
        i = next(k for k in range(min(len(b), len(d))) if b[k] != d[k])
        print("first difference at", hex(i))
