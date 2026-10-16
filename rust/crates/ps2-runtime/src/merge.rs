//! Tekken5-Tekken3-Merge: the mod layer that brings new and replaced game files into Tekken 5.
//!
//! Everything lives in the mod directory (`T5_MOD`, play.bat: `merge\data`):
//!
//! - `files.csv` (`target,file`): TK5DATA1 files. `target` is either a TOC index (replace that
//!   file) or `res:<type>:<id>` (a resource the game looks up by type and id through
//!   FUN_001f09b8, e.g. a new character slot `res:3:80`). `file` is relative to the mod directory
//!   and holds the file exactly as the game sees it after decryption (LZ-compressed where the
//!   originals are).
//! - `ram.csv` (`addr,value`, hex u32, `#` comments): EE RAM words written when `main` starts
//!   (after the boot loader has unpacked the program and its tables).
//! - `blobs.csv` (`addr,file`, hex address): files copied into EE RAM when `main` starts (data a
//!   mod file refers to outside its load buffer, e.g. the select screen's pictures).
//! - `slots.csv`, `grid.csv`: new character slots and the select grid (see `load_slots`).
//!
//! How a file reaches the game (see merge/PLAN.md): the loader reads TK5DATA1 file `i` by the
//! table at 0x0046B730 (sector, size), decrypts it with the key stream k0 = i, k' = 5k + 3
//! (restarted every 2048 bytes) and checks the word sum against 0x0046E9B8. On entry to `main`
//! (hook `merge_main`) each mod file gets its index (replaced, or a free TOC entry for `res:`
//! targets), is encrypted with that key and placed in virtual sectors past the end of the disc
//! image; TK5DATA1 grows to cover them, and the TOC and checksum entries are written to RAM.
//! The hook `merge_file_index` on FUN_001f09b8 returns the allocated index for `res:` targets.

use crate::disc::{Disc, SECTOR};
use ee_core::{Ctx, GPR_A0, GPR_V0};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

const TOC: u32 = 0x0046_B730;
const SUMS: u32 = 0x0046_E9B8;
const TOC_ENTRIES: u32 = 0x623;
/// Resource type table of FUN_001f09b8: {s16 base, u16 kind} per type.
const TYPES: u32 = 0x0046_2F98;
/// TOC entries no lookup of the original game reaches (merge/PLAN.md), in allocation order.
const FREE: [(u32, u32); 3] = [(1556, 1568), (1180, 1180), (1182, 1229)];
const ARCHIVE: &str = "TK5DATA1.BIN";

enum Target {
    Index(u32),
    Res { ty: u32, id: u32 },
}

struct File {
    target: Target,
    data: Vec<u8>,
}

struct State {
    /// (kind, base, id) of the original formula -> allocated TOC index.
    res: Vec<((u32, i32, u32), u32)>,
    /// Files on the virtual disc: (index, sector in TK5DATA1, size, checksum). Placed once; a
    /// later start of `main` (after another program ran) only rewrites the RAM tables.
    placed: Vec<(u32, u32, u32, u32)>,
}

static FILES: OnceLock<(Vec<File>, Vec<(u32, u32)>)> = OnceLock::new();
static STATE: std::sync::Mutex<State> = std::sync::Mutex::new(State { res: Vec::new(), placed: Vec::new() });

fn mod_dir() -> Option<PathBuf> {
    std::env::var_os("T5_MOD").map(PathBuf::from).filter(|p| p.is_dir())
}

fn rows(path: &Path) -> Vec<Vec<String>> {
    let Ok(text) = std::fs::read_to_string(path) else { return Vec::new() };
    text.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .skip(1)
        .map(|l| l.split(',').map(|s| s.trim().to_string()).collect())
        .collect()
}

fn hex(s: &str) -> Option<u32> {
    u32::from_str_radix(s.trim_start_matches("0x").trim_start_matches("0X"), 16).ok()
}

