//! The DVD image (ISO9660, 2048-byte sectors) and its file system.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};

pub const SECTOR: u64 = 2048;

pub struct Disc {
    file: File,
    pub sectors: u64,
    /// Every file: upper-case path without version (e.g. "TK5DATA3.BIN"), LBA, size.
    pub files: Vec<(String, u32, u32)>,
    /// Mod data (`merge.rs`) in virtual sectors past the image: (first sector, bytes).
    virtual_files: Vec<(u64, Vec<u8>)>,
}

impl Disc {
    pub fn open(path: &str) -> std::io::Result<Disc> {
        let file = File::open(path)?;
        let sectors = file.metadata()?.len() / SECTOR;
        let mut d = Disc { file, sectors, files: Vec::new(), virtual_files: Vec::new() };
        let pvd = d.read_bytes(16, 2048)?;
        if &pvd[1..6] != b"CD001" {
            return Err(std::io::Error::new(std::io::ErrorKind::InvalidData, "not an ISO9660 image"));
        }
        let lba = u32::from_le_bytes(pvd[158..162].try_into().unwrap());
        let size = u32::from_le_bytes(pvd[166..170].try_into().unwrap());
        let mut files = Vec::new();
        d.walk(lba, size, String::new(), &mut files, 0)?;
        d.files = files;
        Ok(d)
    }

    fn walk(&mut self, lba: u32, size: u32, prefix: String, out: &mut Vec<(String, u32, u32)>, depth: u32) -> std::io::Result<()> {
        if depth > 8 {
            return Ok(());
        }
        let data = self.read_bytes(lba as u64, size as usize)?;
        let mut pos = 0usize;
        while pos < data.len() {
            let len = data[pos] as usize;
            if len == 0 {
                pos = (pos / 2048 + 1) * 2048;
                continue;
            }
            let rec = &data[pos..(pos + len).min(data.len())];
            pos += len;
            if rec.len() < 34 {
                continue;
            }
            let elba = u32::from_le_bytes(rec[2..6].try_into().unwrap());
            let esize = u32::from_le_bytes(rec[10..14].try_into().unwrap());
            let flags = rec[25];
            let nlen = rec[32] as usize;
            let name = &rec[33..(33 + nlen).min(rec.len())];
            if name == [0] || name == [1] {
                continue;
            }
            let name = String::from_utf8_lossy(name).split(';').next().unwrap_or("").to_uppercase();
            let path = if prefix.is_empty() { name } else { format!("{prefix}\\{name}") };
            if flags & 2 != 0 {
                self.walk(elba, esize, path, out, depth + 1)?;
            } else {
                out.push((path, elba, esize));
            }
        }
        Ok(())
    }

    /// `n` bytes starting at sector `lba`.
    pub fn read_bytes(&mut self, lba: u64, n: usize) -> std::io::Result<Vec<u8>> {
        let mut buf = vec![0u8; n];
        self.read_into(lba * SECTOR, &mut buf)?;
        Ok(buf)
    }

    /// Fill `buf` from byte offset `off` (zeros past the end of the image).
    pub fn read_into(&mut self, off: u64, buf: &mut [u8]) -> std::io::Result<()> {
        buf.fill(0);
        self.file.seek(SeekFrom::Start(off))?;
        let mut got = 0;
        while got < buf.len() {
            let n = self.file.read(&mut buf[got..])?;
            if n == 0 {
                break;
            }
            got += n;
        }
        for (lba, data) in &self.virtual_files {
            let start = lba * SECTOR;
            let (lo, hi) = (off.max(start), (off + buf.len() as u64).min(start + data.len() as u64));
            if lo < hi {
                buf[(lo - off) as usize..(hi - off) as usize]
                    .copy_from_slice(&data[(lo - start) as usize..(hi - start) as usize]);
            }
        }
        Ok(())
    }

    /// First sector after the image and every virtual file.
    pub fn virtual_end(&self) -> u64 {
        self.virtual_files.last().map_or(self.sectors, |(l, d)| l + (d.len() as u64).div_ceil(SECTOR))
    }

    /// Append `data` in new virtual sectors; returns its first sector.
    pub fn add_virtual(&mut self, data: Vec<u8>) -> u64 {
        let lba = self.virtual_end();
        self.virtual_files.push((lba, data));
        lba
    }

    /// Change the recorded size of a file (by `find` path).
    pub fn set_size(&mut self, path: &str, size: u32) {
        let p = path.to_uppercase();
        if let Some(f) = self.files.iter_mut().find(|(n, _, _)| *n == p) {
            f.2 = size;
        }
    }

    /// A file by path ("cdrom0:\\TK5DATA3.BIN;1", "\\SLUS_210.59", "tk5data3.bin" ...).
    pub fn find(&self, path: &str) -> Option<(u32, u32)> {
        let p = path.trim_start_matches("cdrom0:").trim_start_matches("cdrom:");
        let p = p.trim_start_matches(['\\', '/']).split(';').next().unwrap_or("").replace('/', "\\").to_uppercase();
        self.files.iter().find(|(n, _, _)| *n == p).map(|(_, l, s)| (*l, *s))
    }
}
