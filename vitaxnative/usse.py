"""Fail-closed USSE subset -> typed register IR -> Metal.

Encoding facts: Vita3K shader/usse_translator_entry.cpp, data.cpp and
usse_decode_helpers.cpp. No shader names, GUIDs or rendering templates are
used to infer instruction results. Scheduling is serial for this bounded subset.
"""
from dataclasses import dataclass,asdict
import struct
from pathlib import Path
from .gxp import inspect_gxp

PATTERNS={
 'VMOV':'00111pppstrydecbmmaanoooiwwwwkllffgghhhhjjjjjjqqqqqquuuuuuvvvvvv',
 'VPCK':'01000pppsnuydercaaaaffftttmmmmbbkkllgggggggoohiijjqqqqqqvwwwwwwx',
 'V32NMAD':'00001pppsrrydcbawwwwneeeemmoiittkkllffffffzzzzzzzggghhhhhhjjjjjj',
}
SWIZZLES=((0,0,0,0),(1,1,1,1),(2,2,2,2),(3,3,3,3),(0,1,2,3),
          (1,2,3,3),(0,1,2,2),(0,0,1,2),(0,1,0,1),(0,1,3,2),
          (2,0,1,3),(2,3,2,3),(1,2,0,2),(0,0,1,1),(0,2,3,3),(0,1,2,5))


class UnsupportedShader(ValueError):pass


@dataclass(frozen=True)
class Register:
    bank:str
    index:int


@dataclass(frozen=True)
class Operation:
    opcode:str
    destinations:tuple
    sources:tuple
    pc:int
    word:int
    modifiers:tuple=()
    ends_program:bool=False


def fields(word,pattern):
    result={}
    for char,bit in zip(pattern,f'{word:064b}'):
        if char in '01':
            if char!=bit:return None
        elif char!='-':result[char]=(result.get(char,0)<<1)|int(bit)
    return result


def register(bank,index,extended=False,destination=False):
    if extended or bank==3 and destination:raise UnsupportedShader('extended/indexed register bank')
    name=('tmp','out','pa','sa')[bank]
    if not 0<=index<120:raise UnsupportedShader('internal/out-of-range register')
    return Register(name,index)


def decode(word,pc,stage):
    # Single initial phase, no phase jumps or secondary effects. Exact control
    # encoding is accepted independently of shader identity.
    if word==0xfa44070000000000:return Operation('PHAS',(),(),pc,word)
    # Unconditional NOP opcode (Vita3K USSE flow-control encoding); no register effects.
    if word==0xf800094000000000:return Operation('NOP',(),(),pc,word)
    if word==0xfb275000a0200000 and stage=='vertex':return Operation('EMIT',(),(),pc,word,ends_program=True)
    f=fields(word,PATTERNS['V32NMAD'])
    if f is not None:
        if f['p'] or f['y'] or f['g'] not in (0,1) or not f['e'] or f['e']&~3:
            raise UnsupportedShader('V32NMAD predicate/opcode/write mask')
        swizzle=f['z']|(f['i']<<7)|(f['c']<<9)|(f['r']<<10)
        dst=[];src=[]
        for component in range(2):
            if f['e']&(1<<component):
                dst.append(register(f['t'],2*f['f']+component,f['d'],True))
                for selector,bank,index,extended in (
                    ((swizzle>>(3*component))&7,f['k'],f['h'],f['b']),
                    (SWIZZLES[f['w']][component],f['l'],f['j'],f['a'])):
                    src.append(Register('const',selector-4) if selector>=4 else register(bank,2*index+selector,extended))
        return Operation('MUL_F32' if f['g']==0 else 'ADD_F32',tuple(dst),tuple(src),pc,word,(f['m'],f['o']))
    f=fields(word,PATTERNS['VMOV'])
    if f is not None:
        if f['p'] or f['m'] or f['o']!=5 or f['y'] or f['t'] or f['r'] or f['i']:
            raise UnsupportedShader('VMOV predicate/type/test/synchronization mode')
        if f['h']&~3 or not f['h']:raise UnsupportedShader('VMOV F32 write mask')
        dst=[];src=[]
        for repeat in range(f['a']+1):
            for channel in range(2):
                if f['h']&(1<<channel):
                    component=SWIZZLES[f['w']][channel]
                    if component>3:raise UnsupportedShader('VMOV constant swizzle')
                    dst.append(register(f['l'],2*f['j']+2*repeat+channel,f['d'],True))
                    src.append(register(f['f'],2*f['u']+2*repeat+component,f['c']))
        if f['a'] and set(dst)&set(src):raise UnsupportedShader('overlapping repeated VMOV')
        return Operation('MOV_F32',tuple(dst),tuple(src),pc,word,ends_program=bool(f['e']))
    f=fields(word,PATTERNS['VPCK'])
    if f is not None:
        if f['p'] or f['y'] or f['a'] or f['f']!=6 or f['t']!=5 or f['h'] or f['m']!=15:
            raise UnsupportedShader('VPCK supports unscaled unconditional F32 -> F16 full vector only')
        swizzle=(f['x']|(f['v']<<1),f['i'],f['j'],f['o'])
        src=[]
        same=f['q']==f['w'] and f['k']==f['l'] and f['r']==f['c']
        dual=not same or swizzle!=(0,1,2,3)
        for component in swizzle:
            if dual:
                src.append(register(f['k'] if component<2 else f['l'],
                                    (2*f['q'] if component<2 else 2*f['w'])+component%2,
                                    f['r'] if component<2 else f['c']))
            else:src.append(register(f['k'],2*f['q']+component,f['r']))
        dst=tuple(register(f['b'],f['g']+i,f['d'],True) for i in range(2))
        return Operation('PACK_F16',dst,tuple(src),pc,word,ends_program=bool(f['e']))
    raise UnsupportedShader(f'unknown/unsupported USSE major opcode {word>>59:#x}')


