//! GS drawing: rasterization of the kicked primitive and the per-pixel pipeline
//! (texture -> texture function -> fog -> alpha test -> destination alpha test -> depth test ->
//! alpha blend -> dither / clamp -> frame and depth writes, with FBMSK / ZMSK).
//!
//! Coordinates are 12.4 fixed point after XYOFFSET; a pixel is covered when its top-left corner
//! (integer coordinate) lies inside the primitive, with the top-left fill rule.

use crate::gs::*;
use rayon::prelude::*;

/// Batches whose primitives cover more pixels than this are drawn by all cores, one screen
/// tile per task (each tile runs the batch's primitives in order, clipped to the tile).
const PARALLEL_PIXELS: i64 = 4096;
/// Tile size in pixels.
const TILE_W: i32 = 64;
const TILE_H: i32 = 32;
/// Most primitives queued before a flush.
const MAX_BATCH: usize = 4096;

#[derive(Clone, Copy)]
struct GsPtr(*mut Gs);
unsafe impl Send for GsPtr {}
unsafe impl Sync for GsPtr {}

impl GsPtr {
    #[allow(clippy::mut_from_ref)]
    fn get(&self) -> &mut Gs {
        unsafe { &mut *self.0 }
    }
}

/// Pixel rectangle [x0, x1) x [y0, y1) a primitive is drawn into.
#[derive(Clone, Copy)]
struct Clip {
    x0: i32,
    y0: i32,
    x1: i32,
    y1: i32,
}

const NO_CLIP: Clip = Clip { x0: i32::MIN, y0: i32::MIN, x1: i32::MAX, y1: i32::MAX };

/// Run `row` for every row in [y0, y1).
#[inline(always)]
fn rows(gs: &mut Gs, y0: i64, y1: i64, width: i64, mut row: impl FnMut(&mut Gs, i64)) {
    let (k, n) = OWN.with(|o| o.get());
    if k == 0 {
        PIXELS.fetch_add(((y1 - y0).max(0) * width.max(0)) as u64, std::sync::atomic::Ordering::Relaxed);
    }
    if n == 1 {
        for y in y0..y1 {
            row(gs, y);
        }
        return;
    }
    // This worker's bands of BAND rows (band b belongs to worker b % n).
    let band = BAND as i64;
    let mut b = y0.max(0) / band;
    while b * band < y1 {
        if b as u64 % n as u64 == k as u64 {
            for y in (b * band).max(y0)..((b + 1) * band).min(y1) {
                row(gs, y);
            }
            b += n as i64;
        } else {
            b += 1;
        }
    }
}

/// Rows per band of the interleaved row ownership (PCSX2 GSRasterizerList thread height).
const BAND: i32 = 8;

thread_local! {
    /// (worker index, worker count) of a raster worker thread; (0, 1) elsewhere = all rows.
    static OWN: std::cell::Cell<(u32, u32)> = const { std::cell::Cell::new((0, 1)) };
}

#[inline(always)]
fn owns_row(y: i32) -> bool {
    let (k, n) = OWN.with(|o| o.get());
    n == 1 || (y.max(0) / BAND) as u32 % n == k
}

/// Persistent raster workers (PCSX2 GSRasterizerList): every worker draws every batch, in
/// order, but only its own interleaved bands of rows, so batches need no barrier between them.
/// The GS thread waits only when something must see local memory (`wait`), or when a batch
/// for another frame / depth buffer would touch pages a batch in flight uses.
pub struct Workers {
    txs: Vec<std::sync::mpsc::Sender<std::sync::Arc<Vec<Queued>>>>,
    done: std::sync::Arc<Vec<std::sync::atomic::AtomicU64>>,
    sent: u64,
    /// Pages (frame / depth) of the batches in flight, and the buffers of the last one.
    inflight: [u64; 8],
    last_key: Option<(u32, u32, u32, u32, u32, bool)>,
}

impl Workers {
    fn start(gs: &mut Gs) -> Workers {
        let cores = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4);
        // T5_RASTER_THREADS=<n>: pool size for measurements.
        let n = std::env::var("T5_RASTER_THREADS").ok().and_then(|v| v.parse().ok()).unwrap_or(cores.saturating_sub(3).max(2));
        let done: std::sync::Arc<Vec<std::sync::atomic::AtomicU64>> = std::sync::Arc::new((0..n).map(|_| std::sync::atomic::AtomicU64::new(0)).collect());
        let mut txs = Vec::new();
        for k in 0..n {
            let (tx, rx) = std::sync::mpsc::channel::<std::sync::Arc<Vec<Queued>>>();
            txs.push(tx);
            let p = GsPtr(gs);
            let done = done.clone();
            std::thread::Builder::new()
                .name(format!("raster{k}"))
                .spawn(move || {
                    #[cfg(windows)]
                    if k == 0 {
                        #[link(name = "kernel32")]
                        unsafe extern "system" {
                            fn GetCurrentThreadId() -> u32;
                        }
                        crate::gs::RASTER_OS_TID.store(unsafe { GetCurrentThreadId() }, std::sync::atomic::Ordering::Relaxed);
                    }
                    OWN.with(|o| o.set((k as u32, n as u32)));
                    let p = p;
                    let mut seq = 0u64;
                    while let Ok(items) = rx.recv() {
                        let t1 = std::time::Instant::now();
                        for q in items.iter() {
                            // Skip primitives without a row of this worker.
                            let (y0, y1) = (q.bbox.y0.max(0), q.bbox.y1);
                            if y1 - y0 < BAND * n as i32 {
                                let mut any = false;
                                let mut b = y0 / BAND;
                                while b * BAND < y1 {
                                    if b as u32 % n as u32 == k as u32 {
                                        any = true;
                                        break;
                                    }
                                    b += 1;
                                }
                                if !any {
                                    continue;
                                }
                            }
                            draw_queued(p.get(), q, &NO_CLIP);
                        }
                        TILE_US.fetch_add(t1.elapsed().as_micros() as u64, std::sync::atomic::Ordering::Relaxed);
                        seq += 1;
                        done[k].store(seq, std::sync::atomic::Ordering::Release);
                    }
                })
                .expect("raster worker");
        }
        Workers { txs, done, sent: 0, inflight: [0; 8], last_key: None }
    }

    fn idle(&self) -> bool {
        self.done.iter().all(|d| d.load(std::sync::atomic::Ordering::Acquire) >= self.sent)
    }
}

/// A primitive waiting in the batch: its resolved state, vertices (after XYOFFSET) and the
/// pixel bounding box it can touch (scissored).
struct Queued {
    st: std::sync::Arc<Setup>,
    kind: u32,
    vs: [Vertex; 3],
    bbox: Clip,
}

/// Primitives queued for drawing. All write the same frame / depth buffers (`key`), so pixels of
/// different screen tiles are different memory and the tiles can be drawn in parallel. The batch
/// is flushed before anything else touches local memory (transfers, CLUT loads, the display
/// read-out, decoding a texture whose pages it wrote).
#[derive(Default)]
pub struct Batch {
    items: Vec<Queued>,
    key: (u32, u32, u32, u32, u32, bool),
    area: i64,
    /// The frame and depth buffers overlap: draw in order on one core.
    serial: bool,
    /// Pages (of 512) the batch reads or writes as frame / depth buffer.
    pages: [u64; 8],
}

/// Per-primitive state resolved from the registers.
pub(crate) struct Setup {
    tme: bool,
    gouraud: bool,
    fge: bool,
    abe: bool,
    fst: bool,
    ctx: Context,
    // FRAME / ZBUF
    fbp: u32,
    fbw: u32,
    fpsm: u32,
    fbmsk: u32,
    zbp: u32,
    zpsm: u32,
    zmsk: bool,
    // TEST
    ate: bool,
    atst: u32,
    aref: u32,
    afail: u32,
    date: bool,
    datm: bool,
    zte: bool,
    ztst: u32,
    // ALPHA
    aa: u32,
    ab: u32,
    ac: u32,
    ad: u32,
    afix: u32,
    pabe: bool,
    fba: bool,
    colclamp: bool,
    dthe: bool,
    dimx: [[i32; 4]; 4],
    fogcol: [u32; 3],
    // scissor (pixels)
    sx0: i32,
    sx1: i32,
    sy0: i32,
    sy1: i32,
    tex: Option<Tex>,
    /// Largest depth value of the Z format (as f64, for clamping).
    zmax: f64,
    /// The pixel function for this primitive's state (see `plot_fn`).
    plot: PlotFn,
}

