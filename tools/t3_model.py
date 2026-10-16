"""Tekken 3 (PS1) character data: BNS access and the 3DMK model format (merge/PLAN.md).

    python t3_model.py            # check every part of Ogre, True Ogre, Gun Jack, Gon, Dr. B

Model m: BNS 0x5F+4m = 3DMK, 0x60+4m = VAB head, 0x61+4m = textures container, 0x62+4m =
animations. 3DMK: 27 records of 0x38 bytes (w4 vertex block, w6 normals, w7 primitives,
w8 UV lists, w9..w11 joint offset, w12 parent). Formats from FUN_80036cac (transform +
primitives) and FUN_80035190 (UV packet templates) in Tekken3Decomp.
"""
import csv, struct

BNS = r"E:/Decompilation/Decomps/Tekken3/extracted/files/TEKKEN3/TEKKEN3.BNS"
TOC = r"E:/Decompilation/Decomps/Tekken3/extracted/bns_toc.csv"
MODELS = {"Ogre": 22, "True Ogre": 26, "Gun Jack": 28, "Gon": 36, "Dr. B": 38}

_bns = None
_toc = None


def f(i):
    """BNS file i."""
    global _bns, _toc
    if _bns is None:
        _bns = open(BNS, "rb").read()
        _toc = {int(r["index"]): (int(r["offset"], 16), int(r["size"])) for r in csv.DictReader(open(TOC))}
    o, s = _toc[i]
    return _bns[o:o + s]


def u32(d,o): return struct.unpack_from('<I',d,o)[0]
def parts(d):
    out=[]
    for i in range(u32(d,0)):
        w=struct.unpack_from('<14i',d,i*0x38); out.append(w)
    return out
def packed(d,o,n,shift=8,mask=0xff):
    idx=[]; cur=0
    for j in range(n):
        if cur==0: cur=u32(d,o); o+=4
        idx.append(cur&mask); cur>>=shift
    return idx,o
def vblock(d,o):
    head=u32(d,o); o+=4
    lists=[]
    for k in range(2):
        n=u32(d,o); o+=4
        idx,o=packed(d,o,n); lists.append(idx)
    N=u32(d,o); o+=4
    verts=[struct.unpack_from('<hhh',d,o+8*j) for j in range(N)]
    return lists,verts,o+8*N
def vpasses(d, o):
    """Seam passes after the own vertices (FUN_80036cac): (a) 9-bit entries, (b) two lists,
    (c) two lists, (d) 2-bit entries. 9-bit entry = (index byte, halve flag)."""
    def lst9(o):
        n = u32(d, o); o += 4
        e, o = packed(d, o, n, 9, 0x1FF)
        return [(x & 0xFF, bool(x & 0x100)) for x in e], o
    a, o = lst9(o)
    b0, o = lst9(o)
    b1, o = lst9(o)
    c0, o = lst9(o)
    c1, o = lst9(o)
    n = u32(d, o); o += 4
    dd, o = packed(d, o, n, 2, 3)
    return {"a": a, "b": (b0, b1), "c": (c0, c1), "d": dd}, o


def skin(d, order):
    """Symbolic replay of the seam passes over the parts in draw order `order` (record indices).
    Returns {record: [slot weights]} where a slot weight is {(record, own vertex): weight}."""
    def add(x, y):
        r = dict(x)
        for k, v in y.items():
            r[k] = r.get(k, 0) + v
        return r

    def half(x):
        return {k: v * 0.5 for k, v in x.items()}

    G = {}
    S = {}
    out = {}
    recs = parts(d)
    for r in order:
        w = recs[r]
        if w[4] == 0:
            continue
        o = w[4]
        head = u32(d, o)
        lists, verts, end = vblock(d, o)
        P, _ = vpasses(d, end)
        sl = lambda k: k // 2 - 1
        cur_S = dict(S)
        pos = 0
        for idx in lists[0]:
            cur_S[pos] = S.get(sl(idx), {})
            pos += 1
        for idx in lists[1]:
            cur_S[pos] = G.get(sl(idx), {})
            pos += 1
        for j in range(len(verts)):
            cur_S[pos] = {(r, j): 1.0}
            pos += 1
        S = cur_S
        c = sl(head)
        for idx, fl in P["a"]:
            o_ = half(S.get(c, {})) if fl else S.get(c, {})
            s_ = add(o_, G.get(sl(idx), {}))
            G[sl(idx)] = s_; S[c] = s_; c += 1
        for src in (0, 1):
            for idx, fl in P["b"][src]:
                o_ = half(S.get(c, {})) if fl else S.get(c, {})
                S[c] = add((G if src == 0 else S).get(sl(idx), {}), o_); c += 1
        for dst in (0, 1):
            for idx, fl in P["c"][dst]:
                o_ = half(S.get(c, {})) if fl else S.get(c, {})
                S[c] = o_
                (G if dst == 0 else S)[sl(idx)] = o_; c += 1
        for e in P["d"]:
            if e != 1:
                S[c] = half(S.get(c, {}))
            c += 1
        out[r] = [S.get(i, {}) for i in range(max(pos, c))]
    return out


