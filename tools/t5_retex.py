"""Give a built costume file (t5_costume.py) texture ids of its own (Tekken5-Tekken3-Merge).

build_tim2 reuses the ids (GIDX) of the template's dropped costume textures; a real template
player (Paul costume 1, Jack-5 ...) in the same fight loads its textures under the same ids and
ours show its pictures. Texture ids come in blocks of 768 per costume file; blocks no original
file uses are free. Our pictures (after the template's last 8x2 palette strip) get ids
base, base + 1, ...; the mesh's render-state words 0x1040_0000 | id follow.

    python t5_retex.py <model.bin> <block>      # in place
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from t5_costume import container, gidx, GIDX_AT  # noqa: E402

# 768-id blocks used by no original costume file (all 80 slots' sub-file 10)
FREE_BLOCKS = [18, 19, 38, 39, 62, 63, 67, 68, 69, 70, 71, 72, 73, 75, 79]


def pictures(tim):
    cnt, = struct.unpack_from("<H", tim, 6)
    p, out = 16, []
    for _ in range(cnt):
        tot, = struct.unpack_from("<I", tim, p)
        w, h = struct.unpack_from("<HH", tim, p + 0x14)
        out.append((p, (w, h) == (8, 2)))
        p += tot
    return out


def retex(data, block):
    blocks = [bytearray(data[o:o + s]) for o, s in container(data)]
    tim = blocks[1]
    pics = pictures(tim)
    last_strip = max(i for i, (_, strip) in enumerate(pics) if strip)
    remap = {}
    for k, (p, _) in enumerate(pics[last_strip + 1:]):
        old = gidx(tim[p:p + 0x50])
        new = block * 768 + k
        remap[old] = new
        struct.pack_into("<H", tim, p + GIDX_AT, new)
    nudp = blocks[2]
    n = 0
    for o in range(0, len(nudp) - 3, 4):
        v, = struct.unpack_from("<I", nudp, o)
        if v >> 16 == 0x1040 and (v & 0xFFFF) in remap:
            struct.pack_into("<I", nudp, o, 0x10400000 | remap[v & 0xFFFF])
            n += 1
    # the container exactly as before: same offsets, the blocks keep their sizes
    out = bytearray(data)
    for (o, s), b in zip(container(data), blocks):
        assert len(b) == s
        out[o:o + s] = b
    return bytes(out), len(remap), n


if __name__ == "__main__":
    path, block = sys.argv[1], int(sys.argv[2])
    out, pics, words = retex(Path(path).read_bytes(), block)
    Path(path).write_bytes(out)
    print(f"{path}: {pics} textures -> ids {block * 768}.., {words} render words")
