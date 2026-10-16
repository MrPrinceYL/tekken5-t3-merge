"""Decrypt every TK5DATA1.BIN file into merge/extracted/tk5data1/<index>.bin.

The game's loader (FUN_0023f5c0) reads file <i> by the table at 0x0046B730, then
FUN_0023f510 XORs it word by word with a key stream k0 = i, k' = 5k + 3 that restarts at i in
every 2048-byte sector, and checks the 32-bit word sum against the table at 0x0046E9B8.

    python t5_unpack.py [iso] [main.elf]
"""
import struct, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tk5data import lz_decompress

ISO = sys.argv[1] if len(sys.argv) > 1 else r"E:/Decompilation/Game/Tekken 5 (USA).iso"
ELF = sys.argv[2] if len(sys.argv) > 2 else r"E:/Decompilation/Decomps/Tekken5/extracted/elf/main.elf"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "merge" / "extracted" / "tk5data1"
OUT_LZ = ROOT / "merge" / "extracted" / "tk5data1_lz"
LBA, TOC, TOC_END, SUMS = 1219338, 0x46B730, 0x46E848, 0x46E9B8

elf = Path(ELF).read_bytes()
phoff, = struct.unpack_from("<I", elf, 0x1C)
phnum, = struct.unpack_from("<H", elf, 0x2C)
segs = [struct.unpack_from("<8I", elf, phoff + i * 32) for i in range(phnum)]


def read(va, n):
    for _, off, sva, _, fsz, *_ in segs:
        if sva <= va < sva + fsz:
            return elf[off + va - sva: off + va - sva + n]
    raise ValueError(hex(va))


def keystream(i):
    k = np.empty(512, np.uint32)
    v = i & 0xFFFFFFFF
    for n in range(512):
        k[n] = v
        v = (v * 5 + 3) & 0xFFFFFFFF
    return k


def decrypt(i, data):
    words = (len(data) + 3) // 4
    buf = np.frombuffer(data.ljust(words * 4 + (-words * 4) % 2048, b"\0"), np.uint32).copy()
    buf ^= np.tile(keystream(i), len(buf) // 512)
    return buf[:words], buf.tobytes()[:len(data)]


def try_lz(data):
    """The decompressed bytes if the whole file is one LZ stream, else None."""
    try:
        out, end = lz_decompress(data)
    except IndexError:
        return None
    return out if len(data) - 4 <= end <= len(data) and len(out) > len(data) else None


def wordsum(data):
    return int(np.frombuffer(data[: len(data) // 4 * 4], np.uint32).sum(dtype=np.uint64)) & 0xFFFFFFFF


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    OUT_LZ.mkdir(parents=True, exist_ok=True)
    packed = 0
    bad = 0
    count = (TOC_END - TOC) // 8
    with open(ISO, "rb") as iso:
        for i in range(count):
            sector, size = struct.unpack("<II", read(TOC + i * 8, 8))
            if size == 0 or size == 0xFFFFFFFF:
                continue
            iso.seek((LBA + sector) * 2048)
            raw = iso.read(size)
            want, = struct.unpack("<I", read(SUMS + i * 4, 4))
            words, plain = decrypt(i, raw)
            got = int(words[: size // 4].sum(dtype=np.uint64)) & 0xFFFFFFFF
            if got != want and wordsum(raw) == want:
                got, plain = want, raw
            if got != want:
                bad += 1
                print(f"checksum mismatch {i}: {got:08X} != {want:08X}")
            (OUT / f"{i:04d}.bin").write_bytes(plain)
            unpacked = try_lz(plain)
            if unpacked is not None:
                (OUT_LZ / f"{i:04d}.bin").write_bytes(unpacked)
                packed += 1
    print("done,", bad, "checksum mismatches,", packed, "LZ-compressed files")