def vram(m):
    """Player-1 VRAM (1024 x 512 halfwords) with model m's textures (FUN_80035744: pixels at
    x + 0x180, CLUTs at y + 0x1F8)."""
    d = f(0x61 + 4 * m)
    o, s = struct.unpack_from("<II", d, 4)
    V = [[0] * 1024 for _ in range(512)]

    def put(x, y, w, h, data):
        for yy in range(h):
            for xx in range(w):
                if 0 <= y + yy < 512 and 0 <= x + xx < 1024:
                    V[y + yy][x + xx] = struct.unpack_from("<H", data, 2 * (yy * w + xx))[0]

    p = o
    while p + 8 <= o + s and u32(d, p) == 0x10:
        fl = u32(d, p + 4); q = p + 8
        if fl & 8:
            ln, x, y, w, h = struct.unpack_from("<IHHHH", d, q)
            put(x, y + 0x1F8, w, h, d[q + 12:q + ln]); q += ln
        ln, x, y, w, h = struct.unpack_from("<IHHHH", d, q)
        put(x + 0x180, y, w, h, d[q + 12:q + ln])
        p = q + ln
    _face_copy(V, m)
    return V


def _face_copy(V, m):
    """FUN_80033d0c (player 1): MoveImage of a w x h rect, table 0x800959CC[m] =
    (source, size, destination, -) with rects at 0x8009579C (x, y) / 0x8009586C (w, h)."""
    from t3_anim import _ram
    src, size, dst, _ = struct.unpack("<4b", _ram(0x800959CC + 4 * m, 4))
    if src == -1:
        return
    sx, sy = struct.unpack("<hh", _ram(0x8009579C + 4 * src, 4))
    w, h = struct.unpack("<hh", _ram(0x8009586C + 4 * size, 4))
    dx, dy = struct.unpack("<hh", _ram(0x8009579C + 4 * dst, 4))
    block = [V[sy + yy][sx:sx + w] for yy in range(h)]
    for yy in range(h):
        V[dy + yy][dx:dx + w] = block[yy]


def texel(V, a, u, v):
    """RGBA of texel (u, v) for UV-table entry a: CLUT field 0x7E00 + low byte, texture page
    6 + high byte (GPU tpage: x = bits 0-3 * 64, y = bit 4 * 256, colour mode bits 7-8:
    0 = 4 bit, 1 = 8 bit, 2 = 15 bit direct)."""
    clut = 0x7E00 + (a & 0xFF)
    page = 6 + (a >> 8)
    cx, cy = (clut & 0x3F) * 16, clut >> 6
    px, py = (page & 0xF) * 64, ((page >> 4) & 1) * 256
    mode = (page >> 7) & 3
    if mode == 0:
        idx = V[py + v][px + u // 4] >> (4 * (u & 3)) & 15
        c = V[cy][cx + idx]
    elif mode == 1:
        idx = V[py + v][px + u // 2] >> (8 * (u & 1)) & 0xFF
        c = V[cy][cx + idx] if cx + idx < 1024 else 0
    else:
        c = V[py + v][px + u]
    return ((c & 31) * 8, (c >> 5 & 31) * 8, (c >> 10 & 31) * 8, 0 if c == 0 else 255)


def prims(d, o):
    """Primitive lists of a part (FUN_80036cac): [(kind, [(slots, words)])], kind ft3/ft4/gt3/gt4.
    Slots: v0 = w0 & 0x1FC, v1 = w0 >> 7 & 0x1FC, v2 = w0 >> 14 & 0x1FC (byte offsets / 4);
    quads add v3 = w0 >> 23 and are drawn as (v0, v1, v2) + (v1, v2, v3) in packet order.
    Triangles: bit 24 of w0 = double sided, w0 >> 25 = depth bias; quads keep these in w1."""
    res = []
    for kind, nw in (("ft3", 2), ("ft4", 2), ("gt3", 2), ("gt4", 3)):
        n = u32(d, o); o += 4
        L = []
        for _ in range(n):
            ws = struct.unpack_from(f"<{nw}I", d, o); o += 4 * nw
            w0 = ws[0]
            v = [(w0 & 0x1FC) >> 2, (w0 >> 7 & 0x1FC) >> 2, (w0 >> 14 & 0x1FC) >> 2]
            if kind in ("ft4", "gt4"):
                v.append((w0 >> 23) >> 2)
            L.append((v, ws))
        res.append((kind, L))
    return res


def uvs(d,o):
    A0=struct.unpack_from('<H',d,o)[0]; B=o+A0; B0=struct.unpack_from('<H',d,B)[0]; p=B+B0
    res=[]
    for kind,nb in (('ft3',4),('ft4',5),('gt3',4),('gt4',5)):
        n=d[p]; p+=1; L=[]
        for j in range(n):
            e=d[p:p+nb]; p+=nb
            a=struct.unpack_from('<H',d,o+2*(e[0]+1))[0]
            uv=[struct.unpack_from('<H',d,B+2*(x+1))[0] for x in e[1:]]
            L.append((a,[(t&0xff,t>>8) for t in uv]))
        res.append((kind,L))
    return res


if __name__ == "__main__":
    for name, m in MODELS.items():
        d = f(0x5F + 4 * m)
        tot = [0, 0, 0, 0]
        bad = 0
        for w in parts(d):
            if w[4] == 0:
                continue
            vblock(d, w[4])
            P, U = prims(d, w[7]), uvs(d, w[8])
            for k in range(4):
                bad += len(P[k][1]) != len(U[k][1])
                tot[k] += len(P[k][1])
        print(f"{name}: FT3/FT4/GT3/GT4 {tot}, count mismatches {bad}")
