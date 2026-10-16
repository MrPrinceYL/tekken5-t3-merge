"""Name lettering of the new characters for the select screen, assembled from the glyphs of the
original name pictures (layout file 81, ASPT `name_<X>`: 32 px high, bold italic, white).

The italic glyphs overlap in columns, so each picture is first un-sheared (x += (y - h) * slant)
until the letters separate by empty columns; glyphs are cut there and set again with the same
spacing, then sheared back.

    python t5_names.py <out dir>     # name_<KEY>.png per new character + glyphs.png
"""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pngio import write_png  # noqa: E402
from t5_tim2 import decode  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEXT = {"JACK5": "JACK-5", "ROGER": "ROGERJr.", "DEVILJIN": "DEVILJIN"}
NEW = {"OGRE": "OGRE", "TRUEOGRE": "TRUE OGRE", "GUNJACK": "GUN JACK", "GON": "GON", "DRB": "DR. B"}


def pictures():
    f = (ROOT / "merge/extracted/tk5data1/0081.bin").read_bytes()
    po, = struct.unpack_from("<I", f, 12)
    a = f[po:]
    cnt, = struct.unpack_from("<I", a, 4)
    t0 = struct.unpack_from(f"<{cnt}I", a, 8)
    t1 = struct.unpack_from(f"<{cnt}I", a, 8 + 4 * cnt)
    for i in range(cnt):
        n = a[t0[i]:a.index(b"\0", t0[i])].decode()
        if n.startswith("name_") and n[5:].isupper() and "_" not in n[5:]:
            yield n[5:], decode(a, t1[i])[0]


def shear(img, s):
    """Shift row y by round((y - h) * s) (s > 0 un-shears a right-leaning italic)."""
    h, w = img.shape[:2]
    pad = int(abs(s) * h) + 2
    out = np.zeros((h, w + 2 * pad, 4), img.dtype)
    for y in range(h):
        d = int(round((h - 1 - y) * s))
        out[y, pad - d:pad - d + w] = img[y]
    return out


def segments(img):
    """Column ranges of the letters: runs of columns with white fill (the dark outline joins the
    letters); each glyph is cut in the middle of the gaps, outline included."""
    fill = (img[..., 3] > 100) & (img[..., :3].min(axis=2) > 150)
    cols = fill.any(axis=0)
    segs, x = [], 0
    while x < len(cols):
        if cols[x]:
            x0 = x
            while x < len(cols) and cols[x]:
                x += 1
            segs.append((x0, x))
        x += 1
    cut = [0] + [(a[1] + b[0]) // 2 for a, b in zip(segs, segs[1:])] + [len(cols)]
    return list(zip(cut, cut[1:]))


def glyphs():
    out = {}
    for key, img in pictures():
        text = TEXT.get(key, key).replace(" ", "")
        for s in np.arange(0.10, 0.45, 0.01):
            u = shear(img, s)
            segs = segments(u)
            if len(segs) == len(text):
                for ch, (x0, x1) in zip(text, segs):
                    g = u[:, x0:x1]
                    cols = np.nonzero((g[..., 3] > 40).any(axis=0))[0]
                    g = g[:, cols.min():cols.max() + 1]
                    if ch not in out:
                        out[ch] = (s, g)
                break
    return out


def lettering(text, gl, gap=-1, space=9):
    s = float(np.median([v[0] for v in gl.values()]))
    parts = []
    for ch in text:
        if ch == " ":
            parts.append(np.zeros((32, space, 4), np.uint8))
        else:
            parts.append(gl[ch][1])
    # set the glyphs with `gap` columns between their outlines (negative: overlap, max alpha)
    width = sum(p.shape[1] for p in parts) + gap * (len(parts) - 1)
    row = np.zeros((32, width + 2, 4), np.uint8)
    x = 0
    for p in parts:
        seg = row[:, x:x + p.shape[1]]
        take = p[..., 3] >= seg[..., 3]
        seg[take] = p[take]
        x += p.shape[1] + gap
    out = shear(row, -s)
    cols = np.nonzero((out[..., 3] > 0).any(axis=0))[0]
    out = out[:, cols.min():cols.max() + 1]
    w = (out.shape[1] + 7) // 8 * 8                      # originals: width multiple of 8
    res = np.zeros((32, w, 4), np.uint8)
    res[:, :out.shape[1]] = out
    return res


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    gl = glyphs()
    print("glyphs:", "".join(sorted(gl)))
    for key, text in NEW.items():
        missing = [c for c in text if c != " " and c not in gl]
        if missing:
            raise SystemExit(f"{text}: no glyph for {missing}")
        write_png(out / f"name_{key}.png", lettering(text, gl))
    sheet = np.concatenate([np.pad(g[1], ((0, 0), (0, 4), (0, 0))) for _, g in sorted(gl.items())], axis=1)
    write_png(out / "glyphs.png", sheet)


if __name__ == "__main__":
    main(sys.argv[1])
