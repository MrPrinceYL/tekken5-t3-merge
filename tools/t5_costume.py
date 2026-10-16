"""Write a Tekken 5 costume model file from a Tekken 3 character (Tekken5-Tekken3-Merge).

The template is an existing costume model (slot sub-file 10). Kept: skeleton, the other
blocks, the template's TIM2 pictures up to the last 8x2 palette strip. Replaced: the costume
mesh (NUDP, block 2) and its object info (MIF, block 4); the bare body mesh (block 5) is
collapsed so it draws nothing. Formats: merge/PLAN.md ("NUDP vollständig").

    python t5_costume.py <t3 model m> <template costume file> <out file>
"""
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t3_model import vram  # noqa: E402
from t3_to_t5 import convert_mesh, fit_skeleton  # noqa: E402
from t5_model import container, groups  # noqa: E402

MAX_TRIS = 13                             # 39 vertices per VIF packet (VU limit 40)


def outward(tris, W5):
    """Orient every triangle so that its normal cross(B-A, C-A) points away from its main node's
    bone axis; double-sided triangles are emitted both ways."""
    out = []
    for cs, uvd, double in tris:
        P = [c[0] for c in cs]
        main = max(cs[0][1], key=cs[0][1].get)
        R, t = W5[main]
        cen = [sum(p[i] for p in P) / 3 for i in range(3)]
        ax = [R[0][0], R[1][0], R[2][0]]
        rel = [a - b for a, b in zip(cen, t)]
        along = sum(a * b for a, b in zip(rel, ax))
        radial = [r - along * a for r, a in zip(rel, ax)]
        u = [b - a for a, b in zip(P[0], P[1])]
        v = [b - a for a, b in zip(P[0], P[2])]
        n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        flip = sum(a * b for a, b in zip(n, radial)) < 0
        a, uv = uvd
        order = (0, 2, 1) if flip else (0, 1, 2)
        out.append(([cs[i] for i in order], (a, [uv[i] for i in order])))
        if double:
            order = (0, 1, 2) if flip else (0, 2, 1)
            out.append(([cs[i] for i in order], (a, [uv[i] for i in order])))
    return out


def page_of(a):
    return 6 + (a >> 8)


