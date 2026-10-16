import struct
# ELF reader for the main program (rd(addr, n), u32, cstr) used by the merge tools.
elf=open(r'E:/Decompilation/Decomps/Tekken5/extracted/elf/main.elf','rb').read()
phoff,=struct.unpack_from('<I',elf,0x1c); n,=struct.unpack_from('<H',elf,0x2c)
segs=[struct.unpack_from('<8I',elf,phoff+i*32) for i in range(n)]
def va(off):
    for _,o,v,_,fs,*r in segs:
        if o<=off<o+fs: return v+off-o
def rd(a,ln):
    for _,o,v,_,fs,*r in segs:
        if v<=a<v+fs: return elf[o+a-v:o+a-v+ln]
def u32(a): return struct.unpack('<I',rd(a,4))[0]
def find32(x):
    pat=struct.pack('<I',x); i=elf.find(pat); out=[]
    while i>=0:
        if i%4==0: out.append(va(i))
        i=elf.find(pat,i+1)
    return out
def cstr(a): b=rd(a,64); return b.split(b'\0')[0].decode('latin1')