#[derive(Clone)]
struct Tex {
    tbp: u32,
    tbw: u32,
    psm: u32,
    tw: u32,
    th: u32,
    tcc: bool,
    tfx: u32,
    wms: u32,
    wmt: u32,
    minu: i32,
    maxu: i32,
    minv: i32,
    maxv: i32,
    aem: bool,
    ta0: u32,
    ta1: u32,
    mmag: bool,
    mmin: u32,
    mxl: u32,
    lcm: bool,
    l: u32,
    k: f32,
    mip: [(u32, u32); 7],
    /// Decoded levels (RGBA8 after CLUT / TEXA), from the texture cache.
    img: [Option<std::sync::Arc<TexImg>>; 7],
    /// Level 0 size as f32 (STQ scaling).
    wf: f32,
    hf: f32,
    /// (filter, level) when the LOD does not depend on Q (LCM, or no mipmaps and the same
    /// filter both ways): fixed for the primitive.
    fixed_lod: Option<(bool, usize)>,
}

/// The state for the kicked primitive: the previous one's while every register it depends on is
/// unchanged and its textures' pages were not written since.
fn cached_setup(gs: &mut Gs) -> std::sync::Arc<Setup> {
    let a = gs.attrs();
    let c = &gs.ctx[((a >> 9) & 1) as usize];
    let key = [
        a, c.tex0, c.clamp, c.tex1, c.xyoffset, c.miptbp1, c.miptbp2, c.scissor, c.alpha, c.test, c.fba, c.frame, c.zbuf, gs.dimx, gs.fogcol,
        gs.pabe | gs.colclamp << 1 | gs.dthe << 2, gs.texa, gs.clut_hash, 0,
    ];
    if let Some((k, st)) = gs.st_cache.as_ref() {
        if *k == key && gs.st_valid.load(std::sync::atomic::Ordering::Relaxed) {
            return st.clone();
        }
    }
    let st = std::sync::Arc::new(setup(gs));
    // The pages its texture levels cover: a write there invalidates the cached state.
    let mut pages = [0u64; 8];
    if let Some(t) = st.tex.as_ref() {
        let levels = if t.mxl > 0 && t.mmin >= 2 { (t.mxl as usize).min(6) + 1 } else { 1 };
        for l in 0..levels {
            let (first, n) = tex_pages(t, l);
            for i in 0..n.min(512) {
                let p = (first + i) & 511;
                pages[p >> 6] |= 1 << (p & 63);
            }
        }
    }
    gs.st_pages = pages;
    gs.st_valid.store(true, std::sync::atomic::Ordering::Relaxed);
    gs.st_cache = Some((key, st.clone()));
    st
}

/// First page and page count a texture level covers (as `cached_level` checks them).
fn tex_pages(t: &Tex, l: usize) -> (usize, usize) {
    let (tbp, tbw) = if l == 0 { (t.tbp, t.tbw) } else { t.mip[l] };
    let w = 1u32 << t.tw.saturating_sub(l as u32).min(10);
    let h = 1u32 << t.th.saturating_sub(l as u32).min(10);
    let (pw, ph) = page_dims(t.psm);
    let stride = match t.psm { PSMT8 | PSMT4 => (tbw / 2).max(1), _ => tbw.max(1) }.max(w.div_ceil(pw));
    ((tbp / 32) as usize, (stride * h.div_ceil(ph)) as usize)
}

fn setup(gs: &mut Gs) -> Setup {
    let a = gs.attrs();
    let ctx = gs.ctx[((a >> 9) & 1) as usize];
    let frame = ctx.frame;
    let zbuf = ctx.zbuf;
    let test = ctx.test;
    let alpha = ctx.alpha;
    let sc = ctx.scissor;
    let mut dimx = [[0i32; 4]; 4];
    for y in 0..4 {
        for x in 0..4 {
            let v = ((gs.dimx >> (16 * y + 4 * x)) & 7) as i32;
            dimx[y][x] = if v & 4 != 0 { v - 8 } else { v };
        }
    }
    let tme = a & 0x10 != 0;
    let tex = tme.then(|| {
        let t0 = ctx.tex0;
        let t1 = ctx.tex1;
        let cl = ctx.clamp;
        let mut mip = [(0u32, 0u32); 7];
        mip[0] = ((t0 & 0x3FFF) as u32, ((t0 >> 14) & 0x3F) as u32);
        for i in 0..3 {
            mip[1 + i] = (((ctx.miptbp1 >> (20 * i)) & 0x3FFF) as u32, ((ctx.miptbp1 >> (20 * i + 14)) & 0x3F) as u32);
            mip[4 + i] = (((ctx.miptbp2 >> (20 * i)) & 0x3FFF) as u32, ((ctx.miptbp2 >> (20 * i + 14)) & 0x3F) as u32);
        }
        let k = ((t1 >> 32) & 0xFFF) as i32;
        let k = if k & 0x800 != 0 { k - 0x1000 } else { k };
        Tex {
            tbp: (t0 & 0x3FFF) as u32,
            tbw: ((t0 >> 14) & 0x3F) as u32,
            psm: ((t0 >> 20) & 0x3F) as u32,
            tw: ((t0 >> 26) & 0xF) as u32,
            th: ((t0 >> 30) & 0xF) as u32,
            tcc: (t0 >> 34) & 1 != 0,
            tfx: ((t0 >> 35) & 3) as u32,
            wms: (cl & 3) as u32,
            wmt: ((cl >> 2) & 3) as u32,
            minu: ((cl >> 4) & 0x3FF) as i32,
            maxu: ((cl >> 14) & 0x3FF) as i32,
            minv: ((cl >> 24) & 0x3FF) as i32,
            maxv: ((cl >> 34) & 0x3FF) as i32,
            aem: (gs.texa >> 15) & 1 != 0,
            ta0: (gs.texa & 0xFF) as u32,
            ta1: ((gs.texa >> 32) & 0xFF) as u32,
            mmag: (t1 >> 5) & 1 != 0,
            mmin: ((t1 >> 6) & 7) as u32,
            mxl: ((t1 >> 2) & 7) as u32,
            lcm: t1 & 1 != 0,
            l: ((t1 >> 19) & 3) as u32,
            k: k as f32 / 16.0,
            mip,
            img: Default::default(),
            wf: (1u32 << (((t0 >> 26) & 0xF) as u32).min(10)) as f32,
            hf: (1u32 << (((t0 >> 30) & 0xF) as u32).min(10)) as f32,
            fixed_lod: None,
        }
    });
    let mut tex = tex;
    if let Some(t) = tex.as_mut() {
        t.fixed_lod = lod_select(t, None);
        let levels = if t.mxl > 0 && t.mmin >= 2 { (t.mxl as usize).min(6) + 1 } else { 1 };
        for l in 0..levels {
            t.img[l] = Some(cached_level(gs, t, l));
        }
    }
    Setup {
        tme,
        gouraud: a & 8 != 0,
        fge: a & 0x20 != 0,
        abe: a & 0x40 != 0,
        fst: a & 0x100 != 0,
        ctx,
        fbp: ((frame & 0x1FF) * 32) as u32,
        fbw: ((frame >> 16) & 0x3F) as u32,
        fpsm: ((frame >> 24) & 0x3F) as u32,
        fbmsk: (frame >> 32) as u32,
        zbp: ((zbuf & 0x1FF) * 32) as u32,
        zpsm: (((zbuf >> 24) & 0xF) | 0x30) as u32,
        zmsk: (zbuf >> 32) & 1 != 0,
        ate: test & 1 != 0,
        atst: ((test >> 1) & 7) as u32,
        aref: ((test >> 4) & 0xFF) as u32,
        afail: ((test >> 12) & 3) as u32,
        date: (test >> 14) & 1 != 0,
        datm: (test >> 15) & 1 != 0,
        zte: (test >> 16) & 1 != 0,
        ztst: ((test >> 17) & 3) as u32,
        aa: (alpha & 3) as u32,
        ab: ((alpha >> 2) & 3) as u32,
        ac: ((alpha >> 4) & 3) as u32,
        ad: ((alpha >> 6) & 3) as u32,
        afix: ((alpha >> 32) & 0xFF) as u32,
        pabe: gs.pabe & 1 != 0,
        fba: ctx.fba & 1 != 0,
        colclamp: gs.colclamp & 1 != 0,
        dthe: gs.dthe & 1 != 0,
        dimx,
        fogcol: [(gs.fogcol & 0xFF) as u32, ((gs.fogcol >> 8) & 0xFF) as u32, ((gs.fogcol >> 16) & 0xFF) as u32],
        sx0: (sc & 0x7FF) as i32,
        sx1: ((sc >> 16) & 0x7FF) as i32,
        sy0: ((sc >> 32) & 0x7FF) as i32,
        sy1: ((sc >> 48) & 0x7FF) as i32,
        tex,
        zmax: match (((zbuf >> 24) & 0xF) | 0x30) as u32 {
            PSMZ32 => u32::MAX as f64,
            PSMZ24 => 0xFF_FFFF as f64,
            _ => 0xFFFF as f64,
        },
        plot: plot_fn(tme, test & 1 != 0, (test >> 16) & 1 != 0, a & 0x40 != 0, a & 0x20 != 0),
    }
}

/// Interpolated attributes at a pixel.
#[derive(Clone, Copy, Default)]
struct Frag {
    z: f64,
    r: f32,
    g: f32,
    b: f32,
    a: f32,
    s: f32,
    t: f32,
    q: f32,
    f: f32,
}

