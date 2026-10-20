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
# learned by tools/t3_req_learn.py (21.10.): T3 requirements whose aligned T5 entries have no
# requirement (req 39, 57: 28 / 13 samples)
REQ_NONE = (0, 39, 57)


NUMPAD = {1: 0x2, 2: 0x4, 3: 0x8, 4: 0x10, 5: 0x20, 6: 0x40, 7: 0x80, 8: 0x100, 9: 0x200}


def is_t3_sequence(cmd):
    """T3 input-sequence commands (FUN_8002cc28: tables 0x800954D0 / 0x800955CC)."""
    return 0xC00E <= cmd < 0xC00E + 0x3F or 0xC7FF <= cmd < 0xC7FF + 0x29


def t3_sequence(cmd):
    """(frame window, [u16 inputs]) of a T3 input sequence (FUN_8002ca84: oldest first; low
    nibble = numpad direction, high byte = buttons; the last input is the one that triggers)."""
    from t3_anim import _ram
    base, i = (0x800954D0, cmd - 0xC00E) if cmd < 0xC7FF else (0x800955CC, cmd - 0xC7FF)
    p, = struct.unpack("<I", _ram(base + 4 * i, 4))
    win, = struct.unpack("<h", _ram(p, 2))
    out, q = [], p + 2
    while True:
        v, = struct.unpack("<H", _ram(q, 2))
        if not v:
            return win, out
        out.append(v)
        q += 2


def t3_character(m):
    """T3 character id of model m (table 0x800958C4: four model slots per character, m + 6)."""
    from t3_anim import _ram
    tab = _ram(0x800958C4, 4 * 40)
    return next(c for c in range(40) if m + 6 in tab[4 * c:4 * c + 4])


def cond_ok(cond, ms):
    """A T3 cancel condition (byte +2) for the character itself, FUN_8002de24: 0 always,
    1..23 character == cond - 1, 24..46 character != cond - 24, 47..69 opponent == cond - 47
    (unknown here: no), 70..92 model character == cond - 70, 93.. model character != cond - 93.
    Character (+0x16) and model character (+0x18) are the same for the five. The shared
    groups use this for character-only moves: 107 = not Ogre, 90 = True Ogre only, 17 = Gun
    Jack only ..."""
    if cond == 0:
        return True
    ch = t3_character(ms.m)
    if cond < 0x18:
        return ch == cond - 1
    if cond < 0x2F:
        return ch != cond - 0x18
    if cond < 0x46:
        return False
    if cond < 0x5D:
        return ch == cond - 0x46
    return ch != cond - 0x5D
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
        if cmd >= 0xC000 or not cond_ok(cond, ms) or req not in REQ_T3_T5 or not cmd & 0xF:
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
        if cmd >= 0xC000 or not cond_ok(cond, ms) or not cmd & 0xF:
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


def t3_attack_entries(ms, state):
    """Every attack entry of a T3 move's cancel list in T3 order: (key, T3 move, damage, frame
    from, frame to, start frame, T5 requirement condition or 0). Unlike t3_attacks the same
    command can occur several times (e.g. jump attacks rising / falling by frame window)."""
    out = []
    for _, e in ms.cancels(ms.own, ms.own.move(state)[3]):
        cmd, cond, req, _, tgt, _, fr0, fr1, st = e
        if (cmd >= 0xC000 or not cond_ok(cond, ms) or (req not in REQ_NONE and req not in REQ_T3_T5)
                or not cmd & 0xF):
            continue
        pk, idx = ms.resolve(tgt)
        if pk is not ms.own or idx >= pk.count:
            continue
        dmg = pk.move(idx)[5] & 0xFFFF
        if not pk.move_bytes(idx)[0x2D] or dmg & 0x4000:
            continue
        out.append((t5_key(cmd), idx, dmg, max(fr0, 1), fr1, max(st, 1), REQ_T3_T5.get(req, 0)))
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
    # only Gon (x0.43) needs scaled copies of the common T5 animations (reactions, getting up);
    # Ogre x1.04, True Ogre x0.99, Gun Jack x0.875, Dr. B x0.86 use them as they are: the copies
    # cost ~0.8 MB of bank, which the T3 moves need
    if abs(tpl_scale - 1) <= 0.15:
        return out
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