def translate_gxp(path):
    """Produce validated instruction IR and executable MSL for a bounded GXP."""
    info=inspect_gxp(path);raw=Path(path).read_bytes()
    u32=lambda at:struct.unpack_from('<I',raw,at)[0]
    if info['version'] not in ([1,4],[1,5]):raise UnsupportedShader('GXP version')
    if u32(68) or struct.unpack_from('<H',raw,58)[0]!=1:
        raise UnsupportedShader('secondary/multiple shader phases')
    # Reject semantic flags requiring discard, depth, framebuffer fetch or resources.
    if info['flags']&~0x000f1805:raise UnsupportedShader('GXP flags require unsupported stage behavior')
    if u32(24) not in (0,0x10000000) or u32(28) not in (0,1) or any(u32(at) for at in (32,80,84,88,96,112,120,128,136)):
        raise UnsupportedShader('texture/auxiliary resource or literal table')
    # DATA container19 describes SA allocation, not initialized values. Vita3K
    # gxp_parser uses it to locate specific literals/dependent resources. Accept
    # bounded matching allocation metadata; never mark its registers initialized.
    # Any decoded SA read still needs an actual uniform/literal definition.
    data_words=u32(92)
    if data_words:
        containers=next((r for r in info['regions'] if r['name']=='containers'),None)
        data_containers=[]
        if containers:
            data_containers=[struct.unpack_from('<4H',raw,containers['offset']+i*8)
                             for i in range(containers['count'])
                             if struct.unpack_from('<H',raw,containers['offset']+i*8)[0]==19]
        if len(data_containers)!=1 or data_containers[0][3]!=data_words or data_containers[0][2]+data_words>120:
            raise UnsupportedShader('DATA allocation does not match bounded container19')
    primary=next((r for r in info['regions'] if r['name']=='primary USSE'),None)
    if not primary or primary['count']>4096:raise UnsupportedShader('missing/oversized primary program')
    stage=info['stage'];varyings=44+u32(44)
    if not u32(44) or varyings+32>info['declared_size']:raise UnsupportedShader('missing varying metadata')
    initialized={Register('const',i) for i in range(4)};inputs=[];uniforms=[];samplers=[];queries=[]
    def mark(bank,start,count):
        if start<0 or start+count>120:raise UnsupportedShader('interface register range')
        initialized.update(Register(bank,i) for i in range(start,start+count))
    for parameter in info['parameters']:
        if parameter['type'] or not 1<=parameter['components']<=4 or not 1<=parameter['array_size']<=64:
            raise UnsupportedShader('non-F32 or invalid parameter/array bounds')
        start=parameter['resource_index'];count=parameter['components']
        if parameter['category']==0 and stage=='vertex':
            if parameter['array_size']!=1:raise UnsupportedShader('attribute arrays')
            mark('pa',start,count);inputs.append(parameter)
        elif parameter['category']==1 and parameter['container']==14:
            containers=next((r for r in info['regions'] if r['name']=='containers'),None)
            if not containers:raise UnsupportedShader('uniform has no register container')
            found=None
            for i in range(containers['count']):
                ci,_,base,length=struct.unpack_from('<4H',raw,containers['offset']+i*8)
                if ci==14:found=(base,length)
            arrays=parameter['array_size']
            stride=((count+1)&~1) if arrays>1 and count>1 else count
            extent=(arrays-1)*stride+count
            if found is None or start+extent>found[1]:raise UnsupportedShader('uniform outside container')
            for element in range(arrays):mark('sa',found[0]+start+element*stride,count)
            uniforms.append({**parameter,'sa_index':found[0]+start,'stride':stride,'word_span':extent})
        elif parameter['category']==2 and stage=='fragment' and parameter['resource_index']==0 and not parameter['semantic_index']&16:
            if parameter['array_size']!=1:raise UnsupportedShader('sampler arrays')
            samplers.append(parameter)
        else:raise UnsupportedShader('unsupported parameter category/container')
    if stage=='vertex':
        vo1,vo2=struct.unpack_from('<II',raw,varyings+16)
        if vo1&(0x200|0x400|0x10000) or vo2 not in (0,1):
            raise UnsupportedShader('vertex output interface other than position/color0/float2 TEXCOORD0')
        color=bool(vo1&0x800);texcoord=bool(vo2)
        if not color and not texcoord:raise UnsupportedShader('vertex has no supported varying')
        required=[Register('out',i) for i in range(4+4*color+2*texcoord)]
    else:
        if raw[varyings+8]!=0 or raw[varyings+10: varyings+12]!=bytes((1,4)):
            raise UnsupportedShader('fragment output other than PA0 F16x4')
        count=struct.unpack_from('<H',raw,varyings+12)[0]
        at=varyings+16+u32(varyings+16)
        if count!=1 or at<156 or at+16>info['declared_size']:
            raise UnsupportedShader('fragment varying descriptor range/count')
        attribute,resource,size,components=struct.unpack_from('<4I',raw,at)
        color=(attribute&0x4000f000==0xa000 and attribute&0x30100000==0x100000 and
               attribute&0x40f==15 and ((attribute>>22)&3)==3)
        texcoord=(attribute&0x4000f000==0xf000 and attribute&0x40f==0 and
                  attribute&0x300==0x100 and not attribute&0x10 and components==0x20 and resource==0)
        if color:
            if samplers or u32(28):raise UnsupportedShader('unused/ambiguous texture resources')
            mark('pa',0,4)
        elif texcoord:
            if len(samplers)!=1 or u32(28)!=1:raise UnsupportedShader('texture query sampler mapping')
            mark('pa',0,2)
            queries.append({'kind':'sample2d','texture':0,'sampler':0,'coordinates':'TEXCOORD0',
                            'result':'PA0/PA1 packed F16x4','sampling_profile':'normalized coordinates; caller supplies filter; clamp-to-edge'})
        else:raise UnsupportedShader('fragment iterator/query other than F32 COLOR0 or sampler0 TEXCOORD0 F16')
        required=[Register('pa',0),Register('pa',1)]
    operations=[];formats={r:'f32' for r in initialized}
    if queries:formats.update({Register('pa',i):'f16x2' for i in range(2)})
    for i in range(primary['count']):
        pc=primary['offset']+i*8;word=struct.unpack_from('<Q',raw,pc)[0]
        try:operation=decode(word,pc,stage)
        except UnsupportedShader as error:raise UnsupportedShader(f'{stage} USSE +{pc:#x} word {word:016x}: {error}') from error
        if operation.opcode=='PHAS' and i!=0:raise UnsupportedShader('PHAS must be initial')
        if operation.opcode=='EMIT' and i!=primary['count']-1:raise UnsupportedShader('instructions after EMIT')
        if operation.ends_program and i!=primary['count']-1:raise UnsupportedShader('instructions after shader END')
        for source in operation.sources:
            if source not in initialized:raise UnsupportedShader(f'uninitialized {source.bank}{source.index} at {pc:#x}')
        initialized.update(operation.destinations)
        formats.update({r:'f16x2' if operation.opcode=='PACK_F16' else 'f32' for r in operation.destinations})
        operations.append(operation)
    if operations[0].opcode!='PHAS' or stage=='vertex' and operations[-1].opcode!='EMIT':
        raise UnsupportedShader('missing shader phase/vertex emit')
    if any(reg not in initialized for reg in required):raise UnsupportedShader('shader output is not fully defined')
    if stage=='fragment' and any(formats.get(r)!='f16x2' for r in required):
        raise UnsupportedShader('fragment output has no validated F16 pack')
    interface={'color':color,'texcoord':texcoord}
    msl=generate_msl(stage,operations,inputs,uniforms,interface,queries)
    return {'input_sha256':info['sha256'],'stage':stage,'entry':'vx_gxp_v' if stage=='vertex' else 'vx_gxp_f',
            'operations':[asdict(o) for o in operations],'inputs':inputs,'uniforms':uniforms,
            'uniform_words':max((p['resource_index']+p['word_span'] for p in uniforms),default=0),'data_allocation_words':data_words,
            'interface':interface,
            'samplers':samplers,'implicit_queries':queries,'texture_mask':1 if queries else 0,
            'msl':msl,'translation_supported':True,'rendering_verified':False,
            'limitations':['bounded unconditional F32 MOV/ADD/MUL and F32/F16 packing; position/COLOR0/TEXCOORD0; sampler0 nondependent 2D query only']}