fn frag_of(v: &Vertex, st: &Setup) -> Frag {
    let (s, t, q) = if st.fst { (v.u as f32 / 16.0, v.v as f32 / 16.0, 1.0) } else { (v.s, v.t, v.q) };
    Frag { z: v.z as f64, r: v.r as f32, g: v.g as f32, b: v.b as f32, a: v.a as f32, s, t, q, f: v.f as f32 }
}

pub fn draw(gs: &mut Gs, kind: u32) {
    let t0 = std::time::Instant::now();
    queue(gs, kind);
    crate::diag::TIME[5].fetch_add(t0.elapsed().as_micros() as u64, std::sync::atomic::Ordering::Relaxed);
    GS_US[0].fetch_add(t0.elapsed().as_micros() as u64, std::sync::atomic::Ordering::Relaxed);
}

/// GS thread time (µs): queue (setup, texture decode, flushes it triggers), parallel flushes,
/// serial flushes, image transfers, display read-out.
pub static GS_US: [std::sync::atomic::AtomicU64; 5] = [const { std::sync::atomic::AtomicU64::new(0) }; 5];
/// Pixels inside drawn spans (sprites, triangles).
pub static COVERED: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
/// Summed tile work in parallel flushes (µs, over all threads) and tiles drawn.
pub static TILE_US: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
pub static TILES: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
/// Batches flushed (parallel, serial) and their primitives.
pub static FLUSHES: [std::sync::atomic::AtomicU64; 3] = [const { std::sync::atomic::AtomicU64::new(0) }; 3];

/// Resolve the kicked primitive and queue it.
fn queue(gs: &mut Gs, kind: u32) {
    PRIMS.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let st = cached_setup(gs);
    let ofx = (st.ctx.xyoffset & 0xFFFF) as i32;
    let ofy = ((st.ctx.xyoffset >> 32) & 0xFFFF) as i32;
    let n = match kind { 0 => 1, 1 | 2 | 6 => 2, _ => 3 };
    let mut vs = [Vertex::default(); 3];
    for (i, v) in gs.verts.iter().rev().take(n).rev().enumerate() {
        vs[i] = *v;
        vs[i].x -= ofx;
        vs[i].y -= ofy;
    }
    let (mut x0, mut x1, mut y0, mut y1) = (i32::MAX, i32::MIN, i32::MAX, i32::MIN);
    for v in &vs[..n] {
        x0 = x0.min(v.x >> 4);
        x1 = x1.max((v.x + 15) >> 4);
        y0 = y0.min(v.y >> 4);
        y1 = y1.max((v.y + 15) >> 4);
    }
    // Game frames: a sprite pass starting at the top-left corner of the displayed buffer.
    if kind == 6 && x0 <= 0 && y0 <= 0 && st.fbp == ((gs.dispfb[1] & 0x1FF) * 32) as u32 && st.tme {
        GAME_FRAMES.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        // A copy pass onto the displayed buffer: its source was drawn anew since the last copy
        // = one real game frame (the copies themselves repeat every field, shifted for
        // interlacing, so displayed pictures always differ).
        if let Some(t) = st.tex.as_ref() {
            let (first, n) = tex_pages(t, 0);
            let mut sum = first as u64;
            for i in 0..n.min(512) {
                sum = sum.wrapping_mul(31).wrapping_add(gs.page_gen[(first + i) & 511].load(std::sync::atomic::Ordering::Relaxed) as u64);
            }
            let changed = LAST_COPY_SRC.swap(sum, std::sync::atomic::Ordering::Relaxed) != sum;
            crate::diag::tl(if changed { "C new" } else { "C same" });
            if changed {
                RENDERED.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                RENDERED_TOTAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
            }
        }
    }
    if crate::diag::enabled("T5_STATELOG") {
        let t = st.tex.as_ref();
        crate::diag::count_with(|| format!(
            "st_k{}_tme{}_tfx{}_tcc{}_flt{}_psm{:x}_fst{}_abe{}_al{:x}_ate{}_atst{}_zte{}_ztst{}_zmsk{}_fpsm{:x}_zpsm{:x}_fge{}_iip{}_msk{:x}",
            kind, st.tme as u8, t.map_or(9, |t| t.tfx), t.map_or(9, |t| t.tcc as u32), t.map_or(9, |t| t.mmag as u32), t.map_or(0, |t| t.psm),
            st.fst as u8, st.abe as u8, st.ctx.alpha & 0xFF, st.ate as u8, st.atst, st.zte as u8, st.ztst, st.zmsk as u8, st.fpsm, st.zpsm, st.fge as u8, st.gouraud as u8, st.fbmsk
        ));
    }
    if crate::diag::enabled("T5_TEXLOG") {
        if let Some(t) = st.tex.as_ref() {
            let v = &vs[n - 1];
            crate::diag::once(format!("TEX k{} fbp {:#x} tbp {:#x} tbw {} psm {:#x} {}x{} tcc {} tfx {} cbp {:#x} cpsm {:#x} csm {} csa {} texa {:#x} abe {} alpha {:#x} rgba ({},{},{},{}) fst {}",
                kind, st.fbp, t.tbp, t.tbw, t.psm, 1 << t.tw, 1 << t.th, t.tcc as u8, t.tfx, (gs.clut_tex0 >> 37) & 0x3FFF, (gs.clut_tex0 >> 51) & 0xF, (gs.clut_tex0 >> 55) & 1, (gs.clut_tex0 >> 56) & 0x1F, gs.texa, st.abe as u8, st.ctx.alpha, v.r, v.g, v.b, v.a, st.fst as u8));
        }
    }
    if crate::diag::enabled("T5_PRIMSTATS") {
        crate::diag::count_with(|| format!("prim_k{}_{}x{}_tme{}_abe{}_fbp{:x}_tbp{:x}", kind, x1 - x0, y1 - y0, st.tme as u8, st.abe as u8, st.fbp, st.tex.as_ref().map(|t| t.tbp).unwrap_or(0)));
    }
    // Lines and points can reach one pixel past their end points.
    let bbox = Clip {
        x0: (x0 - 1).max(st.sx0).max(0),
        y0: (y0 - 1).max(st.sy0).max(0),
        x1: (x1 + 1).min(st.sx1 + 1).min(2048),
        y1: (y1 + 1).min(st.sy1 + 1).min(2048),
    };
    if bbox.x0 >= bbox.x1 || bbox.y0 >= bbox.y1 {
        return;
    }
    let zwrite = st.zte && !st.zmsk;
    // Depth writes on / off do not split batches (opaque and blended primitives alternate);
    // a batch is serial if any of its primitives writes depth into overlapping FB / Z pages.
    let key = (st.fbp, st.fbw, st.fpsm, st.zbp, st.zpsm, true);
    if gs.batch.key != key || gs.batch.items.len() >= MAX_BATCH {
        flush(gs);
        gs.batch.key = key;
        gs.batch.serial = false;
    }
    // Frame and depth buffer pages overlapping within the scissor rectangle: one pixel's depth
    // may be another's colour, so the batch is drawn in order on one core.
    if zwrite && !gs.batch.serial {
        let rows = |psm: u32| -> u32 {
            let ph = if matches!(psm, PSMCT16 | PSMCT16S | PSMZ16 | PSMZ16S) { 64 } else { 32 };
            (st.sy1 as u32 + 1).div_ceil(ph)
        };
        // Blocks (32 per page) each buffer spans: width in pages x page rows.
        let fb_end = st.fbp + st.fbw.max(1) * rows(st.fpsm) * 32;
        let z_end = st.zbp + st.fbw.max(1) * rows(st.zpsm) * 32;
        gs.batch.serial = st.fbp < z_end && st.zbp < fb_end;
    }
    // The pages the primitive reads or writes as frame / depth buffer are busy until drawn.
    let pages = &mut gs.batch.pages;
    Gs::for_pages(st.fpsm, st.fbp, st.fbw, bbox.x0 as u32, bbox.y0 as u32, bbox.x1 as u32, bbox.y1 as u32, |p| {
        pages[p >> 6] |= 1 << (p & 63);
        true
    });
    if st.zte {
        Gs::for_pages(st.zpsm, st.zbp, st.fbw, bbox.x0 as u32, bbox.y0 as u32, bbox.x1 as u32, bbox.y1 as u32, |p| {
            pages[p >> 6] |= 1 << (p & 63);
            true
        });
    }
    for i in 0..8 {
        gs.busy_pages[i].fetch_or(gs.batch.pages[i], std::sync::atomic::Ordering::Relaxed);
    }
    // The pages the primitive may write change now (texture cache checks happen at queue time).
    if st.fbmsk != 0xFFFF_FFFF {
        gs.touch_rect(st.fpsm, st.fbp, st.fbw, bbox.x0 as u32, bbox.y0 as u32, bbox.x1 as u32, bbox.y1 as u32);
    }
    if zwrite {
        gs.touch_rect(st.zpsm, st.zbp, st.fbw, bbox.x0 as u32, bbox.y0 as u32, bbox.x1 as u32, bbox.y1 as u32);
    }
    gs.batch.area += ((bbox.x1 - bbox.x0) as i64) * ((bbox.y1 - bbox.y0) as i64);
    gs.batch.items.push(Queued { st, kind, vs, bbox });
}