# T3 model -> T3 character id (table 0x800958C4: four model slots per character, value = m + 6).
GON_MODELS = (36, 37)
DRB_MODELS = (38, 39)
STAND_VULN = (0x0842, 0x1052, 0x1952)


def gon_always_low(com):
    """Gon's gimmick (T3 FUN_8003f098: against anyone but Gon the crouch flag +0xDF is always
    set; FUN_8002d8b4: throws on Gon fail): every standing vulnerability becomes its crouching
    form (T5 crouch moves: 0x0842 -> 0x2821, 0x1052 -> 0x3029, 0x1952 -> 0x3929), so high attacks
    and standing throws miss him. Gon against Gon cannot be told apart here (T3 exempts it)."""
    n = 0
    for i in range(len(com.lists["move"])):
        mv = com.move(i)
        v = mv["vuln"]
        if v & 0xFFFF in STAND_VULN:
            mv["vuln"] = (v & ~0xFFFF) | 0x2000 | (v & 0xFF00) | (v & 0xFF) >> 1
            com.lists["move"][i] = com.pack_move(mv)
            n += 1
    print(f"Gon: {n} standing vulnerabilities made low")


def drop_unused_animations(com, anims):
    """Only the own-bank animations (ids 0x4000 + k) that moves still use, renumbered: the
    template's replaced ones and those of dropped moves cost bank memory."""
    used = sorted({com.move(i)["anim"] - 0x4000 for i in range(len(com.lists["move"]))
                   if 0x4000 <= com.move(i)["anim"] < 0x8000})
    new = {k: n for n, k in enumerate(used)}
    for i in range(len(com.lists["move"])):
        mv = com.move(i)
        if 0x4000 <= mv["anim"] < 0x8000:
            mv["anim"] = 0x4000 + new[mv["anim"] - 0x4000]
            com.lists["move"][i] = com.pack_move(mv)
    return [anims[k] for k in used]


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
    clone_of_t3 = {}                                  # T3 move -> new move
    t3_anim = {}                                      # T3 move -> bank index

    def own_anim(t3idx, victim=False):
        """Bank animation id of T3 move t3idx (own or common T3 pack).
        Throw victims are retargeted to a standard T5 skeleton (Paul's): any character."""
        key = (t3idx, victim)
        if key not in t3_anim:
            a = conv.convert(m, t3idx, victim_skel if victim else skel, common=True)
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

    def resting(i):
        """A T3 loop (its follow-up is itself): standing, crouching, lying."""
        nxt = own_move(struct.unpack_from("<H", ms.own.move_bytes(i), 0x10)[0])
        return nxt is not None and nxt[0] == i

    tmpl_names = {com.name(com.move(i)["name"]): i for i in range(len(com.lists["move"]))}

    def lying_template(i):
        """T5 lying loop (face up, with its get-up options) for a T3 lying loop, else None."""
        if resting(i) and ms.own.move(i)[1] & 0xFFFF in (0x3884, 0x4284):
            return tmpl_names.get("dwKAM_00U")
        return None

    def own_move(tgt):
        """(own T3 move, damage word) of a cancel / next target, attack or not; None for the
        common pack."""
        pk, idx = ms.resolve(tgt)
        if pk is not ms.own or idx >= pk.count:
            return None
        return idx, pk.move(idx)[5] & 0xFFFF

    def t3_attack(tgt):
        """(own T3 move, damage) of a cancel target if it is a plain attack, else None."""
        pk, idx = ms.resolve(tgt)
        if pk is not ms.own or idx >= pk.count:
            return None
        dmg = pk.move(idx)[5] & 0xFFFF
        if not pk.move_bytes(idx)[0x2D] or dmg & 0x4000:
            return None
        return idx, dmg

    hitcond_lists = {}

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
        body = tuple(struct.pack(HITCOND, rq, max(1, round(dmg * d / base)) if dmg else 0, rea)
                     for rq, d, rea in seq)
        if body not in hitcond_lists:                 # identical lists are shared
            hitcond_lists[body] = len(H)
            H.extend(body)
        return hitcond_lists[body]

    # requirement lists of the template that hold exactly one condition
    R = [struct.unpack("<HH", e) for e in com.lists["requirement"]]
    req_list = {}
    for k in range(len(R) - 1):
        if R[k + 1][0] == REQ_END and (k == 0 or R[k - 1][0] == REQ_END) and R[k][1] == 0:
            req_list.setdefault(R[k][0], k)

    def t5_reqs(req):
        """T5 requirement list indices for a T3 cancel requirement (one T5 entry each), None if
        it has no T5 equivalent yet. T3 FUN_8002e0bc: 26 = contact not guarded (on hit, T5 40),
        1 = contact (hit or block: T5 40 and 41)."""
        if req in REQ_NONE:
            return [0]
        t5 = {26: (40,), 1: (40, 41)}.get(req) or ((REQ_T3_T5[req],) if req in REQ_T3_T5 else ())
        if not t5 or any(x not in req_list for x in t5):
            return None
        return [req_list[x] for x in t5]

    follow_groups = {}                                # T3 group -> (T5 group start, count) / None

    def follow_entry(e, tmove):
        """T5 entries for one T3 cancel entry of a ported move's list (strings, automatic and
        direction transitions, motions, dashes); [] if it has no T5 form (yet)."""
        cmd, cond, req, _, tgt, _, fr0, fr1, st = e
        rqs = t5_reqs(req)
        if not cond_ok(cond, ms) or rqs is None:
            return []
        out = []
        if is_t3_sequence(cmd):
            a = t3_attack(tgt)
            if a is not None:
                child = clone(tmove, *a)
                out = [struct.pack(CANCEL, t5_sequence(cmd), rq, child, 7, max(fr0, 1), fr1,
                                   max(st, 1), 0) for rq in rqs]
            return out
        if cmd in (0xC001, 0xC002):                    # dash forward / back: T5 0x8001 / 0x8002
            a = own_move(tgt)
            if a is not None and a[0] > 1 and not resting(a[0]):
                child = clone(tmove, *a)
                out = [struct.pack(CANCEL, cmd - 0xC000 + 0x8000, rq, child, 14, max(fr0, 1), fr1,
                                   max(st, 1), 0) for rq in rqs]
            return out
        if cmd >= 0xC000:
            return []
        if cmd == 0x10:
            # automatic continuation in a frame window (multi-part moves): T5 command 0;
            # T3 "on hit" / "on contact" become T5 requirement lists (one entry each)
            a = own_move(tgt)
            if a is not None:
                child = clone(tmove, *a)
                out = [struct.pack(CANCEL, 0, rq, child, 0, max(fr0, 1), fr1, max(st, 1), 0)
                       for rq in rqs]
            return out
        if not cmd & 0xF:
            # direction only (held): landings, rolls, stance changes inside a move
            a = own_move(tgt)
            if a is not None and a[0] > 1:
                lie = lying_template(a[0])
                if lie is not None or not resting(a[0]):
                    child = clone(lie if lie is not None else tmove, *a)
                    out = [struct.pack(CANCEL, t5_key(cmd)[0], rq, child, 0, max(fr0, 1), fr1,
                                       max(st, 1), 0) for rq in rqs]
            return out
        a = t3_attack(tgt)
        if a is None:
            return []
        k = t5_key(cmd)
        child = clone(tmpl_of.get(k, tmove), *a)
        return [struct.pack(CANCEL, k[0] | k[1] << 16 | 0x20 << 24, rq, child, 9, fr0, fr1, st, 0)
                for rq in rqs]

    def clone(tmove, t3idx, dmg):
        """New move = template attack `tmove` with T3 move `t3idx` (animation, damage, active
        frames, follow-ups from its T3 cancel list)."""
        key = (tmove, t3idx)
        if key in clones:
            return clones[key]
        if t3idx in clone_of_t3:                     # one T5 move per T3 move (first template)
            return clone_of_t3[t3idx]
        mv = com.move(tmove)
        b = ms.own.move_bytes(t3idx)
        a = own_anim(t3idx)
        if a is not None:
            mv["anim"] = a
        mv["active_start"], mv["active_end"] = b[0x2D], b[0x2E]
        w = ms.own.move(t3idx)
        # T3 lying (0x3884 face up, 0x4284 face down) has no T5 equivalent value: the template's
        mv["vuln"] = mv["vuln"] if w[1] & 0xFFFF in (0x3884, 0x4284) else w[1]
        mv["hitlevel"] = t5_hitlevel(w[2])
        if mv["hitcond"] < len(com.lists["hitcond"]):
            mv["hitcond"] = copy_hitconds(mv["hitcond"], dmg, t3_reaction(ms, t3idx))
        new = com.add("move", com.pack_move(mv))     # reserved first: strings can loop
        clones[key] = new
        clone_of_t3[t3idx] = new
        # follow-ups: T3 cancels with buttons -> T5 string entries (flag 0x20, extradata 9 as
        # the template's strings); template entries without buttons and its end entry stay
        # (T3's shared groups become T5 group lists once, then called with 0x8005)
        entries = []
        runs = []                                         # [(group or None, [T3 entries])]
        for _, e, gid in ms.cancels_grouped(ms.own, ms.own.move(t3idx)[3]):
            if not runs or runs[-1][0] != gid:
                runs.append((gid, []))
            runs[-1][1].append(e)
        for gid, es in runs:
            if gid is None:
                for e in es:
                    entries.extend(follow_entry(e, tmove))
                continue
            if gid not in follow_groups:
                out = [x for e in es for x in follow_entry(e, tmove)]
                if out:
                    follow_groups[gid] = (len(com.lists["group_cancel"]), len(out))
                    com.lists["group_cancel"].extend(out)
                    com.lists["group_cancel"].append(struct.pack(CANCEL, 0x8006, 0, 0, 0, 0, 0, 0, 0))
                else:
                    follow_groups[gid] = None
            g = follow_groups[gid]
            if g is not None:
                entries.append(struct.pack(CANCEL, 0x8005, 0, g[0], 0, 0, 0, g[1], 0))
        # T3's follow-up at the end of the animation, unless it is standing or a resting loop
        # (those stay the template's: the T5 state machine's own way back)
        nxt = own_move(struct.unpack_from("<H", b, 0x10)[0])
        follow = None
        if nxt is not None and nxt[0] > 1:
            nb = ms.own.move_bytes(nxt[0])
            if own_move(struct.unpack_from("<H", nb, 0x10)[0]) != nxt:
                follow = clone(tmove, *nxt)
            elif lying_template(nxt[0]) is not None:      # knocked down: T3's lying loop
                follow = clone(lying_template(nxt[0]), *nxt)
        length = ms.own.anim_frames(t3idx, ms.common)
        for e in com.lists["cancel"][mv["cancel"]:]:
            f = list(struct.unpack(CANCEL, e))
            if f[0] == 0x8000:
                f[4] = f[6] = length
                if follow is not None:
                    f[2] = follow
                    mv["transition"] = follow
                entries.append(struct.pack(CANCEL, *f))
                break
            # of the template's own entries only the special commands stay (0x8001.. dash,
            # sidestep, groups ...): its direction-only and automatic (on hit ...) transitions
            # are the template move's, T3's own are above
            if 0x8000 < f[0] < 0x10000:
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
    n_added = 0
    queue = [stand]
    t5_groups = {}                                    # T3 group -> (T5 group start, count) / None

    def attack_entry(e):
        """T5 entry data of one T3 cancel entry if it is an attack this character has:
        [(key, T3 move, damage, from, to, start, requirement list indices)] or []. Input
        sequences (motions) get key (T5 sequence command, 0)."""
        cmd, cond, req, _, tgt, _, fr0, fr1, st = e
        rqs = t5_reqs(req)
        if not cond_ok(cond, ms) or rqs is None:
            return []
        if is_t3_sequence(cmd):
            key = (t5_sequence(cmd), 0)
        elif cmd >= 0xC000 or not cmd & 0xF:
            return []
        else:
            key = t5_key(cmd)
        pk, idx = ms.resolve(tgt)
        if pk is not ms.own or idx >= pk.count:
            return []
        dmg = pk.move(idx)[5] & 0xFFFF
        if dmg & 0x4000:
            return []                                   # throws: their own pass
        if not pk.move_bytes(idx)[0x2D] and (idx <= 1 or resting(idx)):
            return []                                   # standing / resting loops: T5 states
        return [(key, idx, dmg, max(fr0, 1), fr1, max(st, 1), rqs)]

    def stand_chain():
        """T3 standing is move 0 and the non-attack moves its follow-ups lead to (Gon: 0 -> 1,
        Dr. B 0 -> 1): the T5 standing loop gets all their entries."""
        out, i = [0], 0
        while len(out) < 4:
            nxt = own_move(struct.unpack_from("<H", ms.own.move_bytes(i), 0x10)[0])
            if nxt is None or nxt[0] in out or ms.own.move_bytes(nxt[0])[0x2D]:
                break
            out.append(nxt[0])
            i = nxt[0]
        return out

    # every T3 resting loop the character can reach, by class: standing ones (Dr. B's 242 ...)
    # join the T5 standing state, crouching ones (vuln bit 0x2000: Dr. B's 243, Ogre's 14 ...)
    # the T5 crouching state (alias 2)
    reach, todo = {0}, [0]
    while todo:
        i = todo.pop()
        nx = struct.unpack_from("<H", ms.own.move_bytes(i), 0x10)[0]
        for _, e in ms.cancels(ms.own, ms.own.move(i)[3]) + [("next", (0, 0, 0, 0, nx, 0, 0, 0, 0))]:
            if cond_ok(e[1], ms):
                pk, k = ms.resolve(e[4])
                if pk is ms.own and k < pk.count and k not in reach:
                    reach.add(k)
                    todo.append(k)
    loops = sorted(i for i in reach if resting(i) and ms.own.move(i)[1] & 0xFFFF not in (0x3884, 0x4284))
    crouch_loops = [i for i in loops if ms.own.move(i)[1] & 0x2000]
    stand_loops = [i for i in loops if not ms.own.move(i)[1] & 0x2000 and i > 1
                   and t3_attack_entries(ms, i)]
    crouch = aliases[2]

    def state_moves(j, st3):
        if j == stand:
            return stand_chain() + [i for i in stand_loops if i not in stand_chain()]
        if j == crouch:
            return crouch_loops or [st3]
        return [st3]

    if crouch_loops and crouch not in pairs:
        pairs[crouch] = crouch_loops[0]
        queue.append(crouch)

    sequences = {}

    def t5_sequence(cmd):
        """T5 command (0x8013 + input_seq index) for a T3 input sequence: inputs oldest first,
        directions as flag 0x40 entries, the triggering one with buttons as flag 0x20 (Paul's
        e.g. 0x808F = n, f, d, d/b+1)."""
        if cmd not in sequences:
            win, ins = t3_sequence(cmd)
            start = len(com.lists["input"])
            for k, v in enumerate(ins):
                d, btn = NUMPAD.get(v & 0xF, 0x20), (v >> 8) & 0xF
                last = k == len(ins) - 1
                flag = 0x20 if last and btn else 0x40
                com.lists["input"].append(struct.pack("<I", flag << 24 | btn << 16 | d))
            sequences[cmd] = 0x8013 + com.add("input_seq", struct.pack("<HHI", max(win, 1), len(ins), start))
        return sequences[cmd]

    n_states = 0
    while queue:
        j = queue.pop(0)
        st3 = pairs[j]
        local = t3_attacks(ms, st3)
        follow = t3_state_moves(ms, st3)
        entries, sample = [], None
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
                sample = sample or f
                continue                      # template attacks: replaced by the T3 list below
            entries.append(struct.pack(CANCEL, *f))
        # the T3 state's attacks, all of them in T3 order with T3's frame windows, in front
        # (T3's shared groups become T5 group lists, called with 0x8005 like the template's)
        ref = sample or [0, 0, 0, 0, 1, 255, 1, 0]
        front = []
        run, run_gid = [], None

        def flush():
            if run_gid is None:
                front.extend(run)
                return
            if run_gid not in t5_groups:
                if not run:
                    t5_groups[run_gid] = None             # nothing of it for this character
                    return
                t5_groups[run_gid] = (len(com.lists["group_cancel"]), len(run))
                com.lists["group_cancel"].extend(run)
                com.lists["group_cancel"].append(struct.pack(CANCEL, 0x8006, 0, 0, 0, 0, 0, 0, 0))
            g = t5_groups[run_gid]
            if g is not None:
                front.append(struct.pack(CANCEL, 0x8005, 0, g[0], 0, 0, 0, g[1], 0))

        state_entries = []
        for s3 in state_moves(j, st3):
            state_entries += ms.cancels_grouped(ms.own, ms.own.move(s3)[3])
        for _, e, gid in state_entries:
            if gid != run_gid:
                flush()
                run, run_gid = [], gid
            if gid is not None and gid in t5_groups:
                continue                                  # translated once already
            for key, t3idx, dmg, fr0, fr1, st, rqs in attack_entry(e):
                if ms.own.move_bytes(t3idx)[0x2D]:
                    tm = tmpl_of.get(key) or next((v for k, v in tmpl_of.items() if k[1] == key[1]),
                                                  next(iter(tmpl_of.values())))
                else:
                    tm = lying_template(t3idx) or stand    # stance changes, rolls ...
                child = clone(tm, t3idx, dmg)
                for rq in rqs:
                    run.append(struct.pack(CANCEL, key[0] | key[1] << 16, rq, child,
                                           ref[3], fr0, fr1, st, ref[7]))
                n_added += 1
        flush()
        entries = front + entries
        mv = com.move(j)
        mv["cancel"] = len(com.lists["cancel"])
        com.lists["cancel"].extend(entries)
        com.lists["move"][j] = com.pack_move(mv)
        if j != stand:
            set_anim(j, st3)
        n_states += 1

    # second pass, all pairs known: the states' T3 direction-only entries to moves that are no
    # T5 state themselves (rolls, landings, special steps) go in front of the T5 movement entries
    paired_t3 = set(pairs.values())
    attack_tmpl = next(iter(tmpl_of.values()))
    for j, st3 in pairs.items():
        front = []
        for _, e in ms.cancels(ms.own, ms.own.move(st3)[3]):
            cmd, cond, req, _, tgt, _, fr0, fr1, st = e
            if cmd >= 0xC000 or cmd & 0xF or cmd == 0x10 or not cond_ok(cond, ms) or req not in REQ_NONE:
                continue
            a = own_move(tgt)
            if a is None or a[0] <= 1 or a[0] in paired_t3 or resting(a[0]):
                continue
            tm = attack_tmpl if ms.own.move_bytes(a[0])[0x2D] else stand
            front.append(struct.pack(CANCEL, t5_key(cmd)[0], 0, clone(tm, *a), 0,
                                     max(fr0, 1), fr1, max(st, 1), 0))
        if front:
            mv = com.move(j)
            k = mv["cancel"]
            old = []
            while True:
                old.append(com.lists["cancel"][k])
                if struct.unpack_from("<I", com.lists["cancel"][k])[0] == 0x8000:
                    break
                k += 1
            mv["cancel"] = len(com.lists["cancel"])
            com.lists["cancel"].extend(front + old)
            com.lists["move"][j] = com.pack_move(mv)
            n_added += len(front)

    # Dr. B's gimmick (T3 moveset, model 38/39): he cannot stay on his feet. Standing with no
    # direction held: T3 131 (stands 20 frames) -> 237 (falls, 30) -> 269 (20) -> 266 (lies, a
    # loop with his ground attacks); holding a direction or attacking keeps him up. Ported as
    # clones (T3 animation and button follow-ups) of T5 lying moves (their vulnerability and
    # get-up options; T3 lying = 0x3884), linked by end entry and transition.
    n_drb = 0
    if m in DRB_MODELS:
        by_name = {com.name(com.move(i)["name"]): i for i in range(n_template)}

        def chain_move(tmpl, t3idx, nxt):
            keep_vuln = com.move(tmpl)["vuln"]
            new = clone(tmpl, t3idx, 0)
            mv = com.move(new)
            if ms.own.move(t3idx)[1] & 0xFFFF == 0x3884:
                mv["vuln"] = keep_vuln
            mv["transition"] = nxt
            for k in range(mv["cancel"], len(com.lists["cancel"])):
                f = list(struct.unpack(CANCEL, com.lists["cancel"][k]))
                if f[0] == 0x8000:
                    f[2] = nxt
                    com.lists["cancel"][k] = struct.pack(CANCEL, *f)
                    break
            com.lists["move"][new] = com.pack_move(mv)
            return new

        lie = clone(by_name["dwKAM_00U"], 266, 0)
        lie = chain_move(by_name["dwKAM_00U"], 266, lie)          # loops on itself
        down = chain_move(by_name["dwDWN_00U"], 269, lie)
        fall = chain_move(by_name["dwDWN_00U"], 237, down)
        still = chain_move(stand, 131, fall)
        mv = com.move(stand)
        entries = com.lists["cancel"]
        k = mv["cancel"]
        while struct.unpack(CANCEL, entries[k])[0] != 0x8000:
            k += 1
        # neutral held (T5 direction 0x20), after every other entry; like the walks' entries
        entries.insert(k, struct.pack(CANCEL, 0x20, 0, still, 14, 1, 255, 1, 0))
        for i in range(len(com.lists["move"])):          # lists behind the insertion shift
            mi = com.move(i)
            if mi["cancel"] > k:
                mi["cancel"] += 1
                com.lists["move"][i] = com.pack_move(mi)
        n_drb = 4

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

    # every other T3 throw of a state (command throws: u/f+1+2, d/f+2+4, character-only ones
    # ...): a new attempt = the template's 1+3 attempt with the T3 attempt's animation and
    # active frames; its side entries (requirement 2..5) lead to the T3 executions of that
    # attempt, sides the T3 throw does not have are dropped
    base_attempt = next(iter(seen_attempts), None)

    def t3_sides(idx):
        out = {}
        for _, t in ms.cancels(ms.own, ms.own.move(idx)[3]):
            pk2, ex = ms.resolve(t[4])
            if pk2 is ms.own and ex + 1 < pk2.count and t[2] in (2, 3, 4, 5):
                out.setdefault(t[2], ex)
        return out

    attempts = {}

    def throw_attempt(idx):
        if idx in attempts:
            return attempts[idx]
        sides = t3_sides(idx)
        mv = com.move(base_attempt)
        a = own_anim(idx)
        if a is not None:
            mv["anim"] = a
        b3 = ms.own.move_bytes(idx)
        mv["active_start"], mv["active_end"] = b3[0x2D], b3[0x2E]
        out = []
        for e in com.lists["cancel"][mv["cancel"]:]:
            f = list(struct.unpack(CANCEL, e))
            if f[0] == 0x8000:
                f[4] = f[6] = ms.own.anim_frames(idx, ms.common)
                out.append(struct.pack(CANCEL, *f))
                break
            side = struct.unpack_from("<H", com.lists["requirement"][f[1]])[0]
            if side in (2, 3, 4, 5) and f[2] < n_template:
                if side not in sides:
                    continue
                f[2] = throw_exec(f[2], sides[side])
            out.append(struct.pack(CANCEL, *f))
        mv["cancel"] = len(com.lists["cancel"])
        com.lists["cancel"].extend(out)
        attempts[idx] = com.add("move", com.pack_move(mv))
        return attempts[idx]

    n_cmd_throws = 0
    if base_attempt is not None:
        for j, st3 in pairs.items():
            front = []
            for _, e in ms.cancels(ms.own, ms.own.move(st3)[3]):
                cmd, cond, req, _, tgt, _, fr0, fr1, st = e
                rqs = t5_reqs(req)
                if not cond_ok(cond, ms) or rqs is None:
                    continue
                if is_t3_sequence(cmd):
                    key = (t5_sequence(cmd), 0)
                elif cmd >= 0xC000 or not cmd & 0xF:
                    continue
                else:
                    key = t5_key(cmd)
                if st3 == 0 and key in ((0, 5), (0, 10), (0x20, 5), (0x20, 10)) and req == 0:
                    continue                                  # the template's 1+3 / 2+4
                pk, idx = ms.resolve(tgt)
                if pk is not ms.own or idx >= pk.count or not ms.own.move(idx)[5] & 0x4000:
                    continue
                if not t3_sides(idx):
                    continue
                at = throw_attempt(idx)
                for rq in rqs:
                    front.append(struct.pack(CANCEL, key[0] | key[1] << 16, rq, at, 0,
                                             max(fr0, 1), fr1, max(st, 1), 0))
            if front:
                mv = com.move(j)
                k = mv["cancel"]
                old = []
                while True:
                    old.append(com.lists["cancel"][k])
                    if struct.unpack_from("<I", com.lists["cancel"][k])[0] == 0x8000:
                        break
                    k += 1
                mv["cancel"] = len(com.lists["cancel"])
                com.lists["cancel"].extend(front + old)
                com.lists["move"][j] = com.pack_move(mv)
                n_cmd_throws += len(front)
    print(f"command throws: {n_cmd_throws} entries, {len(attempts)} attempts")

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
        for t3, new in sorted(attempts.items(), key=lambda kv: kv[1]):
            fh.write(f"{new} T3-{t3} (throw attempt)\n")
    anims = scale_to_body(m, costume, template_slot, com, anims, n_tpl, t3_anim)
    if m in GON_MODELS:
        gon_always_low(com)
    # the game keeps both players' movesets in 938368 bytes, merge/data/ram.csv splits them so
    # that every character but King gets 447872 on either side. Drop the template moves the
    # clones replaced and their cancel lists (indices in states.txt / clones.txt are from before).
    # the template's attacks also sit in the shared group lists (0x8005), reached from states
    # that are not T3 states: out with them too (1:1 T3; generic Co_ / Thr moves stay)
    n_grp = com.drop_group_entries(
        lambda f: not 0x8000 <= f[0] < 0x10000 and f[2] < n_template
        and com.move(f[2])["active_start"] and not keep(f[2]))
    print(f"template attacks dropped from groups: {n_grp}")
    dead = com.remove_dead_moves()
    com.compact_cancels()
    anims = drop_unused_animations(com, anims)
    raw = com.build()
    print(f"moveset: {len(raw)} bytes after dropping {dead} unreachable moves")
    assert len(raw) <= 447872, "moveset larger than a player's moveset area"
    (out / "moveset.bin").write_bytes(lz_pack(raw))
    bank = t5_bank.build(bank_tpl, anims)
    print(f"bank: {len(bank)} bytes")
    # merge/data/ram.csv splits the banks' 5041856 bytes so that every character but King gets
    # 2141120 on either side
    assert len(bank) <= 2141120, "animation bank larger than a player's bank area"
    (out / "bank.bin").write_bytes(bank)
    print(f"added state attacks {n_added}")
    print(f"T3 attacks {len(attacks)}, new moves {len(clones)}, new animations {len(t3_anim)}, "
          f"redirected cancels {redirected}, motions {moved}, throw sides {n_throws}, states {n_states}, "
          f"win poses {n_wins} from T3 {wins}")
    for k, v in sorted(attacks.items()):
        print("  ", k, "-> T3 move", v)


if __name__ == "__main__":
    build(int(sys.argv[1]), sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 0)