def generate_msl(stage,operations,inputs,uniforms,interface,queries):
    lines=['#include <metal_stdlib>','using namespace metal;',
           'struct VXLink { float4 position [[position]];'+
           (' float4 color [[user(color0)]];' if interface['color'] else '')+
           (' float2 texcoord [[user(texcoord0)]];' if interface['texcoord'] else '')+' };']
    if stage=='vertex':
        lines+=['struct VXInput {']
        for i,item in enumerate(inputs):
            count=item['components'];type='float' if count==1 else f'float{count}'
            lines.append(f'{type} a{i} [[attribute({i})]];')
        lines+=['};','vertex VXLink vx_gxp_v(VXInput input [[stage_in]],constant uint *uniforms [[buffer(1)]]) {']
    else:lines+=['fragment float4 vx_gxp_f(VXLink input [[stage_in]],constant uint *uniforms [[buffer(1)]]'+
                 (',texture2d<half> texture0 [[texture(0)]],sampler sampler0 [[sampler(0)]]' if queries else '')+') {']
    lines+=['uint pa[128],sa[128],tmp[128],out[128];']
    for i,item in enumerate(inputs):
        for j in range(item['components']):
            value=f'input.a{i}'+(f'[{j}]' if item['components']>1 else '')
            lines.append(f'pa[{item["resource_index"]+j}]=as_type<uint>({value});')
    for item in uniforms:
        for element in range(item['array_size']):
            offset=element*item['stride']
            for j in range(item['components']):lines.append(f'sa[{item["sa_index"]+offset+j}]=uniforms[{item["resource_index"]+offset+j}];')
    if stage=='fragment' and interface['color']:lines += [f'pa[{j}]=as_type<uint>(input.color[{j}]);' for j in range(4)]
    if queries:lines+=['half4 sample_value=texture0.sample(sampler0,input.texcoord);',
                       'pa[0]=as_type<uint>(sample_value.xy);pa[1]=as_type<uint>(sample_value.zw);']
    for i,op in enumerate(operations):
        def ref(reg):return ('0u','0x3f800000u','0x40000000u','0x3f000000u')[reg.index] if reg.bank=='const' else f'{reg.bank}[{reg.index}]'
        if op.opcode=='MOV_F32':
            lines.append('{')
            for j,src in enumerate(op.sources):lines.append(f'uint s{j}={ref(src)};')
            for j,dst in enumerate(op.destinations):lines.append(f'{ref(dst)}=s{j};')
            lines.append('}')
        elif op.opcode=='PACK_F16':
            values=','.join(f'half(as_type<float>({ref(src)}))' for src in op.sources)
            lines.append(f'{{ half4 value=half4({values});')
            for j,dst in enumerate(op.destinations):lines.append(f'{ref(dst)}=as_type<uint>(value.{"xy" if j==0 else "zw"});')
            lines.append('}')
        elif op.opcode in ('ADD_F32','MUL_F32'):
            lines.append('{')
            for j in range(len(op.destinations)):
                values=[]
                for k in range(2):
                    value=ref(op.sources[j*2+k]);modifier=op.modifiers[k]
                    if modifier&2:value=f'({value}&0x7fffffffu)'
                    if modifier&1:value=f'({value}^0x80000000u)'
                    values.append(f'as_type<float>({value})')
                lines.append(f'float v{j}={values[0]}{"+" if op.opcode=="ADD_F32" else "*"}{values[1]};')
            for j,dst in enumerate(op.destinations):lines.append(f'{ref(dst)}=as_type<uint>(v{j});')
            lines.append('}')
    if stage=='vertex':
        lines+=['VXLink result;result.position=as_type<float4>(uint4(out[0],out[1],out[2],out[3]));']
        if interface['color']:lines.append('result.color=as_type<float4>(uint4(out[4],out[5],out[6],out[7]));')
        if interface['texcoord']:
            start=8 if interface['color'] else 4
            lines.append(f'result.texcoord=as_type<float2>(uint2(out[{start}],out[{start+1}]));')
        lines.append('return result;')
    else:lines+=['return float4(float2(as_type<half2>(pa[0])),float2(as_type<half2>(pa[1])));']
    return '\n'.join(lines+['}'])+'\n'


def translate_pair(vertex,fragment):
    v=translate_gxp(vertex);f=translate_gxp(fragment)
    if v['stage']!='vertex' or f['stage']!='fragment':raise UnsupportedShader('shader pair stage mismatch')
    for varying,needed in f['interface'].items():
        if needed and not v['interface'].get(varying):raise UnsupportedShader(f'fragment requires missing vertex {varying} varying')
    return {'vertex':v,'fragment':f,'rendering_verified':False}