/// Draw the queued primitives.
/// Draw the queued primitives and wait until they are in local memory (before anything reads
/// it: texture decoding, CLUT loads, transfers, the display read-out).
#[track_caller]
pub fn flush_sync(gs: &mut Gs) {
    flush(gs);
    wait(gs);
    for w in &gs.busy_pages {
        w.store(0, std::sync::atomic::Ordering::Relaxed);
    }
}

/// Wait for the batch drawing in the background, if any.
#[track_caller]
pub fn wait(gs: &mut Gs) {
    let Some(w) = gs.workers.as_mut() else { return };
    if !w.idle() {
        crate::diag::tl("R wait");
        let loc = std::panic::Location::caller();
        crate::diag::count_with(|| format!("rwait_{}:{}", loc.file(), loc.line()));
        let t0 = std::time::Instant::now();
        while !w.idle() {
            std::thread::yield_now();
        }
        crate::diag::tl("R waited");
        GS_US[1].fetch_add(t0.elapsed().as_micros() as u64, std::sync::atomic::Ordering::Relaxed);
    }
    w.inflight = [0; 8];
}

/// Draw the queued primitives. A batch for all cores runs in the background while the GS thread
/// goes on with the next commands; the next batch, and anything that reads local memory, waits
/// for it first (`wait`), so drawing stays in order.
pub fn flush(gs: &mut Gs) {
    if gs.batch.items.is_empty() {
        return;
    }
    let t0 = std::time::Instant::now();
    let batch = std::mem::take(&mut gs.batch);
    gs.batch.key = batch.key;
    FLUSHES[2].fetch_add(batch.items.len() as u64, std::sync::atomic::Ordering::Relaxed);
    if batch.serial || crate::diag::enabled("T5_RASTER_SERIAL") {
        wait(gs);
        for q in &batch.items {
            draw_queued(gs, q, &NO_CLIP);
        }
        FLUSHES[1].fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        GS_US[2].fetch_add(t0.elapsed().as_micros() as u64, std::sync::atomic::Ordering::Relaxed);
        return;
    }
    FLUSHES[0].fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    if gs.workers.is_none() {
        gs.workers = Some(Box::new(Workers::start(gs)));
    }
    // Another frame / depth buffer whose pages a batch in flight uses: rows of different
    // workers would alias, so let the earlier drawing finish first.
    let conflict = {
        let w = gs.workers.as_ref().unwrap();
        w.last_key != Some(batch.key) && (0..8).any(|i| w.inflight[i] & batch.pages[i] != 0)
    };
    if conflict {
        wait(gs);
    }
    let w = gs.workers.as_mut().unwrap();
    for i in 0..8 {
        w.inflight[i] |= batch.pages[i];
    }
    w.last_key = Some(batch.key);
    w.sent += 1;
    crate::diag::tl("R flush");
    let items = std::sync::Arc::new(batch.items);
    for tx in &w.txs {
        let _ = tx.send(items.clone());
    }
    crate::diag::TIME[5].fetch_add(t0.elapsed().as_micros() as u64, std::sync::atomic::Ordering::Relaxed);
}

/// Time (µs) and covered pixels by primitive kind 0..7 (diagnostics).
pub static KIND_US: [std::sync::atomic::AtomicU64; 8] = [const { std::sync::atomic::AtomicU64::new(0) }; 8];
pub static KIND_PX: [std::sync::atomic::AtomicU64; 8] = [const { std::sync::atomic::AtomicU64::new(0) }; 8];

/// Per-pixel / per-primitive raster statistics (shared atomic counters and clock reads in the
/// workers' hot loops): only with T5_RASTER_STATS=1.
#[inline(always)]
fn rstats() -> bool {
    static ON: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ON.get_or_init(|| crate::diag::enabled("T5_RASTER_STATS"))
}

fn draw_queued(gs: &mut Gs, q: &Queued, clip: &Clip) {
    if !rstats() {
        draw_queued_inner(gs, q, clip);
        return;
    }
    let t0 = std::time::Instant::now();
    let c0 = COVERED.load(std::sync::atomic::Ordering::Relaxed);
    draw_queued_inner(gs, q, clip);
    let k = (q.kind & 7) as usize;
    KIND_US[k].fetch_add(t0.elapsed().as_nanos() as u64 / 1000, std::sync::atomic::Ordering::Relaxed);
    let _ = c0;
}

fn draw_queued_inner(gs: &mut Gs, q: &Queued, clip: &Clip) {
    let st = &*q.st;
    let vs = &q.vs;
    let inside = |x: i32, y: i32| x >= clip.x0 && x < clip.x1 && y >= clip.y0 && y < clip.y1;
    match q.kind {
        0 => {
            let v = vs[0];
            let px = (v.x + 8) >> 4;
            let py = (v.y + 8) >> 4;
            if inside(px, py) {
                let f = frag_of(&v, st);
                plot(gs, st, px, py, &f);
            }
        }
        1 | 2 => line(gs, st, &vs[0], &vs[1], clip),
        3 | 4 | 5 => triangle(gs, st, &vs[0], &vs[1], &vs[2], clip),
        6 => sprite(gs, st, &vs[0], &vs[1], clip),
        _ => {}
    }
}

fn line(gs: &mut Gs, st: &Setup, a: &Vertex, b: &Vertex, clip: &Clip) {
    let (x0, y0, x1, y1) = (a.x as f32 / 16.0, a.y as f32 / 16.0, b.x as f32 / 16.0, b.y as f32 / 16.0);
    let n = (x1 - x0).abs().max((y1 - y0).abs()).ceil().max(1.0) as i32;
    let fa = frag_of(a, st);
    let fb = frag_of(b, st);
    for i in 0..n {
        let t = i as f32 / n as f32;
        let px = (x0 + (x1 - x0) * t).round() as i32;
        let py = (y0 + (y1 - y0) * t).round() as i32;
        if px < clip.x0 || px >= clip.x1 || py < clip.y0 || py >= clip.y1 {
            continue;
        }
        let f = if st.gouraud { lerp_frag(&fa, &fb, t) } else { Frag { r: fb.r, g: fb.g, b: fb.b, a: fb.a, ..lerp_frag(&fa, &fb, t) } };
        plot(gs, st, px, py, &f);
    }
}

fn lerp_frag(a: &Frag, b: &Frag, t: f32) -> Frag {
    let l = |x: f32, y: f32| x + (y - x) * t;
    Frag {
        z: a.z + (b.z - a.z) * t as f64,
        r: l(a.r, b.r),
        g: l(a.g, b.g),
        b: l(a.b, b.b),
        a: l(a.a, b.a),
        s: l(a.s, b.s),
        t: l(a.t, b.t),
        q: l(a.q, b.q),
        f: l(a.f, b.f),
    }
}

fn sprite(gs: &mut Gs, st: &Setup, a: &Vertex, b: &Vertex, clip: &Clip) {
    let (mut x0, mut x1) = (a.x, b.x);
    let (mut y0, mut y1) = (a.y, b.y);
    let fa = frag_of(a, st);
    let fb = frag_of(b, st);
    let (mut s0, mut s1, mut t0, mut t1) = (fa.s, fb.s, fa.t, fb.t);
    if x0 > x1 {
        std::mem::swap(&mut x0, &mut x1);
        std::mem::swap(&mut s0, &mut s1);
    }
    if y0 > y1 {
        std::mem::swap(&mut y0, &mut y1);
        std::mem::swap(&mut t0, &mut t1);
    }
    let px0 = ((x0 + 15) >> 4).max(st.sx0).max(clip.x0);
    let px1 = ((x1 + 15) >> 4).min(st.sx1 + 1).min(clip.x1);
    let py0 = ((y0 + 15) >> 4).max(st.sy0).max(clip.y0);
    let py1 = ((y1 + 15) >> 4).min(st.sy1 + 1).min(clip.y1);
    if px0 >= px1 || py0 >= py1 {
        return;
    }
    let dx = (x1 - x0).max(1) as f32;
    let dy = (y1 - y0).max(1) as f32;
    // Per pixel steps (one pixel = 16 units of 12.4).
    let ds = (s1 - s0) * 16.0 / dx;
    let dq = (fb.q - fa.q) * 16.0 / dx;
    if sprite_fast_ok(st) {
        let col = [fb.r.clamp(0.0, 255.0) as u32, fb.g.clamp(0.0, 255.0) as u32, fb.b.clamp(0.0, 255.0) as u32, fb.a.clamp(0.0, 255.0) as u32];
        rows(gs, py0 as i64, py1 as i64, (px1 - px0) as i64, |gs, py| {
            let py = py as i32;
            let v = t0 + (t1 - t0) * (((py << 4) - y0) as f32 / dy);
            let mut u = s0 + (s1 - s0) * (((px0 << 4) - x0) as f32 / dx);
            if rstats() { COVERED.fetch_add((px1 - px0) as u64, std::sync::atomic::Ordering::Relaxed); }
            if rstats() { KIND_PX[6].fetch_add((px1 - px0) as u64, std::sync::atomic::Ordering::Relaxed); }
            for px in px0..px1 {
                sprite_px(gs, st, px, py, u, v, &col);
                u += ds;
            }
        });
        return;
    }
    // Flat: the second vertex's colour, depth, fog.
    rows(gs, py0 as i64, py1 as i64, (px1 - px0) as i64, |gs, py| {
        let py = py as i32;
        let mut f = fb;
        let ty = ((py << 4) - y0) as f32 / dy;
        f.t = t0 + (t1 - t0) * ty;
        let tx0 = ((px0 << 4) - x0) as f32 / dx;
        f.s = s0 + (s1 - s0) * tx0;
        f.q = if st.fst { 1.0 } else { fa.q + (fb.q - fa.q) * tx0 };
        let pf = st.plot;
        if rstats() { COVERED.fetch_add((px1 - px0) as u64, std::sync::atomic::Ordering::Relaxed); }
        for px in px0..px1 {
            pf(gs, st, px, py, &f);
            f.s += ds;
            if !st.fst {
                f.q += dq;
            }
        }
    });
}

