"""Tekken 3 attacks in a Tekken 5 moveset (Tekken5-Tekken3-Merge, step 1 of the moveset port).

The template moveset (Paul's COM + animation bank) stays the base: movement, reactions, throws.
Every template cancel (plain list or group list) whose command equals a command of the T3
character's standing cancel list (T3 move 0) and leads to an attack is redirected to a clone of
the template attack with the T3 move's animation (retargeted, t3_anim_to_t5), damage (T3 move
+0x14) and active frames (+0x2D / +0x2E). Commands: T3 bits 0-3 buttons, bits 5-13 directions
(>> 4 = T5 direction, 0x20 = neutral, 0 = any); T5 command = direction | buttons << 16 | flags << 24.

    python t3_moveset_to_t5.py <t3 model> <costume model file> <out dir> [template slot]
"""
import math
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t3_anim_to_t5 as conv  # noqa: E402
import t5_bank  # noqa: E402
from lzpack import pack as lz_pack  # noqa: E402
from t3_moves import Moveset  # noqa: E402
from t3_reactions import Mapper, normal_hit, t3_reaction  # noqa: E402
from t5_anim import scale_floats  # noqa: E402
from t5_com import CANCEL, HITCOND, Com  # noqa: E402
from t3_model import f  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def template_files(slot):
    """(moveset, animation bank) of a template slot: sub-files 0 (LZ) and 1."""
    i = 230 + 11 * slot
    return ROOT / f"merge/extracted/tk5data1_lz/{i:04d}.bin", ROOT / f"merge/extracted/tk5data1/{i + 1:04d}.bin"


def t5_key(t3cmd):
    """(direction mask, buttons) of a T3 command in T5 terms. Both use the same direction bits
    (T3 >> 4): 0x20 = neutral, 0 = any direction."""
    return (t3cmd >> 4) & 0x3FE, t3cmd & 0xF


REQ_END = 0x141                                        # T5 requirement list end
# T3 cancel conditions that mean "always": 0, and 107 (all 90 cond-107 standing entries of the 15
# characters in both games have an unconditional T5 counterpart; used on 1+2, 3+4, d/f+1+2 ...)
FREE = (0, 107)
LEVEL = {1: 1, 2: 2, 3: 4, 4: 5, 6: 7}                # T3 hit level byte -> T5 (T5 has a 3)


def t5_hitlevel(t3):
    """T3 move word 2 (hit level: byte 1 level, byte 0 and bits 16+ flags) in T5 terms."""
    lv = (t3 >> 8) & 0xFF
    return (t3 & ~0xFF00) | LEVEL.get(lv, lv) << 8


# T3 cancel requirement -> T5 requirement condition, learned like the reactions (same command in
# the 15 characters of both games): 36 -> 55, 37/38 (side variants) -> 63/64, 48 -> 50
REQ_T3_T5 = {36: 55, 37: 63, 38: 64, 48: 50}


def t3_req_variants(ms, state=0):
    """{(dirs, buttons, T5 requirement condition): (own T3 move, damage)} of a T3 move's
    requirement-bound attacks with a known T5 requirement."""
    out = {}
    for _, e in ms.cancels(ms.own, ms.own.move(state)[3]):
        cmd, cond, req, _, tgt, *_ = e
        if cmd >= 0xC000 or cond not in FREE or req not in REQ_T3_T5 or not cmd & 0xF:
            continue
        pk, idx = ms.resolve(tgt)
        if pk is not ms.own or idx >= pk.count:
            continue
        dmg = pk.move(idx)[5] & 0xFFFF
        if pk.move_bytes(idx)[0x2D] and not dmg & 0x4000:
            out.setdefault(t5_key(cmd) + (REQ_T3_T5[req],), (idx, dmg))
    return out


def t3_attacks(ms, state=0):
    """{(dirs, buttons): own T3 move} from a T3 move's cancel list (default: standing; first
    entry wins)."""
    out = {}
    w = ms.own.move(state)
    for _, e in ms.cancels(ms.own, w[3]):
        cmd, cond, req, _, tgt, *_ = e
        if cmd >= 0xC000 or cond not in FREE or not cmd & 0xF:
            continue
        pk, idx = ms.resolve(tgt)
        if pk is not ms.own or idx >= pk.count:
            continue
        mv = pk.move(idx)
        dmg = mv[5] & 0xFFFF
        a0 = pk.move_bytes(idx)[0x2D]
        if not a0 or dmg & 0x4000:                    # no attack, or a throw (needs the
            continue                                  # opponent's animations: later)
        out.setdefault(t5_key(cmd), (idx, dmg))
    return out


