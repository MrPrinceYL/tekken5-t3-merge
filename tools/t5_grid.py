"""Character select grid with the new characters -> merge/data/grid.csv (Tekken5-Tekken3-Merge).

Original grid (0x471A18, FUN_0024ba50): 31 cells {u16 character, s8 up, s8 down, u8 left,
u8 right}: two rows of 11 (cells 0..9 + random 30, 10..19 + 29) and a top row of 9 (20..28).
New layout (user, 13.10.): the top row of 9 moves below the two middle rows, with Dr. B on its
left and Gun Jack on its right; Gon, True Ogre and Ogre above the middle (columns 4..6).
Moving wraps around vertically and horizontally like the original.

    python t5_grid.py
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

ORIG_CELLS = 0x471A18
NEW = {"GON": (31, 36), "TOG": (32, 34), "OGR": (33, 33), "DRB": (34, 37), "GJK": (35, 35)}  # cell, char


def orig_chars():
    exec(open(ROOT / "tools/elfread.py").read(), g := {})
    return [struct.unpack("<H", g["rd"](ORIG_CELLS + 6 * i, 2))[0] for i in range(31)]


def main():
    chars = orig_chars() + [0] * 5
    for cell, ch in NEW.values():
        chars[cell] = ch
    rows = [
        {4: 31, 5: 32, 6: 33},
        dict(enumerate([0, 1, 2, 3, 4, 30, 5, 6, 7, 8, 9])),
        dict(enumerate([10, 11, 12, 13, 14, 29, 15, 16, 17, 18, 19])),
        dict(enumerate([34] + list(range(20, 29)) + [35])),
    ]
    pos = {cell: (r, c) for r, row in enumerate(rows) for c, cell in row.items()}
    out = ["# Auswahlraster (tools/t5_grid.py): cell,char,up,down,left,right", "cell,char,up,down,left,right"]
    for cell in range(36):
        r, c = pos[cell]
        cols = sorted(rows[r])

        def vert(step):
            k = r
            while True:
                k = (k + step) % len(rows)
                if c in rows[k]:
                    return rows[k][c]

        i = cols.index(c)
        left = rows[r][cols[(i - 1) % len(cols)]]
        right = rows[r][cols[(i + 1) % len(cols)]]
        out.append(f"{cell},{chars[cell]},{vert(-1)},{vert(1)},{left},{right}")
    (ROOT / "merge/data/grid.csv").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