/// Textured UV sprites without fog, alpha / depth / destination alpha tests or depth writes into a
/// 32 / 24-bit frame buffer (the full-screen copy and blend passes): `sprite_px` does exactly what
/// `plot_g` does for them, without the parts that cannot apply.
fn sprite_fast_ok(st: &Setup) -> bool {
    let Some(t) = st.tex.as_ref() else { return false };
    st.tme
        && st.fst
        && !st.fge
        && !st.ate
        && !st.date
        && (!st.zte || (st.ztst == 1 && st.zmsk))
        && matches!(st.fpsm, PSMCT32 | PSMCT24)
        && t.tfx <= 1
        && matches!(t.fixed_lod, Some((_, 0)))
}

#[inline(always)]
fn sprite_px(gs: &mut Gs, st: &Setup, x: i32, y: i32, u: f32, v: f32, col: &[u32; 4]) {
    let t = st.tex.as_ref().unwrap();
    let (ux, uy) = (x as u32 & 2047, y as u32 & 2047);
    let filter = t.fixed_lod.unwrap().0;
    let tx = if filter {
        let u16 = (u * 16.0).floor() as i32 - 8;
        let v16 = (v * 16.0).floor() as i32 - 8;
        let (iu, iv) = (u16 >> 4, v16 >> 4);
        let (fu, fv) = ((u16 & 15) as u32, (v16 & 15) as u32);
        if fu == 0 && fv == 0 {
            texel_raw(t, 0, iu, iv)
        } else {
            let c00 = texel_raw(t, 0, iu, iv);
            let c10 = texel_raw(t, 0, iu + 1, iv);
            let c01 = texel_raw(t, 0, iu, iv + 1);
            let c11 = texel_raw(t, 0, iu + 1, iv + 1);
            let (w00, w10, w01, w11) = ((16 - fu) * (16 - fv), fu * (16 - fv), (16 - fu) * fv, fu * fv);
            const M: u32 = 0x00FF_00FF;
            let rb = (((c00 & M) * w00 + (c10 & M) * w10 + (c01 & M) * w01 + (c11 & M) * w11) >> 8) & M;
            let ga = ((((c00 >> 8) & M) * w00 + ((c10 >> 8) & M) * w10 + ((c01 >> 8) & M) * w01 + ((c11 >> 8) & M) * w11) >> 8) & M;
            rb | (ga << 8)
        }
    } else {
        texel_raw(t, 0, u.floor() as i32, v.floor() as i32)
    };
    let txc = [tx & 0xFF, (tx >> 8) & 0xFF, (tx >> 16) & 0xFF, tx >> 24];
    let mut c = *col;
    if t.tfx == 0 {
        for i in 0..3 {
            c[i] = ((txc[i] * c[i]) >> 7).min(255);
        }
        if t.tcc {
            c[3] = ((txc[3] * c[3]) >> 7).min(255);
        }
    } else {
        c[0] = txc[0];
        c[1] = txc[1];
        c[2] = txc[2];
        if t.tcc {
            c[3] = txc[3];
        }
    }
    let fpsm = st.fpsm;
    let blend = st.abe && !(st.pabe && c[3] & 0x80 == 0);
    let dst = if blend || st.fbmsk != 0 || fpsm != PSMCT32 { gs.read_pixel(fpsm, st.fbp, st.fbw, ux, uy) } else { 0 };
    if blend {
        let da = if fpsm == PSMCT24 { 0x80 } else { dst >> 24 };
        let cs = [c[0] as i32, c[1] as i32, c[2] as i32];
        let cd = [(dst & 0xFF) as i32, ((dst >> 8) & 0xFF) as i32, ((dst >> 16) & 0xFF) as i32];
        let pick = |sel: u32, i: usize| match sel {
            0 => cs[i],
            1 => cd[i],
            _ => 0,
        };
        let cc = match st.ac {
            0 => c[3] as i32,
            1 => da as i32,
            _ => st.afix as i32,
        };
        for i in 0..3 {
            let v = (((pick(st.aa, i) - pick(st.ab, i)) * cc) >> 7) + pick(st.ad, i);
            c[i] = if st.colclamp { v.clamp(0, 255) as u32 } else { (v & 0xFF) as u32 };
        }
    }
    if st.fba {
        c[3] |= 0x80;
    }
    let out = c[0] | (c[1] << 8) | (c[2] << 16) | (c[3] << 24);
    let msk = st.fbmsk;
    gs.store_pixel(fpsm, st.fbp, st.fbw, ux, uy, (out & !msk) | (dst & msk));
}

/// Textured triangles without fog or destination alpha test into a 32 / 24-bit frame buffer,
/// texture function modulate / decal: `tri_px` does what `plot_g` does for them.
fn tri_fast_ok(st: &Setup) -> bool {
    let Some(t) = st.tex.as_ref() else { return false };
    st.tme && !st.fge && !st.date && matches!(st.fpsm, PSMCT32 | PSMCT24) && t.tfx <= 1
}

#[inline(always)]
fn tri_px(gs: &mut Gs, st: &Setup, ux: u32, uy: u32, f: &Frag) {
    let t = st.tex.as_ref().unwrap();
    let tx = sample(t, f, st.fst);
    let clampc = |v: f32| v.clamp(0.0, 255.0) as u32;
    let mut c = [clampc(f.r), clampc(f.g), clampc(f.b), clampc(f.a)];
    if t.tfx == 0 {
        for i in 0..3 {
            c[i] = ((tx[i] * c[i]) >> 7).min(255);
        }
        if t.tcc {
            c[3] = ((tx[3] * c[3]) >> 7).min(255);
        }
    } else {
        c[0] = tx[0];
        c[1] = tx[1];
        c[2] = tx[2];
        if t.tcc {
            c[3] = tx[3];
        }
    }
    // Alpha test.
    let mut write_fb = true;
    let mut write_rgb_only = false;
    let mut write_z = !st.zmsk;
    if st.ate {
        let a = c[3];
        let pass = match st.atst {
            0 => false,
            1 => true,
            2 => a < st.aref,
            3 => a <= st.aref,
            4 => a == st.aref,
            5 => a >= st.aref,
            6 => a > st.aref,
            _ => a != st.aref,
        };
        if !pass {
            match st.afail {
                0 => return,
                1 => write_z = false,
                2 => write_fb = false,
                _ => {
                    write_rgb_only = true;
                    write_z = false;
                }
            }
        }
    }
    // 32-bit colour and depth (CT32 / CT24, Z32 / Z24): one swizzle for both addresses.
    let wide = matches!(st.zpsm, PSMZ32 | PSMZ24);
    let (fa, za) = if wide {
        let page = (ux >> 6) + (uy >> 5) * st.fbw.max(1);
        let block = BLOCK32[((uy >> 3) & 3) as usize][((ux >> 3) & 7) as usize];
        let word = COLUMN32[(uy & 7) as usize][(ux & 7) as usize];
        let off = (page << 11) + word;
        ((((st.fbp << 6) + off + (block << 6)) as usize * 4) & (VRAM - 1), (((st.zbp << 6) + off + ((block ^ 0x18) << 6)) as usize * 4) & (VRAM - 1))
    } else {
        (0, 0)
    };
    // Depth test.
    let z = f.z.clamp(0.0, st.zmax) as u32;
    if st.zte {
        let dz = if wide {
            let v = gs.r32(za);
            if st.zpsm == PSMZ24 { v & 0xFF_FFFF } else { v }
        } else {
            gs.read_pixel(st.zpsm, st.zbp, st.fbw, ux, uy)
        };
        let pass = match st.ztst {
            0 => false,
            1 => true,
            2 => z >= dz,
            _ => z > dz,
        };
        if !pass {
            return;
        }
    }
    let fpsm = st.fpsm;
    let blend = st.abe && !(st.pabe && c[3] & 0x80 == 0);
    let dst = if blend || st.fbmsk != 0 || write_rgb_only || fpsm != PSMCT32 || !write_fb {
        if wide {
            let v = gs.r32(fa);
            if fpsm == PSMCT24 { v & 0xFF_FFFF } else { v }
        } else {
            gs.read_pixel(fpsm, st.fbp, st.fbw, ux, uy)
        }
    } else {
        0
    };
    if blend {
        let da = if fpsm == PSMCT24 { 0x80 } else { dst >> 24 };
        let cs = [c[0] as i32, c[1] as i32, c[2] as i32];
        let cd = [(dst & 0xFF) as i32, ((dst >> 8) & 0xFF) as i32, ((dst >> 16) & 0xFF) as i32];
        let pick = |sel: u32, i: usize| match sel {
            0 => cs[i],
            1 => cd[i],
            _ => 0,
        };
        let cc = match st.ac {
            0 => c[3] as i32,
            1 => da as i32,
            _ => st.afix as i32,
        };
        for i in 0..3 {
            let v = (((pick(st.aa, i) - pick(st.ab, i)) * cc) >> 7) + pick(st.ad, i);
            c[i] = if st.colclamp { v.clamp(0, 255) as u32 } else { (v & 0xFF) as u32 };
        }
    }
    if st.fba {
        c[3] |= 0x80;
    }
    if write_fb {
        let out = c[0] | (c[1] << 8) | (c[2] << 16) | (c[3] << 24);
        let mut msk = st.fbmsk;
        if write_rgb_only {
            msk |= 0xFF00_0000;
        }
        let v = (out & !msk) | (dst & msk);
        if wide {
            // CT24 keeps the word's top byte.
            let v = if fpsm == PSMCT24 { (gs.r32(fa) & 0xFF00_0000) | (v & 0xFF_FFFF) } else { v };
            gs.w32(fa, v);
        } else {
            gs.store_pixel(fpsm, st.fbp, st.fbw, ux, uy, v);
        }
    }
    if write_z && st.zte {
        if wide {
            let v = if st.zpsm == PSMZ24 { (gs.r32(za) & 0xFF00_0000) | (z & 0xFF_FFFF) } else { z };
            gs.w32(za, v);
        } else {
            gs.store_pixel(st.zpsm, st.zbp, st.fbw, ux, uy, z);
        }
    }
}

