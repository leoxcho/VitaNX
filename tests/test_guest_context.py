"""CPU state suspension and integrated kernel runtime behavior."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_recompiler as support
ROOT=Path(__file__).resolve().parents[1]

class GuestContextTests(unittest.TestCase):
    translate=support.RecompilerTests.translate

    def test_quantum_preserves_flags_registers_and_termination(self):
        # CMP r0,#0; MOVEQ r1,#7; MOVNE r1,#9; BX LR.
        result=self.translate(support.elf([0xe3500000,0x03a01007,0x13a01009,0xe12fff1e]))
        source=result['c_source']+r'''
uint32_t vx_import(uint32_t n,uint32_t*r,uint8_t*m,size_t z){(void)n;(void)r;(void)m;(void)z;return 0;}
int vx_runtime_stop_requested(uint32_t*s){(void)s;return 0;}
#include <assert.h>
int main(void){uint8_t mem[65536]={0};vx_guest_state a={0},b={0};
 a.pc=b.pc=0x100;a.r[14]=b.r[14]=0xffffffff;b.r[0]=1;
 a.f[63]=0x7fc12345;b.f[63]=0x81234567;
 for(int i=0;i<4;i++){assert(vx_guest_resume(&a,mem,sizeof mem,1)>=0);assert(vx_guest_resume(&b,mem,sizeof mem,1)>=0);}
 assert(a.r[1]==7&&b.r[1]==9&&a.f[63]==0x7fc12345&&b.f[63]==0x81234567);
 assert(a.z==1&&b.z==0);assert(vx_guest_resume(&a,mem,sizeof mem,1)==0);return 0;}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(source)
            subprocess.run(['clang','-O2',str(p/'test.c'),'-o',str(p/'test')],check=True,capture_output=True)
            subprocess.run([str(p/'test')],check=True,capture_output=True,timeout=5)

    def test_mutex_events_and_pointer_errors(self):
        source=r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
static uint8_t mem[65536];static uint32_t r[16];
static uint32_t call(uint32_t nid,uint32_t a,uint32_t b,uint32_t c,uint32_t d){r[0]=a;r[1]=b;r[2]=c;r[3]=d;return vx_import(nid,r,mem,sizeof mem);}
int main(void){strcpy((char*)mem+32,"game");r[13]=1024;
 uint32_t m=call(0xED53334A,32,2,0,0);assert(m<0x80000000);
 assert(!call(0x1D8D7945,m,2,0,0));assert(!call(0x1D8D7945,m,1,0,0));
 assert(call(0x1A372EC8,m,4,0,0)==0x80028144);assert(!call(0x1A372EC8,m,3,0,0));
 assert(call(0x1A372EC8,m,1,0,0)==0x80028146);assert(!call(0xCB78710D,m,0,0,0));
 assert(call(0x1D8D7945,m,1,0,0)==0x80028141);
 m=call(0xED53334A,32,0,1,0);assert(call(0x1D8D7945,m,1,0,0)==0x80028142);
 uint32_t e=call(0x8516D040,32,0,0,0);assert(e<0x80000000);
 assert(call(0x1FBB0FE1,e,1,0,128)==0x800280e3);
 assert(!call(0xEC94DFF7,e,7,0,0));assert(!call(0x1FBB0FE1,e,3,4,128));
 assert(mem[128]==7);assert(call(0x1FBB0FE1,e,1,0,128)==0x800280e3);
 assert(!call(0x1FBB0FE1,e,4,2,128));assert(mem[128]==4);
 assert(call(0x1FBB0FE1,e,4,0,128)==0x800280e3);
 assert(call(0x1FBB0FE1,e,1,6,128)==0x80020005);
 assert(call(0x1FBB0FE1,e,1,0,65534)==0x80020006);
 assert(!call(0x5840162C,e,0,0,0));assert(call(0xEC94DFF7,e,1,0,0)==0x800280e1);
 vx_runtime_shutdown();return 0;}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),str(p/'test.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(p/'test')],check=True,capture_output=True)
            subprocess.run([str(p/'test')],check=True,capture_output=True,timeout=5)
