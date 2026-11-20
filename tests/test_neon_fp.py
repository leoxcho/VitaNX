"""Independent rational oracle and native vector-state tests for ARM standard FP."""
from fractions import Fraction
from decimal import Decimal, localcontext
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import unittest
import test_recompiler as support

ROOT=Path(__file__).resolve().parents[1]

def finite(bits):
    exp=(bits>>23)&255
    if not exp:return Fraction(0)
    value=Fraction((bits&0x7fffff)|0x800000)*Fraction(2)**(exp-150)
    return -value if bits>>31 else value

def rounded(value):
    sign=0x80000000 if value<0 else 0;value=abs(value)
    if not value:return 0,0
    if value<Fraction(2)**-126:return sign,8
    exp=value.numerator.bit_length()-value.denominator.bit_length()
    if value<Fraction(2)**exp:exp-=1
    scaled=value*Fraction(2)**(23-exp)
    mant,rem=divmod(scaled.numerator,scaled.denominator)
    if 2*rem>scaled.denominator or (2*rem==scaled.denominator and mant&1):mant+=1
    if mant==1<<24:mant>>=1;exp+=1
    if exp>127:return sign|0x7f800000,20
    return sign|((exp+127)<<23)|(mant&0x7fffff),16 if rem else 0

def estimate(bits):
    exp=(bits>>23)&255
    with localcontext() as ctx:
        ctx.prec=60
        scaled=Decimal((bits&0x7fffff)|0x800000)/Decimal(2)**(25 if exp&1 else 24)
        grid=512 if exp&1 else 256
        midpoint=(int(scaled*grid)+Decimal('0.5'))/grid
        quantized=int((Decimal(1)/midpoint.sqrt()*256).to_integral_value(rounding='ROUND_HALF_EVEN'))
    return ((380-exp)//2)<<23|((quantized&255)<<15)

def reciprocal(bits):
    exp=(bits>>23)&255
    scaled=Fraction((bits&0x7fffff)|0x800000,1<<24)
    midpoint=Fraction(int(scaled*512)*2+1,1024)
    exact=256/midpoint
    integer,remainder=divmod(exact.numerator,exact.denominator)
    if remainder*2>=exact.denominator:integer+=1
    return (bits&0x80000000)|((253-exp)<<23)|((integer&255)<<15)

class NeonFpTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def test_scalar_duplicate_lane_aliases(self):
        for imm,bits,index in [(1,8,0),(15,8,7),(6,16,1),(12,32,1),(4,32,0)]:
            word=0xf3b00c40|(imm<<16)
            value=(0xfedcba9876543210>>(bits*index))&((1<<bits)-1)
            expected=value*(0xffffffff//((1<<bits)-1))
            for thumb in (False,True):
                raw=0xef000000|(word&0xffffff)|((word&0x1000000)<<4)
                code=([0xec92,0x0b04,raw>>16,raw&65535,0xec83,0x0b04,0x4770] if thumb
                      else [0xec920b04,word,0xec830b04,0xe12fff1e])
                r=self.translate(support.elf(code,thumb))
                self.run_code(r,'r[2]=600;r[3]=700;vx_write32(mem+600,0x76543210);vx_write32(mem+604,0xfedcba98);',
                              ''.join(f'if(vx_read32(mem+{700+i*4})!={expected}u)return 30;' for i in range(4)))
        for word in (0xf3b00c40,0xf3b80c40,0xf3b41c40):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))

    def test_vector_multiply_and_pairwise_add(self):
        values=[0x3f800000,0x40000000,0x40400000,0x40800000,
                0x40a00000,0x40c00000,0x40e00000,0x41000000]
        initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},{v}u);' for i,v in enumerate(values))
        for thumb in (False,True):
            for word,expected in [(0xf3000d52,[0x40a00000,0x41400000,0x41a80000,0x42000000]),
                                  (0xf3000d01,[0x40400000,0x40e00000,values[2],values[3]])]:
                raw=0xef000000|(word&0xffffff)|((word&0x1000000)<<4)
                code=([0xec92,0x0b08,raw>>16,raw&65535,0xec83,0x0b04,0x4770] if thumb else
                      [0xec920b08,word,0xec830b04,0xe12fff1e])
                self.run_code(self.translate(support.elf(code,thumb)),initial,
                              ''.join(f'if(vx_read32(mem+{700+i*4})!={v}u)return 40;' for i,v in enumerate(expected)))
        for word in (0xf3001d54,0xf3000d44):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))

    def test_vector_accumulate_is_nonfused(self):
        for subtract in (False,True):
            word=0xf2020d54|(int(subtract)<<21)
            code=[0xec920b0c,word,0xec830b04,0xeef14a10,0xe12fff1e]
            values=[0x3f800000 if subtract else 0xbf800000]*4+[0x3f800001]*4+[0x3f7ffffe]*4
            initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},{v}u);' for i,v in enumerate(values))
            checks='if(r[4]!=16)return 70;'+''.join(f'if(vx_read32(mem+{700+i*4}))return 71;' for i in range(4))
            self.run_code(self.translate(support.elf(code)),initial,checks)

    def test_scalar_fp_multiply_and_accumulate_aliases(self):
        bits=lambda x:struct.unpack('<I',struct.pack('<f',x))[0]
        vals=[bits(i) for i in range(1,9)]
        initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},{v}u);' for i,v in enumerate(vals))
        for opc,expected in [(0x100,[11,14,17,20]),(0x500,[-9,-10,-11,-12]),(0x900,[10,12,14,16])]:
            word=0xf3a20060|opc  # Q0,Q1,D0[1]; scalar aliases destination.
            for thumb in (False,True):
                raw=0xef000000|(word&0xffffff)|((word&0x1000000)<<4)
                code=([0xec92,0x0b08,raw>>16,raw&65535,0xec83,0x0b04,0x4770] if thumb else
                      [0xec920b08,word,0xec830b04,0xe12fff1e])
                self.run_code(self.translate(support.elf(code,thumb)),initial,
                              ''.join(f'if(vx_read32(mem+{700+i*4})!={bits(v)}u)return 100;' for i,v in enumerate(expected)))
        self.run_code(self.translate(support.elf([0xec920b08,0xf2a10162,0xec830b04,0xe12fff1e])),initial,
                      ''.join(f'if(vx_read32(mem+{700+i*4})!={bits(v)}u)return 101;' for i,v in enumerate([19,26,3,4])))

    def test_minmax_nan_zero_and_signed_order(self):
        cases=[(0,0x80000000,0x80000000,0,0),
               (1,0x80000001,0x80000000,0,128),
               (0xbf800000,0xc0000000,0xc0000000,0xbf800000,0),
               (0x7f800000,0xff800000,0xff800000,0x7f800000,0),
               (0x7fc12345,0x3f800000,0x7fc00000,0x7fc00000,0),
               (0x7f812345,1,0x7fc00000,0x7fc00000,129)]
        data=','.join('{'+','.join(str(v)+'u' for v in row)+'}' for row in cases)
        self.compile_run('''#include <stdint.h>
#include "vita_neon_fp.h"
int main(void){uint32_t rows[][5]={'''+data+'''};
 for(unsigned i=0;i<sizeof rows/sizeof rows[0];i++)for(unsigned min=0;min<2;min++){
 uint32_t f=0;if(vx_neon_minmax(rows[i][0],rows[i][1],min,&f)!=rows[i][min?2:3]||f!=rows[i][4])return 1;}
 return 0;}
''')
        initial='r[2]=600;r[3]=700;vx_write32(mem+600,0xc0000000);vx_write32(mem+604,0x40400000);vx_write32(mem+608,0x40000000);vx_write32(mem+612,0xc0400000);'
        for word,expected in [(0xf2200f01,[0xc0000000,0xc0400000]),(0xf2000f01,[0x40000000,0x40400000])]:
            self.run_code(self.translate(support.elf([0xec920b04,word,0xec830b02,0xe12fff1e])),initial,
                          ''.join(f'if(vx_read32(mem+{700+i*4})!={v}u)return 110;' for i,v in enumerate(expected)))

    def test_raw_negate_and_bit_select_preserve_fp_payloads(self):
        values=[0,0x7f800001,0xffc12345,1]
        code=[0xec920b04,0xf3b907c0,0xec830b04,0xeef14a10,0xe12fff1e]
        initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},{v}u);' for i,v in enumerate(values))
        self.run_code(self.translate(support.elf(code)),initial,
                      'if(r[4])return 90;'+''.join(f'if(vx_read32(mem+{700+i*4})!={v^0x80000000}u)return 91;' for i,v in enumerate(values)))
        d,n,m=0x0123456789abcdef,0xfedcba9876543210,0xaaaabbbbccccdddd
        for word,expected in [(0xf3110112,(n&d)|(m&~d)),(0xf3210112,(d&~m)|(n&m)),(0xf3310112,(d&m)|(n&~m))]:
            words=[0xec920b06,word,0xec830b02,0xeef14a10,0xe12fff1e]
            initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*8+j*4},{(v>>(j*32))&0xffffffff}u);' for i,v in enumerate((d,n,m)) for j in range(2))
            self.run_code(self.translate(support.elf(words)),initial,'if(r[4])return 92;'+''.join(f'if(vx_read32(mem+{700+i*4})!={(expected>>(i*32))&0xffffffff}u)return 93;' for i in range(2)))

    def test_reciprocal_estimate_and_step(self):
        rows=[((127<<23)|(bucket<<15)|23,reciprocal((127<<23)|(bucket<<15)|23),0) for bucket in range(256)]
        rows += [(0,0x7f800000,2),(0x80000000,0xff800000,2),
                 (1,0x7f800000,130),(0x7f800000,0,0),(0xff800000,0x80000000,0),
                 (0x7e800000,0,8),(0xfeffffff,0x80000000,8),
                 (0x7fc12345,0x7fc00000,0),(0x7f812345,0x7fc00000,1)]
        data=','.join('{'+','.join(str(x)+'u' for x in row)+'}' for row in rows)
        self.compile_run('''#include <stdint.h>
#include <stdio.h>
#include "vita_neon_fp.h"
int main(void){uint32_t rows[][3]={'''+data+'''};
 for(unsigned i=0;i<sizeof rows/sizeof rows[0];i++){uint32_t f=0,v=vx_neon_recip(rows[i][0],&f);
  if(v!=rows[i][1]||f!=rows[i][2]){fprintf(stderr,"recip %u %08x/%x expected %08x/%x\\n",i,v,f,rows[i][1],rows[i][2]);return 1;}}
 uint32_t f=0;if(vx_neon_recip_step(0,0x7f800000,&f)!=0x40000000||f)return 2;
 if(vx_neon_recip_step(0x7f800001,0,&f)!=0x7fc00000||f!=1)return 3;
 return 0;}
''')
        values=[0x3f800000,0x40000000,0xc0800000,0x41100000];expected=[]
        for a in values:
            e=reciprocal(a);prod,_=rounded(finite(a)*finite(e))
            step,_=rounded(2-finite(prod));out,_=rounded(finite(e)*finite(step));expected.append(out)
        code=[0xec920b04,0xf3bb2540,0xf2024f50,0xf3022d54,0xec832b04,0xe12fff1e]
        initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},{v}u);' for i,v in enumerate(values))
        self.run_code(self.translate(support.elf(code)),initial,
                      ''.join(f'if(vx_read32(mem+{700+i*4})!={v}u)return 80;' for i,v in enumerate(expected)))

    def test_byte_extract_and_insert_shifts(self):
        a=0xfedcba98765432100123456789abcdef;b=0x8070605040302010ffeeddccbbaa9988
        for word,bits,shift,left in [(0xf3a00592,64,32,True),(0xf3a00492,64,32,False),
                                     (0xf38f0552,8,7,True),(0xf3900412,16,16,False),
                                     (0xf3a00412,32,32,False)]:
            quad=bool(word&64);width=128 if quad else 64;count=width//32
            mask=(1<<bits)-1;expected=0
            for pos in range(0,width,bits):
                dst=(a>>pos)&mask;src=(b>>pos)&mask
                keep=(1<<shift)-1 if left else mask^((1<<(bits-shift))-1)
                out=(dst&keep)|(((src<<shift) if left else (src>>shift))&(mask^keep))
                expected|=out<<pos
            result=self.translate(support.elf([0xec920b08,word,0xec830b04,0xe12fff1e]))
            # D2/Q1 source begins at word 4; unused D destination neighbours
            # must retain their original payload.
            initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},{((a if i<4 else b)>>(32*(i%4)))&0xffffffff}u);' for i in range(8))
            checks=''.join(f'if(vx_read32(mem+{700+i*4})!={((expected if i<count else a)>>(32*i))&0xffffffff}u)return 60;' for i in range(4))
            self.run_code(result,initial,checks)
        for quad in (False,True):
            count=4 if quad else 2
            for offset in (0,1,count*4-1):
                word=0xf2b00402|(offset<<8)|(64 if quad else 0)
                # Use offset field without the initial #4 value.
                word=(word&~0xf00)|(offset<<8)
                n=a&((1<<(count*32))-1);m=b&((1<<(count*32))-1)
                expected=((n|(m<<(count*32)))>>(offset*8))&((1<<(count*32))-1)
                source=[0xec920b08,word,0xec830b04,0xe12fff1e]
                # m=D2 for D form, Q1=D2-D3 for Q form.
                initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},{((a if i<4 else b)>>(32*(i%4)))&0xffffffff}u);' for i in range(8))
                self.run_code(self.translate(support.elf(source)),initial,
                              ''.join(f'if(vx_read32(mem+{700+i*4})!={(expected>>(32*i))&0xffffffff}u)return 61;' for i in range(count)))

    def test_reciprocal_sqrt_buckets_specials_and_refinement(self):
        rows=[]
        for exp in (126,127):
            for bucket in range(128):
                bits=(exp<<23)|(bucket<<16)|0x1234
                rows.append((bits,estimate(bits),0))
        rows += [(0,0x7f800000,2),(0x80000000,0xff800000,2),
                 (1,0x7f800000,130),(0x80000001,0xff800000,130),
                 (0x7f800000,0,0),(0xff800000,0x7fc00000,1),
                 (0xbf800000,0x7fc00000,1),(0x7fc12345,0x7fc00000,0),
                 (0x7f812345,0x7fc00000,1)]
        data=','.join('{'+','.join(str(x)+'u' for x in row)+'}' for row in rows)
        rng=random.Random(117);steps=[]
        for _ in range(128):
            a=(rng.randrange(100,150)<<23)|rng.getrandbits(23)
            b=(rng.randrange(100,150)<<23)|rng.getrandbits(23)
            prod,pflags=rounded(finite(a)*finite(b));result,flags=rounded((3-finite(prod))/2)
            steps.append((a,b,result,flags|pflags))
        steps += [(0,0x7f800000,0x3fc00000,0),(0xff800000,0x80000000,0x3fc00000,0),
                  (1,0x7f800000,0x3fc00000,128),(0x7f812345,0,0x7fc00000,1)]
        steps_data=','.join('{'+','.join(str(x)+'u' for x in row)+'}' for row in steps)
        self.compile_run('''#include <stdint.h>
#include <stdio.h>
#include "vita_neon_fp.h"
int main(void){uint32_t rows[][3]={'''+data+'''};
 for(unsigned i=0;i<sizeof rows/sizeof rows[0];i++){uint32_t f=0,v=vx_neon_rsqrte(rows[i][0],&f);
  if(v!=rows[i][1]||f!=rows[i][2]){fprintf(stderr,"estimate %u %08x/%x expected %08x/%x\\n",i,v,f,rows[i][1],rows[i][2]);return 1;}}
 uint32_t steps[][4]={'''+steps_data+'''};
 for(unsigned i=0;i<sizeof steps/sizeof steps[0];i++){uint32_t f=0,v=vx_neon_rsqrt_step(steps[i][0],steps[i][1],&f);
  if(v!=steps[i][2]||f!=steps[i][3]){fprintf(stderr,"step %u %08x/%x expected %08x/%x\\n",i,v,f,steps[i][2],steps[i][3]);return 2;}}
 return 0;}
''')
        values=[0x3f800000,0x40000000,0x40800000,0x41100000]
        expected=[]
        for a in values:
            e=estimate(a);prod,_=rounded(finite(e)**2);p,_=rounded(finite(prod)*finite(a))
            step,_=rounded((3-finite(p))/2);out,_=rounded(finite(e)*finite(step));expected.append(out)
        code=[0xec920b04,0xf3bb25c0,0xf3024d52,0xf2244f50,0xf3022d54,0xec832b04,0xe12fff1e]
        initial='r[2]=600;r[3]=700;'+''.join(f'vx_write32(mem+{600+i*4},{v}u);' for i,v in enumerate(values))
        self.run_code(self.translate(support.elf(code)),initial,
                      ''.join(f'if(vx_read32(mem+{700+i*4})!={v}u)return 50;' for i,v in enumerate(expected)))

    def compile_run(self,source):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(source)
            r=subprocess.run(['clang','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
                              '-I',str(ROOT/'runtime'),str(p/'test.c'),'-o',str(p/'test')],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            r=subprocess.run([str(p/'test')],capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode,0,r.stderr)

    def test_standard_arithmetic_rational_oracle_and_specials(self):
        rows=[];rng=random.Random(0x811064e8)
        for op in range(3):
            for _ in range(192):
                a=rng.getrandbits(32);b=rng.getrandbits(32)
                if ((a>>23)&255)==255 or ((b>>23)&255)==255:continue
                x,y=finite(a),finite(b)
                result,flags=rounded((x+y,x-y,x*y)[op])
                # Exact-zero signs are checked separately below.
                if not x or not y or not ((x+y,x-y,x*y)[op]):continue
                if (a&0x7fffffff)<0x800000 or (b&0x7fffffff)<0x800000:flags|=128
                rows.append((a,b,op,result,flags))
        rows += [(0,0x80000000,1,0,0),(0x80000000,0,1,0x80000000,0),
                 (0x80000000,0x80000000,1,0,0),(0x80000000,0x80000000,0,0x80000000,0),
                 (0x3f800000,0x33800000,1,0x3f7fffff,0),
                 (0x3f800000,0x33000000,1,0x3f800000,16),
                 (0x3f800001,0x33800000,0,0x3f800002,16),
                 (0x00800001,0x00800000,1,0,8),
                 (0x80800001,0x80800000,1,0x80000000,8),
                 (1,0x80000001,1,0,128),(0x80000001,0,1,0x80000000,128),
                 (0x7f800000,0x7f800000,1,0x7fc00000,1),
                 (0xff800000,0x7f800000,1,0xff800000,0),
                 (0x7fc12345,0,1,0x7fc00000,0),
                 (0x7f812345,0x7fc12345,1,0x7fc00000,1),
                 (0x7fc12345,1,1,0x7fc00000,128),
                 (0x7f7fffff,0xff7fffff,1,0x7f800000,20),
                 (0x00800000,0x3f000000,2,0,8),
                 (0x80000000,0x7f800000,2,0x7fc00000,1)]
        data=','.join('{'+','.join(str(v)+'u' for v in row)+'}' for row in rows)
        self.compile_run('''#include <stdint.h>
#include <stdio.h>
#include <fenv.h>
#include "vita_neon_fp.h"
int main(void){uint32_t rows[][5]={'''+data+'''};
 fesetround(FE_UPWARD);feraiseexcept(FE_DIVBYZERO);
 for(unsigned i=0;i<sizeof rows/sizeof rows[0];i++){
  uint32_t fpscr=0xf7c09f02u,*r=rows[i];
  uint32_t value=vx_neon_binary(r[0],r[1],r[2],&fpscr);
  if(value!=r[3]||fpscr!=(0xf7c09f02u|r[4])){
   fprintf(stderr,"case %u: %08x %08x op%u => %08x/%08x expected %08x/%08x\\n",i,r[0],r[1],r[2],value,fpscr,r[3],0xf7c09f02u|r[4]);return 1;}
 }
 return fegetround()!=FE_UPWARD||fetestexcept(FE_ALL_EXCEPT)!=FE_DIVBYZERO;
}
''')

    def test_exact_vsub_vector_alias_state_and_decode_rejections(self):
        for thumb,word in [(True,0xef222d40),(False,0xf2222d40),
                           (False,0xf2622de0),(False,0xf2222d00)]:
            code=[word>>16,word&65535,0x4770] if thumb else [word,0xe12fff1e]
            result=self.translate(support.elf(code,thumb))
            high=bool(word&0x00400000);start=36 if high else 4
            # q1 aliases first source; high variant q9=q9-q8. D form writes
            # only D2. Distinct lanes catch sequential clobbering and indexing.
            initial=''.join(f's.f[{start+i}]={v}u;s.f[{start-4+i}]={b}u;' for i,(v,b) in enumerate(zip(
                [0x3f800000,0xc0000000,0x7f800000,0x00800001],
                [0x3f000000,0x3f800000,0x7f800000,0x00800000])))
            count=2 if not word&64 else 4
            expected=[0x3f000000,0xc0400000,0x7fc00000,0]
            checks=''.join(f'if(s.f[{start+i}]!={v}u)return {10+i};' for i,v in enumerate(expected[:count]))
            if count==2:checks+=f'if(s.f[{start+2}]!=0x7f800000u||s.f[{start+3}]!=0x00800001u)return 19;'
            source=result['c_source']+'''
uint32_t vx_import(uint32_t n,uint32_t*r,uint8_t*m,size_t z){(void)n;(void)r;(void)m;(void)z;return 0;}
int vx_runtime_stop_requested(uint32_t*s){(void)s;return 0;}
int main(void){uint8_t mem[65536]={0};vx_guest_state s={0};
 s.pc='''+str(result['entry'])+''';s.r[14]=0xffffffffu;s.r[13]=600;
 s.n=1;s.z=0;s.c=1;s.v=1;s.fpscr=0xf7c09f02u;
 '''+initial+'''int rc=vx_guest_resume(&s,mem,sizeof mem,1);
 if(rc<0||s.instructions!=1||s.r[13]!=600||s.n!=1||s.z||s.c!=1||s.v!=1)return 20;
 if(s.fpscr!=(0xf7c09f02u|'''+str(9 if count==4 else 0)+'''u))return 21;
 '''+checks+'''return 0;}
'''
            # Generated generic entry points have intentionally unused arguments.
            with tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);(p/'test.c').write_text(source)
                subprocess.run(['clang','-O2',str(p/'test.c'),'-o',str(p/'test')],check=True,capture_output=True)
                r=subprocess.run([str(p/'test')],capture_output=True)
                self.assertEqual(r.returncode,0,r.stderr)
        for word in (0xf2223d40,0xf2232d40,0xf2222d41):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))
