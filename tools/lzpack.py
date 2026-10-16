"""Namco LZ packer, the inverse of tk5data.lz_decompress (flag byte, bits LSB-first below a
sentinel bit, 1 = literal, 0 = big-endian u16 back-reference: 11-bit distance (0 = 0x800),
5-bit length (0 = 32); a zero flag byte ends the stream). Greedy matching with a hash chain.
"""
import sys


def pack(data):
    out = bytearray()
    n = len(data)
    head = {}
    i = 0
    items = []                                    # (is_literal, payload bytes)

    def flush():
        if not items:
            return
        flag = 1 << len(items)
        for k, (lit, _) in enumerate(items):
            if lit:
                flag |= 1 << k
        out.append(flag)
        for _, p in items:
            out.extend(p)
        items.clear()

    while i < n:
        best_len, best_dist = 0, 0
        if i + 3 <= n:
            key = bytes(data[i:i + 3])
            for j in reversed(head.get(key, [])[-48:]):
                dist = i - j
                if dist > 0x800:
                    break
                ln = 0
                while ln < 32 and i + ln < n and data[j + ln] == data[i + ln]:
                    ln += 1
                if ln > best_len:
                    best_len, best_dist = ln, dist
                    if ln == 32:
                        break
        if best_len >= 3:
            v = ((best_len & 31) << 11) | (best_dist & 0x7FF)
            items.append((False, bytes(((v >> 8) & 0xFF, v & 0xFF))))
            step = best_len
        else:
            items.append((True, bytes((data[i],))))
            step = 1
        for k in range(i, min(i + step, n - 2)):
            head.setdefault(bytes(data[k:k + 3]), []).append(k)
        i += step
        if len(items) == 7:
            flush()
    flush()
    out.append(0)
    return bytes(out)


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    from tk5data import lz_decompress
    d = open(sys.argv[1], "rb").read()
    p = pack(d)
    back, _ = lz_decompress(p)
    print(len(d), "->", len(p), "roundtrip", back == d)