fn triangle(gs: &mut Gs, st: &Setup, a: &Vertex, b: &Vertex, c: &Vertex, clip: &Clip) {
    let (ax, ay, bx, by, cx, cy) = (a.x as i64, a.y as i64, b.x as i64, b.y as i64, c.x as i64, c.y as i64);
    let area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
    if area == 0 {
        return;
    }
    let minx = ((ax.min(bx).min(cx) + 15) >> 4).max(st.sx0 as i64).max(clip.x0 as i64);
    let maxx = ((ax.max(bx).max(cx) + 15) >> 4).min(st.sx1 as i64 + 1).min(clip.x1 as i64);
    let miny = ((ay.min(by).min(cy) + 15) >> 4).max(st.sy0 as i64).max(clip.y0 as i64);
    let maxy = ((ay.max(by).max(cy) + 15) >> 4).min(st.sy1 as i64 + 1).min(clip.y1 as i64);
    if minx >= maxx || miny >= maxy {
        return;
    }
    let fa = frag_of(a, st);
    let fb = frag_of(b, st);
    let fc = frag_of(c, st);
    // Edge functions w = (x1 - x0) * (py - y0) - (y1 - y0) * (px - x0), orientation normalised so
    // inside is >= 0, with the top-left rule as a bias (pixels exactly on a right or bottom edge
    // are not drawn). Edges: k = 0 (b, c), 1 (c, a), 2 (a, b): the weights of a, b, c.
    let sign = if area > 0 { 1i64 } else { -1 };
    let edges = [(bx, by, cx, cy), (cx, cy, ax, ay), (ax, ay, bx, by)];
    let bias = |(x0, y0, x1, y1): (i64, i64, i64, i64)| {
        let (dx, dy) = ((x1 - x0) * sign, (y1 - y0) * sign);
        if dy < 0 || (dy == 0 && dx > 0) { 0 } else { -1 }
    };
    let biases = edges.map(bias);
    // w at pixel (px, py): e0 + ex * px + ey * py (px, py in pixels), times `sign`.
    let coef = edges.map(|(x0, y0, x1, y1)| {
        let ex = -(y1 - y0) * 16 * sign;
        let ey = (x1 - x0) * 16 * sign;
        let e0 = ((y1 - y0) * x0 - (x1 - x0) * y0) * sign;
        (e0, ex, ey)
    });
    let inv = 1.0 / (area * sign) as f64;
    // Attribute gradients per pixel step in x (barycentric weights are w_k * inv).
    let lx = coef.map(|(_, ex, _)| ex as f64 * inv);
    let gx = |va: f32, vb: f32, vc: f32| (va as f64 * lx[0] + vb as f64 * lx[1] + vc as f64 * lx[2]) as f32;
    let dz = fa.z * lx[0] + fb.z * lx[1] + fc.z * lx[2];
    let (ds, dt, dq, dfog) = (gx(fa.s, fb.s, fc.s), gx(fa.t, fb.t, fc.t), gx(fa.q, fb.q, fc.q), gx(fa.f, fb.f, fc.f));
    let (dr, dg, db, da) = (gx(fa.r, fb.r, fc.r), gx(fa.g, fb.g, fc.g), gx(fa.b, fb.b, fc.b), gx(fa.a, fb.a, fc.a));
    let flat = Frag { r: fc.r, g: fc.g, b: fc.b, a: fc.a, ..Frag::default() };
    let fast = tri_fast_ok(st);
    rows(gs, miny, maxy, maxx - minx, |gs, py| {
        // The covered span of this row: each edge bounds x from one side.
        let (mut xs, mut xe) = (minx, maxx);
        let mut w0 = [0i64; 3];
        for k in 0..3 {
            let (e0, ex, ey) = coef[k];
            let w = e0 + ey * py + ex * minx + biases[k];
            w0[k] = w;
            if ex == 0 {
                if w < 0 {
                    return;
                }
            } else if ex > 0 {
                // w + ex * (x - minx) >= 0  =>  x >= minx + ceil(-w / ex)
                if w < 0 {
                    xs = xs.max(minx + (-w + ex - 1) / ex);
                }
            } else {
                // x <= minx + floor(w / -ex)
                if w < 0 {
                    return;
                }
                xe = xe.min(minx + w / -ex + 1);
            }
        }
        if xs >= xe {
            return;
        }
        // Exact weights at the span start, then steps.
        let l = |k: usize| (w0[k] - biases[k] + coef[k].1 * (xs - minx)) as f64 * inv;
        let (l0, l1, l2) = (l(0), l(1), l(2));
        let (f0, f1, f2) = (l0 as f32, l1 as f32, l2 as f32);
        let mix = |x: f32, y: f32, z: f32| x * f0 + y * f1 + z * f2;
        let mut f = Frag {
            z: fa.z * l0 + fb.z * l1 + fc.z * l2,
            s: mix(fa.s, fb.s, fc.s),
            t: mix(fa.t, fb.t, fc.t),
            q: mix(fa.q, fb.q, fc.q),
            f: mix(fa.f, fb.f, fc.f),
            ..flat
        };
        if st.gouraud {
            f.r = mix(fa.r, fb.r, fc.r);
            f.g = mix(fa.g, fb.g, fc.g);
            f.b = mix(fa.b, fb.b, fc.b);
            f.a = mix(fa.a, fb.a, fc.a);
        }
        let pf = st.plot;
        if rstats() { COVERED.fetch_add((xe - xs) as u64, std::sync::atomic::Ordering::Relaxed); }
        if rstats() { KIND_PX[4].fetch_add((xe - xs) as u64, std::sync::atomic::Ordering::Relaxed); }
        if fast {
            for px in xs..xe {
                tri_px(gs, st, px as u32 & 2047, py as u32 & 2047, &f);
                f.z += dz;
                f.s += ds;
                f.t += dt;
                f.q += dq;
                if st.gouraud {
                    f.r += dr;
                    f.g += dg;
                    f.b += db;
                    f.a += da;
                }
            }
            return;
        }
        for px in xs..xe {
            pf(gs, st, px as i32, py as i32, &f);
            f.z += dz;
            f.s += ds;
            f.t += dt;
            f.q += dq;
            f.f += dfog;
            if st.gouraud {
                f.r += dr;
                f.g += dg;
                f.b += db;
                f.a += da;
            }
        }
    });
}

// ---- texturing ----

/// A decoded texture level: RGBA8 texels (alpha after TEXA expansion), row-major.
pub struct TexImg {
    pub w: u32,
    pub h: u32,
    pub data: Vec<u32>,
}