fn load() -> &'static (Vec<File>, Vec<(u32, u32)>) {
    FILES.get_or_init(|| {
        let Some(dir) = mod_dir() else { return (Vec::new(), Vec::new()) };
        let mut files = Vec::new();
        for r in rows(&dir.join("files.csv")) {
            let (Some(t), Some(f)) = (r.first(), r.get(1)) else { continue };
            let target = if let Some(rest) = t.strip_prefix("res:") {
                let mut p = rest.split(':').map(|x| x.parse::<u32>().ok());
                match (p.next().flatten(), p.next().flatten()) {
                    (Some(ty), Some(id)) => Target::Res { ty, id },
                    _ => {
                        crate::diag::log(format!("merge: bad target {t}"));
                        continue;
                    }
                }
            } else if let Ok(i) = t.parse::<u32>() {
                Target::Index(i)
            } else {
                crate::diag::log(format!("merge: bad target {t}"));
                continue;
            };
            match std::fs::read(dir.join(f)) {
                Ok(data) => files.push(File { target, data }),
                Err(e) => crate::diag::log(format!("merge: {f}: {e}")),
            }
        }
        let ram = rows(&dir.join("ram.csv"))
            .iter()
            .filter_map(|r| Some((hex(r.first()?)?, hex(r.get(1)?)?)))
            .collect();
        crate::diag::log(format!("merge: {} files, mod dir {}", files.len(), dir.display()));
        (files, ram)
    })
}

fn rd32(c: &Ctx, addr: u32) -> u32 {
    let o = ee_core::ram_off(addr).expect("merge: address outside RAM");
    u32::from_le_bytes(c.ram()[o..o + 4].try_into().unwrap())
}

fn wr32(c: &Ctx, addr: u32, v: u32) {
    let o = ee_core::ram_off(addr).expect("merge: address outside RAM");
    c.ram()[o..o + 4].copy_from_slice(&v.to_le_bytes());
}

/// (kind, base) of resource type `ty` (FUN_001f09b8's table).
fn kind_base(c: &Ctx, ty: u32) -> (u32, i32) {
    let w = rd32(c, TYPES + ty * 4);
    (w >> 16, w as u16 as i16 as i32)
}

/// FUN_0023f510's cipher (its own inverse; the key restarts at the index in every sector) and
/// FUN_0023f260's checksum: the sum of the whole plain words.
fn encrypt(index: u32, plain: &[u8]) -> (Vec<u8>, u32) {
    let sum = plain.chunks_exact(4).fold(0u32, |s, w| s.wrapping_add(u32::from_le_bytes(w.try_into().unwrap())));
    let mut out = plain.to_vec();
    out.resize(plain.len().div_ceil(4) * 4, 0);
    for chunk in out.chunks_mut(SECTOR as usize) {
        let mut k = index;
        for w in chunk.chunks_mut(4) {
            let v = u32::from_le_bytes(w.try_into().unwrap()) ^ k;
            w.copy_from_slice(&v.to_le_bytes());
            k = k.wrapping_mul(5).wrapping_add(3);
        }
    }
    out.truncate(plain.len());
    (out, sum)
}

/// Hook on `main`: allocate indices, place the files on the virtual disc, patch the tables.
pub fn on_main(c: &mut Ctx) {
    let (files, ram) = load();
    if files.is_empty() && ram.is_empty() {
        load_blobs(c);
        load_slots(c);
        return;
    }
    let mut state = STATE.lock().unwrap();
    if state.placed.is_empty() && !files.is_empty() {
        let m = crate::machine();
        let Some(disc) = m.disc.as_mut() else { return };
        let mut free = FREE.iter().flat_map(|&(a, b)| a..=b).filter(|&i| rd32(c, TOC + i * 8 + 4) == 0);
        for f in files {
            let index = match f.target {
                Target::Index(i) if i < TOC_ENTRIES => i,
                Target::Index(i) => {
                    crate::diag::log(format!("merge: index {i} outside the TOC"));
                    continue;
                }
                Target::Res { ty, id } => {
                    let key = {
                        let (kind, base) = kind_base(c, ty);
                        (kind, base, id)
                    };
                    if let Some(&(_, i)) = state.res.iter().find(|(k, _)| *k == key) {
                        crate::diag::log(format!("merge: res:{ty}:{id} given twice, keeping index {i}"));
                        continue;
                    }
                    let Some(i) = free.next() else {
                        crate::diag::log("merge: no free TOC entries left".to_string());
                        continue;
                    };
                    state.res.push((key, i));
                    i
                }
            };
            let (enc, sum) = encrypt(index, &f.data);
            let sector = place(disc, enc);
            state.placed.push((index, sector, f.data.len() as u32, sum));
            crate::diag::log(format!("merge: file {index}: {} bytes at TK5DATA1 sector {sector}", f.data.len()));
        }
    }
    for &(index, sector, size, sum) in &state.placed {
        wr32(c, TOC + index * 8, sector);
        wr32(c, TOC + index * 8 + 4, size);
        wr32(c, SUMS + index * 4, sum);
    }
    for &(addr, v) in ram {
        wr32(c, addr, v);
    }
    drop(state);
    load_blobs(c);
    load_slots(c);
}