def textures(tris, V):
    """One 8-bit texture per T3 UV entry (texture page + CLUT), cropped to the used rectangle.
    Returns ([(w, h, indices, palette)], {uv entry: (texture, x0, y0, w, h)})."""
    rects = {}
    for _, (a, uv) in tris:
        k = rects.setdefault(a, [255, 255, 0, 0])
        for u, v in uv:
            k[0], k[1], k[2], k[3] = min(k[0], u), min(k[1], v), max(k[2], u), max(k[3], v)
    texs, where = [], {}
    for a, (x0, y0, x1, y1) in sorted(rects.items()):
        # the GS (TEX0 TW/TH) only knows power-of-two sizes: the game derives them from the picture,
        # so other sizes stretch the UVs (Gon / Gun Jack / Dr. B have large odd-sized pages)
        w = min(256, max(16, 1 << (x1 - x0).bit_length()))
        h = min(256, max(8, 1 << (y1 - y0).bit_length()))
        x0, y0 = min(x0, 256 - w), min(y0, 256 - h)
        clut = 0x7E00 + (a & 0xFF)
        page = page_of(a)
        cx, cy = (clut & 0x3F) * 16, clut >> 6
        px, py = (page & 0xF) * 64, ((page >> 4) & 1) * 256
        mode = (page >> 7) & 3
        ncol = 16 if mode == 0 else 256
        pal = []
        for i in range(256):
            c = V[cy][cx + i] if i < ncol and cx + i < 1024 else 0
            rgb = ((c & 31) * 255 // 31, (c >> 5 & 31) * 255 // 31, (c >> 10 & 31) * 255 // 31)
            pal.append(rgb + ((0,) if c == 0 else (0x80,)))
        idx = bytearray()
        for yy in range(y0, y0 + h):
            for xx in range(x0, x0 + w):
                if mode == 0:
                    idx.append(V[py + yy][px + xx // 4] >> (4 * (xx & 3)) & 15)
                else:
                    idx.append(V[py + yy][px + xx // 2] >> (8 * (xx & 1)) & 0xFF)
        where[a] = (len(texs), x0, y0, w, h)
        texs.append((w, h, bytes(idx), pal))
    return texs, where


GIDX_AT = 0x30 + 0x18      # picture header extension "eXt" + "GIDX" chunk: u16 texture id, u16 0x1040


def gidx(hdr):
    """Texture id of a picture header (the render state word 0 is 0x1040_0000 | id)."""
    return struct.unpack_from("<H", hdr, GIDX_AT)[0] if hdr[0x30:0x33] == b"eXt" else None


def tim2_picture(template_hdr, w, h, idx, pal, tex_id):
    """One TIM2 picture: 8-bit indexed, 256-colour 32-bit CLUT in CSM1 order (like the game's),
    texture id `tex_id` in its GIDX header chunk."""
    hdr = bytearray(template_hdr)
    struct.pack_into("<H", hdr, GIDX_AT, tex_id)
    clut = list(pal)
    for b in range(0, 256, 32):
        clut[b + 8:b + 16], clut[b + 16:b + 24] = clut[b + 16:b + 24], clut[b + 8:b + 16]
    cl = b"".join(bytes(c) for c in clut)
    struct.pack_into("<III", hdr, 0, len(hdr) + len(idx) + len(cl), len(cl), len(idx))
    struct.pack_into("<HBBBB", hdr, 0xE, 256, 0, 1, 3, 5)
    struct.pack_into("<HH", hdr, 0x14, w, h)
    hdr[0x18:0x30] = bytes(0x18)                    # GS registers: filled in by the game
    return bytes(hdr) + idx + cl


def build_tim2(template, texs):
    """Template pictures up to the last 8x2 palette strip, then ours. Texture ids (GIDX) are
    reserved per file in a shared table, so ours reuse ids of the dropped costume textures
    that no kept picture uses. Returns (TIM2 bytes, texture id of each of ours)."""
    cnt, = struct.unpack_from("<H", template, 6)
    p, hdr8, entries = 16, None, []
    for _ in range(cnt):
        tot, _, _, hsz = struct.unpack_from("<IIIH", template, p)
        w, h = struct.unpack_from("<HH", template, p + 0x14)
        if hdr8 is None and template[p + 0x13] == 5 and template[p + 0x12] == 3:
            hdr8 = template[p:p + hsz]
        entries.append((p, tot, (w, h) == (8, 2)))
        p += tot
    last_strip = max((i for i, e in enumerate(entries) if e[2]), default=-1)
    kept = entries[:last_strip + 1]
    kept_ids = {gidx(template[q:q + 0x50]) for q, _, _ in kept}
    free = sorted({gidx(template[q:q + 0x50]) for q, _, _ in entries[last_strip + 1:]} - kept_ids - {None})
    assert len(free) >= len(texs), f"only {len(free)} free texture ids for {len(texs)} textures"
    ids = free[:len(texs)]
    body = b"".join(template[q:q + t] for q, t, _ in kept)
    body += b"".join(tim2_picture(hdr8, *t, ids[k]) for k, t in enumerate(texs))
    head = bytearray(template[:16])
    struct.pack_into("<H", head, 6, len(kept) + len(texs))
    return bytes(head) + body, ids


def _f(vals):
    return list(struct.unpack(f"<{len(vals)}I", struct.pack(f"<{len(vals)}f", *vals)))


def vif_packet(verts, ntris):
    """VIF packet (layout of the game's packets): verts = [(pos, normal, uv, [(slot, w)])],
    triangles = consecutive vertex triples, ADC on the first two vertices of every triple."""
    n = len(verts)
    w = [0x01000105, 0x60018000, n, 0x20000000, 0x00000080]
    w += [0x78000000 | n << 16 | 0x8001] + [x for v in verts for x in _f(v[0])]
    w += [0x68000000 | n << 16 | 0x8002] + [x for v in verts for x in _f(v[1])]
    w += [0x64000000 | n << 16 | 0x8004] + [x for v in verts for x in _f(v[2])]
    w += [0x01000102, 0x6C000000 | n << 16 | 0x80CC]
    for v in verts:
        ws = (list(v[3]) + [(0, 0.0)] * 4)[:4]
        w += _f([x[1] for x in ws])
    w += [0x6E000000 | n << 16 | 0xC0CD]
    for v in verts:
        ws = (list(v[3]) + [(0, 0.0)] * 4)[:4]
        w.append(struct.unpack("<I", bytes(x[0] * 7 for x in ws))[0])
    w += [0x01000500, 0x20000000, 0xFFFFFF7F]
    w += [0x70060000 | 0x8000 | (5 * 3 * k + 1) for k in range(ntris)]
    tail = [0x01000101, 0x20000000, 0x00000000, 0x14000000]
    while (len(w) + 1 + len(tail)) % 4:
        w.append(0)
    total = len(w) + 1 + len(tail)
    return struct.pack(f"<{total}I", 0x00910000 | total * 4, *w, *tail)


def template_state(tmpl):
    """State area of a template NUDP (between the group table and the first VIF packet: blocks of
    0x30 bytes the render-state words 1 and 2 point at, e.g. lighting parameters and the VU1
    function table loaded by command 0xEC) and the most common opaque render state."""
    gs = groups(tmpl)
    table_end = 0x20 + sum(0x18 + 0x28 * len(g["batches"]) for g in gs)
    data_start = min(bt["offset"] for g in gs for bt in g["batches"])
    count = {}
    for g in gs:
        for bt in g["batches"]:
            st = bt["state"][1:]
            if st[2] == 0x80000042:
                count[st] = count.get(st, 0) + 1
    state = max(count, key=count.get)
    return tmpl[table_end:data_start], table_end, state


def build_nudp(tris, where, tex_ids, tmpl):
    """NUDP block: one group per batch, one VIF packet per batch (<= 13 triangles, <= 10 nodes);
    the template's state area is kept (relocated) behind the group table."""
    area, old_at, (w1, w2, w3) = template_state(tmpl)
    acc = {}
    for cs, _ in tris:
        P = [c[0] for c in cs]
        u = [b - a for a, b in zip(P[0], P[1])]
        v = [b - a for a, b in zip(P[0], P[2])]
        n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        for p in P:
            a = acc.setdefault(tuple(round(x, 1) for x in p), [0.0, 0.0, 0.0])
            for i in range(3):
                a[i] += n[i]

    def normal(p):
        a = acc[tuple(round(x, 1) for x in p)]
        ln = math.sqrt(sum(x * x for x in a)) or 1.0
        return [x / ln for x in a]

    by_mat = {}
    for cs, (a, uv) in tris:
        by_mat.setdefault(a, []).append((cs, uv))
    batches = []
    for a, L in sorted(by_mat.items()):
        tex, x0, y0, tw, th = where[a]
        cur, nodes = [], set()
        for cs, uv in L:
            mine = {k for c in cs for k in c[1]}
            if len(cur) == MAX_TRIS or len(nodes | mine) > 10:
                batches.append((tex_ids[tex], cur, sorted(nodes)))
                cur, nodes = [], set()
            nodes |= mine
            cur.append((cs, [((u - x0 + 0.5) / tw, (v - y0 + 0.5) / th) for u, v in uv]))
        if cur:
            batches.append((tex_ids[tex], cur, sorted(nodes)))
    assert len(batches) <= 255, f"{len(batches)} groups do not fit one NUDP block"
    table, data = bytearray(), bytearray()
    area_at = (0x20 + len(batches) * 0x40 + 15) // 16 * 16
    delta = area_at - old_at
    state = (w1 + delta, w2 + delta, w3)
    data_start = (area_at + len(area) + 15) // 16 * 16
    for mat, cur, pal in batches:
        slot = {nd: i for i, nd in enumerate(pal)}
        verts = []
        for cs, uv in cur:
            for c, t in zip(cs, uv):
                verts.append((c[0], normal(c[0]), t, [(slot[k], wt) for k, wt in c[1].items()]))
        pk = vif_packet(verts, len(cur))
        P = [v[0] for v in verts]
        cen = [sum(p[i] for p in P) / len(P) for i in range(3)]
        rad = max(math.sqrt(sum((x - y) ** 2 for x, y in zip(p, cen))) for p in P)
        load = {}
        for v in verts:
            for s, wt in v[3]:
                load[s] = load.get(s, 0) + wt
        g = bytearray(0x40)
        g[0], g[3] = 0x20, pal[max(load, key=load.get)]
        struct.pack_into("<HH4f", g, 4, 1, len(verts), *cen, rad)
        struct.pack_into("<4I", g, 0x18, 0x10400000 | mat, *state)
        struct.pack_into("<IHHI", g, 0x28, data_start + len(data), len(pk) // 16, 1, 0)
        g[0x36:0x40] = bytes(pal + [0xFF] * (10 - len(pal)))
        table += g
        data += pk
    out = bytearray(0x20)
    out[0:4] = b"NUDP"
    out[8:12] = bytes((3, 0x51, len(batches), 0))
    out += table
    out += bytes(area_at - len(out)) + area
    out += bytes(data_start - len(out))
    out += data
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out), len(batches)


def build_mif(template, ngroups):
    """MIF block for ngroups groups: template entry 0 for every group, one name each."""
    _, eo, o2, o3 = struct.unpack_from("<4I", template, 0x10)
    entry = template[eo:eo + 0xC0]
    names = bytearray(struct.pack("<I", ngroups))
    offs = []
    for i in range(ngroups):
        offs.append(len(names))
        names += f"t3_{i:03d}_O_OBJ".encode() + b"\0"
    while len(names) % 16:
        names += b"\0"
    new_o2 = eo + 0xC0 * ngroups
    out = bytearray(template[:eo])
    struct.pack_into("<4I", out, 0x10, ngroups, eo, new_o2, new_o2 + len(names))
    for i in range(ngroups):
        e = bytearray(entry)
        struct.pack_into("<I", e, 0, offs[i])
        out += e
    return bytes(out + names + template[o3:])


BODY_CENTRE = (0.0, 1150.0, 0.0)          # pelvis height of the T5 bind pose
BODY_SCALE = 0.02


def hide_body(block):
    """Shrink the bare body mesh (block 5) to 2 % around the pelvis, hidden inside the new model.
    (Collapsing it to one point made VU1 programs hang on the degenerate triangles.)"""
    b = bytearray(block)
    for g in groups(block):
        for bt in g["batches"]:
            p, end = bt["offset"], bt["offset"] + bt["qwc"] * 16
            cl, wl = 1, 1
            while p + 4 <= end:
                w, = struct.unpack_from("<I", b, p)
                cmd, num, imm = (w >> 24) & 0x7F, (w >> 16) & 0xFF, w & 0xFFFF
                if cmd >= 0x60:
                    vn, vl = (cmd >> 2) & 3, cmd & 3
                    comp, size = vn + 1, [32, 16, 8, 5][vl]
                    nn = num or 256
                    reads = nn if cl >= wl else (nn // wl) * cl + min(nn % wl, cl)
                    nbytes = ((size * comp * reads + 31) // 32) * 4
                    if (comp, size) == (3, 32) and (imm & 0x3FF) == 1 and reads:
                        for i in range(reads):
                            q = p + 4 + 12 * i
                            pos = struct.unpack_from("<3f", b, q)
                            struct.pack_into("<3f", b, q, *(c + (x - c) * BODY_SCALE for x, c in zip(pos, BODY_CENTRE)))
                    p += 4 + nbytes
                    continue
                p += 4
                if cmd == 0x01:
                    cl, wl = imm & 0xFF, imm >> 8
                elif cmd == 0x20:
                    p += 4
                elif cmd in (0x30, 0x31):
                    p += 16
    return bytes(b)


def build_costume(m, template_path, out_path):
    d = open(template_path, "rb").read()
    blocks = [d[o:o + s] for o, s in container(d)]
    blocks[3], W5 = fit_skeleton(d, m)          # the T3 character's own proportions
    tris = outward(convert_mesh(m, W5), W5)
    tris = [t for t in tris if not (page_of(t[1][0]) & 0x60)]     # semi-transparent effect planes
    texs, where = textures(tris, vram(m))
    blocks[1], tex_ids = build_tim2(blocks[1], texs)
    blocks[2], ng = build_nudp(tris, where, tex_ids, blocks[2])
    blocks[4] = build_mif(blocks[4], ng)
    blocks[5] = hide_body(blocks[5])
    n = len(blocks)
    off = (4 + 8 * n + 15) // 16 * 16
    head = bytearray(struct.pack("<I", n))
    body = bytearray()
    for blk in blocks:
        head += struct.pack("<II", off + len(body), len(blk))
        body += blk
        while len(body) % 16:
            body += b"\0"
    out = bytes(head) + bytes(off - len(head)) + bytes(body)
    Path(out_path).write_bytes(out)
    return len(out), len(tris), len(texs), ng


if __name__ == "__main__":
    size, nt, ntex, ng = build_costume(int(sys.argv[1]), sys.argv[2], sys.argv[3])
    print(f"{sys.argv[3]}: {size} bytes, {nt} triangles, {ntex} textures, {ng} groups")
