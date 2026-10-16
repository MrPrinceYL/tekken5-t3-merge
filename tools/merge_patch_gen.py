"""Derive rows for merge/patches.csv from the original instruction sheet: an instruction keeps its
form, only its 16-bit immediate changes (lui / addiu / slti / lw / sw ...). Prints the rows.

    python merge_patch_gen.py <addr>=<new imm> ...     # e.g. 0x0028F44C=0x12 0x0028F45C=0xa00
"""
import csv
import re
import sys
from pathlib import Path

csv.field_size_limit(1 << 30)
ROOT = Path(__file__).resolve().parent.parent


def fmt(v):
    return f"-0x{-v:x}" if v < 0 else f"0x{v:x}"


def main(args):
    want = {}
    for a in args:
        addr, imm = a.split("=")
        want[int(addr, 16)] = int(imm, 0)
    # the original sheet: the backup of the first patch run, else the current sheet
    for r in csv.DictReader(open(ROOT / "sheets/instructions/main.csv", encoding="utf-8", newline="")):
        a = int(r["addr"], 16)
        if a not in want:
            continue
        word = int.from_bytes(bytes.fromhex(r["bytes"]), "little")
        old = word & 0xFFFF
        old_s = old - 0x10000 if old & 0x8000 else old
        new = want[a]
        nword = (word & 0xFFFF0000) | (new & 0xFFFF)
        nbytes = nword.to_bytes(4, "little").hex().upper()
        asm = r["asm"].lstrip("_")
        op = asm.split()[0]
        # assembler text: the immediate as written (hex, maybe negative or as offset(reg))
        asm2 = re.sub(re.escape(fmt(old_s if op not in ("lui", "ori", "andi", "xori") else old)) + r"(?=\(|$)",
                      fmt(new), asm)
        # p-code constant: C<hex>:<size>; lui puts the immediate unshifted (C48:4 C10:4)
        pc = r["pcode"]
        sizes = re.findall(r"C([0-9a-f]+):(\d)", pc)
        done = False
        for h, sz in sizes:
            v = int(h, 16)
            bits = 8 * int(sz)
            if v in (old, old_s & ((1 << bits) - 1)):
                nv = new & ((1 << bits) - 1) if op not in ("lui",) else new
                if op not in ("lui", "ori", "andi", "xori") and new < 0:
                    nv = new & ((1 << bits) - 1)
                pc = pc.replace(f"C{h}:{sz}", f"C{nv:x}:{sz}", 1)
                done = True
                break
        assert done, (r["addr"], pc)
        assert asm2 != asm or old == new, (r["addr"], asm)
        print(f'main,{r["addr"]},{r["bytes"]},{nbytes},"{asm2}",{pc}')


if __name__ == "__main__":
    main(sys.argv[1:])
