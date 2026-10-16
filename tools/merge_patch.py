"""Apply the merge's code patches (merge/patches.csv) to the instruction sheets.

Every row replaces one instruction: `variant,addr,old_bytes,new_bytes,asm,pcode`. The sheet row
must still hold `old_bytes` (or already `new_bytes`: then nothing changes), so a patch never
lands on the wrong instruction. `delay` is kept from the sheet; for a delay slot the branch row before it is patched as well (its
p-code includes the delay slot's). Afterwards regenerate:
`T5_VARIANTS=main python gen_rust.py`.

    python merge_patch.py
"""
import csv
import io
from pathlib import Path

csv.field_size_limit(1 << 30)
ROOT = Path(__file__).resolve().parent.parent
PATCHES = ROOT / "merge" / "patches.csv"


def main():
    rows = [r for r in csv.DictReader(l for l in open(PATCHES, encoding="utf-8") if not l.startswith("#"))]
    by_variant = {}
    for r in rows:
        by_variant.setdefault(r["variant"], {})[int(r["addr"], 16)] = r
    for variant, patches in by_variant.items():
        path = ROOT / "sheets" / "instructions" / f"{variant}.csv"
        text = open(path, encoding="utf-8", newline="").read()
        reader = csv.DictReader(io.StringIO(text, newline=""))
        fields = reader.fieldnames
        out_rows, done = [], set()
        changed = 0
        for r in reader:
            p = patches.get(int(r["addr"], 16))
            if p:
                done.add(int(r["addr"], 16))
                if r["bytes"].upper() == p["new_bytes"].upper():
                    pass
                elif r["bytes"].upper() == p["old_bytes"].upper():
                    asm = p["asm"]
                    if r["delay"] == "1" and not asm.startswith("_"):
                        asm = "_" + asm
                    if r["delay"] == "1":
                        prev = out_rows[-1]
                        if r["pcode"] not in prev["pcode"]:
                            raise SystemExit(f"{variant} {r['addr']}: delay slot p-code not in branch {prev['addr']}")
                        prev["pcode"] = prev["pcode"].replace(r["pcode"], p["pcode"], 1)
                    r["bytes"], r["asm"], r["pcode"] = p["new_bytes"].upper(), asm, p["pcode"]
                    changed += 1
                else:
                    raise SystemExit(f"{variant} {r['addr']}: sheet has {r['bytes']}, patch expects {p['old_bytes']}")
            out_rows.append(r)
        missing = set(patches) - done
        if missing:
            raise SystemExit(f"{variant}: addresses not in sheet: {sorted(hex(a) for a in missing)}")
        buf = io.StringIO(newline="")
        w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\r\n")
        w.writeheader()
        w.writerows(out_rows)
        tmp = path.with_suffix(".csv.tmp")
        open(tmp, "w", encoding="utf-8", newline="").write(buf.getvalue())
        tmp.replace(path)
        print(f"{variant}: {changed} instructions patched, {len(patches) - changed} already applied")


if __name__ == "__main__":
    main()