# T5 state moves that may be paired with the T3 state of the same command (checked by name: the
# same direction means a sidestep in T5 but a jump in T3, turns and crouch-to-stand differ too)
PAIRABLE = re.compile(r"^(sJUMP_0[0E][_FB]|sWALK_00[FB](Lp)?|Pl_sDASHF(Lp)?|sDASH_00B(Lp)?|"
                      r"sSTEP_00B(Lp)?|sRUN__00F|st2cr_00[FB]?|Pl_st2cr00_|Pl_cWALKF|cWALK_00B)$")
def t3_win_poses(ms, skel):
    """T3 win poses: among the last 40 own moves those not reachable from standing, >= 90
    frames, vuln 0x842, that end standing upright (pelvis >= 90 % of the standing height) and
    never jump (<= 130 %). Checked on Ogre (preview: arms raised / roaring), Gon, Dr. B (rising
    from a crouch)."""
    p = ms.own
    seen, queue = {0}, [0]
    while queue:
        i = queue.pop()
        nxt = [ms.resolve(e[4]) for _, e in ms.cancels(p, p.move(i)[3])]
        nxt.append((p, p.move(i)[4] & 0xFFFF))
        for pk, idx in nxt:
            if pk is p and idx < p.count and idx not in seen:
                seen.add(idx)
                queue.append(idx)
    stand = conv.pelvis_height(ms, 0, skel, 0)
    out = []
    for i in range(max(0, p.count - 40), p.count):
        n = p.anim_frames(i, ms.common)
        if i in seen or p.move(i)[1] != 0x842 or n < 90:
            continue
        h = [conv.pelvis_height(ms, i, skel, fr) for fr in list(range(0, n, 6)) + [n - 1]]
        if h[-1] >= 0.9 * stand and max(h) <= 1.3 * stand:
            out.append(i)
    return out


T3_SPECIAL = {0x8001: 0xC001, 0x8002: 0xC002}           # T5 -> T3: dash forward / back


def t3_state_moves(ms, state):
    """{T5 command: own T3 move} of a T3 move's button-less entries (directions, dashes)."""
    out = {}
    for _, e in ms.cancels(ms.own, ms.own.move(state)[3]):
        cmd, cond, req, _, tgt, *_ = e
        if cond or req or (cmd < 0xC000 and cmd & 0xF):
            continue
        if cmd >= 0xC000:
            key = next((k for k, v in T3_SPECIAL.items() if v == cmd), None)
        else:
            key = t5_key(cmd)[0]
        pk, idx = ms.resolve(tgt)
        if (key is not None and pk is ms.own and 0 < idx < pk.count
                and not pk.move_bytes(idx)[0x2D]):
            out.setdefault(key, idx)
    return out


def t3_motions(ms):
    """{direction mask: own T3 move} of the standing list's direction-only entries (walk,
    crouch, jumps)."""
    out = {}
    w = ms.own.move(0)
    for _, e in ms.cancels(ms.own, w[3]):
        cmd, cond, req, _, tgt, *_ = e
        if cmd >= 0xC000 or cond or req or cmd & 0xF or not cmd & 0x10:
            continue
        pk, idx = ms.resolve(tgt)
        if pk is ms.own and idx < pk.count:
            out.setdefault(t5_key(cmd)[0], idx)
    return out


def leg_length(skel):
    """Thigh + shin of a T5 skeleton (nodes 15, 16)."""
    _, tr, _ = skel
    return sum(math.sqrt(sum(x * x for x in tr[n])) for n in (15, 16))


COMMON_BANK = ROOT / "merge/extracted/tk5data1/0018.bin"   # the 0x8000 + k animations


