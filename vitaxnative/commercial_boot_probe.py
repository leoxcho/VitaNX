"""Read-only Thumb decoding audit for a decrypted commercial Vita ELF.

Reports code-decoder coverage, not dynamic execution or a native app.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import struct

from .elf_segments import inspect_elf_segments
from .recompiler import _decode_thumb,_decode_thumb32,_decode_arm


def probe(path:Path,entry:int,max_instructions:int=500)->dict:
    path=Path(path)
    if max_instructions<1 or max_instructions>10000:raise ValueError('invalid decode budget')
    info=inspect_elf_segments(path)
    if info['elf_type'] not in (0xfe00,0xfe04):raise ValueError('Vita commercial SCE ELF required')
    data=path.read_bytes()
    targets=[entry];seen=set();errors=[];calls=[]
    while targets and len(seen)<max_instructions:
        ip=targets.pop()
        if ip in seen:continue
        thumb=bool(ip&1);address=ip&~1
        s=next((s for s in info['segments'] if s['flags']&1 and
            s['virtual_address']<=address and address+(2 if thumb else 4)<=
            s['virtual_address']+s['file_size']),None)
        if s is None:
            errors.append({'address':f'0x{ip:08x}','reason':'target outside executable bytes'});break
        fileoff=s['file_offset']+address-s['virtual_address']
        width=2 if thumb else 4
        word=int.from_bytes(data[fileoff:fileoff+width],'little')
        decoder=_decode_thumb if thumb else _decode_arm
        if thumb and word>>11 in (0b11101,0b11110,0b11111):
            width=4;word=int.from_bytes(data[fileoff:fileoff+width],'little')
            decoder=_decode_thumb32
        try:
            condition,code,branches,link=decoder(word,address)
        except ValueError as exc:
            errors.append({'address':f'0x{ip:08x}','opcode':f'0x{word:08x}',
                           'width':width,'reason':str(exc)})
            break
        seen.add(ip)
        if link:calls.append(f'0x{ip:08x}')
        for dest in branches:targets.append(dest)
        if not ('goto dispatch;' in code and condition=='1' and not link):
            targets.append((address+width)|int(thumb))
    return {'file':path.name,'requested_entry':f'0x{entry:08x}',
        'decoded_instruction_addresses':len(seen),
        'static_branch_and_call_count':len(calls),
        'first_error':errors[0] if errors else None,
        'remaining_unvisited_edges':len(targets),
        'budget_exhausted':len(seen)>=max_instructions,
        'executed':False,'native_app_built':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('elf',type=Path)
    p.add_argument('--entry',type=lambda s:int(s,0),required=True)
    p.add_argument('--limit',type=int,default=500)
    a=p.parse_args();print(json.dumps(probe(a.elf,a.entry,a.limit),indent=2))
