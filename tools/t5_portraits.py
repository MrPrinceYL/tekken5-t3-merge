"""Portraits of the new characters in the Tekken 5 formats, from the Tekken 3 renders in
merge/png/t3_to_t5_portraits (Tekken5-Tekken3-Merge).

- Select icon kao_<code>: 56 x 56, the frame of an original icon (kao_PAU) with the face in its
  inner area (x 10..46, y 7..48), over a dark backdrop like the original icons.
- Loading / select portrait: 456 x 448, 8-bit TIM2 with transparent background like files
  187.. (Typ 42); the figure from the head down, head near the top edge, P1 version facing
  right at the left edge, P2 version mirrored at the right edge.

White backgrounds (Gun Jack, Gon, Dr. B) are removed by a flood fill of near-white from the
image border; the 2-pixel edge band is un-matted (alpha from the distance to white).

    python t5_portraits.py <out dir>    # kao_<code>.png, portrait_<code>_{l,r}.png/.tim2, sheet
"""
import struct
import sys
from collections import deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pngio import read_png, resize, write_png  # noqa: E402
from t5_tim2 import decode, encode8, tim2_file  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RENDERS = ROOT / "merge/png/t3_to_t5_portraits"

# code: (render, face box x0, y0, x1, y1 in the render, portrait cut line y in the render (the
# figure from its top down to here fills the portrait height), backdrop of the icon)
CHARS = {
    "OGR": ("ogre", (104, 212, 172, 289), 600, (70, 30, 20)),
    "TOG": ("true_ogre", (255, 165, 355, 279), 540, (60, 55, 15)),
    "GJK": ("gun_jack", (250, 50, 340, 152), 430, (40, 45, 55)),
    "GON": ("gon", (115, 0, 250, 153), 250, (90, 45, 10)),
    "DRB": ("dr_b", (225, 38, 315, 140), 420, (30, 60, 70)),
}
# own icon pictures (merge/png/t3_to_t5_portraits, sharper than the faces in the renders):
# file, face box, flat background colour to cut away from the border (or None)
ICON_SRC = {"OGR": ("kao_ogre", (88, 150, 238, 321), (175, 174, 172)),
            "TOG": ("kao_true_ogre", (62, 36, 278, 281), None)}
ICON_IN = (10, 7, 47, 49)                     # inner area x0, y0, x1, y1 (exclusive)
PORTRAIT = (456, 448)


def remove_white(img, thr=246, colour=None):
    """Make the white (or flat `colour`) background connected to the border transparent."""
    h, w = img.shape[:2]
    if img[..., 3].min() < 255:
        return img                             # already cut out
    rgb = img[..., :3].astype(np.int32)
    if colour is None:
        white = rgb.min(axis=2) >= thr
    else:
        white = np.abs(rgb - np.array(colour)).max(axis=2) <= 6
    bg = np.zeros((h, w), bool)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if white[y, x] and not bg[y, x]:
                bg[y, x] = True
                q.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if white[y, x] and not bg[y, x]:
                bg[y, x] = True
                q.append((y, x))
    while q:
        y, x = q.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and white[ny, nx] and not bg[ny, nx]:
                bg[ny, nx] = True
                q.append((ny, nx))
    out = img.astype(np.float64)
    out[bg, 3] = 0
    # edge band: pixels next to the background, alpha from how far they are from white
    band = np.zeros_like(bg)
    near = bg.copy()
    for _ in range(2):
        grow = near.copy()
        grow[1:] |= near[:-1]
        grow[:-1] |= near[1:]
        grow[:, 1:] |= near[:, :-1]
        grow[:, :-1] |= near[:, 1:]
        band |= grow & ~bg & ~near
        near = grow
    ref = np.array(colour if colour is not None else (255, 255, 255), np.float64)
    m = np.abs(rgb - ref).max(axis=2).astype(np.float64)
    a = np.clip(m / 70.0, 0.15, 1.0)
    for c in range(3):
        ch = out[..., c]
        ch[band] = np.clip((ch[band] - ref[c] * (1 - a[band])) / a[band], 0, 255)
    out[band, 3] = 255 * a[band]
    return out


def load(code):
    name = CHARS[code][0]
    return remove_white(read_png(RENDERS / f"{name}.png")).astype(np.float64)


def over(fg, bg):
    a = fg[..., 3:4] / 255.0
    out = fg * a + bg * (1 - a)
    out[..., 3] = np.maximum(fg[..., 3], bg[..., 3])
    return out