def scale_to_body(m, costume, template_slot, com, anims, n_tpl, t3_anim):
    """Root and pelvis positions (float bones 0, 1) fitted to the character's size, as T3 does it:
    T3 scales the root position by the 3DMK size (FUN_80035bc0 -> player +0x4EE, FUN_80038970;
    Gon 45 %, Dr. B 90 %, Ogre 105 %). Template and common-bank animations scale by leg length
    (character / template skeleton); common ones are copied into the own bank for that. Throw
    victim moves (`*_y`) play on the opponent and keep their animations."""
    size, = struct.unpack_from("<I", f(0x5F + 4 * m), 4)
    tpl_skel = conv.skeleton_of((ROOT / f"merge/extracted/tk5data1/{230 + 11 * template_slot + 10:04d}.bin").read_bytes())
    tpl_scale = leg_length(conv.skeleton_of(Path(costume).read_bytes())) / leg_length(tpl_skel)
    print(f"body scale: T3 size {size} %, template animations x{tpl_scale:.3f}")
    if abs(tpl_scale - 1) < 1e-3 and size == 100:
        return anims
    n = len(com.lists["move"])
    victim = {com.move(i)["anim"] for i in range(n) if com.name(com.move(i)["name"]).endswith("_y")}
    own = {i for (_, v), i in t3_anim.items() if i is not None and not v}
    out = []
    for i, a in enumerate(anims):
        s = 1.0 if 0x4000 + i in victim else tpl_scale if i < n_tpl else size / 100 if i in own else 1.0
        out.append(scale_floats(a, s) if a and abs(s - 1) > 1e-3 else a)
    common = t5_bank_anims(COMMON_BANK.read_bytes())
    copied = {}
    for i in range(n):
        mv = com.move(i)
        a = mv["anim"]
        # 0x8000 = motOrigin: the engine treats it specially (redirected, the fight hung on loading)
        if a <= 0x8000 or a in victim or not common[a - 0x8000]:
            continue
        if a not in copied:
            copied[a] = 0x4000 + len(out)
            out.append(scale_floats(common[a - 0x8000], tpl_scale))
        mv["anim"] = copied[a]
        com.lists["move"][i] = com.pack_move(mv)
    print(f"  common animations copied and scaled: {len(copied)}")
    return out


def t5_bank_anims(data):
    """Animations of a bare bank (no container)."""
    from t5_anim import bank
    return bank(data)[1]