/// Size in pixels of a page in each storage mode (for the pages a texture covers).
fn page_dims(psm: u32) -> (u32, u32) {
    match psm {
        PSMCT16 | PSMCT16S | PSMZ16 | PSMZ16S => (64, 64),
        PSMT8 => (128, 64),
        PSMT4 => (128, 128),
        _ => (64, 32),
    }
}

/// Level `l` of texture `t`, decoded, from the cache unless its pages were written since.
fn cached_level(gs: &mut Gs, t: &Tex, l: usize) -> std::sync::Arc<TexImg> {
    let (tbp, tbw) = if l == 0 { (t.tbp, t.tbw) } else { t.mip[l] };
    let w = 1u32 << t.tw.saturating_sub(l as u32).min(10);
    let h = 1u32 << t.th.saturating_sub(l as u32).min(10);
    let indexed = matches!(t.psm, PSMT8 | PSMT8H | PSMT4 | PSMT4HL | PSMT4HH);
    let clut_hash = if indexed { gs.clut_hash } else { 0 };
    let key = ((tbp as u64) | (tbw as u64) << 14 | (t.psm as u64) << 20 | (w as u64) << 26 | (h as u64) << 38, clut_hash,
               (t.ta0 as u64) | (t.ta1 as u64) << 8 | (t.aem as u64) << 16);
    // Generation sum of the pages the texture covers.
    let (pw, ph) = page_dims(t.psm);
    let stride = match t.psm { PSMT8 | PSMT4 => (tbw / 2).max(1), _ => tbw.max(1) }.max(w.div_ceil(pw));
    let pages = (stride * h.div_ceil(ph)) as usize;
    let first = (tbp / 32) as usize;
    let mut sum = 0u64;
    for i in 0..pages.min(512) {
        sum = sum.wrapping_mul(31).wrapping_add(gs.page_gen[(first + i) & 511].load(std::sync::atomic::Ordering::Relaxed) as u64 + 1);
    }
    if let Some((g, img)) = gs.tex_cache.get(&key) {
        if *g == sum {
            return img.clone();
        }
    }
    // The pages changed since the image was cached: wait only if queued or running drawing
    // uses one of them (PCSX2 GSRendererSW::CheckSourcePages).
    let busy = (0..pages.min(512)).any(|i| {
        let p = (first + i) & 511;
        gs.busy_pages[p >> 6].load(std::sync::atomic::Ordering::Relaxed) & (1 << (p & 63)) != 0
    });
    if busy {
        flush_sync(gs);
    }
    let mut data = Vec::with_capacity((w * h) as usize);
    for y in 0..h {
        for x in 0..w {
            let raw = gs.read_pixel(t.psm, tbp, tbw, x & 2047, y & 2047);
            let c = match t.psm {
                PSMT8 | PSMT8H | PSMT4 | PSMT4HL | PSMT4HH => {
                    let e = gs.clut[(raw & 255) as usize];
                    let cpsm = ((gs.clut_tex0 >> 51) & 0xF) as u32;
                    if cpsm == PSMCT16 || cpsm == PSMCT16S { pack(c16(e, t)) } else { e }
                }
                PSMCT16 | PSMCT16S => pack(c16(raw, t)),
                PSMCT24 => {
                    let rgb = raw & 0xFF_FFFF;
                    let a = if t.aem && rgb == 0 { 0 } else { t.ta0 };
                    rgb | (a << 24)
                }
                _ => raw,
            };
            data.push(c);
        }
    }
    let img = std::sync::Arc::new(TexImg { w, h, data });
    if gs.tex_cache.len() > 512 {
        gs.tex_cache.clear();
    }
    gs.tex_cache.insert(key, (sum, img.clone()));
    img
}

fn pack(c: [u32; 4]) -> u32 {
    c[0] | c[1] << 8 | c[2] << 16 | c[3] << 24
}

/// A texel as RGBA (0..255, alpha after TEXA expansion).
#[inline(always)]
fn texel(t: &Tex, level: usize, u: i32, v: i32) -> [u32; 4] {
    let c = texel_raw(t, level, u, v);
    [c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF, c >> 24]
}

/// Texture wrap (CLAMP): repeat, clamp, region clamp, region repeat. Sizes are powers of two.
#[inline(always)]
fn wrap(c: i32, size: i32, mode: u32, min: i32, max: i32) -> i32 {
    match mode {
        0 => c & (size - 1),
        1 => c.clamp(0, size - 1),
        2 => c.clamp(min, max).clamp(0, size - 1),
        _ => ((c & min) | max) & (size - 1),
    }
}

/// A texel as packed RGBA8.
#[inline(always)]
fn texel_raw(t: &Tex, level: usize, u: i32, v: i32) -> u32 {
    if level == 0 {
        if let Some(img) = t.img[0].as_ref() {
            // Level 0 (nearly every fetch): sizes are powers of two, the wrapped / clamped
            // coordinates lie inside the image.
            let (w, h) = (img.w as i32, img.h as i32);
            let x = wrap(u, w, t.wms, t.minu, t.maxu);
            let y = wrap(v, h, t.wmt, t.minv, t.maxv);
            debug_assert!(((y * w + x) as usize) < img.data.len());
            return unsafe { *img.data.get_unchecked((y * w + x) as usize) };
        }
        return 0;
    }
    let Some(img) = t.img[level].as_ref().or(t.img[0].as_ref()) else { return 0 };
    let (w, h) = (img.w as i32, img.h as i32);
    let x = wrap(u, w, t.wms, t.minu >> level, t.maxu >> level);
    let y = wrap(v, h, t.wmt, t.minv >> level, t.maxv >> level);
    img.data[(y * w + x) as usize]
}

fn c16(c: u32, t: &Tex) -> [u32; 4] {
    let r = (c & 31) << 3;
    let g = ((c >> 5) & 31) << 3;
    let b = ((c >> 10) & 31) << 3;
    let a = if c & 0x8000 != 0 { t.ta1 } else if t.aem && c & 0x7FFF == 0 { 0 } else { t.ta0 };
    [r, g, b, a]
}

/// Filter and mip level: from LCM / K, or (with Q) log2(1 / Q) << L + K. None when it needs Q.
#[inline(always)]
fn lod_select(t: &Tex, q: Option<f32>) -> Option<(bool, usize)> {
    let lod = if t.lcm {
        t.k
    } else if t.mxl == 0 && t.mmag == (t.mmin & 1 == 1) {
        0.0
    } else {
        ((1.0 / q?.abs().max(1e-6)).log2()) * (1 << t.l) as f32 + t.k
    };
    Some(if lod <= 0.0 || t.mxl == 0 {
        (if lod <= 0.0 { t.mmag } else { t.mmin & 1 == 1 }, 0usize)
    } else {
        let lvl = (lod.round() as u32).min(t.mxl) as usize;
        (t.mmin == 1 || t.mmin >= 4, if t.mmin >= 2 { lvl } else { 0 })
    })
}

#[inline(always)]
fn sample(t: &Tex, f: &Frag, fst: bool) -> [u32; 4] {
    let (w, h) = (t.wf, t.hf);
    // UV (FST) coordinates are texels already; STQ are normalised and divided by Q per pixel.
    let (mut u, mut v) = if fst {
        (f.s, f.t)
    } else if f.q != 0.0 {
        (f.s / f.q * w, f.t / f.q * h)
    } else {
        (0.0, 0.0)
    };
    // LOD: LCM = 1 fixed K, else (log2(1 / Q) << L) + K. Without mipmaps (MXL 0) only its sign
    // matters (magnification or minification filter).
    let (filter, level) = match t.fixed_lod {
        Some(fl) => fl,
        None => lod_select(t, Some(f.q)).unwrap(),
    };
    if level > 0 {
        u /= (1 << level) as f32;
        v /= (1 << level) as f32;
    }
    if !filter {
        return texel(t, level, u.floor() as i32, v.floor() as i32);
    }
    // Bilinear as the GS does it: texel coordinates have 4 fraction bits, the weights are
    // (16 - f) and f in each direction.
    let u16 = (u * 16.0).floor() as i32 - 8;
    let v16 = (v * 16.0).floor() as i32 - 8;
    let (iu, iv) = (u16 >> 4, v16 >> 4);
    let (fu, fv) = ((u16 & 15) as u32, (v16 & 15) as u32);
    if fu == 0 && fv == 0 {
        return texel(t, level, iu, iv);
    }
    let c00 = texel_raw(t, level, iu, iv);
    let c10 = texel_raw(t, level, iu + 1, iv);
    let c01 = texel_raw(t, level, iu, iv + 1);
    let c11 = texel_raw(t, level, iu + 1, iv + 1);
    let (w00, w10, w01, w11) = ((16 - fu) * (16 - fv), fu * (16 - fv), (16 - fu) * fv, fu * fv);
    const M: u32 = 0x00FF_00FF;
    // R / B and G / A in the two halves of a word: one multiply per texel and pair.
    let rb = (((c00 & M) * w00 + (c10 & M) * w10 + (c01 & M) * w01 + (c11 & M) * w11) >> 8) & M;
    let ga = ((((c00 >> 8) & M) * w00 + ((c10 >> 8) & M) * w10 + ((c01 >> 8) & M) * w01 + ((c11 >> 8) & M) * w11) >> 8) & M;
    let c = rb | (ga << 8);
    [c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF, c >> 24]
}

