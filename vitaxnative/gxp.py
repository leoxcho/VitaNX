"""Read-only bounded GXP inventory, never shader acceptance or translation.

Layout reference: Vita3K's SceGxmProgram/SceGxmProgramParameter declarations:
https://github.com/Vita3K/Vita3K/blob/master/vita3k/gxm/include/gxm/types.h
Offsets are relative to their own fields; USSE instructions are 64-bit words.
"""
import hashlib
import struct
from pathlib import Path

HEADER_SIZE=156
MAX_SIZE=16*1024*1024
MAX_ITEMS=65536


def inspect_gxp(path):
    path=Path(path)
    with path.open('rb') as stream:
        raw=stream.read(MAX_SIZE+1)
    if len(raw)>MAX_SIZE:raise ValueError('GXP exceeds inspection size limit')
    if len(raw)<HEADER_SIZE or raw[:4]!=b'GXP\0':
        raise ValueError('invalid or truncated GXP header')
    major,minor,sdk=struct.unpack_from('<BBH',raw,4)
    if major!=1 or minor<4:raise ValueError('unsupported GXP version')
    u32=lambda offset:struct.unpack_from('<I',raw,offset)[0]
    size=u32(8)
    if not HEADER_SIZE<=size<=len(raw):raise ValueError('invalid GXP declared size')
    regions=[]

    def region(name,count,offset_field,stride,alignment=4,minimum=HEADER_SIZE):
        if count>MAX_ITEMS:raise ValueError(f'GXP {name} exceeds item limit')
        if not count:return None
        relative=u32(offset_field)
        start=offset_field+relative
        length=count*stride
        if not relative or start<minimum or start%alignment or start>size or length>size-start:
            raise ValueError(f'GXP {name} outside declared data or misaligned')
        if any(start<r['offset']+r['size'] and r['offset']<start+length for r in regions):
            raise ValueError(f'GXP {name} overlaps another inspected region')
        result={'name':name,'offset':start,'size':length,'count':count}
        regions.append(result)
        return result

    # Real SDK shaders can start at offsets congruent to 4 modulo 8.
    # Instruction size is eight bytes; file alignment is only four bytes.
    primary=region('primary USSE',u32(60),64,8)
    secondary=region('secondary USSE',u32(68),72,8)
    parameters=region('parameters',u32(36),40,16)
    if u32(44):
        at=44+u32(44)
        # Fragment programs without iterators need only the first 16 bytes.
        # Genuine SDK images reuse the unused tail for primary instructions.
        short=bool(u32(20)&1) and 156<=at<=size-16 and struct.unpack_from('<H',raw,at+12)[0]==0
        # Original GXP 1.4 programs can place varyings at152, reusing the
        # optional sampler_query_info_offset tail added to later headers.
        region('varyings',1,44,16 if short else 32,minimum=152 if minor==4 else HEADER_SIZE)
    for name,count_field,offset_field,stride in (
        ('literals',112,116,8),('uniform buffers',120,124,8),
        ('dependent samplers',128,132,4),('texture dependent samplers',136,140,4),
        ('containers',144,148,8)):
        region(name,u32(count_field),offset_field,stride)
    params=[]
    if parameters:
        for i in range(parameters['count']):
            at=parameters['offset']+i*16
            name_at=at+struct.unpack_from('<i',raw,at)[0]
            if not HEADER_SIZE<=name_at<size:raise ValueError('GXP parameter name outside declared data')
            end=raw.find(b'\0',name_at,min(size,name_at+4096))
            if end<0:raise ValueError('GXP parameter name is unterminated or too long')
            if any(name_at<r['offset']+r['size'] and r['offset']<end+1 for r in regions):
                raise ValueError('GXP parameter name overlaps an inspected region')
            params.append({'name':raw[name_at:end].decode('utf-8',errors='replace'),
                           'category':raw[at+4]&15,'type':raw[at+4]>>4,
                           'components':raw[at+5]&15,'container':raw[at+5]>>4,
                           'semantic':raw[at+6],'semantic_index':raw[at+7],
                           'array_size':u32(at+8),'resource_index':u32(at+12)})
    programs=[]
    for item in (primary,secondary):
        if item:
            begin=item['offset'];data=raw[begin:begin+item['size']]
            programs.append({**item,'sha256':hashlib.sha256(data).hexdigest(),
                             'preview_words':[f'{value:016x}' for value, in
                                              struct.iter_unpack('<Q',data[:128])]})
    return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),
            'format':'GXP','version':[major,minor],'sdk_version':sdk,
            'declared_size':size,'trailing_bytes':len(raw)-size,
            'stage':'fragment' if u32(20)&1 else 'vertex','flags':u32(20),
            'parameters':params,'regions':regions,'programs':programs,
            'translation_supported':False,
            'unsupported_reason':'USSE instruction decoding and Metal lowering are not implemented',
            'limitations':['selected structural regions only; not complete GXP semantic validation',
                           'no shader execution or rendering claim']}
