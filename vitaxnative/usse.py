"""Fail-closed USSE subset -> typed register IR -> Metal.

Encoding facts: Vita3K shader/usse_translator_entry.cpp, data.cpp and
usse_decode_helpers.cpp. No shader names, GUIDs or rendering templates are
used to infer instruction results. Scheduling is serial for this bounded subset.
"""
from collections import deque
from dataclasses import dataclass,asdict,replace
import struct
from pathlib import Path
from .gxp import MAX_SIZE, inspect_gxp_bytes

PATTERNS={
 'PHAS':'11111010s100eirc--matwwwppppppppbbnn--------xxxxxxoooooooddddddd',
 'VTST':'01001ppps-oydrceavttiizzmhhhnnbbkkffgggggggwlluuuujjjjjjjqqqqqqq',
 'BR':'11111ppps000e-----wynba00r----------------iloooooooooooooooooooo',
 'SMP':'11100pppsn-ymrceffaaddlltbbggkhhiijjoooooooqqqqqqquuuuuuuvvvvvvv',
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
    target:int|None=None


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
    phase=fields(word,PATTERNS['PHAS'])
    if phase is not None:
        address=(phase['x']<<14)|(phase['o']<<7)|phase['d']
        if not phase['i'] or any(phase[key] for key in 'sercmabn'):
            raise UnsupportedShader('dynamic or rate-changing PHAS')
        if phase['w']==7 and not address:
            return Operation('PHAS',(),(),pc,word)
        if phase['w']==0 and address:
            return Operation('PHAS',(),(),pc,word,target=address)
        raise UnsupportedShader('unsupported PHAS wait condition')
    if word==0xf800094000000000:return Operation('NOP',(),(),pc,word)
    if word==0xfb275000a0200000 and stage=='vertex':return Operation('EMIT',(),(),pc,word,ends_program=True)
    branch=fields(word,PATTERNS['BR'])
    if branch is not None:
        if not branch['r'] or any(branch[key] for key in 'sewybail') or branch['p']==7:
            raise UnsupportedShader('absolute, PN or synchronized BR')
        offset=branch['o']
        if offset&(1<<19):offset-=1<<20
        pred=branch['p']
        sources=() if not pred else (Register('pred',pred-1 if pred<=4 else pred-5),)
        return Operation('BR',(),sources,pc,word,(pred>=5,),target=offset)
    test=fields(word,PATTERNS['VTST'])
    if test is not None:
        if (any(test[key] for key in 'psoydcetmwll') or not test['a'] or test['u']!=14
                or test['h']>=4 or test['z'] not in (1,2) or test['i']>=3):
            raise UnsupportedShader('VTST other than unconditional F32 subtraction comparison')
        lane=test['h']
        lhs=register(test['k'],2*test['j']+lane)
        rhs=register(test['f'],2*test['q']+(0 if test['v'] else lane))
        return Operation('CMP_F32',(Register('pred',test['n']),),(lhs,rhs),pc,word,
                         (test['i'],test['z']==1,bool(test['r'])))
    sample=fields(word,PATTERNS['SMP'])
    if sample is not None:
        f=sample
        if (stage!='fragment' or any(f[k] for k in 'pymceabgl') or
                f['d']!=1 or f['i']!=3 or f['f'] not in (2,3)):
            raise UnsupportedShader('SMP requires unconditional 2D implicit-LOD F16/F32 sampling')
        coord_bank=((0,2),(1,3))[f['r']][f['k']]
        src=tuple(register(coord_bank,2*f['q']+j) for j in range(2))
        dst=tuple(register(2 if f['t'] else 0,f['o']+j,False,True)
                  for j in range(2 if f['f']==2 else 4))
        return Operation('SAMPLE_F16' if f['f']==2 else 'SAMPLE_F32',dst,src,pc,word,(2*f['u'],))
    f=fields(word,PATTERNS['V32NMAD'])
    if f is not None:
        opcodes={0:'MUL_F32',1:'ADD_F32',5:'MIN_F32',6:'MAX_F32'}
        if f['p'] or f['y'] or f['g'] not in opcodes or not f['e'] or f['e']&~3:
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
        return Operation(opcodes[f['g']],tuple(dst),tuple(src),pc,word,(f['m'],f['o']))
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
    with Path(path).open('rb') as stream:
        return translate_gxp_bytes(stream.read(MAX_SIZE+1), path)


def translate_gxp_bytes(raw, path='<guest memory>'):
    info=inspect_gxp_bytes(raw, path)
    u32=lambda at:struct.unpack_from('<I',raw,at)[0]
    if info['version'] not in ([1,4],[1,5]):raise UnsupportedShader('GXP version')
    phase_count=struct.unpack_from('<H',raw,58)[0]
    if not 1<=phase_count<=32:raise UnsupportedShader('invalid primary shader phase count')
    # Reject semantic flags requiring discard, depth, framebuffer fetch or resources.
    if info['flags']&~0x000f1805:raise UnsupportedShader('GXP flags require unsupported stage behavior')
    if u32(24) not in (0,0x10000000) or any(u32(at)&~0x33333333 for at in (28,32)) or any(u32(at) for at in (80,84,88,96,120,136)):
        raise UnsupportedShader('texture/auxiliary resource or literal table')
    container_region=next((r for r in info['regions'] if r['name']=='containers'),None)
    containers={}
    if container_region:
        for index in range(container_region['count']):
            ident,_,base,length=struct.unpack_from('<4H',raw,container_region['offset']+index*8)
            if ident in containers:raise UnsupportedShader('duplicate register container')
            containers[ident]=(base,length)
    data_words=u32(92)
    if data_words:
        data=containers.get(19)
        if data is None or data[1]!=data_words or sum(data)>120:
            raise UnsupportedShader('DATA allocation does not match bounded container19')
    primary=next((r for r in info['regions'] if r['name']=='primary USSE'),None)
    if not primary or primary['count']>4096:raise UnsupportedShader('missing/oversized primary program')
    secondary=next((r for r in info['regions'] if r['name']=='secondary USSE'),None)
    if secondary:
        end=secondary['offset']+secondary['size']
        if secondary['count']>4096 or not u32(76) or 76+u32(76)!=end:
            raise UnsupportedShader('inconsistent secondary program extent')
    stage=info['stage'];varyings=44+u32(44)
    if not u32(44) or varyings+32>info['declared_size']:raise UnsupportedShader('missing varying metadata')
    initialized={Register('const',i) for i in range(4)};inputs=[];uniforms=[];samplers=[];queries=[];iterators=[]
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
            found=containers.get(14)
            arrays=parameter['array_size']
            stride=((count+1)&~1) if arrays>1 and count>1 else count
            extent=(arrays-1)*stride+count
            if found is None or start+extent>found[1]:raise UnsupportedShader('uniform outside container')
            for element in range(arrays):mark('sa',found[0]+start+element*stride,count)
            uniforms.append({**parameter,'sa_index':found[0]+start,'stride':stride,'word_span':extent})
        elif parameter['category']==2 and stage=='fragment' and start<16 and not parameter['semantic_index']&16:
            if parameter['array_size']!=1 or any(p['resource_index']==start for p in samplers):
                raise UnsupportedShader('duplicate sampler or sampler arrays')
            samplers.append(parameter)
        else:raise UnsupportedShader('unsupported parameter category/container')
    declared_samplers={item['resource_index'] for item in samplers}
    dependent={}
    dependent_region=next((r for r in info['regions'] if r['name']=='dependent samplers'),None)
    if dependent_region:
        data=containers.get(19)
        if stage!='fragment' or data is None or dependent_region['count']>64:
            raise UnsupportedShader('dependent sampler table without fragment DATA container')
        for offset in range(dependent_region['offset'],dependent_region['offset']+dependent_region['size'],4):
            layout,sa_offset=struct.unpack_from('<2H',raw,offset)
            slot=layout//4
            sa=data[0]+sa_offset
            if (slot not in declared_samplers or sa_offset>=data[1] or sa>=120
                    or sa in dependent or Register('sa',sa) in initialized):
                raise UnsupportedShader('invalid dependent sampler binding')
            dependent[sa]=slot
    literals={}
    literal_region=next((r for r in info['regions'] if r['name']=='literals'),None)
    if literal_region:
        container=containers.get(16,containers.get(19))
        if container is None or literal_region['count']>120:
            raise UnsupportedShader('literal table has no bounded SA container')
        base,length=container
        for index in range(literal_region['count']):
            offset,bits=struct.unpack_from('<2I',raw,literal_region['offset']+index*8)
            register_index=base+offset
            if offset>=length or register_index>=120 or register_index in dependent or Register('sa',register_index) in initialized:
                raise UnsupportedShader('literal outside its SA container or overlapping an initialized register')
            mark('sa',register_index,1)
            literals[register_index]=bits
    texcoords=set()
    if stage=='vertex':
        vo1,vo2=struct.unpack_from('<II',raw,varyings+16)
        if vo1&(0x200|0x400|0x10000) or vo2>>30:
            raise UnsupportedShader('unsupported vertex output interface')
        color=bool(vo1&0x800)
        for coord in range(10):
            layout=(vo2>>(coord*3))&7
            if layout not in (0,1):raise UnsupportedShader('texture coordinate output other than F32xy')
            if layout:texcoords.add(coord)
        if not color and not texcoords:raise UnsupportedShader('vertex has no supported varying')
        required=[Register('out',i) for i in range(4+4*color+2*len(texcoords))]
    else:
        if raw[varyings+8]!=0 or raw[varyings+10:varyings+12]!=bytes((1,4)):
            raise UnsupportedShader('fragment output other than PA0 F16x4')
        count=struct.unpack_from('<H',raw,varyings+12)[0]
        at=varyings+16+u32(varyings+16)
        if not 1<=count<=32 or at<156 or at+count*16>info['declared_size']:
            raise UnsupportedShader('fragment varying descriptor range/count')
        if any(at<r['offset']+r['size'] and r['offset']<at+count*16 and
               (r['name']!='varyings' or at<varyings+20) for r in info['regions']):
            raise UnsupportedShader('fragment varying descriptors overlap shader data')
        color=False
        pa=0
        for index in range(count):
            attribute,resource,size,components=struct.unpack_from('<4I',raw,at+index*16)
            kind=attribute&0x4000f000
            coord=attribute&0x40f
            if kind!=0xf000:
                width=((attribute>>22)&3)+1
                words=((size>>4)&3)+1
                if kind==0xa000 and attribute&0x30100000==0x100000 and width==4:
                    name='color'
                    color=True
                elif kind<=0x9000 and width==2 and not attribute&0x30000000:
                    name=f'texcoord{kind>>12}'
                    texcoords.add(kind>>12)
                else:raise UnsupportedShader('unsupported fragment iterator')
                if words<width:
                    if count!=1 or kind!=0xa000:raise UnsupportedShader('fragment iterator allocation')
                    words=width  # Original single COLOR0 fixtures use legacy descriptor size zero.
                mark('pa',pa,width)
                iterators.append((pa,width,name))
                pa+=words
            if coord==15:continue
            if coord>=10 or resource not in declared_samplers or attribute&0x300!=0x100 or attribute&0x10 or components not in (0x20,0x30):
                raise UnsupportedShader('unsupported fragment texture query')
            words=2 if components==0x20 else 4
            if ((size>>6)&3)+1!=words and not (count==1 and size==0 and words==2):
                raise UnsupportedShader('fragment texture query allocation')
            mark('pa',pa,words)
            texcoords.add(coord)
            queries.append({'kind':'sample2d','texture':resource,'sampler':resource,'coordinates':f'TEXCOORD{coord}',
                            'coordinate_index':coord,'destination':pa,'word_count':words})
            pa+=words
        required=[Register("pa",0),Register("pa",1)]

    operations=[];formats={r:'f32' for r in initialized}
    flow={}
    for query in queries:
        if query['word_count']==2:
            formats.update({Register('pa',query['destination']+i):'f16x2' for i in range(2)})
    dependent_slots=set()
    def lower_phase(region, is_secondary):
        phase='secondary' if is_secondary else 'primary'
        decoded=[]
        i,phases,next_phase=0,0,None
        while i<region['count']:
            pc=region['offset']+i*8
            word=struct.unpack_from('<Q',raw,pc)[0]
            try:operation=decode(word,pc,stage)
            except UnsupportedShader as error:
                raise UnsupportedShader(f'{stage} {phase} USSE +{pc:#x} word {word:016x}: {error}') from error
            if operation.opcode=='PHAS':
                if is_secondary and (i!=0 or operation.target is not None):
                    raise UnsupportedShader('secondary program phase transition')
                if i and next_phase!=i:
                    raise UnsupportedShader('PHAS entered without a scheduled transition')
                next_phase=operation.target
                if next_phase is not None and not i<next_phase<region['count']:
                    raise UnsupportedShader('PHAS target outside forward program bounds')
                phases+=1
            if operation.opcode=='EMIT' and (is_secondary or next_phase is not None):
                raise UnsupportedShader('vertex EMIT before final primary stage')
            if operation.opcode=='BR':
                target=i+operation.target
                if is_secondary or operation.sources or target<=i or target>=region['count'] or next_phase is not None and target>=next_phase:
                    raise UnsupportedShader('BR target leaves its phase')
                decoded.append(operation)
                i=target
                continue
            if operation.opcode in ('SAMPLE_F16','SAMPLE_F32'):
                if is_secondary or operation.modifiers[0] not in dependent:
                    raise UnsupportedShader('SMP has no primary dependent sampler binding')
                slot=dependent[operation.modifiers[0]]
                dependent_slots.add(slot)
                operation=replace(operation,modifiers=(slot,))
            if is_secondary and operation.opcode=='CMP_F32':
                raise UnsupportedShader('secondary predicates')
            if is_secondary:
                # The secondary stage computes secondary attributes. Its ordinary
                # register encodings all select SA, while special constants keep
                # their own bank. Indexed and internal operands still fail closed.
                remap=lambda reg: reg if reg.bank=='const' else Register('sa',reg.index)
                operation=replace(operation,destinations=tuple(map(remap,operation.destinations)),
                                  sources=tuple(map(remap,operation.sources)))
            for source in operation.sources:
                if source not in initialized:
                    raise UnsupportedShader(f'uninitialized {source.bank}{source.index} at {pc:#x}')
            if operation.opcode!='MOV_F32' and any(formats[r]!='f32' for r in operation.sources):
                raise UnsupportedShader('F32 operation reading a packed half register')
            initialized.update(operation.destinations)
            if operation.opcode=='MOV_F32':
                formats.update(zip(operation.destinations,[formats[r] for r in operation.sources]))
            else:
                result_type='f16x2' if operation.opcode in ('PACK_F16','SAMPLE_F16') else ('pred' if operation.opcode=='CMP_F32' else 'f32')
                formats.update({r:result_type for r in operation.destinations})
            decoded.append(operation)
            if operation.ends_program and next_phase is not None:
                i=next_phase
                if fields(struct.unpack_from('<Q',raw,region['offset']+i*8)[0],PATTERNS['PHAS']) is None:
                    raise UnsupportedShader('PHAS target is not a phase entry')
                continue
            if operation.ends_program and i!=region['count']-1:
                raise UnsupportedShader('instructions after shader phase END')
            i+=1
            if next_phase is not None and i>=next_phase:
                raise UnsupportedShader('phase transition without END')
        if not is_secondary and phases!=phase_count:
            raise UnsupportedShader('primary phase metadata does not match reachable phases')
        return decoded

    def lower_control_flow():
        # Track definitely defined register types across branches and backedges.
        start,count=primary['offset'],primary['count']
        words=lambda i:struct.unpack_from('<Q',raw,start+i*8)[0]
        entries={}
        i=0
        while True:
            op=decode(words(i),start+i*8,stage)
            if op.opcode!='PHAS':raise UnsupportedShader('PHAS target is not a phase entry')
            target=op.target
            if target is not None and not i<target<count:
                raise UnsupportedShader('PHAS target outside forward program bounds')
            entries[i]=target if target is not None else count
            if target is None:break
            i=target
        if len(entries)!=phase_count:raise UnsupportedShader('primary phase metadata does not match reachable phases')
        decoded={}
        exits=set()
        pending=[(0,0)]
        while pending:
            i,entry=pending.pop()
            if i in decoded:continue
            limit=entries[entry]
            op=decode(words(i),start+i*8,stage)
            if op.opcode=='PHAS' and i!=entry:raise UnsupportedShader('unscheduled PHAS')
            if op.opcode=='EMIT' and limit!=count:raise UnsupportedShader('vertex EMIT before final primary stage')
            if op.opcode in ('SAMPLE_F16','SAMPLE_F32'):
                if op.modifiers[0] not in dependent:raise UnsupportedShader('SMP has no primary dependent sampler binding')
                slot=dependent[op.modifiers[0]]
                dependent_slots.add(slot)
                op=replace(op,modifiers=(slot,))
            if op.opcode=='BR':
                target=i+op.target
                if not entry<target<limit:raise UnsupportedShader('BR target leaves its phase')
                edges=[(target,entry)]
                if op.sources:
                    if i+1>=limit:raise UnsupportedShader('branch fallthrough leaves its phase')
                    edges.append((i+1,entry))
            elif op.ends_program and limit<count:
                edges=[(limit,limit)]
            elif op.ends_program or i+1==limit:
                if limit<count:raise UnsupportedShader('phase transition without END')
                if stage=='vertex' and op.opcode!='EMIT':raise UnsupportedShader('missing shader phase/vertex emit')
                exits.add(i)
                edges=[]
            else:
                edges=[(i+1,entry)]
            decoded[i]=op
            flow[op.pc]=tuple(start+n*8 for n,_ in edges)
            pending.extend(edges)
        if not exits or any(entry not in decoded for entry in entries):
            raise UnsupportedShader('shader control flow has no reachable exit or phase')
        incoming={0:dict(formats)}
        queue=deque([0])
        def transfer(op, inputs):
            output=dict(inputs)
            for j,dest in enumerate(op.destinations):
                value=(inputs.get(op.sources[j]) if op.opcode=='MOV_F32' else
                       'pred' if op.opcode=='CMP_F32' else
                       'f16x2' if op.opcode in ('PACK_F16','SAMPLE_F16') else 'f32')
                if value is None:output.pop(dest,None)
                else:output[dest]=value
            return output
        while queue:
            i=queue.popleft()
            op=decoded[i]
            output=transfer(op,incoming[i])
            for address in flow[op.pc]:
                target=(address-start)//8
                old=incoming.get(target)
                merged=dict(output) if old is None else {r:value for r,value in old.items() if output.get(r)==value}
                if old!=merged:
                    incoming[target]=merged
                    queue.append(target)
        for i,op in decoded.items():
            for source in op.sources:
                value=incoming[i].get(source)
                expected='pred' if op.opcode=='BR' else 'f32'
                if value is None or (op.opcode!='MOV_F32' and value!=expected):
                    raise UnsupportedShader(f'branch path reads undefined or mistyped {source.bank}{source.index} at {op.pc:#x}')
        outputs=[transfer(decoded[i],incoming[i]) for i in exits]
        for reg in required:
            value=outputs[0].get(reg)
            if value is None or any(state.get(reg)!=value for state in outputs):
                raise UnsupportedShader('shader branch exits disagree on output definitions')
            formats[reg]=value
            initialized.add(reg)
        return [decoded[i] for i in sorted(decoded)]

    if secondary:
        operations.extend(lower_phase(secondary,True))
    branch_words=(fields(struct.unpack_from('<Q',raw,primary['offset']+i*8)[0],PATTERNS['BR'])
                  for i in range(primary['count']))
    complex_flow=any(b and b['r'] and (b['p'] or not b['o'] or b['o']&(1<<19)) for b in branch_words)
    primary_operations=lower_control_flow() if complex_flow else lower_phase(primary,False)
    if primary_operations[0].opcode!='PHAS' or not flow and stage=='vertex' and primary_operations[-1].opcode!='EMIT':
        raise UnsupportedShader('missing shader phase/vertex emit')
    operations.extend(primary_operations)
    if any(reg not in initialized for reg in required):raise UnsupportedShader('shader output is not fully defined')
    if stage=='fragment' and any(formats.get(r)!='f16x2' for r in required):
        raise UnsupportedShader('fragment output has no validated F16 pack')
    query_slots={query['texture'] for query in queries}
    texture_slots=query_slots|dependent_slots
    texture_flags=sum(1<<(4*i) for i in query_slots)+sum(2<<(4*i) for i in set(dependent.values()))
    if texture_slots!=declared_samplers or texture_flags!=(u32(28)|(u32(32)<<32)):
        raise UnsupportedShader('inconsistent shader texture bindings')
    interface={'color':color,'texcoord':0 in texcoords}
    varying_mask=int(color)|sum(1<<(i+1) for i in texcoords)
    msl=generate_msl(stage,operations,inputs,uniforms,color,sorted(texcoords),iterators,queries,literals,texture_slots,flow)
    return {'input_sha256':info['sha256'],'stage':stage,'entry':'vx_gxp_v' if stage=='vertex' else 'vx_gxp_f',
            'operations':[asdict(o) for o in operations],
            'secondary_operation_count':len(operations)-len(primary_operations),'inputs':inputs,'uniforms':uniforms,
            'uniform_words':max((p['resource_index']+p['word_span'] for p in uniforms),default=0),'data_allocation_words':data_words,
            'interface':interface,'varying_mask':varying_mask,
            'samplers':samplers,'implicit_queries':queries,'texture_mask':sum(1<<i for i in texture_slots),
            'msl':msl,'translation_supported':True,'rendering_verified':False,
            'limitations':['bounded F32 MOV/ADD/MUL/MIN/MAX, VTST and F32/F16 packing; bounded conditional and backward flow, F32xy texture coordinates and bounded dependent/nondependent 2D queries']}


def generate_msl(stage,operations,inputs,uniforms,color,texcoords,iterators,queries,literals,texture_slots,flow):
    lines=['#include <metal_stdlib>','using namespace metal;',
           'struct VXLink { float4 position [[position]];'+
           (' float4 color [[user(color0)]];' if color else '')+
           ''.join(f' float2 texcoord{i} [[user(texcoord{i})]];' for i in texcoords)+' };']
    if stage=='vertex':
        lines+=['struct VXInput {']
        for i,item in enumerate(inputs):
            count=item['components'];type='float' if count==1 else f'float{count}'
            lines.append(f'{type} a{i} [[attribute({i})]];')
        lines+=['};','vertex VXLink vx_gxp_v(VXInput input [[stage_in]],constant uint *uniforms [[buffer(1)]]) {']
    else:lines+=['fragment float4 vx_gxp_f(VXLink input [[stage_in]],constant uint *uniforms [[buffer(1)]]'+
                 ''.join(f',texture2d<float> texture{i} [[texture({i})]],sampler sampler{i} [[sampler({i})]]'
                         for i in sorted(texture_slots))+') {']
    lines+=['uint pa[128],sa[128],tmp[128],out[128];']
    for i,item in enumerate(inputs):
        for j in range(item['components']):
            value=f'input.a{i}'+(f'[{j}]' if item['components']>1 else '')
            lines.append(f'pa[{item["resource_index"]+j}]=as_type<uint>({value});')
    for item in uniforms:
        for element in range(item['array_size']):
            offset=element*item['stride']
            for j in range(item['components']):lines.append(f'sa[{item["sa_index"]+offset+j}]=uniforms[{item["resource_index"]+offset+j}];')
    for register_index,bits in literals.items():lines.append(f'sa[{register_index}]=0x{bits:08x}u;')
    for start,count,name in iterators:
        lines.extend(f'pa[{start+j}]=as_type<uint>(input.{name}[{j}]);' for j in range(count))
    for i,query in enumerate(queries):
        slot,coord,dst,words=(query[key] for key in ('texture','coordinate_index','destination','word_count'))
        value=f'texture{slot}.sample(sampler{slot},input.texcoord{coord})'
        if words==2:
            lines.extend([f'half4 sample{i}=half4({value});',
                          f'pa[{dst}]=as_type<uint>(sample{i}.xy);pa[{dst+1}]=as_type<uint>(sample{i}.zw);'])
        else:
            lines.append(f'uint4 sample{i}=as_type<uint4>({value});')
            lines.extend(f'pa[{dst+j}]=sample{i}[{j}];' for j in range(4))
    if any(op.opcode=='CMP_F32' for op in operations):lines.append('bool pred[4];')
    for op in operations:
        if flow and op.pc in flow:
            if op.pc==next(iter(flow)):
                lines.append(f'uint pc={op.pc}u; for (uint step=0; pc && step<65536u; ++step) {{ switch(pc) {{')
            lines.append(f'case {op.pc}u: {{')
        def ref(reg):return ('0u','0x3f800000u','0x40000000u','0x3f000000u')[reg.index] if reg.bank=='const' else f'{reg.bank}[{reg.index}]'
        if op.opcode=='CMP_F32':
            sign,equal,neg=op.modifiers
            compare=(('!=','<','>'),('==','<=','>='))[equal][sign]
            left,right=(f'as_type<float>({ref(src)})' for src in op.sources)
            if neg:left=f'-({left})'
            ordered=f'!isnan({left}) && !isnan({right}) && ' if compare=='!=' else ''
            lines.append(f'{ref(op.destinations[0])}={ordered}({left} {compare} {right});')
        elif op.opcode=='MOV_F32':
            lines.append('{')
            for j,src in enumerate(op.sources):lines.append(f'uint s{j}={ref(src)};')
            for j,dst in enumerate(op.destinations):lines.append(f'{ref(dst)}=s{j};')
            lines.append('}')
        elif op.opcode in ('SAMPLE_F16','SAMPLE_F32'):
            slot=op.modifiers[0]
            coords=','.join(f'as_type<float>({ref(src)})' for src in op.sources)
            value=f'texture{slot}.sample(sampler{slot},float2({coords}))'
            lines.append('{')
            if op.opcode=='SAMPLE_F16':
                lines.append(f'half4 value=half4({value});')
                lines.extend(f'{ref(dst)}=as_type<uint>(value.{component});'
                             for dst,component in zip(op.destinations,('xy','zw')))
            else:
                lines.append(f'uint4 value=as_type<uint4>({value});')
                lines.extend(f'{ref(dst)}=value[{j}];' for j,dst in enumerate(op.destinations))
            lines.append('}')
        elif op.opcode=='PACK_F16':
            values=','.join(f'half(as_type<float>({ref(src)}))' for src in op.sources)
            lines.append(f'{{ half4 value=half4({values});')
            for j,dst in enumerate(op.destinations):lines.append(f'{ref(dst)}=as_type<uint>(value.{"xy" if j==0 else "zw"});')
            lines.append('}')
        elif op.opcode in ('ADD_F32','MUL_F32','MIN_F32','MAX_F32'):
            lines.append('{')
            for j in range(len(op.destinations)):
                values=[]
                for k in range(2):
                    value=ref(op.sources[j*2+k]);modifier=op.modifiers[k]
                    if modifier&2:value=f'({value}&0x7fffffffu)'
                    if modifier&1:value=f'({value}^0x80000000u)'
                    values.append(f'as_type<float>({value})')
                if op.opcode in ('MIN_F32','MAX_F32'):
                    function='fmin' if op.opcode=='MIN_F32' else 'fmax'
                    expression=f'{function}({values[0]},{values[1]})'
                else:
                    operator='+' if op.opcode=='ADD_F32' else '*'
                    expression=f'{values[0]}{operator}{values[1]}'
                lines.append(f'float v{j}={expression};')
            for j,dst in enumerate(op.destinations):lines.append(f'{ref(dst)}=as_type<uint>(v{j});')
            lines.append('}')
        if flow and op.pc in flow:
            edges=flow[op.pc]
            if len(edges)==2:
                pred=ref(op.sources[0])
                condition=f'!{pred}' if op.modifiers[0] else pred
                lines.append(f'pc={condition}?{edges[0]}u:{edges[1]}u; break; }}')
            else:
                lines.append(f'pc={edges[0] if edges else 0}u; break; }}')
    if flow:
        lines.append('default: pc=0u; break; } }')
        if stage=='vertex':lines.append('if(pc) { VXLink invalid={}; return invalid; }')
        else:lines.append('if(pc) discard_fragment();')
    if stage=='vertex':
        lines+=['VXLink result;result.position=as_type<float4>(uint4(out[0],out[1],out[2],out[3]));']
        if color:lines.append('result.color=as_type<float4>(uint4(out[4],out[5],out[6],out[7]));')
        start=8 if color else 4
        for coord in texcoords:
            lines.append(f'result.texcoord{coord}=as_type<float2>(uint2(out[{start}],out[{start+1}]));')
            start+=2
        lines.append('return result;')
    else:lines+=['return float4(float2(as_type<half2>(pa[0])),float2(as_type<half2>(pa[1])));']
    return '\n'.join(lines+['}'])+'\n'


def translate_pair(vertex,fragment):
    v=translate_gxp(vertex);f=translate_gxp(fragment)
    if v['stage']!='vertex' or f['stage']!='fragment':raise UnsupportedShader('shader pair stage mismatch')
    if f['varying_mask']&~v['varying_mask']:
        raise UnsupportedShader('fragment requires missing vertex varying')
    return {'vertex':v,'fragment':f,'rendering_verified':False}
