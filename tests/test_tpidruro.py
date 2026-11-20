"""ARM/Thumb TPIDRURO reads and scheduler-backed Vita user TLS placement."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_recompiler as support
ROOT=Path(__file__).resolve().parents[1]

class ThreadPointerTests(unittest.TestCase):
    translate=support.RecompilerTests.translate

    def compile_run(self,source,runtime=False):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(source);(p/'save').mkdir()
            cmd=['clang','-std=c11','-O2','-I',str(ROOT/'runtime'),str(p/'test.c')]
            if runtime:cmd.append(str(ROOT/'runtime/vita_runtime.c'))
            r=subprocess.run(cmd+['-o',str(p/'test')],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            r=subprocess.run([str(p/'test'),str(p/'save')],capture_output=True,text=True,timeout=5)
            self.assertEqual(r.returncode,0,r.stderr)

    def test_arm_thumb_read_condition_flags_and_context_isolation(self):
        for thumb,word,reg,expected in [(False,0xee1d0f70,0,0x12340),
                                        (False,0x0e1daf70,10,99),
                                        (True,0xee1daf70,10,0x12340)]:
            code=[word>>16,word&65535,0x4770] if thumb else [word,0xe12fff1e]
            r=self.translate(support.elf(code,thumb))
            source=r['c_source']+r'''
#include <assert.h>
uint32_t vx_import(uint32_t n,uint32_t*r,uint8_t*m,size_t z){(void)n;(void)r;(void)m;(void)z;return 0;}
int vx_runtime_stop_requested(uint32_t*s){(void)s;return 0;}
int main(void){uint8_t m[65536]={0};vx_guest_state a={0},b={0};
 a.pc=b.pc=ENTRY;a.r[REG]=b.r[REG]=99;a.tpidruro=0x12340;b.tpidruro=0x56780;
 a.n=b.n=1;a.c=b.c=1;a.v=b.v=1;a.fpscr=b.fpscr=0xa5000010;a.exclusive_valid=1;
 assert(vx_guest_resume(&a,m,sizeof m,1)==1);assert(vx_guest_resume(&b,m,sizeof m,1)==1);
 assert(a.r[REG]==EXPECTED);assert(b.r[REG]==OTHER);
 assert(a.n==1&&!a.z&&a.c==1&&a.v==1&&a.fpscr==0xa5000010&&a.exclusive_valid==1);
 assert(a.tpidruro==0x12340&&b.tpidruro==0x56780);return 0;}
'''
            source=source.replace('ENTRY',str(r['entry'])).replace('REG',str(reg)).replace('EXPECTED',str(expected)).replace('OTHER',str(99 if expected==99 else 0x56780))
            self.compile_run(source)
        for word in (0xee1dff70,0xee1ddf70,0xee0d0f70,0xee1d0f50):
            with self.assertRaises(ValueError):self.translate(support.elf([word,0xe12fff1e]))

    def test_vita_prefix_template_and_per_thread_user_pointer(self):
        source=r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
static unsigned phase,child_ran;static uint32_t root_tp;
int vx_guest_target_valid(uint32_t p){return p==0x200;}
static uint32_t tls(uint32_t key,uint8_t*m,size_t z){uint32_t r[16]={key};return vx_import(0xB295EB61,r,m,z);}
static int resume(vx_guest_state*s,uint8_t*m,size_t z,uint32_t budget){
 (void)budget;
 if(s->pc==0x200){assert(s->tpidruro==8192+0x800&&s->tpidruro!=root_tp);assert(m[s->tpidruro]==0xa5&&!m[s->tpidruro+144]);
  assert(tls(7,m,z)==8192+28);m[s->tpidruro+144]=11;vx_guest_memory_written();child_ran=1;return 0;}
 if(!phase++){
  root_tp=s->tpidruro;assert(root_tp==4096+0x800);assert(m[root_tp]==0xa5&&!m[root_tp+12]&&!m[root_tp+159]);
  assert(!m[4096+256]);assert(tls(7,m,z)==4096+28);assert(tls(256,m,z)==4096+1024);assert((int32_t)tls(257,m,z)<0);
  m[root_tp+144]=77;vx_guest_memory_written();
  uint32_t r[16]={32,0x200,128,4096};r[13]=260000;uint32_t id=vx_import(0xC5C11EE7,r,m,z);assert(id<0x80000000u);
  memset(r,0,sizeof r);r[0]=id;assert(!vx_import(0xF08DE149,r,m,z));return 1;
 }
 assert(child_ran&&m[root_tp+144]==77&&m[8192+0x800+144]==11);assert(s->tpidruro==root_tp);return 0;
}
int main(int argc,char**argv){assert(argc==2);static uint8_t m[262144];memcpy(m+32,"tpidruro",9);memset(m+2048,0xa5,12);
 assert(!vx_runtime_mount(argv[1]));assert(!vx_runtime_set_heap(147456,32768));
 assert(vx_runtime_set_tls_user_offset(0x800)==-1);
 assert(!vx_runtime_set_tls(4096,4096,2048,12,160));assert(vx_runtime_set_tls_user_offset(4096)==-1);
 assert(!vx_runtime_set_tls_user_offset(0x800));vx_guest_state s={0};s.pc=0x100;s.r[13]=260000;
 assert(!vx_runtime_run(&s,m,sizeof m,resume));vx_runtime_shutdown();return 0;}
'''
        self.compile_run(source,runtime=True)
