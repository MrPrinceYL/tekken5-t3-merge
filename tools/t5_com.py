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
