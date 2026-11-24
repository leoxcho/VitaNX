"""Synthetic encoding regressions plus optional genuine local shader corpus."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from vitaxnative.usse import translate_gxp,translate_pair,UnsupportedShader,decode,PATTERNS

ROOT=Path(__file__).resolve().parents[1]


def vertex():
    data=bytearray(278);data[:4]=b'GXP\0'
    struct.pack_into('<BBHI',data,4,1,5,0x200,len(data))
    for at,value in ((20,0x90000),(24,0x10000000),(36,2),(40,232-40),
                     (44,156-44),(60,4),(64,192-64),(100,4),(144,1),(148,224-148)):
        struct.pack_into('<I',data,at,value)
    struct.pack_into('<H',data,58,1);struct.pack_into('<I',data,172,0x800)
    struct.pack_into('<4Q',data,192,0xfa44070000000000,0x3880152183000000,0x38801521c3080000,0xfb275000a0200000)
    struct.pack_into('<4H',data,224,14,0,0,4)
    struct.pack_into('<iBBBBII',data,232,264-232,0,4,11,0,1,0)
    struct.pack_into('<iBBBBII',data,248,270-248,1,0xe4,0,0,1,0)
    data[264:270]=b'inPos\0';data[270:278]=b'gvColor\0'
    return data


def fragment():
    data=bytearray(212);data[:4]=b'GXP\0'
    struct.pack_into('<BBHI',data,4,1,5,0x200,len(data))
    for at,value in ((20,0x81001),(44,156-44),(60,2),(64,196-64)):
        struct.pack_into('<I',data,at,value)
    struct.pack_into('<H',data,58,1);data[166]=1;data[167]=4
    struct.pack_into('<H',data,168,1);struct.pack_into('<I',data,172,4)
    struct.pack_into('<4I',data,176,0x0ed0a00f,0,0,0x30)
    struct.pack_into('<2Q',data,196,0xfa44070000000000,0x40800d7ea0198002)
    return data


def semantic_c(result):
    """Independent C lowering for native register/numeric differential checks."""
    lines=['#include <stdint.h>','#include <string.h>','#include <math.h>',
           'void shader(const uint32_t *p,const uint32_t *s,uint32_t *result){',
           'uint32_t pa[128],sa[128],out[128]={0},tmp[128]={0};memcpy(pa,p,512);memcpy(sa,s,512);']
    for op in result['operations']:
        def ref(reg):return ('0u','0x3f800000u','0x40000000u','0x3f000000u')[reg['index']] if reg['bank']=='const' else f'{reg["bank"]}[{reg["index"]}]'
        if op['opcode']=='MOV_F32':
            lines+=['{']+[f'uint32_t v{i}={ref(r)};' for i,r in enumerate(op['sources'])]
            lines += [f'{ref(r)}=v{i};' for i,r in enumerate(op['destinations'])]+['}']
        elif op['opcode']=='PACK_F16':
            lines+=['{_Float16 values[4];']
            for i,r in enumerate(op['sources']):
                lines.append(f'uint32_t b{i}={ref(r)};float f{i};memcpy(&f{i},&b{i},4);values[{i}]=(_Float16)f{i};')
            for i,r in enumerate(op['destinations']):lines.append(f'memcpy(&{ref(r)},values+{i*2},4);')
            lines+=['}']
        elif op['opcode'] in ('ADD_F32','MUL_F32','MIN_F32','MAX_F32'):
            lines+=['{']
            for i,r in enumerate(op['sources']):
                value=ref(r);modifier=op['modifiers'][i%2]
                if modifier&2:value=f'({value}&0x7fffffffu)'
                if modifier&1:value=f'({value}^0x80000000u)'
                lines.append(f'uint32_t b{i}={value};float f{i};memcpy(&f{i},&b{i},4);')
            for i,r in enumerate(op['destinations']):
                left,right=f'f{i*2}',f'f{i*2+1}'
                if op['opcode'] in ('MIN_F32','MAX_F32'):
                    function='fminf' if op['opcode']=='MIN_F32' else 'fmaxf'
                    expression=f'{function}({left},{right})'
                else:
                    operator='+' if op['opcode']=='ADD_F32' else '*'
                    expression=f'{left}{operator}{right}'
                lines.append(f'float v{i}={expression};')
            for i,r in enumerate(op['destinations']):lines.append(f'memcpy(&{ref(r)},&v{i},4);')
            lines+=['}']
    lines+=['memcpy(result,'+('out' if result['stage']=='vertex' else 'pa')+',512);','}']
    return '\n'.join(lines)


class UsseTests(unittest.TestCase):
    def translate(self,data):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shader.gxp';path.write_bytes(data);return translate_gxp(path)

    def execute(self,result,p,s,expected):
        if not shutil.which('clang'):self.skipTest('native Clang required')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            words=lambda values:','.join(str(v)+'u' for v in values)
            source=semantic_c(result)+'\nint main(void){uint32_t p[128]={'+words(p)+'},s[128]={'+words(s)+'},r[128];shader(p,s,r);'
            source+=''.join(f'if(r[{i}]!={value}u)return {i+1};' for i,value in enumerate(expected))+'return 0;}\n'
            (root/'test.c').write_text(source)
            subprocess.run(['clang','-O2',str(root/'test.c'),'-o',str(root/'test')],check=True,capture_output=True)
            process=subprocess.run([root/'test'],capture_output=True,timeout=5)
            self.assertEqual(process.returncode,0,process.stderr)

    def test_predicated_backedge(self):
        data=fragment()
        data.extend(bytes(16))
        struct.pack_into('<I',data,8,len(data))
        struct.pack_into('<I',data,60,4)
        pattern=PATTERNS['VTST']
        fields={'a':1,'z':1,'k':2,'f':2,'u':14,'q':1}
        compare=0
        for bit,field in enumerate(reversed(pattern)):
            value=int(field) if field in '01' else (fields.get(field,0)>>pattern[len(pattern)-bit:].count(field))&1
            compare|=value<<bit
        # Compare COLOR.x and COLOR.z to set p0. A true p0 retries the
        # comparison. False falls through to the usual fragment output pack.
        struct.pack_into('<4Q',data,196,0xfa44070000000000,compare,
                         0xf9000040000fffff,0x40800d7ea0198002)
        result=self.translate(data)
        self.assertEqual([op['opcode'] for op in result['operations']],['PHAS','CMP_F32','BR','PACK_F16'])
        self.assertEqual(result['operations'][2]['target'],-1)
        self.assertIn('pred[0]=(as_type<float>(pa[0]) == as_type<float>(pa[2]));',result['msl'])
        self.assertIn('pc=pred[0]?204u:220u',result['msl'])
        struct.pack_into('<Q',data,204,0xf800094000000000)
        with self.assertRaisesRegex(UnsupportedShader,'undefined or mistyped pred0'):
            self.translate(data)

    def test_forward_primary_phase_and_two_texture_resources(self):
        data=fragment()
        data.extend(bytes(152))
        for at,value in ((8,len(data)),(28,0x2101),(36,3),(40,288-40),
                         (60,7),(64,224-64),(92,4),(128,1),(132,352-132),
                         (144,1),(148,356-148)):
            struct.pack_into('<I',data,at,value)
        struct.pack_into('<HHH',data,168,2,0,4)
        struct.pack_into('<4I',data,176,0xf100,0,0xc0,0x30)
        struct.pack_into('<4I',data,192,0xf101,2,0xc0,0x30)
        struct.pack_into('<H',data,58,2)
        pattern=PATTERNS['SMP']
        fields={'f':3,'d':1,'t':1,'k':1,'i':3,'q':2,'u':6}
        sample=0
        for bit,field in enumerate(reversed(pattern)):
            value=int(field) if field in '01' else (fields.get(field,0)>>pattern[len(pattern)-bit:].count(field))&1
            sample|=value<<bit
        struct.pack_into('<7Q',data,224,
                         0xfa44000000000004, 0xf800004000000002, 0xffffffffffffffff,
                         0x40840d7ea0198002, 0xfa44070000000000, sample, 0x40800d7ea0198002)
        for index,slot in enumerate((0,2,3)):
            struct.pack_into('<iBBBBII',data,288+index*16,48-index*13,2,1,0,0,1,slot)
        data[336:345]=b's0\0s2\0s3\0'
        struct.pack_into('<2H',data,352,3*4,0)
        struct.pack_into('<4H',data,356,19,0,12,4)
        result=self.translate(data)
        self.assertEqual(result['texture_mask'],13)
        self.assertEqual(result['varying_mask'],6)
        self.assertEqual([op['opcode'] for op in result['operations']],
                         ['PHAS','BR','PACK_F16','PHAS','SAMPLE_F32','PACK_F16'])
        self.assertIn('texture2.sample(sampler2,input.texcoord1)',result['msl'])
        self.assertIn('texture3.sample(sampler3,float2(as_type<float>(pa[4]),as_type<float>(pa[5])))',
                      result['msl'])
        struct.pack_into('<Q',data,224,0xfa44000000000002)
        with self.assertRaisesRegex(UnsupportedShader,'BR target leaves its phase'):
            self.translate(data)

    def test_v32_min_max_decode_and_lowering(self):
        def instruction(op):
            values={'e':3,'t':1,'k':2,'l':3,'f':2,'z':8,'w':4,'g':op}
            pattern=PATTERNS['V32NMAD']
            shifts={field:pattern.count(field) for field in values}
            word=0
            for field in pattern:
                word <<= 1
                if field in '01':
                    word |= int(field)
                elif field in values:
                    shifts[field]-=1
                    word |= (values[field]>>shifts[field])&1
            return word

        data=vertex()
        data[216:216]=bytes(8)
        for offset,value in ((8,len(data)),(40,240-40),(60,5),(148,232-148)):
            struct.pack_into('<I',data,offset,value)
        p=[0x3f800000,0x40800000,0,0x3f800000]
        s=[0x40000000,0x40400000,0,0x3f800000]
        for mode,function in ((5,'fmin'),(6,'fmax')):
            struct.pack_into('<Q',data,216,instruction(mode))
            result=self.translate(data)
            self.assertIn(function+'(',result['msl'])
            self.execute(result,p,s,p+(p[:1]+s[1:] if mode==5 else s[:1]+p[1:]))

    def test_embedded_literals_initialize_secondary_registers(self):
        data=vertex()
        data.extend(bytes(34))
        struct.pack_into('<I',data,8,len(data))
        struct.pack_into('<I',data,36,1)  # The color source is now inline literals.
        struct.pack_into('<II',data,112,4,280-116)
        struct.pack_into('<4H',data,224,16,0,0,4)
        for i,value in enumerate((0x3f800000,0x80000000,0x3e800000,0x7fc01234)):
            struct.pack_into('<II',data,280+i*8,i,value)
        result=self.translate(data)
        self.assertEqual(result['uniform_words'],0)
        self.assertIn('sa[1]=0x80000000u;',result['msl'])
        self.assertIn('sa[3]=0x7fc01234u;',result['msl'])
        struct.pack_into('<I',data,304,2)
        with self.assertRaisesRegex(UnsupportedShader,'overlapping'):
            self.translate(data)
        struct.pack_into('<I',data,304,4)
        with self.assertRaisesRegex(UnsupportedShader,'outside'):
            self.translate(data)

    def test_actual_mov_fields_and_native_register_semantics(self):
        result=self.translate(vertex())
        p=[0x80000000,0x3eaaaaab,0x7f800000,0x3f800000]
        s=[0x3e4ccccd,0x3f19999a,0x3f666666,0x3f800000]
        self.execute(result,p,s,p+s)
        self.assertIn('out[4]=s0',result['msl'])
        # Alter instruction swizzle, keeping all interface data unchanged.
        data=vertex();word=struct.unpack_from('<Q',data,200)[0]
        positions=[63-i for i,c in enumerate('00111pppstrydecbmmaanoooiwwwwkllffgghhhhjjjjjjqqqqqquuuuuuvvvvvv') if c=='w']
        mask=sum(1<<i for i in positions);word=(word&~mask)|(1<<min(positions))
        struct.pack_into('<Q',data,200,word)
        self.execute(self.translate(data),p,s,[p[1],p[1],p[3],p[3]]+s)

    def test_half_pack_rounding_signed_zero_and_infinity(self):
        result=self.translate(fragment())
        values=[-0.0,1.00048828125,65504.0,float('inf')]
        bits=[struct.unpack('<I',struct.pack('<f',f))[0] for f in values]
        packed=struct.pack('<4e',*values);expected=list(struct.unpack('<2I',packed))
        self.execute(result,bits,[],expected)
        self.assertIn('half4 value=',result['msl'])

    def test_reject_predicates_unknown_words_and_uninitialized_reads(self):
        cases=[]
        for word in (0x3880152183000000|(1<<56),0x0123456789abcdef,0x3880152183000040):
            data=vertex();struct.pack_into('<Q',data,200,word);cases.append(data)
        data=vertex();struct.pack_into('<I',data,68,1);cases.append(data)
        for data in cases:
            with self.assertRaises(ValueError):self.translate(data)

    def test_genuine_local_shaders_use_same_decoder(self):
        root=ROOT/'artifacts/sly-shaders-20261029'
        if not root.exists():self.skipTest('local game shader corpus unavailable')
        for name in ('PostProc_Fill_V.vpo','Debug.fpo'):
            result=translate_gxp(root/name)
            self.assertTrue(result['translation_supported']);self.assertFalse(result['rendering_verified'])
        texture=translate_gxp(root/'PostProc_Copy.fpo')
        self.assertEqual(texture['texture_mask'],1)
        self.assertEqual(texture['implicit_queries'][0]['coordinates'],'TEXCOORD0')
        self.assertIn('texture0.sample(sampler0,input.texcoord)',texture['msl'])
        with self.assertRaises(UnsupportedShader):translate_pair(root/'PostProc_Fill_V.vpo',root/'PostProc_Copy.fpo')
        self.assertEqual(translate_pair(root/'PostProc_Copy_V.vpo',root/'PostProc_Copy.fpo')['fragment']['texture_mask'],1)

    def test_genuine_vertex_arithmetic_and_texcoord_interface(self):
        path=ROOT/'artifacts/sly-shaders-20261029/PostProc_Copy_V.vpo'
        if not path.exists():self.skipTest('local genuine GXP unavailable')
        result=translate_gxp(path)
        bits=lambda values:[struct.unpack('<I',struct.pack('<f',f))[0] for f in values]
        p=bits([1,2,.5,1,.25,.75,0,0]);s=bits([.1,.2,0,0])
        self.execute(result,p,s,bits([.9,1.8,.5,1,.25,.75]))
        self.assertEqual(result['interface'],{'color':False,'texcoord':True})

    def test_generated_msl_compiles_with_real_metal_toolchain(self):
        if not shutil.which('xcrun'):self.skipTest('Apple Metal compiler unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for index,data in enumerate((vertex(),fragment())):
                source=root/f'shader{index}.metal';source.write_text(self.translate(data)['msl'])
                result=subprocess.run(([os.environ['VX_METAL_COMPILER']] if os.environ.get('VX_METAL_COMPILER') else ['xcrun','metal'])+['-std=macos-metal2.0','-c',str(source),'-o',str(root/f'shader{index}.air')],
                                      capture_output=True,text=True,timeout=30)
                if result.returncode and ('missing Metal Toolchain' in result.stderr or 'cannot execute tool' in result.stderr):
                    self.skipTest(result.stderr.strip())
                self.assertEqual(result.returncode,0,result.stderr)

    def test_uniform_arrays_padded_mapping_container_base_and_bounds(self):
        data=vertex();data[253]=0xe3
        struct.pack_into('<I',data,256,2)
        struct.pack_into('<4H',data,224,14,0,8,8)
        # Read second float3 element at SA12, with xxxx swizzle per repeat.
        word=struct.unpack_from('<Q',data,208)[0]
        def field(word,key,value):
            positions=[63-i for i,c in enumerate(PATTERNS['VMOV']) if c==key]
            mask=sum(1<<i for i in positions)
            return (word&~mask)|(value<<min(positions))
        word=field(field(word,'u',6),'w',0)
        struct.pack_into('<Q',data,208,word)
        result=self.translate(data)
        self.assertEqual(result['uniform_words'],7)
        self.assertIn('sa[12]=uniforms[4];',result['msl'])
        self.assertNotIn('sa[11]=',result['msl'])
        self.execute(result,[1,2,3,4],[0]*12+[5,6,7],[1,2,3,4,5,5,7,7])
        # Container span includes padding; reads from padding are rejected.
        struct.pack_into('<H',data,230,6)
        with self.assertRaisesRegex(UnsupportedShader,'outside container'):self.translate(data)
        struct.pack_into('<H',data,230,8)
        struct.pack_into('<Q',data,208,field(word,'w',4))
        with self.assertRaisesRegex(UnsupportedShader,'uninitialized sa15'):self.translate(data)
        struct.pack_into('<I',data,256,65)
        with self.assertRaises(UnsupportedShader):self.translate(data)
