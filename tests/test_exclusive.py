"""Execute actual ARM/Thumb exclusives, ABA conflicts and scheduler retries."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_recompiler as support

ROOT=Path(__file__).resolve().parents[1]

class ExclusiveTests(unittest.TestCase):
    translate=support.RecompilerTests.translate
    run_code=support.RecompilerTests.run_code

    def test_word_success_retry_and_thumb_offset(self):
        for thumb,code in [(False,[0xe1902f9f,0xe2822001,0xe1803f92,0xe3530000,0x1afffffa,0xe12fff1e]),
                           (True,[0xe850,0x2f02,0x3201,0xe840,0x2302,0x2b00,0xd1f8,0x4770])]:
            result=self.translate(support.elf(code,thumb))
            address=608 if thumb else 600
            self.run_code(result,f'r[0]=600;vx_write32(mem+{address},0xffffffffu);',
                          f'if(r[0]!=600||r[3]||vx_read32(mem+{address}))return 10;')

    def test_clear_missing_mismatched_and_consumed_reservations(self):
        for thumb,code in [(False,[0xe1902f9f,0xf57ff01f,0xe1803f92,0xe12fff1e]),
                           (True,[0xe850,0x2f00,0xf3bf,0x8f2f,0xe840,0x2300,0x4770]),
                           (False,[0xe1803f92,0xe12fff1e]),
                           (False,[0xe1902f9f,0xe2800004,0xe1803f92,0xe2400004,0xe1804f92,0xe12fff1e])]:
            result=self.translate(support.elf(code,thumb))
            self.run_code(result,'r[0]=600;r[2]=99;vx_write32(mem+600,7);vx_write32(mem+604,9);',
                          'if(r[3]!=1||vx_read32(mem+600)!=7||vx_read32(mem+604)!=9)return 11;'+
                          ('if(r[4]!=1)return 15;' if 0xe1804f92 in code else ''))
        # Conditional STREX that does not execute must not consume reservation.
        r=self.translate(support.elf([0xe1902f9f,0xe3560000,0x01803f92,0xe1803f92,0xe12fff1e]))
        self.run_code(r,'r[0]=600;r[6]=1;vx_write32(mem+600,7);','if(r[3])return 12;')

    def test_aba_conflicts_from_translated_word_byte_halfword_stores(self):
        for stores in ([0xe5804000,0xe5805000],[0xe5c04000,0xe5c05000],
                       [0xe1c040b0,0xe1c050b0],[0xe8800010,0xe8800020]):
            r=self.translate(support.elf([0xe1902f9f,*stores,0xe1803f92,0xe12fff1e]))
            self.run_code(r,'r[0]=600;r[4]=9;r[5]=7;vx_write32(mem+600,7);',
                          'if(r[3]!=1||vx_read32(mem+600)!=7)return 13;')

    def test_alignment_bounds_and_invalid_encodings(self):
        for code in ([0xe1902f9f,0xe12fff1e],[0xe1803f92,0xe12fff1e]):
            r=self.translate(support.elf(code))
            for address in (602,65536,0xfffffffc):
                self.run_code(r,f'r[0]={address}u;r[2]=123;r[3]=456;mem[600]=77;',
                              'if(rc!=-2||r[2]!=123||r[3]!=456||mem[600]!=77)return 14;rc=0;')
        for word in (0xe1d02f9f,0xe1f02f9f,0xe1b02f9f,0xe1c03f92,0xe1e03f92,0xe1a04f92,
                     0xe190ff9f,0xe19f2f9f,0xe1800f92,0xe1802f92):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))
        for first,second in [(0xe8d0,0x2f4f),(0xe8d0,0x2f5f),(0xe8d0,0x237f),
                             (0xe8c0,0x2f43),(0xe8c0,0x2f53),(0xe8c0,0x2374),
                             (0xe850,0xdf00),(0xe840,0x2000),(0xe840,0x2200)]:
            with self.assertRaises(ValueError):self.translate(support.elf([first,second,0x4770],True))

    def native_state(self,body,*,runtime=False):
        code=[0xe1902f9f,0xe2822001,0xe1803f92,0xe3530000,0x1afffffa,0xe12fff1e]
        r=self.translate(support.elf(code))
        stub='uint32_t vx_import(uint32_t n,uint32_t*r,uint8_t*m,size_t z){(void)n;(void)r;(void)m;(void)z;return 0;}\nint vx_runtime_stop_requested(uint32_t*s){(void)s;return 0;}\n'
        source=r['c_source']+'\n#include <assert.h>\n'+('#include "vita_runtime.h"\n' if runtime else stub)+body
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(source);(p/'save').mkdir()
            cmd=['clang','-std=c11','-O2','-I',str(ROOT/'runtime'),str(p/'test.c')]
            if runtime:cmd.append(str(ROOT/'runtime/vita_runtime.c'))
            c=subprocess.run(cmd+['-o',str(p/'test')],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            proc=subprocess.run([str(p/'test'),str(p/'save')],capture_output=True,text=True,timeout=10)
            self.assertEqual(proc.returncode,0,proc.stderr)

    def test_context_state_size_identity_flags_and_external_writes(self):
        self.native_state(r'''
static void init(vx_guest_state*s){memset(s,0,sizeof *s);s->pc=0x100;s->r[0]=600;s->r[14]=UINT32_MAX;s->n=s->v=1;s->c=1;s->fpscr=0xa5000010;}
int main(void){uint8_t m[65536]={0},other[65536]={0};vx_guest_state a,b;
 for(int mode=0;mode<4;mode++){
  init(&a);init(&b);vx_write32(m+600,7);
  assert(vx_guest_resume(&a,m,sizeof m,1)==1);assert(a.exclusive_valid&&a.exclusive_address==600&&a.exclusive_size==4);
  assert(a.n==1&&a.v==1&&a.c==1&&!a.z&&a.fpscr==0xa5000010);
  assert(!b.exclusive_valid);b.r[0]=604;assert(vx_guest_resume(&b,m,sizeof m,1)==1);
  assert(a.exclusive_address==600&&b.exclusive_address==604);
  if(mode==0)a.exclusive_size=8;
  if(mode==1)vx_guest_memory_written();
  if(mode==2){vx_write32(m+600,9);vx_write32(m+600,7);}
  assert(vx_guest_resume(&a,mode==3?other:m,sizeof m,2)==1);
  assert(a.r[3]==1&&!a.exclusive_valid&&vx_read32(m+600)==7);
 }
 return 0;}
''')

    def test_real_scheduler_switch_causes_failed_store_then_retry(self):
        self.native_state(r'''
static int started,child_ran,failed,success;
static int resume(vx_guest_state*s,uint8_t*m,size_t z,uint32_t budget){
 (void)budget;
 if(s->r[0]==0){assert(!s->exclusive_valid);child_ran++;return 0;}
 if(!started){uint32_t r[16]={0};r[0]=32;r[1]=0x104;r[2]=256;r[3]=4096;r[13]=60000;
  uint32_t uid=vx_import(0xC5C11EE7,r,m,z);assert(uid<0x80000000u);memset(r,0,sizeof r);r[0]=uid;assert(!vx_import(0xF08DE149,r,m,z));started=1;
 }
 uint32_t before=s->pc;int rc=vx_guest_resume(s,m,z,1);
 if(before==0x108){if(s->r[3])failed++;else success++;}
 return rc;
}
int main(int argc,char**argv){assert(argc==2);uint8_t m[65536]={0};memcpy(m+32,"exclusive",10);
 assert(!vx_runtime_mount(argv[1]));assert(!vx_runtime_set_heap(8192,32768));
 vx_guest_state s={0};s.pc=0x100;s.r[0]=600;s.r[13]=60000;s.r[14]=UINT32_MAX;
 assert(!vx_runtime_run(&s,m,sizeof m,resume));
 assert(child_ran==1&&failed==1&&success==1&&vx_read32(m+600)==1);
 vx_runtime_shutdown();return 0;}
''',runtime=True)

    def test_runtime_import_boundary_invalidates_reservation(self):
        self.native_state(r'''
int main(void){uint8_t m[65536]={0};vx_guest_state s={0};s.pc=0x100;s.r[0]=600;s.r[14]=UINT32_MAX;
 vx_write32(m+600,7);assert(vx_guest_resume(&s,m,sizeof m,1)==1&&s.exclusive_valid);
 uint32_t r[16]={0};vx_import(0x2BE3E066,r,m,sizeof m);
 assert(vx_guest_resume(&s,m,sizeof m,2)==1);
 assert(s.r[3]==1&&vx_read32(m+600)==7);vx_runtime_shutdown();return 0;}
''',runtime=True)

    def test_commercial_stack_adjustment_preserves_nzcv(self):
        # Actual next blocker: SUB.W SP,SP,#728; inverse ADD.W uses same imm.
        code=[0x2801,0xf5ad,0x7d36,0xf50d,0x7d36,
              0xd500,0x2401,0xd100,0x2401,0xd200,0x2401,0xd600,0x2401,0x4770]
        r=self.translate(support.elf(code,True))
        self.run_code(r,'r[0]=0x80000000u;r[13]=6000;',
                      'if(r[0]!=0x80000000u||r[13]!=6000||r[4])return 120;')
