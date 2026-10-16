"""Character select layout (TK5DATA1 file 81) with the new characters (Tekken5-Tekken3-Merge).

File 81 = container {ASBF layout, ASPT pictures}. ASBF (offsets relative to its start, the game
relocates every pointer field by the load address, FUN_002b3f28; list: layout81_pointers.txt):
header (+0x10 picture records, +0x20 clips, +0x28 nodes, +0x34/+0x48/+0x50 their offsets),
picture records 0x14 {ASPT name offset, ASPT TIM2 offset, texture slot, f32 w, f32 h} at 0x180,
nodes 0xF0 at 0xB90 (+0x68 name, +0x70 next sibling, +0x78 picture record, +0x90 x, +0x94 y),
clips 0x8C at 0xD170 (one per node: +0 name record, +4 node, +0xC commands, +0x38 count,
+0x78 back record), the root clip ("locator", clip 0) with the instance list (RObj 0x6C: +8 node,
+0xC x, +0x10 y, +0x68 picture record; count at root clip +0x3C) at 0x171A0.
ASPT: 'ASPT', u32 count, then count x name offset, count x TIM2 offset, count x (unused) words;
its offsets are relative to the ASPT start and relocated the same way. Picture record k uses the
texture of ASPT entry count - 1 - k.

The file is loaded into a fixed buffer exactly as large as the original (buffer 0x46 at
0x1068D40, FUN_00100a78 / FUN_001017b8 with the constant arena 0x808B40). So the face and name
pictures (kao_*, name_*) move to EE RAM 0x10000.. (kernel RAM no game code touches; merge.rs
writes `select/layout_0081_pics.bin` there, merge/data/blobs.csv): their ASPT offsets are
(address - ASPT load address) mod 2^32, which the relocation turns into the absolute address.

New nodes = clones of a template node (node, clip with its command block, RObj, picture record)
with their own name, picture and position:
- icons kao_<code> from kao_PAU at the grid position (merge/PLAN.md: the old top row below the
  middle rows with Dr. B / Gun Jack beside it, Gon / True Ogre / Ogre above the middle);
- name letterings name_<KEY>_L / _R from name_PAUL_L / _R (picture name_<KEY>).

    python t5_layout.py <out dir> <portrait dir> <name dir>
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pngio import read_png  # noqa: E402
from t5_tim2 import decode, encode8  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "merge/extracted/tk5data1/0081.bin"
BUFFER = 0x01068D40                    # load address of file 81 (buffer 0x46)
BUFFER_SIZE = 0xDB980
EXT_ADDR = 0x00010000                  # pictures moved out of the buffer
EXT_END = 0x00070000
EXT_PREFIX = ("kao_", "name_")

# new icons: (code, column, row)   rows: 0 = new top, 1/2 = the original middle rows, 3 = bottom
ICONS = [("GON", 4, 0), ("TOG", 5, 0), ("OGR", 6, 0), ("DRB", 0, 3), ("GJK", 10, 3)]
NAMES = ["OGRE", "TRUEOGRE", "GUNJACK", "GON", "DRB"]
ROW_Y = [-50.0, -103.0, -156.0, -209.0]
DY = 28.0                              # whole grid shift (screen fit)
OLD_TOP = ["ROG", "ANN", "BAE", "MOK", "DVJ", "GAN", "WAN", "BRU", "KUM"]   # y -50 -> bottom row

IMG0, NODE0, CLIP0, ROBJ0 = 0x180, 0xB90, 0xD170, 0x171A0


def col_x(c):
    return -241.0 + 48.0 * c


def align(n, a=16):
    return (n + a - 1) // a * a


def tim2_blob(pic):
    return b"TIM2" + struct.pack("<BBH", 4, 0, 1) + bytes(8) + pic


def build(out_dir, portrait_dir, name_dir):
    out_dir = Path(out_dir)
    f = SRC.read_bytes()
    nblk, = struct.unpack_from("<I", f, 0)
    (ao, asz), (po, psz) = [struct.unpack_from("<II", f, 4 + 8 * i) for i in range(nblk)]
    A = bytes(f[ao:ao + asz])
    T = bytes(f[po:po + psz])
    ptrs = [int(x, 16) for x in (ROOT / "tools/layout81_pointers.txt").read_text().split()
            if x[0] != "#" and all(c in "0123456789abcdef" for c in x)]
    u = lambda o: struct.unpack_from("<I", A, o)[0]
    n_img, n_clips, n_nodes = u(0x10), u(0x20), u(0x28)
    assert (u(0x34), u(0x50), u(0x48)) == (IMG0, NODE0, CLIP0)
    nodes = {}
    for i in range(n_nodes):
        o = NODE0 + i * 0xF0
        s = u(o + 0x68)
        nodes[A[s:A.index(b"\0", s)].decode("latin1")] = o
    clip_of = {u(CLIP0 + i * 0x8C + 4): CLIP0 + i * 0x8C for i in range(n_clips)}
    root = CLIP0
    robj_n = u(root + 0x3C)
    assert u(root + 0x10) == ROBJ0
    robj_of = {u(ROBJ0 + i * 0x6C + 8): ROBJ0 + i * 0x6C for i in range(robj_n)}
    last = max(nodes.values())
    assert u(last + 0x70) == 0, "last node is not the end of the sibling chain"

    # ---- pictures: originals + new ones
    cnt, = struct.unpack_from("<I", T, 4)
    t0 = struct.unpack_from(f"<{cnt}I", T, 8)
    t1 = struct.unpack_from(f"<{cnt}I", T, 8 + 4 * cnt)
    pics = []                                    # (name, TIM2 file bytes)
    for i in range(cnt):
        nm = T[t0[i]:T.index(b"\0", t0[i])].decode("latin1")
        tot, = struct.unpack_from("<I", T, t1[i] + 16)
        pics.append((nm, T[t1[i]:t1[i] + 16 + tot]))
    by_name = {nm: k for k, (nm, _) in enumerate(pics)}
    kao_hdr = decode(T, t1[by_name["kao_PAU"]])[1]
    name_hdr = decode(T, t1[by_name["name_PAUL"]])[1]
    sizes = {}
    clones = []                                  # (template node name, new name, picture, x, y)
    for code, colm, row in ICONS:
        img = read_png(Path(portrait_dir) / f"kao_{code}.png")
        pics.append((f"kao_{code}", tim2_blob(encode8(img, kao_hdr))))
        sizes[f"kao_{code}"] = img.shape[1], img.shape[0]
        clones.append(("kao_PAU", f"kao_{code}", f"kao_{code}", col_x(colm), ROW_Y[row] + DY))
    for key in NAMES:
        img = read_png(Path(name_dir) / f"name_{key}.png")
        pics.append((f"name_{key}", tim2_blob(encode8(img, name_hdr))))
        sizes[f"name_{key}"] = img.shape[1], img.shape[0]
        for side in "LR":
            clones.append((f"name_PAUL_{side}", f"name_{key}_{side}", f"name_{key}", None, None))
    n = len(pics)
    k = len(clones)

    # ---- ASPT: header, names, internal TIM2s; kao_/name_ TIM2s into the external blob
    names_blob = bytearray()
    name_off = []
    head_size = 8 + 12 * n
    for nm, _ in pics:
        name_off.append(head_size + len(names_blob))
        names_blob += nm.encode("latin1") + b"\0"
    inner = bytearray(names_blob)
    ext = bytearray()
    container_aspt = None                        # filled once the ASBF size is known
    tim_inner, tim_ext = {}, {}
    for idx, (nm, blob) in enumerate(pics):
        if nm.startswith(EXT_PREFIX):
            while len(ext) % 16:
                ext += b"\0"
            tim_ext[idx] = len(ext)
            ext += blob
        else:
            while (head_size + len(inner)) % 16:
                inner += b"\0"
            tim_inner[idx] = head_size + len(inner)
            inner += blob
    assert EXT_ADDR + len(ext) <= EXT_END, "external picture area full"

    # ---- ASBF: insertions (original offsets) and relocation
    n_new_img = n - cnt
    ins = [(IMG0 + 0x14 * n_img, align(0x14 * n_new_img)), (NODE0 + 0xF0 * n_nodes, 0xF0 * k),
           (CLIP0 + 0x8C * n_clips, align(0x8C * k)), (ROBJ0 + 0x6C * robj_n, align(0x6C * k))]

    def S(v):
        return v + sum(m for p, m in ins if p <= v)

    out = bytearray()
    prev = 0
    region = {}
    for p, m in ins:
        out += A[prev:p]
        region[p] = len(out)
        out += bytes(m)
        prev = p
    out += A[prev:]
    w32 = lambda o, v: struct.pack_into("<I", out, o, v & 0xFFFFFFFF)
    wf = lambda o, v: struct.pack_into("<f", out, o, v)
    for p in ptrs:
        v = u(p)
        if v:
            w32(S(p), S(v))
    for off in (0x10, 0x20, 0x28):
        w32(off, u(off) + (n_new_img if off == 0x10 else k))
    w32(S(root) + 0x3C, robj_n + k)

    def append(b, al=16):
        nonlocal out
        while len(out) % al:
            out += b"\0"
        o = len(out)
        out += b
        return o

    recs = [region[ins[0][0]] + 0x14 * j for j in range(n_new_img)]
    nnodes = [region[ins[1][0]] + 0xF0 * j for j in range(k)]
    nclips = [region[ins[2][0]] + 0x8C * j for j in range(k)]
    nrobj = [region[ins[3][0]] + 0x6C * j for j in range(k)]
    rec_of_pic = {}
    for j in range(n_new_img):
        rec_of_pic[cnt + j] = recs[j]
    in_tpl = lambda base, size: [p for p in ptrs if base <= p < base + size]
    for j, (tpl, new, pic, x, y) in enumerate(clones):
        tn = nodes[tpl]
        tc, tr = clip_of[tn], robj_of[tn]
        aux0 = u(tc + 0xC)
        aux1 = min(u(c + 0xC) for c in clip_of.values() if u(c + 0xC) > aux0)
        name_at = append(new.encode() + b"\0", 4)
        blk = bytearray(A[aux0:aux1])
        aux = append(bytes(blk))
        for p in in_tpl(aux0, aux1 - aux0):
            v = u(p)
            if v:
                nv = (aux + v - aux0 if aux0 <= v < aux1 else nclips[j] if v == tc else
                      nnodes[j] if v == tn else S(v))
                w32(aux + p - aux0, nv)
        q = out.find(tpl.encode() + b"\0", aux, aux + len(blk))
        if q >= 0:                               # clip's own name (same length, cut if longer)
            out[q:q + len(tpl)] = new.encode()[:len(tpl)].ljust(len(tpl), b"\0")
        rec = rec_of_pic[by_name.get(pic, None) if pic in by_name else
                         cnt + [nm for nm, _ in pics[cnt:]].index(pic)]
        out[nnodes[j]:nnodes[j] + 0xF0] = A[tn:tn + 0xF0]
        w32(nnodes[j] + 0x68, name_at)
        w32(nnodes[j] + 0x70, nnodes[j + 1] if j + 1 < k else 0)
        w32(nnodes[j] + 0x78, rec)
        out[nclips[j]:nclips[j] + 0x8C] = A[tc:tc + 0x8C]
        for p in in_tpl(tc, 0x8C):
            v = u(p)
            if v:
                w32(nclips[j] + p - tc, nnodes[j] if v == tn else aux + v - aux0 if aux0 <= v < aux1 else S(v))
        out[nrobj[j]:nrobj[j] + 0x6C] = A[tr:tr + 0x6C]
        for p in in_tpl(tr, 0x6C):
            v = u(p)
            if v:
                w32(nrobj[j] + p - tr, S(v))
        w32(nrobj[j] + 8, nnodes[j])
        w32(nrobj[j] + 0x68, rec)
        if x is not None:
            wf(nnodes[j] + 0x90, x)
            wf(nnodes[j] + 0x94, y)
            wf(nrobj[j] + 0xC, x)
            wf(nrobj[j] + 0x10, y)
    w32(S(last) + 0x70, nnodes[0])

    # move the grid: old top row to the bottom, everything by DY
    for nm, o in nodes.items():
        if not nm.startswith("kao_") or nm == "kao_hatena_select":
            continue
        y = struct.unpack_from("<f", A, o + 0x94)[0]
        if nm[4:] in OLD_TOP:
            assert abs(y - ROW_Y[0]) < 1.0, (nm, y)
            y = ROW_Y[3]
        y += DY
        wf(S(o) + 0x94, y)
        r = robj_of.get(o)
        if r is not None:
            wf(S(r) + 0x10, y)

    while len(out) % 16:
        out += b"\0"
    A2 = out
    a_off = 0x20
    p_off = align(a_off + len(A2), 64)
    aspt_addr = BUFFER + p_off

    # ASPT offsets: internal relative to the ASPT, external = address - ASPT address
    def tim_off(idx):
        return tim_inner[idx] if idx in tim_inner else (EXT_ADDR + tim_ext[idx] - aspt_addr) & 0xFFFFFFFF

    old_rec_pic = {}
    for i in range(n_img):
        r = IMG0 + 0x14 * i
        b = u(r + 4)
        old_rec_pic[S(r)] = t1.index(b)
    for r, idx in old_rec_pic.items():
        struct.pack_into("<II", A2, r, name_off[idx], tim_off(idx))
    for idx, r in rec_of_pic.items():
        A2[r:r + 0x14] = A[IMG0:IMG0 + 0x14]
        w, h = sizes[pics[idx][0]]
        struct.pack_into("<IIIff", A2, r, name_off[idx], tim_off(idx), 0, float(w), float(h))
    # the loader gives picture record k the texture of ASPT entry n - 1 - k (FUN_002b2578): the
    # records of the new pictures follow the original ones, so their entries come first
    order = [cnt + n_new_img - 1 - i for i in range(n_new_img)] + list(range(cnt))
    head = bytearray(b"ASPT" + struct.pack("<I", n))
    head += struct.pack(f"<{n}I", *[name_off[i] for i in order])
    head += struct.pack(f"<{n}I", *[tim_off(i) for i in order])
    head += bytes(4 * n)
    T2 = bytes(head) + bytes(inner)

    hdr = struct.pack("<I", 2) + struct.pack("<II", a_off, len(A2)) + struct.pack("<II", p_off, len(T2))
    res = bytearray(hdr) + bytes(a_off - len(hdr)) + A2
    res += bytes(p_off - len(res)) + T2
    assert len(res) <= BUFFER_SIZE, f"file 81 is {len(res)} bytes, buffer {BUFFER_SIZE}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "layout_0081.bin").write_bytes(bytes(res))
    (out_dir / "layout_0081_pics.bin").write_bytes(bytes(ext))
    return len(res), len(ext)


if __name__ == "__main__":
    size, ext = build(sys.argv[1], sys.argv[2], sys.argv[3])
    print(f"layout_0081.bin {size} bytes (buffer {BUFFER_SIZE}), pictures at 0x{EXT_ADDR:x}: {ext} bytes")