def build(m, costume, out_dir, template_slot=0):
    ms = Moveset(m)
    attacks = t3_attacks(ms)
    variants = t3_req_variants(ms)
    tcom, tbank = template_files(template_slot)
    com = Com(tcom.read_bytes())
    bank_tpl = tbank.read_bytes()
    _, _, anims = t5_bank.read(bank_tpl)
    anims = list(anims)
    n_tpl = len(anims)
    skel = conv.skeleton_of(Path(costume).read_bytes())
    victim_skel = conv.skeleton_of((ROOT / "merge/extracted/tk5data1/0240.bin").read_bytes())
    reactions = Mapper(com)
    clones = {}                                       # (template move, T3 move) -> new move
    t3_anim = {}                                      # T3 move -> bank index

    def own_anim(t3idx, victim=False):
        """Bank animation id of T3 move t3idx (None: common-pack animation, not converted).
        Throw victims are retargeted to a standard T5 skeleton (Paul's): any character."""
        key = (t3idx, victim)
        if key not in t3_anim:
            a = conv.convert(m, t3idx, victim_skel if victim else skel)
            if a is None:
                t3_anim[key] = None
            else:
                t3_anim[key] = len(anims)
                anims.append(a)
        return None if t3_anim[key] is None else 0x4000 + t3_anim[key]

    def set_anim(mi, t3idx):
        mv = com.move(mi)
        a = own_anim(t3idx)
        if a is not None:
            mv["anim"] = a
            com.lists["move"][mi] = com.pack_move(mv)

    tmpl_of = {}                                      # T5 key -> template attack move

    def t3_attack(tgt):
        """(own T3 move, damage) of a cancel target if it is a plain attack, else None."""
        pk, idx = ms.resolve(tgt)
        if pk is not ms.own or idx >= pk.count:
            return None
        dmg = pk.move(idx)[5] & 0xFFFF
        if not pk.move_bytes(idx)[0x2D] or dmg & 0x4000:
            return None
        return idx, dmg

    def copy_hitconds(h, dmg, rea_t3=None):
        """Copy the template's hit condition list (entries up to the one whose requirement list
        is empty = always, first value 0x141) with the T3 damage; conditional entries (counter
        hit etc.) keep their ratio to the last entry."""
        H, R = com.lists["hitcond"], com.lists["requirement"]
        seq = []
        while True:
            e = struct.unpack(HITCOND, H[h + len(seq)])
            seq.append(e)
            if struct.unpack_from("<H", R[e[0]])[0] == REQ_END or len(seq) > 8:
                break
        base = seq[-1][1] or 1
        if rea_t3 is not None:                        # T3 reaction of the normal hit
            r = reactions(rea_t3)
            if r is not None:
                seq[-1] = (seq[-1][0], seq[-1][1], r)
        start = len(H)
        for rq, d, rea in seq:
            H.append(struct.pack(HITCOND, rq, max(1, round(dmg * d / base)) if dmg else 0, rea))
        return start

    def clone(tmove, t3idx, dmg):
        """New move = template attack `tmove` with T3 move `t3idx` (animation, damage, active
        frames, follow-ups from its T3 cancel list)."""
        key = (tmove, t3idx)
        if key in clones:
            return clones[key]
        mv = com.move(tmove)
        b = ms.own.move_bytes(t3idx)
        a = own_anim(t3idx)
        if a is not None:
            mv["anim"] = a
        mv["active_start"], mv["active_end"] = b[0x2D], b[0x2E]
        w = ms.own.move(t3idx)
        mv["vuln"], mv["hitlevel"] = w[1], t5_hitlevel(w[2])
        if mv["hitcond"] < len(com.lists["hitcond"]):
            mv["hitcond"] = copy_hitconds(mv["hitcond"], dmg, t3_reaction(ms, t3idx))
        new = com.add("move", com.pack_move(mv))     # reserved first: strings can loop
        clones[key] = new
        # follow-ups: T3 cancels with buttons -> T5 string entries (flag 0x20, extradata 9 as
        # the template's strings); template entries without buttons and its end entry stay
        entries = []
        for _, e in ms.cancels(ms.own, ms.own.move(t3idx)[3]):
            cmd, cond, req, _, tgt, _, fr0, fr1, st = e
            if cmd >= 0xC000 or cond not in FREE or req or not cmd & 0xF:
                continue
            a = t3_attack(tgt)
            if a is None:
                continue
            k = t5_key(cmd)
            child = clone(tmpl_of.get(k, tmove), *a)
            entries.append(struct.pack(CANCEL, k[0] | k[1] << 16 | 0x20 << 24, 0, child, 9,
                                       fr0, fr1, st, 0))
        length = ms.own.anim_frames(t3idx, ms.common)
        for e in com.lists["cancel"][mv["cancel"]:]:
            f = list(struct.unpack(CANCEL, e))
            if f[0] == 0x8000:
                f[4] = f[6] = length
                entries.append(struct.pack(CANCEL, *f))
                break
            if not (f[0] >> 16) & 0xFF:
                entries.append(e)
        start = len(com.lists["cancel"])
        com.lists["cancel"].extend(entries)
        mv["cancel"] = start
        com.lists["move"][new] = com.pack_move(mv)
        return new

    redirected = 0
    n_template = len(com.lists["move"])

    def keep(mvi):
        """Template attacks that stay: generic context moves (Co_: getup kicks, back turned,
        running, sidestep; jump attacks excepted, T3 has its own) and throws."""
        nm = com.name(com.move(mvi)["name"])
        return (nm.startswith("Co_") and "jp" not in nm) or nm.startswith("Thr")

    # standing (alias 1): T3 move 0; its direction-only cancels (walk, crouch, jump) too
    aliases = struct.unpack_from("<36I", com.head, 0x18)
    stand = aliases[1]
    set_anim(stand, 0)
    motions = t3_motions(ms)
    moved = 0
    for e in com.lists["cancel"][com.move(stand)["cancel"]:]:
        cmd, _, mvi, *_ = struct.unpack(CANCEL, e)
        if cmd == 0x8000:
            break
        if cmd >= 0x10000 or cmd >= 0x8000 or mvi >= n_template:
            continue
        if cmd in motions and not com.move(mvi)["active_start"]:
            set_anim(mvi, motions[cmd])
            moved += 1
    for lst in ("cancel", "group_cancel"):
        for i, e in enumerate(com.lists[lst]):
            f = list(struct.unpack(CANCEL, e))
            cmd, mvi = f[0], f[2]
            if 0x8000 <= cmd < 0x10000 or mvi >= n_template:
                continue
            key = (cmd & 0xFFFF, (cmd >> 16) & 0xFF)
            if key[0] == 0 and key not in attacks:      # T5 "any": T3 neutral attack
                key = (0x20, key[1])
            rc = struct.unpack_from("<H", com.lists["requirement"][f[1]])[0]
            variant = variants.get(key + (rc,))
            if (key not in attacks and variant is None) or not com.move(mvi)["active_start"]                     or keep(mvi):
                continue
            t3idx, dmg = variant or attacks[key]
            tmpl_of.setdefault(key, mvi)
            f[2] = clone(mvi, t3idx, dmg)
            com.lists[lst][i] = struct.pack(CANCEL, *f)
            redirected += 1
    # states: pairs (T5 state move, T3 state move) reached by the same button-less command
    # (direction, dash) from standing; each paired T5 state gets its own cancel list (groups
    # inlined) whose button entries lead to the T3 state's attacks
    def inline(start):
        out = []
        for e in com.lists["cancel"][start:]:
            f = struct.unpack(CANCEL, e)
            if f[0] == 0x8005:
                g = f[2]
                while True:
                    ge = com.lists["group_cancel"][g]
                    gf = struct.unpack(CANCEL, ge)
                    if gf[0] == 0x8006:
                        break
                    out.append(ge)
                    g += 1
                continue
            out.append(e)
            if f[0] == 0x8000:
                return out
        return out

    pairs = {stand: 0}
    queue = [stand]
    n_states = 0
    while queue:
        j = queue.pop(0)
        st3 = pairs[j]
        local = t3_attacks(ms, st3)
        follow = t3_state_moves(ms, st3)
        entries = []
        for e in inline(com.move(j)["cancel"]):
            f = list(struct.unpack(CANCEL, e))
            cmd, mvi = f[0], f[2]
            if f[0] == 0x8000 or (0x8000 <= cmd < 0x10000 and cmd not in T3_SPECIAL):
                entries.append(e)
                continue
            btn = (cmd >> 16) & 0xFF
            if mvi < n_template and not btn:
                k = cmd if cmd in T3_SPECIAL else cmd & 0xFFFF
                if (k in follow and mvi not in pairs and not com.move(mvi)["active_start"]
                        and PAIRABLE.match(com.name(com.move(mvi)["name"]))):
                    pairs[mvi] = follow[k]
                    queue.append(mvi)
            elif mvi < n_template and com.move(mvi)["active_start"] and not keep(mvi):
                key = (cmd & 0xFFFF, btn)
                if key[0] == 0 and key not in local:
                    key = (0x20, btn)
                if key in local:
                    f[2] = clone(mvi, *local[key])
            entries.append(struct.pack(CANCEL, *f))
        mv = com.move(j)
        mv["cancel"] = len(com.lists["cancel"])
        com.lists["cancel"].extend(entries)
        com.lists["move"][j] = com.pack_move(mv)
        if j != stand:
            set_anim(j, st3)
        n_states += 1

    # throws: T5 attempt (1+3 / 2+4) -> executions by side requirement (same ids as T3's:
    # 2 front, 3 back, 4/5 sides, parameter 1536); execution = thrower move `*_n` whose hit
    # reaction sends the opponent to the victim move `*_y`. T3: execution N, victim N+1.
    def copy_cancels(start, length):
        out = []
        for e in com.lists["cancel"][start:]:
            f = list(struct.unpack(CANCEL, e))
            if f[0] == 0x8000:
                f[4] = f[6] = length
                out.append(struct.pack(CANCEL, *f))
                break
            out.append(e)
        i = len(com.lists["cancel"])
        com.lists["cancel"].extend(out)
        return i

    def t3_throw_map(buttons):
        """{side requirement: T3 execution} of the standing list's throw on `buttons`."""
        for _, e in ms.cancels(ms.own, ms.own.move(0)[3]):
            cmd, cond, *_ = e
            if cmd >= 0xC000 or cond or cmd & 0xF != buttons:
                continue
            pk, idx = ms.resolve(e[4])
            if pk is not ms.own or idx >= pk.count or not ms.own.move(idx)[5] & 0x4000:
                continue
            out = {}
            for _, t in ms.cancels(ms.own, ms.own.move(idx)[3]):
                pk2, ex = ms.resolve(t[4])
                if pk2 is ms.own and ex + 1 < pk2.count:
                    out.setdefault(t[2], ex)
            return out
        return {}

    thrown = {}

    def throw_exec(x, ex):
        if (x, ex) in thrown:
            return thrown[(x, ex)]
        H = com.lists["hitcond"]
        mv = com.move(x)
        a, av = own_anim(ex), own_anim(ex + 1, victim=True)
        if a is None or av is None:
            thrown[(x, ex)] = x
            return x
        hn = normal_hit(com, mv["hitcond"])
        rq, dm, rea = struct.unpack(HITCOND, H[hn])
        r = bytearray(com.lists["reactions"][rea])
        ymoves = struct.unpack_from("<14H", r, 52)
        y = next((v for v in ymoves if v < n_template), None)
        if y is None:
            thrown[(x, ex)] = x
            return x
        length = ms.own.anim_frames(ex, ms.common)
        vm = com.move(y)
        vm["anim"] = av
        vm["cancel"] = copy_cancels(vm["cancel"], ms.own.anim_frames(ex + 1, ms.common))
        y2 = com.add("move", com.pack_move(vm))
        struct.pack_into("<14H", r, 52, *[y2 if v == y else v for v in ymoves])
        rea2 = com.add("reactions", bytes(r))
        dmg = ms.own.move(ex)[5] & 0xFFFF
        h0 = len(H)
        for k in range(mv["hitcond"], hn + 1):
            rq_, dm_, re_ = struct.unpack(HITCOND, H[k])
            H.append(struct.pack(HITCOND, rq_, dmg or dm_, rea2 if k == hn else re_))
        mv["anim"] = a
        mv["hitcond"] = h0
        mv["cancel"] = copy_cancels(mv["cancel"], length)
        thrown[(x, ex)] = com.add("move", com.pack_move(mv))
        return thrown[(x, ex)]

    n_throws = 0
    seen_attempts = set()
    for lst in ("cancel", "group_cancel"):
        for e in com.lists[lst]:
            cmd, _, mvi, *_ = struct.unpack(CANCEL, e)
            btn = (cmd >> 16) & 0xFF
            if 0x8000 <= cmd < 0x10000 or btn not in (5, 10) or mvi >= n_template:
                continue
            if not com.name(com.move(mvi)["name"]).startswith("Thr") or mvi in seen_attempts:
                continue
            seen_attempts.add(mvi)
            sides = t3_throw_map(btn)
            st = com.move(mvi)["cancel"]
            for i in range(st, len(com.lists["cancel"])):
                f = list(struct.unpack(CANCEL, com.lists["cancel"][i]))
                if f[0] == 0x8000:
                    break
                side = struct.unpack_from("<H", com.lists["requirement"][f[1]])[0]
                if side in sides and f[2] < n_template:
                    f[2] = throw_exec(f[2], sides[side])
                    com.lists["cancel"][i] = struct.pack(CANCEL, *f)
                    n_throws += 1

    # win poses (template moves *_Win_A..E, *_Win_Round) -> T3 win poses; intros stay
    wins = t3_win_poses(ms, skel)
    n_wins = 0
    if wins:
        slots = [i for i in range(n_template)
                 if re.search(r"_Win_([A-E]|Round)$", com.name(com.move(i)["name"]))]
        for k, mi in enumerate(slots):
            t3 = wins[k % len(wins)]
            a = own_anim(t3)
            if a is None:
                continue
            mv = com.move(mi)
            mv["anim"] = a
            mv["cancel"] = copy_cancels(mv["cancel"], ms.own.anim_frames(t3, ms.common))
            com.lists["move"][mi] = com.pack_move(mv)
            n_wins += 1

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "states.txt", "w", encoding="utf-8") as fh:
        for j, st3 in pairs.items():
            fh.write(f"{j} {com.name(com.move(j)['name'])} = T3-{st3}\n")
    with open(out / "clones.txt", "w", encoding="utf-8") as fh:
        for (tm, t3), new in sorted(clones.items(), key=lambda kv: kv[1]):
            fh.write(f"{new} T3-{t3} ({com.name(com.move(tm)['name'])})\n")
    anims = scale_to_body(m, costume, template_slot, com, anims, n_tpl, t3_anim)
    (out / "moveset.bin").write_bytes(lz_pack(com.build()))
    (out / "bank.bin").write_bytes(t5_bank.build(bank_tpl, anims))
    print(f"T3 attacks {len(attacks)}, new moves {len(clones)}, new animations {len(t3_anim)}, "
          f"redirected cancels {redirected}, motions {moved}, throw sides {n_throws}, states {n_states}, "
          f"win poses {n_wins} from T3 {wins}")
    for k, v in sorted(attacks.items()):
        print("  ", k, "-> T3 move", v)


if __name__ == "__main__":
    build(int(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 0)