/// `blobs.csv`: copy files into EE RAM.
fn load_blobs(c: &Ctx) {
    let Some(dir) = mod_dir() else { return };
    for r in rows(&dir.join("blobs.csv")) {
        let (Some(addr), Some(file)) = (r.first().and_then(|a| hex(a)), r.get(1)) else { continue };
        match std::fs::read(dir.join(file)) {
            Ok(b) => {
                wr_bytes(c, addr, &b);
                crate::diag::log(format!("merge: {file} ({} bytes) at {addr:#x}", b.len()));
            }
            Err(e) => crate::diag::log(format!("merge: {file}: {e}")),
        }
    }
}

/// Put `data` in virtual sectors past the image (and past earlier mod files); grow TK5DATA1 to
/// reach them. Returns the sector relative to TK5DATA1.
fn place(disc: &mut Disc, data: Vec<u8>) -> u32 {
    let (lba, _) = disc.find(ARCHIVE).expect("merge: no TK5DATA1.BIN on the disc");
    let abs = disc.add_virtual(data);
    let rel = (abs - lba as u64) as u32;
    let end = (disc.virtual_end() - lba as u64) * SECTOR;
    disc.set_size(ARCHIVE, end.min(u32::MAX as u64) as u32);
    rel
}

/// Hook on FUN_001f09b8(id, type): the allocated index for a `res:` target; for a new slot
/// (id >= 80, kind 2) without its own file, the template slot's file; else the original.
pub fn file_index(c: &mut Ctx) -> bool {
    let (id, ty) = (c.gpr32(GPR_A0), c.gpr32(GPR_A0 + 1));
    let (kind, base) = kind_base(c, ty);
    if std::env::var_os("T5_RESLOG").is_some() {
        crate::diag::log(format!("res type {ty} id {id} (kind {kind}, base {base})"));
    }
    let state = STATE.lock().unwrap();
    if let Some(&(_, i)) = state.res.iter().find(|(k, _)| *k == (kind, base, id)) {
        c.set_gpr32(GPR_V0, i);
        return true;
    }
    drop(state);
    if kind == 2 && id >= SLOTS {
        if let Some(e) = ext_slot(id) {
            c.set_gpr32(GPR_V0, (base + e.template as i32 * 11 + 230) as u32);
            return true;
        }
    }
    false
}

// ------------------------------------------------------------------ new character slots

/// Slot table (80 x 0x24 bytes): u16 character, u16 costume, u32 name index (field 2), u32
/// fields 4, 6, 8, 10, 12, u16 field 14, u32 behaviour function (field 16). merge/PLAN.md.
const SLOT_TABLE: u32 = 0x0046_5B68;
const SLOT_SIZE: u32 = 0x24;
const SLOTS: u32 = 80;

#[derive(Clone)]
struct ExtSlot {
    slot: u32,
    template: u32,
    /// The entry with the new character id (select screen, names, portraits).
    entry: [u8; 0x24],
    /// The character id the fight runs with: the template slot's. Fight code indexes many
    /// tables with 33 entries by the player's character (+0x40: hit spheres, body data, the
    /// save file's per-character records), so a new id there reads and writes past them.
    fight_char: u32,
}

static EXT: std::sync::Mutex<Vec<ExtSlot>> = std::sync::Mutex::new(Vec::new());

fn ext_slot(slot: u32) -> Option<ExtSlot> {
    EXT.lock().unwrap().iter().find(|e| e.slot == slot).cloned()
}

