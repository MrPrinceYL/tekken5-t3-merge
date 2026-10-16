"""Tekken 5 animation bank files (moveset sub-file 1/3/5; Tekken5-Tekken3-Merge): container of 6
blocks, block 0 = bank (u8 0x64, u8 0, u16 count, u16 23, u16 descriptor[23], u32 offset[count]
from the bank start, 2-byte aligned animations; offset 0 = none). Blocks are 4-byte aligned.
"""
import struct

from t5_anim import bank


def read(data):
    n, = struct.unpack_from("<I", data, 0)
    blocks = [data[o:o + s] for o, s in (struct.unpack_from("<II", data, 4 + 8 * i) for i in range(n))]
    desc, anims = bank(blocks[0])
    return blocks, desc, anims


def build_bank(desc, anims):
    head = struct.pack("<BBHH", 0x64, 0, len(anims), len(desc)) + struct.pack(f"<{len(desc)}H", *desc)
    off = len(head) + 4 * len(anims)
    body, offs, seen = bytearray(), [], {}
    for a in anims:
        if not a:
            offs.append(0)
            continue
        if a in seen:
            offs.append(seen[a])
            continue
        while (off + len(body)) % 2:
            body += b"\0"
        seen[a] = off + len(body)
        offs.append(seen[a])
        body += a
    return head + struct.pack(f"<{len(offs)}I", *offs) + bytes(body)


def build(template, anims):
    """Container like `template` with block 0 rebuilt from `anims` (list of animation bytes)."""
    blocks, desc, _ = read(template)
    blocks[0] = build_bank(desc, anims)
    n = len(blocks)
    off = (4 + 8 * n + 15) // 16 * 16
    head = bytearray(struct.pack("<I", n))
    body = bytearray()
    for b in blocks:
        while (off + len(body)) % 4:
            body += b"\0"
        head += struct.pack("<II", off + len(body), len(b))
        body += b
    return bytes(head) + bytes(off - len(head)) + bytes(body)