def icon(code, frame):
    """56 x 56 select icon."""
    _, (x0, y0, x1, y1), _, back = CHARS[code]
    if code in ICON_SRC:
        name, (x0, y0, x1, y1), flat = ICON_SRC[code]
        img = read_png(RENDERS / f"{name}.png")
        img = (remove_white(img, colour=flat) if flat else img).astype(np.float64)
    else:
        img = load(code)
    ix0, iy0, ix1, iy1 = ICON_IN
    w, h = ix1 - ix0, iy1 - iy0
    face = resize(img[y0:y1, x0:x1], w, h)
    g = np.linspace(1.0, 0.35, h)[:, None, None]
    bg = np.ones((h, w, 4)) * np.array([*back, 255.0])
    bg[..., :3] *= g
    out = frame.astype(np.float64).copy()
    out[iy0:iy1, ix0:ix1] = over(face, bg)
    out[iy0:iy1, ix0:ix1, 3] = 255
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def portrait(code):
    """456 x 448 P1 portrait (figure at the left edge, transparent background)."""
    img = load(code)
    _, (x0, y0, x1, y1), cut, _ = CHARS[code]
    a = img[..., 3]
    ys, xs = np.nonzero(a > 8)
    top = ys.min()
    s = (PORTRAIT[1] - 8) / (cut - top)
    sh, sw = img.shape[:2]
    small = resize(img, max(1, round(sw * s)), max(1, round(sh * s)))
    W, H = PORTRAIT
    out = np.zeros((H, W, 4))
    # head top 8 px below the edge; face centre at x = 130 (Tekken 5 P1 portraits: 85..180)
    oy = 8 - round(top * s)
    ox = min(130 - round((x0 + x1) / 2 * s), -round(xs.min() * s))   # never a gap at the left
    sy0, sx0 = max(0, -oy), max(0, -ox)
    dy0, dx0 = max(0, oy), max(0, ox)
    hh = min(H - dy0, small.shape[0] - sy0)
    ww = min(W - dx0, small.shape[1] - sx0)
    out[dy0:dy0 + hh, dx0:dx0 + ww] = small[sy0:sy0 + hh, sx0:sx0 + ww]
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def template_frame():
    f = (ROOT / "merge/extracted/tk5data1/0081.bin").read_bytes()
    po, = struct.unpack_from("<I", f, 12)
    a = f[po:]
    cnt, = struct.unpack_from("<I", a, 4)
    t0 = struct.unpack_from(f"<{cnt}I", a, 8)
    t1 = struct.unpack_from(f"<{cnt}I", a, 8 + 4 * cnt)
    i = [k for k in range(cnt) if a[t0[k]:].startswith(b"kao_PAU\0")][0]
    return decode(a, t1[i])[0]


def portrait_header():
    d = (ROOT / "merge/extracted/tk5data1/0187.bin").read_bytes()
    return decode(d)[1]


# name index (slot field 2) of the new characters, for file 82 (entry = index * 2 + side)
NAME_INDEX = {"OGR": 33, "TOG": 34, "GJK": 35, "GON": 36, "DRB": 37}


def select_container(portraits, out_path):
    """Extra entries of file 82 (big select portraits, 456 x 224 = the loading portrait at half
    height): u32 count, count x {offset, size}, TIM2s (16-byte aligned)."""
    f = (ROOT / "merge/extracted/tk5data1_lz/0082.bin").read_bytes()
    o0, = struct.unpack_from("<I", f, 4)
    hdr = decode(f, o0)[1]
    first = min(NAME_INDEX.values())
    n = 2 * (max(NAME_INDEX.values()) - first + 1)
    blobs = [b""] * n
    for code, (l, r) in portraits.items():
        k = 2 * (NAME_INDEX[code] - first)
        for side, img in ((0, l), (1, r)):
            half = np.clip(np.round(resize(img, img.shape[1], img.shape[0] // 2)), 0, 255).astype(np.uint8)
            blobs[k + side] = tim2_file([encode8(half, hdr)])
    head = 4 + 8 * n
    out = bytearray(struct.pack("<I", n) + bytes(8 * n))
    while len(out) % 16:
        out += b"\0"
    for i, b in enumerate(blobs):
        while len(out) % 16:
            out += b"\0"
        struct.pack_into("<II", out, 4 + 8 * i, len(out) if b else 0, len(b))
        out += b
    Path(out_path).write_bytes(bytes(out))
    return len(out)


def main(out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frame = template_frame()
    phdr = portrait_header()
    sheet = []
    both = {}
    for code in CHARS:
        ic = icon(code, frame)
        write_png(out / f"kao_{code}.png", ic)
        p = portrait(code)
        pr = p[:, ::-1].copy()
        write_png(out / f"portrait_{code}_l.png", p)
        write_png(out / f"portrait_{code}_r.png", pr)
        for side, img in (("l", p), ("r", pr)):
            (out / f"portrait_{code}_{side}.tim2").write_bytes(tim2_file([encode8(img, phdr)]))
        both[code] = (p, pr)
        sheet.append((ic, p))
        print(code, "done")
    # overview: icons (x4) above the portraits (x0.5) on a blue backdrop
    W = 228 * len(sheet)
    S = np.zeros((224 + 224, W, 4))
    S[..., :3] = (40, 60, 90)
    S[..., 3] = 255
    for k, (ic, p) in enumerate(sheet):
        big = ic.repeat(4, 0).repeat(4, 1).astype(np.float64)
        S[0:224, k * 228:k * 228 + 224] = over(big, S[0:224, k * 228:k * 228 + 224])
        half = resize(p, 228, 224)
        S[224:448, k * 228:(k + 1) * 228] = over(half, S[224:448, k * 228:(k + 1) * 228])
    write_png(out / "overview.png", np.clip(S, 0, 255).astype(np.uint8))
    sel = ROOT / "merge/data/select/portraits_0082.bin"
    print(sel, select_container(both, sel), "bytes")


if __name__ == "__main__":
    main(sys.argv[1])