/// Free EE RAM for the merge's tables: MIPS code bytes that are never executed (the program runs
/// as recompiled Rust), 64 KB aligned so patched code reaches it with one `lui` (merge/patches.csv).
const MOD_AREA: u32 = 0x0012_0000;
/// Select screen icon pointers by character (FUN_0028fd68 / FUN_00290078, 38 entries).
const MOD_ICONS: u32 = MOD_AREA;
const MOD_GRID: u32 = MOD_AREA + 0x100;
const MOD_CHARS: u32 = MOD_AREA + 0x200;
const MOD_STRINGS: u32 = MOD_AREA + 0x400;
/// Select screen name nodes by character (FUN_0028f448 etc., 38 x 8 bytes; patched).
const MOD_NAME_NODES: u32 = MOD_AREA + 0x800;
/// Name node table {id, "|name_X_L", "|name_X_R"} (0x47A6E8, 33 entries; patched to 38).
const MOD_NAME_TABLE: u32 = MOD_AREA + 0xA00;
const NAME_TABLE: u32 = 0x0047_A6E8;
/// Texture table of the big select portraits {loaded, ?, 66 x {name, TIM2, slot, w, h}}
/// (0x3BBF20, FUN_002965d8 / FUN_00296788): moved here with 76 entries (patched loops).
const PTABLE: u32 = MOD_AREA + 0xC00;
const PTABLE_ORIG: u32 = 0x003B_BF20;
const PTABLE_SIZE: u32 = 8 + 76 * 20;
/// File 82 (big select portraits, entry = name index * 2 + side) is unpacked into buffer 0x22;
/// its 66 entries are extended by `select/portraits_0082.bin` (u32 count, count x {offset, size},
/// TIM2s), copied behind the packed file 82 in buffer 0x1E (0x11B46C0, up to 0x14C5F00) when the
/// select screen registers its portraits.
const PORTRAIT_CONTAINER: u32 = 0x00C2_CA00;
/// Loading screen portraits by name index {P1 picture, P2 picture} (0x47B478, 33 x 2 bytes;
/// patched FUN_00292700): resource type 42 id = picture; new names get 43 + 2 * (index - 33).
const LOAD_PORTRAITS: u32 = MOD_AREA + 0x1300;
const LOAD_PORTRAITS_ORIG: u32 = 0x0047_B478;
/// Costume parameters by slot (3 floats; FUN_003049d0 by slot, FUN_00304d40 by the character's
/// first slot): 0x482028 has 80 entries, patched to this copy with room for 120.
const SLOT_PARAMS: u32 = MOD_AREA + 0x1400;
const SLOT_PARAMS_ORIG: u32 = 0x0048_2028;
const SLOT_PARAMS_N: u32 = 120;
const PORTRAIT_ENTRIES: u32 = 66;
const PORTRAIT_BLOB: u32 = 0x013A_0000;
const PORTRAIT_BLOB_END: u32 = 0x014C_5F00;

static PORTRAITS: std::sync::Mutex<Option<(Vec<u8>, Vec<(u32, u32)>)>> = std::sync::Mutex::new(None);
const MOD_END: u32 = MOD_AREA + 0x1000;
/// Select grid table pointer {cells, count} per game mode (FUN_0024ba50), 6 modes.
const GRID_MODES: u32 = 0x0047_19E8;
/// Characters with an own record in FUN_00218ac8's table (0x3ABF88, 32 x 8 bytes).
const CHAR_RECORDS: u32 = 32;
/// Name tables by slot field 2 (FUN_00239230 / 248 / 260): 33 original names.
const NAMES: u32 = 33;

#[derive(Clone)]
struct ExtChar {
    id: u32,
    record: u32,
}

struct Names {
    upper: Vec<(u32, u32)>,
    full: Vec<(u32, u32)>,
    short: Vec<(u32, u32)>,
}

static EXT_CHARS: std::sync::Mutex<Vec<ExtChar>> = std::sync::Mutex::new(Vec::new());
static EXT_NAMES: std::sync::Mutex<Names> =
    std::sync::Mutex::new(Names { upper: Vec::new(), full: Vec::new(), short: Vec::new() });

fn wr_bytes(c: &Ctx, addr: u32, b: &[u8]) {
    let o = ee_core::ram_off(addr).expect("merge: address outside RAM");
    c.ram()[o..o + b.len()].copy_from_slice(b);
}

