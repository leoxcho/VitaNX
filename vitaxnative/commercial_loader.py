"""Verified Vita SCE ELF32 module image rebasing, TLS, exact-NID link planning.

This module does not execute foreign instructions. Unrecognized relocation forms
fail closed. Actual relocation targets/Thumb MOV immediates are rewritten.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import argparse
import json
import struct

from .commercial_vita_inventory import inventory

MAX_MODULE_SIZE=32*1024*1024
MAX_TLS=1024*1024
PT_SCE_RELA=0x60000000
ALIGN=0x10000


def align(value, alignment=ALIGN):
    return ((value+alignment-1)//alignment)*alignment


def _u32(data,off):return struct.unpack_from('<I',data,off)[0]
def _write32(data,off,value):struct.pack_into('<I',data,off,value&0xffffffff)


def _thumb_mov_imm(word):
    h1,h2=word&0xffff,word>>16
    return ((h1&15)<<12)|(((h1>>10)&1)<<11)|(((h2>>12)&7)<<8)|(h2&255)


def _replace_thumb_mov_imm(word,value):
    h1,h2=word&0xffff,word>>16
    h1=(h1 & ~0x40f) | ((value>>12)&15) | (((value>>11)&1)<<10)
    h2=(h2 & ~0x70ff) | (((value>>8)&7)<<12) | (value&255)
    return h1|(h2<<16)


@dataclass
class MappedModule:
    name:str
    path:Path
    old_base:int
    new_base:int
    memory:bytearray
    segments:list
    metadata:dict
    relocation_counts:dict
    tls_template:bytes
    tls_memsz:int

    @property
    def delta(self):return self.new_base-self.old_base
    def guest_address(self,original):return original+self.delta
    def tls_for_thread(self):
        """New isolated zero-initialized TLS block on each guest-thread creation."""
        return bytearray(self.tls_template+b'\0'*(self.tls_memsz-len(self.tls_template)))
    def word(self,old_address):return _u32(self.memory,old_address-self.old_base)


def map_module(path:Path,new_base:int|None=None)->MappedModule:
    path=Path(path)
    metadata=inventory(path)
    segs=metadata['load_segments']
    if not segs:raise ValueError('module has no load segments')
    old_base=min(x['address'] for x in segs)
    high=max(x['address']+x['memory_size'] for x in segs)
    size=high-old_base
    if size<=0 or size>MAX_MODULE_SIZE:raise ValueError('module memory size exceeds cap')
    if new_base is None:new_base=old_base
    if new_base%ALIGN:raise ValueError('new module base must be 64KB aligned')
    if new_base+size>0x100000000:raise ValueError('guest address overflow')
    raw=path.read_bytes()
    image=bytearray(size)
    for seg in segs:
        src=seg['offset'];off=seg['address']-old_base
        image[off:off+seg['file_size']]=raw[src:src+seg['file_size']]
    tls=metadata['tls'];fs=tls['file_size'];ms=tls['memory_size']
    if fs>ms or ms>MAX_TLS:raise ValueError('invalid TLS template sizing')
    tls_template=b''
    if fs:
        # Vita module info uses a module-base-relative TLS source offset.
        source=old_base+int(tls['start'],16)
        for seg in segs:
            if seg['address']<=source and source+fs<=seg['address']+seg['file_size']:
                off=source-old_base
                tls_template=bytes(image[off:off+fs]);break
        else:raise ValueError('TLS template is outside initialized load memory')
    phoff=struct.unpack_from('<I',raw,28)[0]
    phnum=struct.unpack_from('<H',raw,44)[0]
    counts=Counter()
    for ph in range(phnum):
        typ,off,_,_,length=struct.unpack_from('<IIIII',raw,phoff+32*ph)
        if typ!=PT_SCE_RELA:continue
        if off>len(raw) or length>len(raw)-off or length%12:
            raise ValueError('unsupported relocation payload bounds/form')
        for cursor in range(off,off+length,12):
            first,addend,site_offset=struct.unpack_from('<III',raw,cursor)
            if first&15 or first>>20:raise ValueError('relocation form/paired relocation unsupported')
            symi,code,datai=(first>>4)&15,(first>>8)&255,(first>>16)&15
            if symi>=len(segs) or datai>=len(segs):
                # PT_LOAD indices are not guaranteed contiguous in all modules;
                # indices must refer to program headers, not load-order.
                lookup={s['index']:s for s in segs}
                if symi not in lookup or datai not in lookup:
                    raise ValueError('relocation references missing load segment')
                syms=lookup[symi];dst=lookup[datai]
            else:
                lookup={s['index']:s for s in segs}
                if symi not in lookup or datai not in lookup:raise ValueError('relocation indices invalid')
                syms,dst=lookup[symi],lookup[datai]
            if site_offset>dst['file_size'] or 4>dst['file_size']-site_offset:
                raise ValueError('relocation site outside file-backed segment')
            place=dst['address']+site_offset-old_base
            if not 0<=place<=len(image)-4:raise ValueError('relocation exceeds mapped memory')
            old_target=(syms['address']+addend)&0xffffffff
            new_target=(syms['address']+(new_base-old_base)+addend)&0xffffffff
            word=_u32(image,place)
            if code==2:  # R_ARM_ABS32
                if word!=old_target:raise ValueError('original ABS32 relocation mismatch')
                new_word=new_target
            elif code in (47,48):  # R_ARM_THM_MOVW_ABS_NC, MOVT_ABS
                first_half,second_half=word&0xffff,word>>16
                expected_opcode=0xf240 if code==47 else 0xf2c0
                if first_half&0xfbf0!=expected_opcode or second_half&0x8000:
                    raise ValueError('Thumb MOVW/MOVT relocation opcode mismatch')
                before=old_target&0xffff if code==47 else old_target>>16
                after=new_target&0xffff if code==47 else new_target>>16
                if _thumb_mov_imm(word)!=before:
                    raise ValueError('original Thumb relocation immediate mismatch')
                new_word=_replace_thumb_mov_imm(word,after)
            else:
                raise ValueError(f'unsupported commercial relocation type {code}')
            _write32(image,place,new_word)
            counts[code]+=1
    return MappedModule(metadata['module'],path,old_base,new_base,image,segs,
                        metadata,dict(counts),tls_template,ms)


def make_link_plan(modules:list[MappedModule]):
    """Exact library+symbol NID target addresses after module rebasing.

    Does not patch import stubs. Unknown providers or duplicate candidates
    are preserved for the runtime linker to reject/resolve explicitly.
    """
    exported={}
    for mod in modules:
        for lib in mod.metadata['exports']:
            for nid,old_address in zip(lib['function_nids'],lib['function_addresses']):
                # Some exports may be non-code descriptors; keep only mapped
                # valid executable addresses as binding candidates.
                addr=int(old_address,16)
                if not any(seg['flags']&1 and seg['address']<= (addr&~1) and (addr&~1)+2<=seg['address']+seg['file_size'] for seg in mod.segments):
                    raise ValueError('function export outside executable mapped bytes')
                key=(lib['library_nid'],nid)
                exported.setdefault(key,[]).append({'module':mod.name,
                   'address':f'0x{mod.guest_address(addr):08x}'})
    result={}
    for mod in modules:
        bindings=[];missing=[]
        for lib in mod.metadata['imports']:
            for nid,stub in zip(lib['function_nids'],lib['function_stubs']):
                candidate=exported.get((lib['library_nid'],nid),[])
                entry={'library':lib['library'], 'library_nid':lib['library_nid'],
                       'function_nid':nid,'guest_stub':f'0x{mod.guest_address(int(stub,16)):08x}'}
                if len(candidate)==1:bindings.append({**entry,'target':candidate[0]})
                else:missing.append({**entry,'candidate_count':len(candidate)})
        result[mod.name]={'resolved':len(bindings),'unresolved_or_ambiguous':len(missing),
                          'bound_targets':bindings,'other_imports':{
                              'variable':mod.metadata['import_variable_count'],
                              'tls_variable':mod.metadata['import_tls_count']}}
    return result


def map_commercial_game(paths:list[Path], *, support_base=0x90000000):
    """Map one fixed-address main plus rebase support modules, without execution."""
    if not paths:raise ValueError('no modules')
    result=[];next_base=support_base
    for i,path in enumerate(paths):
        mod=map_module(path,None if i==0 else next_base)
        for other in result:
            if mod.new_base<other.new_base+len(other.memory) and other.new_base<mod.new_base+len(mod.memory):
                raise ValueError('guest module address collision')
        if any(other.name==mod.name for other in result):raise ValueError('duplicate module name')
        result.append(mod)
        if i:next_base=align(mod.new_base+len(mod.memory))
    return result


def report(paths):
    modules=map_commercial_game(paths)
    links=make_link_plan(modules)
    return {'status':'REBASED_AND_STAGED_NOT_EXECUTED',
       'modules':[{'name':m.name,'base_before':f'0x{m.old_base:08x}',
          'base_after':f'0x{m.new_base:08x}','mapped_bytes':len(m.memory),
          'relocations_applied':sum(m.relocation_counts.values()),
          'relocation_types':m.relocation_counts,
          'tls_template_bytes':len(m.tls_template),'tls_per_thread_bytes':m.tls_memsz}
          for m in modules], 'imports':{n:{k:v for k,v in x.items() if k!='bound_targets'} for n,x in links.items()},
          'limitations':['NID bindings are planned, not patched into guest stubs',
                         'Vita kernel APIs and runtime services are not implemented here',
                         'ARM/Thumb code was not executed or rebuilt as native app']}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('paths',nargs='+',type=Path)
    args=ap.parse_args();print(json.dumps(report(args.paths),indent=2))


def link_variables(modules, external_exports=None):
    """Bind exact library/NID exports through Vita variable relocation tables.

    Formats 1Alt/2Alt only; checked ABS32 and Thumb MOVW/MOVT. Missing symbols
    remain explicit requirements. Validate the complete plan before committing.
    Layout reference: Vita3K kernel relocation.cpp and load_self.cpp (GPLv2).
    """
    exports={k:[v] for k,v in (external_exports or {}).items()};writes=[];missing=[];resolved=[]
    for m in modules:
        for lib in m.metadata['exports']:
            for nid,address in zip(lib['variable_nids'],lib['variable_addresses']):
                old=int(address,16)
                if not any(s['address']<=old<s['address']+s['memory_size'] for s in m.segments):
                    raise ValueError('variable export outside mapped memory')
                exports.setdefault((lib['library_nid'],nid),[]).append(m.guest_address(old))
    for m in modules:
        lookup={s['index']:s for s in m.segments}
        for lib in m.metadata['imports']:
            for nid,reference in zip(lib['variable_nids'],lib['variable_references']):
                candidates=exports.get((lib['library_nid'],nid),[])
                item={'module':m.name,'library':lib['library'],'nid':nid}
                if len(candidates)!=1:missing.append({**item,'candidate_count':len(candidates)});continue
                off=int(reference,16)-m.old_base
                if not 0<=off<=len(m.memory)-4:raise ValueError('variable reference header outside image')
                header=_u32(m.memory,off);length=(header>>4)&0xffffff
                if header&0xf000000f or length<4 or off+length>len(m.memory):raise ValueError('invalid variable reference size')
                cursor,end=off+4,off+length
                while cursor<end:
                    if end-cursor<8:raise ValueError('truncated variable relocation')
                    first,site=struct.unpack_from('<II',m.memory,cursor)
                    form,segment,code=first&15,(first>>4)&15,(first>>8)&255
                    if form==1:addend=first>>16;cursor+=8
                    elif form==2:
                        if first>>16 or end-cursor<12:raise ValueError('invalid extended variable relocation')
                        addend=_u32(m.memory,cursor+8);cursor+=12
                    else:raise ValueError('unsupported variable relocation format')
                    if segment not in lookup:raise ValueError('variable relocation segment missing')
                    seg=lookup[segment]
                    if site>seg['memory_size'] or 4>seg['memory_size']-site:raise ValueError('variable relocation site outside segment')
                    dest=seg['address']-m.old_base+site;value=(candidates[0]+addend)&0xffffffff
                    old=_u32(m.memory,dest)
                    if code==2:new=value
                    elif code in (47,48):
                        if old&0xfbf0!=(0xf240 if code==47 else 0xf2c0) or old>>16&0x8000:raise ValueError('variable MOV relocation opcode mismatch')
                        new=_replace_thumb_mov_imm(old,value&65535 if code==47 else value>>16)
                    else:raise ValueError(f'unsupported variable relocation type {code}')
                    writes.append((m,dest,new))
                resolved.append(item)
    seen=set()
    for m,dest,new in writes:
        for byte in range(dest,dest+4):
            key=(id(m),byte)
            if key in seen:raise ValueError('overlapping variable relocation sites')
            seen.add(key)
    for m,dest,new in writes:_write32(m.memory,dest,new)
    return {'bound':resolved,'missing':missing,'relocations_applied':len(writes)}
