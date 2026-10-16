"""Tables of contents of TK5DATA0.BIN / TK5DATA1.BIN (Tekken5-Tekken3-Merge groundwork).

The game looks files up by index (FUN_0023fd08 -> FUN_0023f378 / FUN_0023fcb0): a table of
(sector, size) pairs in the main program, TK5DATA1 at 0x0046B730, TK5DATA0 at 0x0046E848.
Writes merge/tk5data<n>_toc.csv: index, sector, size, first 16 bytes.

    python t5_archives.py [iso] [main.elf]
"""
import csv, struct, sys
from pathlib import Path

ISO = sys.argv[1] if len(sys.argv) > 1 else r"E:/Decompilation/Game/Tekken 5 (USA).iso"
ELF = sys.argv[2] if len(sys.argv) > 2 else r"E:/Decompilation/Decomps/Tekken5/extracted/elf/main.elf"
OUT = Path(__file__).resolve().parent.parent / "merge"
# name, LBA, archive size, TOC address, TOC end (None: until an entry leaves the archive)
ARCHIVES = [("tk5data1", 1219338, 1297731584, 0x46B730, 0x46E848),
            ("tk5data0", 207333, 2072586240, 0x46E848, None)]

elf = Path(ELF).read_bytes()
phoff, = struct.unpack_from("<I", elf, 0x1C)
phnum, = struct.unpack_from("<H", elf, 0x2C)
segs = [struct.unpack_from("<8I", elf, phoff + i * 32) for i in range(phnum)]


def read(va, n):
    for _, off, sva, _, fsz, *_ in segs:
        if sva <= va < sva + fsz:
            return elf[off + va - sva: off + va - sva + n]
    raise ValueError(hex(va))


OUT.mkdir(exist_ok=True)
with open(ISO, "rb") as iso:
    for name, lba, archive_size, toc, end in ARCHIVES:
        rows = []
        i = 0
        while end is None or toc + i * 8 < end:
            sector, size = struct.unpack("<II", read(toc + i * 8, 8))
            if size != 0xFFFFFFFF and sector * 2048 + size > archive_size:
                if end is None:
                    break
                raise ValueError(f"{name} entry {i} outside the archive")
            if size not in (0, 0xFFFFFFFF):
                iso.seek((lba + sector) * 2048)
                rows.append((i, sector, size, iso.read(16).hex()))
            i += 1
        with open(OUT / f"{name}_toc.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["index", "sector", "size", "head16"])
            w.writerows(rows)
        print(name, len(rows), "files")