/// `slots.csv` (`slot,template,char,costume,name,short,upper,full`; empty = the template slot's
/// value): new slots built from a template slot's entry; `name` is the slot's field 2 (index of
/// the name tables), `short`/`upper`/`full` the names for a new index (>= 33): `kao_<short>`
/// icons, "OGRE", "Ogre". A new character (char >= 33) gets its own record (FUN_00218ac8) listing
/// its slots as costumes. `grid.csv` (`cell,char,up,down,left,right`): the select grid of every
/// mode. Called from `on_main` once the tables are in RAM.
fn load_slots(c: &Ctx) {
    let Some(dir) = mod_dir() else { return };
    let mut ext = Vec::new();
    let mut names = Names { upper: Vec::new(), full: Vec::new(), short: Vec::new() };
    let mut str_at = MOD_STRINGS;
    let mut put_str = |c: &Ctx, s: &str| {
        let a = str_at;
        let mut b = s.as_bytes().to_vec();
        b.push(0);
        assert!(a + b.len() as u32 <= MOD_NAME_NODES, "merge: string area full");
        wr_bytes(c, a, &b);
        str_at = (a + b.len() as u32 + 3) & !3;
        a
    };
    let mut chars: Vec<(u32, Vec<u32>)> = Vec::new();
    // name node table: the 33 originals, then one entry per new character with a `label`
    let mut name_rows = 33u32;
    for i in 0..33 * 3 {
        wr32(c, MOD_NAME_TABLE + 4 * i, rd32(c, NAME_TABLE + 4 * i));
    }
    for r in rows(&dir.join("slots.csv")) {
        let num = |i: usize| r.get(i).and_then(|x| x.parse::<u32>().ok());
        let text = |i: usize| r.get(i).filter(|x| !x.is_empty()).cloned();
        let (Some(slot), Some(template)) = (num(0), num(1)) else { continue };
        if slot < SLOTS || template >= SLOTS {
            crate::diag::log(format!("merge: bad slot row {r:?}"));
            continue;
        }
        let o = ee_core::ram_off(SLOT_TABLE + template * SLOT_SIZE).unwrap();
        let mut entry = [0u8; 0x24];
        entry.copy_from_slice(&c.ram()[o..o + 0x24]);
        let fight_char = field(&entry, 0, true);
        if let Some(ch) = num(2) {
            entry[0..2].copy_from_slice(&(ch as u16).to_le_bytes());
        }
        if let Some(co) = num(3) {
            entry[2..4].copy_from_slice(&(co as u16).to_le_bytes());
        }
        if let Some(nm) = num(4) {
            entry[4..8].copy_from_slice(&nm.to_le_bytes());
            if nm >= NAMES {
                if let Some(t) = text(5) {
                    names.short.push((nm, put_str(c, &t)));
                }
                if let Some(t) = text(6) {
                    names.upper.push((nm, put_str(c, &t)));
                }
                if let Some(t) = text(7) {
                    names.full.push((nm, put_str(c, &t)));
                }
            }
        }
        let ch = field(&entry, 0, true);
        if let Some(label) = text(8) {
            if ch > CHAR_RECORDS && chars.iter().all(|(id, _)| *id != ch) {
                let l = put_str(c, &format!("|name_{label}_L"));
                let r = put_str(c, &format!("|name_{label}_R"));
                let row = MOD_NAME_TABLE + 12 * name_rows;
                wr32(c, row, ch);
                wr32(c, row + 4, l);
                wr32(c, row + 8, r);
                name_rows += 1;
            }
        }
        if ch > CHAR_RECORDS {
            match chars.iter_mut().find(|(id, _)| *id == ch) {
                Some((_, v)) => v.push(slot),
                None => chars.push((ch, vec![slot])),
            }
        }
        ext.push(ExtSlot { slot, template, entry, fight_char });
    }
    // character records {u32 slot list, u16 costumes, u16 unlocked costumes} + slot lists
    let mut ext_chars = Vec::new();
    let mut list_at = MOD_CHARS + 8 * chars.len() as u32;
    // the select screen picks costumes from a table made for at least two (FUN_0024c500): a
    // character with one slot gets it twice
    for (_, slots) in chars.iter_mut() {
        if slots.len() == 1 {
            slots.push(slots[0]);
        }
    }
    for (k, (id, slots)) in chars.iter().enumerate() {
        let rec = MOD_CHARS + 8 * k as u32;
        wr32(c, rec, list_at);
        wr32(c, rec + 4, slots.len() as u32 | (slots.len() as u32) << 16);
        for (i, s) in slots.iter().enumerate() {
            wr32(c, list_at + 4 * i as u32, *s);
        }
        list_at += 4 * slots.len() as u32;
        ext_chars.push(ExtChar { id: *id, record: rec });
    }
    assert!(list_at <= MOD_STRINGS, "merge: character area full");
    // select grid
    let grid = rows(&dir.join("grid.csv"));
    if !grid.is_empty() {
        let mut n = 0;
        for r in &grid {
            let v: Vec<i32> = r.iter().filter_map(|x| x.parse().ok()).collect();
            let [cell, ch, up, down, left, right] = v[..] else {
                crate::diag::log(format!("merge: bad grid row {r:?}"));
                continue;
            };
            let a = MOD_GRID + 6 * cell as u32;
            wr_bytes(c, a, &[(ch & 0xFF) as u8, (ch >> 8) as u8, up as u8, down as u8, left as u8, right as u8]);
            n = n.max(cell as u32 + 1);
        }
        assert!(MOD_GRID + 6 * n <= MOD_CHARS, "merge: grid area full");
        for m in 0..6 {
            wr32(c, GRID_MODES + 8 * m, MOD_GRID);
            wr32(c, GRID_MODES + 8 * m + 4, n);
        }
    }
    // costume parameters: originals, new slots from their template
    for i in 0..SLOTS * 3 {
        wr32(c, SLOT_PARAMS + 4 * i, rd32(c, SLOT_PARAMS_ORIG + 4 * i));
    }
    for e in &ext {
        assert!(e.slot < SLOT_PARAMS_N, "merge: slot {} beyond the costume parameter table", e.slot);
        for k in 0..3 {
            wr32(c, SLOT_PARAMS + 12 * e.slot + 4 * k, rd32(c, SLOT_PARAMS_ORIG + 12 * e.template + 4 * k));
        }
    }
    // loading screen portraits
    for i in 0..66 {
        let o = ee_core::ram_off(LOAD_PORTRAITS_ORIG + i).unwrap();
        let b = c.ram()[o];
        wr_bytes(c, LOAD_PORTRAITS + i, &[b]);
    }
    for e in &ext {
        let idx = field(&e.entry, 4, false);
        if (NAMES..NAMES + 40).contains(&idx) {
            let pic = 43 + 2 * (idx - NAMES);
            wr_bytes(c, LOAD_PORTRAITS + 2 * idx, &[pic as u8, pic as u8 + 1]);
        }
    }
    // big select portraits
    for i in 0..PTABLE_SIZE / 4 {
        wr32(c, PTABLE + 4 * i, 0);
    }
    *PORTRAITS.lock().unwrap() = std::fs::read(dir.join("select/portraits_0082.bin")).ok().map(|b| {
        let n = u32::from_le_bytes(b[0..4].try_into().unwrap());
        let e = (0..n)
            .map(|i| {
                let o = 4 + 8 * i as usize;
                (u32::from_le_bytes(b[o..o + 4].try_into().unwrap()), u32::from_le_bytes(b[o + 4..o + 8].try_into().unwrap()))
            })
            .collect();
        assert!(PORTRAIT_BLOB + b.len() as u32 <= PORTRAIT_BLOB_END, "merge: portrait blob too large");
        (b, e)
    });
    crate::diag::log(format!("merge: {} new slots, {} new characters, {} grid cells", ext.len(), ext_chars.len(), grid.len()));
    *EXT.lock().unwrap() = ext;
    *EXT_CHARS.lock().unwrap() = ext_chars;
    *EXT_NAMES.lock().unwrap() = names;
}

