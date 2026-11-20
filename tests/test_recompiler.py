import json
import platform
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from vitaxnative.recompiler import translate_elf

ROOT = Path(__file__).resolve().parents[1]


def elf(words, thumb=False):
    code = struct.pack('<' + ('H' if thumb else 'I') * len(words), *words)
    header = bytearray(0x100)
    header[:16] = b'\x7fELF\x01\x01\x01' + bytes(9)
    struct.pack_into('<HHIIIIIHHHHHH', header, 16, 2, 40, 1, 0x101 if thumb else 0x100, 52, 0, 0x5000000, 52, 32, 1, 0, 0, 0)
    struct.pack_into('<IIIIIIII', header, 52, 1, 0x100, 0x100, 0x100, len(code), len(code), 5, 0x100)
    return header + code


class RecompilerTests(unittest.TestCase):
    def translate(self, blob, **kw):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'a.elf'; p.write_bytes(blob)
            return translate_elf(p, **kw)

    def run_code(self, result, initial='', checks=''):
        if not shutil.which('clang'):
            self.skipTest('Clang required for executable translation test')
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            values = ','.join(str(x) for x in result['memory_image'])
            main = '\nint main(void){uint32_t r[16]={0};uint8_t mem[65536]={'+values+'};r[14]=0xffffffffu;'+initial+'int rc=vx_guest(r,mem,sizeof mem);'+checks+'return rc!=0;}\n'
            (d/'guest.c').write_text(result['c_source'] + '\nint vx_runtime_stop_requested(uint32_t*s){return 0;}\nuint32_t vx_import(uint32_t n,uint32_t*r,uint8_t*m,size_t z){return 0;}\n' + main)
            subprocess.run(['clang','-O2','-Wall','-Wno-unused-function', str(d/'guest.c'),'-lm','-o',str(d/'guest')], check=True, capture_output=True)
            proc = subprocess.run([str(d/'guest')], capture_output=True, timeout=5)
            self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_arm_bitfield_insert_clear_and_mvn(self):
        # Conditional BFI r3,r3,#16,#16 emitted by the SDK compiler.
        result=self.translate(elf([0xe7df3813,0xe12fff1e]))
        self.run_code(result,'r[3]=0xff00;', 'if(r[3]!=0xff00ff00u)return 31;')
        # BFC r0,#8,#8 preserves bits outside the field.
        result=self.translate(elf([0xe7cf041f,0xe12fff1e]))
        self.run_code(result,'r[0]=0xffffffffu;', 'if(r[0]!=0xffff00ffu)return 32;')
        # BFI same register with full-width field and MSB-only insertion.
        result=self.translate(elf([0xe7df0011,0xe12fff1e]))
        self.run_code(result,'r[1]=0x80000001u;', 'if(r[0]!=0x80000001u)return 33;')
        result=self.translate(elf([0xe7df0f91,0xe12fff1e]))
        self.run_code(result,'r[0]=5;r[1]=1;', 'if(r[0]!=0x80000005u)return 34;')
        result=self.translate(elf([0xe3e030ff,0xe12fff1e]))
        self.run_code(result,checks='if(r[3]!=0xffffff00u)return 35;')
        with self.assertRaisesRegex(ValueError,'bitfield extent'):
            self.translate(elf([0xe7c00411,0xe12fff1e]))

    def test_arm_pc_relative_literals_and_bounds(self):
        result=self.translate(elf([0xe59f0000,0xe12fff1e,0x12345678]))
        self.run_code(result,checks='if(r[0]!=0x12345678u)return 18;')
        result=self.translate(elf([0xe51f0004,0xe12fff1e]))
        self.run_code(result,checks='if(r[0]!=0xe12fff1eu)return 19;')
        result=self.translate(elf([0xe59f0fff,0xe12fff1e]))
        self.run_code(result,checks='if(r[0]!=0)return 20;')
        result=self.translate(elf([0xe51f0fff,0xe12fff1e]))
        self.run_code(result,checks='if(rc!=-2)return 21;rc=0;')
        with self.assertRaisesRegex(ValueError,'PC-relative store'):
            self.translate(elf([0xe58f0000,0xe12fff1e]))

    def test_high_address_translation_memory_bounds(self):
        blob=bytearray(elf([0xe5810000,0xe5912000,0xe12fff1e]))
        struct.pack_into('<I',blob,24,0x81000100)
        struct.pack_into('<II',blob,52+8,0x81000100,0x81000100)
        result=self.translate(blob)
        self.assertEqual(result['memory_base'],0x81000000)
        self.assertLess(len(result['memory_image']),4096)
        self.run_code(result,'r[0]=0x12345678;r[1]=0x810001f5;',
                      'if(r[2]!=r[0]||mem[501]!=0x78)return 14;')
        self.run_code(result,'r[1]=0x80ffffff;', 'if(rc!=-2)return 15;rc=0;')
        self.run_code(result,'r[1]=0x8100ffff;', 'if(rc!=-2)return 16;rc=0;')

    def test_arm_arithmetic_native_execution(self):
        # mov r0,r1; add r0,r0,r2; sub r0,r0,#3; bx lr
        result = self.translate(elf([0xe1a00001,0xe0800002,0xe2400003,0xe12fff1e]))
        self.run_code(result, 'r[1]=0xffffffffu;r[2]=7;', 'if(r[0]!=3)return 10;')

    def test_arm_conditional_control_and_flags(self):
        # cmp r0,r1; movcc r2,#1; movcs r3,#1; bx lr
        result = self.translate(elf([0xe1500001,0x33a02001,0x23a03001,0xe12fff1e]))
        self.run_code(result, 'r[0]=0x80000000u;r[1]=0x7fffffffu;', 'if(r[2]!=0||r[3]!=1)return 11;')
        self.run_code(result, 'r[0]=0;r[1]=1;', 'if(r[2]!=1||r[3]!=0)return 12;')

    def test_thumb_loop_native_execution(self):
        # movs r0,#3; subs r0,#1; bne -6; bx lr
        result = self.translate(elf([0x2003,0x3801,0xd1fd,0x4770], True))
        self.run_code(result, checks='if(r[0])return 13;')

    def test_arm_memory_little_endian_unaligned(self):
        result = self.translate(elf([0xe5810000,0xe5912000,0xe12fff1e]))
        self.run_code(result, 'r[0]=0x12345678;r[1]=501;', 'if(r[2]!=r[0]||mem[501]!=0x78||mem[504]!=0x12)return 14;')
        self.run_code(result, 'r[1]=65535;', 'if(rc!=-2)return 15;rc=0;')

    def test_unsupported_and_outside_code_rejected(self):
        for blob in [elf([0xffffffff]), elf([0xeaffffff]), elf([0xf000,0xf800],True)]:
            with self.assertRaises(ValueError): self.translate(blob)

    def test_bad_dynamic_target_traps(self):
        result = self.translate(elf([0xe12fff10]))
        self.run_code(result, 'r[0]=1234;', 'if(rc!=-3)return 16;rc=0;')

    def test_instruction_budget_traps_loop(self):
        result = self.translate(elf([0xeafffffe]))
        self.run_code(result, checks='if(rc!=-4)return 17;rc=0;')

    def test_homebrew_stdout_actual_runtime(self):
        if not shutil.which('clang'): self.skipTest('Clang required')
        manifest = json.loads((ROOT/'fixtures/recompiler/hello.json').read_text())
        result = translate_elf(ROOT/'fixtures/recompiler/hello.elf', {int(k):v for k,v in manifest['imports'].items()})
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            values = ','.join(str(x) for x in result['memory_image'])
            (d/'guest.c').write_text(result['c_source']+'\nint main(void){uint32_t r[16]={0};uint8_t mem[65536]={'+values+'};r[14]=0xffffffffu;int rc=vx_guest(r,mem,sizeof mem);return rc||r[0]!='+str(manifest['expected_r0'])+';}')
            subprocess.run(['clang','-O2',str(d/'guest.c'),str(ROOT/'runtime/vita_runtime.c'),'-lm','-o',str(d/'guest')],check=True,capture_output=True)
            proc = subprocess.run([str(d/'guest')],capture_output=True,timeout=5)
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertEqual(proc.stdout.decode(),manifest['expected_stdout'])

    def test_arm_stack_call_and_movw_movt(self):
        # push {r4,lr}; movw r4,#0x5678; movt r4,#0x1234;
        # mov r0,r4; pop {r4,pc}
        result = self.translate(elf([0xe92d4010,0xe3054678,0xe3414234,0xe1a00004,0xe8bd8010]))
        self.run_code(result, 'r[13]=65536;r[4]=99;',
                      'if(r[0]!=0x12345678u||r[4]!=99||r[13]!=65536)return 18;')
        self.run_code(result, 'r[13]=4;', 'if(rc!=-2)return 19;rc=0;')

    def test_arm_adds_and_subs_flags_boundaries(self):
        for opcode in (0xe0900001,0xe0500001):
            # adds/subs r0,r0,r1; record N,V,C,Z separately.
            result = self.translate(elf([opcode,0x43a02001,0x63a03001,
                                         0x23a04001,0x03a05001,0xe12fff1e]))
            subtract = opcode == 0xe0500001
            for a,b in [(0xffffffff,1),(0x7fffffff,1),(0x80000000,1),(0,0)]:
                value=(a-b if subtract else a+b)&0xffffffff
                carry=int(a>=b) if subtract else int(a+b>0xffffffff)
                overflow=int(bool(((a^b)&(a^value) if subtract else ~(a^b)&(a^value))&0x80000000))
                checks=f'if(r[0]!={value}u||r[2]!={value>>31}||r[3]!={overflow}||r[4]!={carry}||r[5]!={int(value==0)})return 20;'
                with self.subTest(opcode=opcode,a=a,b=b):
                    self.run_code(result,f'r[0]={a}u;r[1]={b}u;',checks)

    def test_thumb_stack_movw_movt_native_execution(self):
        # Clang assembled: push {r4,lr}; movw r4,#0x5678;
        # movt r4,#0x1234; mov r0,r4; pop {r4,pc}.
        result = self.translate(elf([0xb510,0xf245,0x6478,0xf2c1,0x2434,0x4620,0xbd10],True))
        self.run_code(result,'r[13]=65536;r[4]=99;',
                      'if(r[0]!=0x12345678u||r[4]!=99||r[13]!=65536)return 21;')
        self.run_code(result,'r[13]=4;','if(rc!=-2)return 22;rc=0;')

    def test_thumb_bl_forward_and_backward_native_execution(self):
        for words in ([0xb500,0xf000,0xf802,0x3001,0xbd00,0x2007,0x4770],
                      [0xe001,0x2007,0x4770,0xb500,0xf7ff,0xfffb,0x3001,0xbd00]):
            result = self.translate(elf(words,True))
            self.run_code(result,'r[13]=65536;',
                          'if(r[0]!=8||r[13]!=65536)return 23;')

    def test_thumb_blx_register_return_state(self):
        # push {lr}; blx r3; adds r0,#1; pop {pc}; target: movs r0,#7; bx lr.
        result = self.translate(elf([0xb500,0x4798,0x3001,0xbd00,0x2007,0x4770],True),
                                imports={0x2000:0})
        # Unknown dynamic addresses trap; explicit imports return through odd LR.
        self.run_code(result,'r[13]=65536;r[3]=0x2000;',
                      'if(r[0]!=1||r[13]!=65536)return 24;')

    def test_thumb_wide_truncation_it_and_overlaps_rejected(self):
        for words in ([0xf240], [0xf2c0], [0xbf1c,0x2001],
                      [0xf44d,0x5300,0x4770], [0xd000,0xf242,0x2001,0x4770]):
            with self.subTest(words=words), self.assertRaises(ValueError):
                self.translate(elf(words,True))

    def test_c_compiled_thumb_native_runtime(self):
        if not shutil.which('clang') or not shutil.which('ld.lld'):
            self.skipTest('Clang and LLD required')
        source = r'''
typedef unsigned int u32;
static const char text[]="Thumb C native ABI test\n";
__attribute__((noinline)) static int helper(void){
 return ((int (*)(int,const void*,u32))0x2348)(1,text,sizeof(text)-1);
}
int _start(void){return helper()+1;}
'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp/'main.c').write_text(source)
            subprocess.run(['clang','-target','armv7-none-eabi','-mthumb','-march=armv7-a',
                            '-O1','-ffreestanding','-fno-builtin','-fno-unwind-tables',
                            '-fno-asynchronous-unwind-tables','-c',str(tmp/'main.c'),
                            '-o',str(tmp/'main.o')],check=True,capture_output=True)
            subprocess.run(['ld.lld','-m','armelf','-T',str(ROOT/'fixtures/homebrew/link.ld'),
                            str(tmp/'main.o'),'-o',str(tmp/'main.elf')],check=True,capture_output=True)
            result = translate_elf(tmp/'main.elf',imports={0x2348:0x34efd876})
            self.assertEqual(result['entry']&1,1)
            values = ','.join(str(x) for x in result['memory_image'])
            (tmp/'native.c').write_text(result['c_source']+'\nint main(void){uint32_t r[16]={0};static uint8_t mem[2097152]={'+values+'};r[13]=sizeof(mem);r[14]=0xffffffffu;return vx_guest(r,mem,sizeof(mem))||r[0]!=25;}')
            subprocess.run(['clang','-O2',str(tmp/'native.c'),str(ROOT/'runtime/vita_runtime.c'),'-lm',
                            '-o',str(tmp/'native')],check=True,capture_output=True)
            run = subprocess.run([str(tmp/'native')],check=True,capture_output=True,timeout=5)
            self.assertEqual(run.stdout,b'Thumb C native ABI test\n')

    def test_arm_register_shift_values_and_flags(self):
        cases=[]
        for kind in range(4):
            for x in (0,1,0x80000001,0xffffffff):
                for count in (0,1,31,32,33,255,256):
                    for carry in (0,1):
                        amount=count&255;value=x;c=carry
                        if amount:
                            if kind==0:
                                value=(x<<amount)&0xffffffff if amount<32 else 0
                                c=(x>>(32-amount))&1 if amount<=32 else 0
                            elif kind==1:
                                value=x>>amount if amount<32 else 0
                                c=(x>>(amount-1))&1 if amount<=32 else 0
                            elif kind==2:
                                value=((x if x<0x80000000 else x-0x100000000)>>min(amount,32))&0xffffffff
                                c=(x>>(amount-1))&1 if amount<32 else x>>31
                            else:
                                rotation=amount&31
                                value=((x>>rotation)|(x<<(32-rotation)))&0xffffffff if rotation else x
                                c=value>>31
                        cases.append((kind,x,count,carry,value,c))
        for kind in range(4):
            # CMP seeds carry, MOVS shifted register, conditional MOVs capture flags.
            result=self.translate(elf([0xe1580009,0xe1b02110|(kind<<5),
                                       0x23a03001,0x43a04001,0x03a05001,0x63a06001,0xe12fff1e]))
            rows=','.join('{'+','.join(str(v)+'u' for v in case[1:])+'}' for case in cases if case[0]==kind)
            checks=('uint32_t cases[][5]={'+rows+'};for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++){'
                    'for(int j=0;j<16;j++)r[j]=0;r[0]=cases[i][0];r[1]=cases[i][1];'
                    'r[8]=cases[i][2];r[9]=1;r[14]=0xffffffffu;rc=vx_guest(r,mem,sizeof mem);'
                    'if(rc||r[2]!=cases[i][3]||r[3]!=cases[i][4]||r[4]!=(r[2]>>31)||r[5]!=(r[2]==0)||r[6])return 41;}')
            self.run_code(result,checks=checks)

    def test_arm_immediate_shifts_rrx_and_logical_flag_preservation(self):
        # CMP sets C=1,V=1; MOVS RRX preserves V; EORS records logical result.
        result=self.translate(elf([0xe1580009,0xe1b02060,0x63a03001,0x23a04001,0xe12fff1e]))
        self.run_code(result,'r[8]=0x80000000u;r[9]=1;r[0]=3;',
                      'if(r[2]!=0x80000001u||r[3]!=1||r[4]!=1)return 42;')
        for kind,expected,carry in ((0,0x80000001,1),(1,0,1),(2,0xffffffff,1)):
            result=self.translate(elf([0xe1580009,0xe1b02000|(kind<<5),0x23a03001,0xe12fff1e]))
            self.run_code(result,'r[8]=1;r[9]=1;r[0]=0x80000001u;',
                          f'if(r[2]!={expected}u||r[3]!={carry})return 43;')
        for opcode,expected in ((0xe0002001,0x123450fe),(0xe0202001,0xedcbaf01),
                                (0xe1802001,0xffffffff),(0xe1c02001,0xedcbaf01)):
            result=self.translate(elf([opcode,0xe12fff1e]))
            self.run_code(result,'r[0]=0xffffffffu;r[1]=0x123450feu;',
                          f'if(r[2]!={expected}u)return 44;')

    def test_arm_multiply_accumulate_alias_and_invalid_encodings(self):
        result=self.translate(elf([0xe0000190,0xe0223291,0xe12fff1e]))
        self.run_code(result,'r[0]=0xffffffffu;r[1]=3;r[2]=5;r[3]=7;',
                      'if(r[0]!=0xfffffffdu||r[2]!=22)return 45;')
        for opcode in (0xe1d0f0b0,0xe0000090|0x1000,0xe1000000):
            with self.assertRaises(ValueError):self.translate(elf([opcode,0xe12fff1e]))

    def test_thumb_stack_literals_byte_halfword_and_arithmetic(self):
        # SP-relative stack slot; byte and halfword roundtrips; restore stack.
        words=[0xb081,0x9000,0x9900,0xb001,0x7011,0x7813,0x8051,0x8854,0x1840,0x1e45,0x4770]
        result=self.translate(elf(words,True))
        self.run_code(result,'r[13]=65000;r[0]=0x12345678;r[2]=600;',
                      'if(r[1]!=0x12345678||r[3]!=0x78||r[4]!=0x5678||r[5]!=0x2468acef||r[13]!=65000)return 46;')
        result=self.translate(elf([0x4800,0x4770,0x5678,0x1234],True))
        self.run_code(result,checks='if(r[0]!=0x12345678u)return 47;')

    def test_thumb_blx_immediate_interworking_and_alignment(self):
        # BLX at pc=0x102 aligns pc+4 to 0x104 and calls ARM code at 0x10c.
        blob=bytearray(elf([0xb500,0xf000,0xe804,0x3001,0xbd00,0xbf00,0x0007,0xe3a0,0xff1e,0xe12f],True))
        result=self.translate(blob)
        self.run_code(result,'r[13]=65000;', 'if(r[0]!=8||r[13]!=65000)return 48;')

    def test_carry_arithmetic_native_flags_and_wraparound(self):
        values=(0,1,0x7fffffff,0x80000000,0xffffffff)
        for subtract in (False,True):
            rows=[]
            for a in values:
                for b in values:
                    for carry in (0,1):
                        raw=a-b-(1-carry) if subtract else a+b+carry
                        value=raw&0xffffffff
                        c=int(raw>=0) if subtract else int(raw>0xffffffff)
                        v=int(bool(((a^b)&(a^value) if subtract else ~(a^b)&(a^value))&0x80000000))
                        rows.append((a,b,carry,value,c,v))
            data=','.join('{'+','.join(str(v)+'u' for v in row)+'}' for row in rows)
            for thumb in (False,True):
                if thumb:
                    words=[0x429a,0x4188 if subtract else 0x4148,0xd300,0x4644,0xd500,0x4645,0xd100,0x4646,0xd700,0x4647,0x4770]
                    # Conditional skips capture C,N,Z,V; branch offsets are zero.
                else:
                    words=[0xe1520003,0xe0d00001 if subtract else 0xe0b00001,
                           0x23a04001,0x43a05001,0x03a06001,0x63a07001,0xe12fff1e]
                result=self.translate(elf(words,thumb))
                checks=('uint32_t cases[][6]={'+data+'};for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++){'
                        'for(int j=0;j<16;j++)r[j]=0;r[0]=cases[i][0];r[1]=cases[i][1];r[2]=cases[i][2];r[3]=1;r[8]=1;r[14]=0xffffffffu;'
                        'rc=vx_guest(r,mem,sizeof mem);if(rc||r[0]!=cases[i][3]||r[4]!=cases[i][4]||r[5]!=(r[0]>>31)||r[6]!=(r[0]==0)||r[7]!=cases[i][5])return 49;}')
                self.run_code(result,checks=checks)

    def test_wide_branches_and_arm_thumb_interworking(self):
        result=self.translate(elf([0xf000,0xb802,0x2001,0x4770,0x2007,0x4770],True))
        self.run_code(result,checks='if(r[0]!=7)return 50;')
        result=self.translate(elf([0x2800,0xf040,0x8002,0x2001,0x4770,0x2007,0x4770],True))
        self.run_code(result,'r[0]=0;', 'if(r[0]!=1)return 51;')
        self.run_code(result,'r[0]=3;', 'if(r[0]!=7)return 52;')
        result=self.translate(elf([0xe92d4000,0xfa000001,0xe8bd8000,0xe1a00000,0x47702007]))
        self.run_code(result,'r[13]=65000;', 'if(r[0]!=7||r[13]!=65000)return 53;')

    def test_arm_indexed_memory_writeback_and_fault_order(self):
        # STR r0,[r1],#4; LDR r2,[r1,#-4]!; STRB/LDRB with writeback.
        result=self.translate(elf([0xe4810004,0xe5312004,0xe5e10001,0xe4513001,0xe12fff1e]))
        self.run_code(result,'r[0]=0x12345678;r[1]=600;',
                      'if(r[2]!=r[0]||r[3]!=0x78||r[1]!=600)return 54;')
        result=self.translate(elf([0xe4810004,0xe12fff1e]))
        self.run_code(result,'r[1]=65535;', 'if(rc!=-2||r[1]!=65535)return 55;rc=0;')
        for word in (0xe4911004,0xe49f0004,0xe4b10004):
            with self.assertRaises(ValueError):self.translate(elf([word,0xe12fff1e]))

    def test_thumb2_byte_halfword_and_stack_memory(self):
        words=[0xf881,0x0001,0xf891,0x2001,0xf8a1,0x0002,0xf8b1,0x3002,
               0xf8cd,0x0000,0xf8dd,0x4000,0x4770]
        result=self.translate(elf(words,True))
        self.run_code(result,'r[0]=0x12345678;r[1]=600;r[13]=65000;',
                      'if(r[2]!=0x78||r[3]!=0x5678||r[4]!=r[0])return 56;')
        self.run_code(result,'r[1]=65535;r[13]=65000;', 'if(rc!=-2)return 57;rc=0;')
