"""Read-only Vita SCE ELF import/export, TLS and relocation inventory.

Supports inspection of retail modules that require TLS or variable imports.
Unlike a linker, this intentionally does *not* initialize TLS, apply relocations,
resolve imports, execute instructions, or authorize a runnable build.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import struct

MAX_FILE = 128 * 1024 * 1024
MAX_TABLE = 4 * 1024 * 1024
MAX_RECORDS = 65536


def inventory(path: Path) -> dict:
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_FILE:
        raise ValueError('missing or oversized ELF')
    data = path.read_bytes()
    if len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('ELF32 little-endian required')
    typ, machine, version, entry, phoff = struct.unpack_from('<HHIII', data, 16)
    phentsize, phnum = struct.unpack_from('<HH', data, 42)
    if machine != 40 or version != 1 or typ not in (0xfe00,0xfe04) or not 1 <= phnum <= 64 or phentsize != 32 or phoff+32*phnum>len(data):
        raise ValueError('unsupported Vita ELF header')
    load=[]; rel=[]
    for n in range(phnum):
        t,off,va,pa,sz,msz,flags,align=struct.unpack_from('<IIIIIIII',data,phoff+32*n)
        if off>len(data) or sz>len(data)-off:raise ValueError('out-of-bounds program header')
        if t == 1:
            if msz<sz or va+msz>2**32:raise ValueError('invalid PT_LOAD')
            load.append(dict(index=n,offset=off,address=va,file_size=sz,memory_size=msz,flags=flags))
        elif t == 0x60000000:rel.append(dict(offset=off,bytes=sz))
    def loc(addr,n):
        if n<0 or n>MAX_TABLE:raise ValueError('metadata table too large')
        for s in load:
            i=addr-s['address']
            if 0<=i<=s['file_size'] and n<=s['file_size']-i:
                return s['offset']+i
        raise ValueError(f'unmapped metadata at {addr:#x}, {n} bytes')
    def read(addr,fmt):return struct.unpack_from(fmt,data,loc(addr,struct.calcsize(fmt)))
    def label(addr):
        if addr==0:return None
        start=loc(addr,1)
        end=data.find(b'\0',start,min(start+256,len(data)))
        if end<0:raise ValueError('unterminated library label')
        return data[start:end].decode('utf-8',errors='replace')
    def arr(addr,count):
        if count<0 or count>MAX_RECORDS:raise ValueError('excessive table elements')
        return list(read(addr,'<'+str(count)+'I')) if count else []
    modseg=entry>>30
    base=next((s['address'] for s in load if s['index']==modseg),None)
    if base is None:raise ValueError('module info segment absent')
    mo=base+(entry&0x3fffffff)
    off=loc(mo,0x50)
    name=data[off+4:off+31].split(b'\0',1)[0].decode('utf-8',errors='replace')
    attributes,version=read(mo,'<HH')
    ex_top,ex_end,im_top,im_end=read(mo+0x24,'<IIII')
    module_nid,tls_start,tls_filesz,tls_memsz,start_off,stop_off=read(mo+0x34,'<IIIIII')
    def table(top,end):
        if end<top or end-top>MAX_TABLE:raise ValueError('invalid table extent')
        loc(base+top,end-top)
        return (base+top,base+end)
    exports=[];imports=[]
    cursor,end=table(ex_top,ex_end)
    while cursor<end:
        size,res,lv=read(cursor,'<BBH')
        if size!=0x20 or res or cursor+size>end or len(exports)>=MAX_RECORDS:raise ValueError('invalid exports')
        flags,nf,nv,nt,nid,libname,nidptr,ptr=read(cursor+4,'<HHIIIIII')
        total=nf+nv+nt
        if total>MAX_RECORDS:raise ValueError('oversized exports')
        exported_nids=arr(nidptr,total)
        exported_entries=arr(ptr,total)
        exports.append(dict(library=label(libname),library_nid=f'{nid:08x}',functions=nf,variables=nv,tls_variables=nt,
                            function_nids=[f'{v:08x}' for v in exported_nids[:nf]],
                            variable_nids=[f'{v:08x}' for v in exported_nids[nf:nf+nv]],
                            tls_nids=[f'{v:08x}' for v in exported_nids[nf+nv:]],
                            function_addresses=[f'{v:08x}' for v in exported_entries[:nf]],
                            variable_addresses=[f'{v:08x}' for v in exported_entries[nf:nf+nv]],
                            tls_addresses=[f'{v:08x}' for v in exported_entries[nf+nv:]]))
        cursor+=size
    cursor,end=table(im_top,im_end)
    while cursor<end:
        size,res,lv=read(cursor,'<BBH')
        if size not in (0x24,0x34) or cursor+size>end or len(imports)>=MAX_RECORDS:raise ValueError('invalid import record')
        flags,nf,nv,nt=read(cursor+4,'<HHHH')
        if size==0x34:
            libnid,libname=read(cursor+0x10,'<II');nptr,sptr=read(cursor+0x1c,'<II')
        else:
            libnid,libname,nptr,sptr=read(cursor+0x0c,'<IIII')
        vnptr,vsptr=read(cursor+(0x24 if size==0x34 else 0x1c),'<II')
        imported_variables=arr(vnptr,nv);variable_refs=arr(vsptr,nv)
        imported_nids=arr(nptr,nf)
        imported_stubs=arr(sptr,nf)
        imports.append(dict(library=label(libname),library_nid=f'{libnid:08x}',functions=nf,variables=nv,tls_variables=nt,
                            function_nids=[f'{v:08x}' for v in imported_nids],
                            function_stubs=[f'{v:08x}' for v in imported_stubs],
                            variable_nids=[f'{v:08x}' for v in imported_variables],
                            variable_references=[f'{v:08x}' for v in variable_refs],
                            raw_record_size=size))
        cursor+=size
    return {
        'file':path.name, 'module':name, 'elf_type':f'0x{typ:04x}', 'module_info':f'0x{mo:08x}',
        'module_nid':f'{module_nid:08x}', 'startup_entry':f'0x{base+start_off:08x}' if start_off != 0xffffffff else None,
        'tls':{'start':f'0x{tls_start:08x}', 'file_size':tls_filesz, 'memory_size':tls_memsz},
        'load_segments':load, 'relocation_segments':rel,
        'import_library_count':len(imports), 'import_function_count':sum(r['functions'] for r in imports),
        'import_variable_count':sum(r['variables'] for r in imports),'import_tls_count':sum(r['tls_variables'] for r in imports),
        'export_library_count':len(exports),'export_function_count':sum(r['functions'] for r in exports),
        'export_variable_count':sum(r['variables'] for r in exports),'export_tls_count':sum(r['tls_variables'] for r in exports),
        'imports':imports,'exports':exports,'status':'STRUCTURAL_INSPECTION_ONLY_NO_EXECUTION'
    }

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('paths',nargs='+',type=Path)
    args=p.parse_args()
    print(json.dumps([inventory(path) for path in args.paths],indent=2))