fn field(e: &[u8; 0x24], off: usize, half: bool) -> u32 {
    if half {
        u16::from_le_bytes(e[off..off + 2].try_into().unwrap()) as u32
    } else {
        u32::from_le_bytes(e[off..off + 4].try_into().unwrap())
    }
}

/// All slot entries (the original ones from RAM, then the new ones) for the searches.
fn all_entries(c: &Ctx) -> Vec<[u8; 0x24]> {
    let mut v = Vec::new();
    for i in 0..SLOTS {
        let o = ee_core::ram_off(SLOT_TABLE + i * SLOT_SIZE).unwrap();
        let mut e = [0u8; 0x24];
        e.copy_from_slice(&c.ram()[o..o + 0x24]);
        v.push(e);
    }
    v.extend(EXT.lock().unwrap().iter().map(|e| e.entry));
    v
}

/// T5_FORCE_SLOT=<player>:<slot>[,...] (testing): the character select result of a player.
fn forced_slot(player: u32) -> Option<u32> {
    let v = std::env::var("T5_FORCE_SLOT").ok()?;
    v.split(',').find_map(|p| {
        let (a, b) = p.split_once(':')?;
        if a.parse::<u32>().ok()? == player { b.parse().ok() } else { None }
    })
}

/// Pointer to the new name `idx` of table `kind` ("upper", "full", "short").
fn name_ptr(kind: &str, idx: u32) -> Option<u32> {
    let n = EXT_NAMES.lock().unwrap();
    let t = match kind {
        "upper" => &n.upper,
        "full" => &n.full,
        _ => &n.short,
    };
    t.iter().find(|(i, _)| *i == idx).map(|&(_, p)| p)
}