// ---- the pixel pipeline ----

/// Frames the game finished drawing (see `queue`).
pub static GAME_FRAMES: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
/// Real game frames: copy passes whose source frame buffer was drawn since the previous one
/// (per log period, and since start for the FPS overlay). THE frame rate measure.
pub static RENDERED: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
pub static RENDERED_TOTAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
static LAST_COPY_SRC: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
pub static PIXELS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
pub static PRIMS: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// A pixel function specialised for a primitive's texture / alpha test / depth test / blend /
/// fog switches (PCSX2's software renderer selects scanline functions the same way).
type PlotFn = fn(&mut Gs, &Setup, i32, i32, &Frag);

fn plot_fn(tme: bool, ate: bool, zte: bool, abe: bool, fge: bool) -> PlotFn {
    macro_rules! pick {
        ($($t:literal $a:literal $z:literal $b:literal $f:literal),*) => {
            match (tme, ate, zte, abe, fge) {
                $(($t, $a, $z, $b, $f) => plot_g::<$t, $a, $z, $b, $f>,)*
            }
        };
    }
    pick!(
        false false false false false, false false false false true, false false false true false, false false false true true,
        false false true false false, false false true false true, false false true true false, false false true true true,
        false true false false false, false true false false true, false true false true false, false true false true true,
        false true true false false, false true true false true, false true true true false, false true true true true,
        true false false false false, true false false false true, true false false true false, true false false true true,
        true false true false false, true false true false true, true false true true false, true false true true true,
        true true false false false, true true false false true, true true false true false, true true false true true,
        true true true false false, true true true false true, true true true true false, true true true true true
    )
}

/// A pixel outside the scissor rectangle is not drawn (spans are clipped already; points and
/// lines check here).
#[inline(always)]
fn plot(gs: &mut Gs, st: &Setup, x: i32, y: i32, f: &Frag) {
    if x < st.sx0 || x > st.sx1 || y < st.sy0 || y > st.sy1 || x < 0 || y < 0 || !owns_row(y) {
        return;
    }
    (st.plot)(gs, st, x, y, f);
}

fn plot_g<const TME: bool, const ATE: bool, const ZTE: bool, const ABE: bool, const FGE: bool>(gs: &mut Gs, st: &Setup, x: i32, y: i32, f: &Frag) {
    let (ux, uy) = (x as u32 & 2047, y as u32 & 2047);
    let clampc = |v: f32| v.clamp(0.0, 255.0) as u32;
    let mut c = [clampc(f.r), clampc(f.g), clampc(f.b), clampc(f.a)];
    if let (true, Some(t)) = (TME, st.tex.as_ref()) {
        let tx = sample(t, f, st.fst);
        let m = |a: u32, b: u32| (a * b) >> 7;
        match t.tfx {
            0 => {
                c[0] = m(tx[0], c[0]).min(255);
                c[1] = m(tx[1], c[1]).min(255);
                c[2] = m(tx[2], c[2]).min(255);
                if t.tcc {
                    c[3] = m(tx[3], c[3]).min(255);
                }
            }
            1 => {
                c[0] = tx[0];
                c[1] = tx[1];
                c[2] = tx[2];
                if t.tcc {
                    c[3] = tx[3];
                }
            }
            2 | 3 => {
                let fa = c[3];
                c[0] = (m(tx[0], c[0]) + fa).min(255);
                c[1] = (m(tx[1], c[1]) + fa).min(255);
                c[2] = (m(tx[2], c[2]) + fa).min(255);
                if t.tcc {
                    c[3] = if t.tfx == 2 { (tx[3] + fa).min(255) } else { tx[3] };
                }
            }
            _ => {}
        }
    }
    if FGE {
        let fv = clampc(f.f);
        for i in 0..3 {
            c[i] = (c[i] * fv + st.fogcol[i] * (255 - fv)) >> 8;
        }
    }
    // Alpha test.
    let mut write_fb = true;
    let mut write_rgb_only = false;
    let mut write_z = !st.zmsk;
    if ATE {
        let a = c[3];
        let pass = match st.atst {
            0 => false,
            1 => true,
            2 => a < st.aref,
            3 => a <= st.aref,
            4 => a == st.aref,
            5 => a >= st.aref,
            6 => a > st.aref,
            _ => a != st.aref,
        };
        if !pass {
            match st.afail {
                0 => return,
                1 => write_z = false,
                2 => write_fb = false,
                _ => {
                    write_rgb_only = true;
                    write_z = false;
                }
            }
        }
    }
    let fpsm = st.fpsm;
    // The destination is needed for blending, the destination alpha test, masks and the
    // formats that keep part of the word.
    let need_dst = (ABE && !(st.pabe && c[3] & 0x80 == 0)) || st.date || st.fbmsk != 0 || write_rgb_only || fpsm != PSMCT32 || !write_fb;
    let dst = if need_dst { gs.read_pixel(fpsm, st.fbp, st.fbw, ux, uy) } else { 0 };
    let (dr, dg, db, da) = match fpsm {
        PSMCT16 | PSMCT16S | PSMZ16 | PSMZ16S => (((dst & 31) << 3), (((dst >> 5) & 31) << 3), (((dst >> 10) & 31) << 3), if dst & 0x8000 != 0 { 0x80 } else { 0 }),
        PSMCT24 | PSMZ24 => (dst & 0xFF, (dst >> 8) & 0xFF, (dst >> 16) & 0xFF, 0x80),
        _ => (dst & 0xFF, (dst >> 8) & 0xFF, (dst >> 16) & 0xFF, dst >> 24),
    };
    // Destination alpha test.
    if st.date {
        let bit = match fpsm {
            PSMCT16 | PSMCT16S => dst & 0x8000 != 0,
            PSMCT32 => dst & 0x8000_0000 != 0,
            _ => false,
        };
        if bit != st.datm {
            return;
        }
    }
    // Depth test.
    let z = f.z.clamp(0.0, st.zmax) as u32;
    if ZTE {
        let dz = gs.read_pixel(st.zpsm, st.zbp, st.fbw, ux, uy);
        let pass = match st.ztst {
            0 => false,
            1 => true,
            2 => z >= dz,
            _ => z > dz,
        };
        if !pass {
            return;
        }
    }
    // Alpha blend.
    if ABE && !(st.pabe && c[3] & 0x80 == 0) {
        let cs = [c[0] as i32, c[1] as i32, c[2] as i32];
        let cd = [dr as i32, dg as i32, db as i32];
        let pick = |sel: u32, i: usize| match sel {
            0 => cs[i],
            1 => cd[i],
            _ => 0,
        };
        let cc = match st.ac {
            0 => c[3] as i32,
            1 => da as i32,
            _ => st.afix as i32,
        };
        for i in 0..3 {
            let v = (((pick(st.aa, i) - pick(st.ab, i)) * cc) >> 7) + pick(st.ad, i);
            c[i] = if st.colclamp { v.clamp(0, 255) as u32 } else { (v & 0xFF) as u32 };
        }
    }
    if st.dthe && (fpsm == PSMCT16 || fpsm == PSMCT16S) {
        let d = st.dimx[(uy & 3) as usize][(ux & 3) as usize];
        for i in 0..3 {
            let v = c[i] as i32 + d;
            c[i] = if st.colclamp { v.clamp(0, 255) as u32 } else { (v & 0xFF) as u32 };
        }
    }
    if st.fba {
        c[3] |= 0x80;
    }
    if write_fb {
        let mut out = match fpsm {
            PSMCT16 | PSMCT16S | PSMZ16 | PSMZ16S => (c[0] >> 3) | ((c[1] >> 3) << 5) | ((c[2] >> 3) << 10) | (((c[3] >> 7) & 1) << 15),
            _ => c[0] | (c[1] << 8) | (c[2] << 16) | (c[3] << 24),
        };
        let mut msk = st.fbmsk;
        if fpsm == PSMCT16 || fpsm == PSMCT16S {
            msk = ((msk >> 3) & 0x1F) | ((msk >> 6) & 0x3E0) | ((msk >> 9) & 0x7C00) | ((msk >> 16) & 0x8000);
        }
        if write_rgb_only {
            msk |= if fpsm == PSMCT16 || fpsm == PSMCT16S { 0x8000 } else { 0xFF00_0000 };
        }
        out = (out & !msk) | (dst & msk);
        gs.store_pixel(fpsm, st.fbp, st.fbw, ux, uy, out);
    }
    if write_z && ZTE {
        gs.store_pixel(st.zpsm, st.zbp, st.fbw, ux, uy, z);
    }
}