fn rd16(c: &Ctx, addr: u32) -> u16 {
    let o = ee_core::ram_off(addr).expect("merge: address outside RAM");
    u16::from_le_bytes(c.ram()[o..o + 2].try_into().unwrap())
}

/// Hooks on the slot table's accessor functions (sheets/hle.csv): for slots >= 80 they answer
/// from the extension (or run the original with the template slot); searches include it.
pub fn slot_hook(c: &mut Ctx, name: &str) -> bool {
    let a0 = c.gpr32(GPR_A0);
    let get = match name {

        "merge_slot_f6p" => Some((rd16(c, a0 + 0x42) as u32, 12, false)),
        "merge_slot_f8p" => Some((rd16(c, a0 + 0x42) as u32, 16, false)),
        "merge_slot_f0" => Some((a0, 0, true)),
        "merge_slot_f1" => Some((a0, 2, true)),
        "merge_slot_f2" => Some((a0, 4, false)),
        "merge_slot_f10" => Some((a0, 20, false)),
        "merge_slot_f14" => Some((a0, 28, true)),
        "merge_slot_f12" => Some((a0, 24, false)),
        _ => None,
    };
    // FUN_00218c20(player): the character of the player's slot = the player's +0x40
    if name == "merge_slot_f0p" {
        let slot = rd16(c, a0 + 0x42) as u32;
        if slot < SLOTS {
            return false;
        }
        let Some(e) = ext_slot(slot) else { return false };
        c.set_gpr32(GPR_V0, e.fight_char);
        return true;
    }
    if let Some((slot, off, half)) = get {
        if slot < SLOTS {
            return false;
        }
        let Some(e) = ext_slot(slot) else { return false };
        c.set_gpr32(GPR_V0, field(&e.entry, off, half));
        return true;
    }
    match name {
        // FUN_00218c58: field 4 of the player's slot (Mokujin's own rule stays with the original)
        "merge_slot_f4p" => {
            let slot = rd16(c, a0 + 0x42) as u32;
            if slot < SLOTS || rd16(c, a0 + 0x40) == 0x12 {
                return false;
            }
            let Some(e) = ext_slot(slot) else { return false };
            c.set_gpr32(GPR_V0, field(&e.entry, 8, false));
            true
        }
        // FUN_00218d18 / d60 / da8: name of the slot (by its field 2)
        "merge_slot_upper" | "merge_slot_full" | "merge_slot_short" if a0 >= SLOTS => {
            let Some(e) = ext_slot(a0) else { return false };
            let idx = field(&e.entry, 4, false);
            if idx < NAMES {
                c.set_gpr32(GPR_A0, e.template);
                return false;
            }
            c.set_gpr32(GPR_V0, name_ptr(&name[11..], idx).unwrap_or(0));
            true
        }
        // FUN_00239230 / 248 / 260: name tables by field 2
        "merge_name_upper" | "merge_name_full" | "merge_name_short" if a0 >= NAMES => {
            match name_ptr(&name[11..], a0) {
                Some(p) => {
                    c.set_gpr32(GPR_V0, p);
                    true
                }
                None => false,
            }
        }
        // FUN_00218ac8(char): the character's record (slots per costume)
        "merge_char_record" if a0 > CHAR_RECORDS => {
            match EXT_CHARS.lock().unwrap().iter().find(|e| e.id == a0) {
                Some(e) => {
                    c.set_gpr32(GPR_V0, e.record);
                    true
                }
                None => false,
            }
        }
        // FUN_00218c10(char): unlocked (bit mask of 32 characters)
        "merge_char_unlocked" if a0 > CHAR_RECORDS => {
            let known = EXT_CHARS.lock().unwrap().iter().any(|e| e.id == a0);
            c.set_gpr32(GPR_V0, known as u32);
            true
        }
        // calls through the entry (behaviour function): run the original with the template slot
        "merge_slot_call" => {
            if a0 >= SLOTS {
                if let Some(e) = ext_slot(a0) {
                    c.set_gpr32(GPR_A0, e.template);
                }
            }
            false
        }
        "merge_find_f2_by_char" | "merge_find_f12_by_char" => {
            let ch = (a0 & 0xFFFF) as i16;
            let off = if name == "merge_find_f2_by_char" { 4 } else { 24 };
            let hit = all_entries(c).into_iter().find(|e| field(e, 0, true) as i16 == ch);
            let dflt = if off == 4 { 0 } else { 0x1E };
            c.set_gpr32(GPR_V0, hit.map(|e| field(&e, off, false)).unwrap_or(dflt));
            true
        }
        "merge_find_char_by_f12" => {
            let hit = all_entries(c).into_iter().find(|e| field(e, 24, false) == a0);
            c.set_gpr32(GPR_V0, hit.map(|e| field(&e, 0, true)).unwrap_or(0x20));
            true
        }
        "merge_find_f12_by_f2" => {
            let hit = all_entries(c).into_iter().find(|e| field(e, 4, false) == a0);
            c.set_gpr32(GPR_V0, hit.map(|e| field(&e, 24, false)).unwrap_or(0x1E));
            true
        }
        // FUN_002965d8(table, slot, n): registers the big portraits (relocated table); first
        // brings the new portraits behind the packed file 82
        "merge_ptable_register" => {
            if a0 == PTABLE_ORIG {
                c.set_gpr32(GPR_A0, PTABLE);
                if rd32(c, PTABLE) == 0 {
                    if let Some((b, _)) = PORTRAITS.lock().unwrap().as_ref() {
                        wr_bytes(c, PORTRAIT_BLOB, b);
                    }
                }
            }
            false
        }
        "merge_ptable_free" => {
            if a0 == PTABLE_ORIG {
                c.set_gpr32(GPR_A0, PTABLE);
            }
            false
        }
        // FUN_00296788(table, name index, side): the portrait entry (original: index < 0x21)
        "merge_ptable_get" => {
            if a0 != PTABLE_ORIG {
                return false;
            }
            let (idx, side) = (c.gpr32(GPR_A0 + 1), c.gpr32(GPR_A0 + 2) & 1);
            let t = PTABLE;
            let w = |i: u32| rd32(c, t + 4 * i);
            let mut v = 0;
            if idx < (PTABLE_SIZE - 8) / 40 && w(0) != 0 {
                let l = idx * 10 + 2;
                if side == 0 {
                    if w(l + 1) != 0 {
                        v = t + 4 * l;
                    }
                } else {
                    let r = idx * 10 + 7;
                    v = t + 4 * r;
                    if w(r + 1) == 0 {
                        v = if w(l + 1) != 0 { t + 4 * l } else { 0 };
                    }
                }
            }
            c.set_gpr32(GPR_V0, v);
            true
        }
        // FUN_0025f450 / 428 / 458: count, entry, size of a container; file 82 gets more entries
        "merge_container_count" if a0 == PORTRAIT_CONTAINER => match PORTRAITS.lock().unwrap().as_ref() {
            Some((_, e)) => {
                c.set_gpr32(GPR_V0, PORTRAIT_ENTRIES + e.len() as u32);
                true
            }
            None => false,
        },
        "merge_container_entry" | "merge_container_size" if c.gpr32(GPR_A0 + 1) == PORTRAIT_CONTAINER && a0 >= PORTRAIT_ENTRIES => {
            let k = (a0 - PORTRAIT_ENTRIES) as usize;
            let (off, size) = PORTRAITS.lock().unwrap().as_ref().and_then(|(_, e)| e.get(k).copied()).unwrap_or((0, 0));
            let v = if name == "merge_container_size" { size } else if size != 0 { PORTRAIT_BLOB + off } else { 0 };
            c.set_gpr32(GPR_V0, v);
            true
        }
        // FUN_00219910(player): the character select result (test override)
        "merge_select_result" => match forced_slot(a0) {
            Some(slot) => {
                c.set_gpr32(GPR_V0, slot);
                true
            }
            None => false,
        },
        _ => false,
    }
}
