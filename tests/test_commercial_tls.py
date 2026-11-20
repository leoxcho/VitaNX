"""Native runtime tests for isolated TLS and loader-supplied process parameters."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

class CommercialTLSTests(unittest.TestCase):
    def test_scheduler_tls_isolation_template_and_lifecycle(self):
        source=r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
static uint32_t child,root_tls,child_tls;
int vx_guest_target_valid(uint32_t pc){return pc==0x200;}
static uint32_t tls(uint32_t key,uint8_t*m,size_t size){uint32_t r[16]={key};return vx_import(0xB295EB61,r,m,size);}
static int resume(vx_guest_state*s,uint8_t*m,size_t size,uint32_t budget){
 (void)budget;
 if(s->pc==0x200){child_tls=tls(7,m,size);assert(child_tls!=root_tls);assert(!m[child_tls]);m[child_tls]=11;assert(m[child_tls-28+256]==0xa5);s->pc=UINT32_MAX;return 0;}
 if(!s->r[4]){
  root_tls=tls(7,m,size);assert(root_tls==4096+28);assert(!m[root_tls]);m[root_tls]=77;
  assert(m[4096+256]==0xa5);assert(!m[4096+256+12]);
  assert(tls(63,m,size)==4096+252);assert((int32_t)tls(64,m,size)<0);
  uint32_t r[16]={0};r[0]=32;r[1]=0x200;r[2]=128;r[3]=4096;r[13]=60000;
  child=vx_import(0xC5C11EE7,r,m,size);assert((int32_t)child>0);
  memset(r,0,sizeof r);r[0]=child;assert(!vx_import(0xF08DE149,r,m,size));s->r[4]=1;return 1;
 }
 assert(m[root_tls]==77&&m[child_tls]==11);
 uint32_t r[16]={child,7};assert(vx_import(0xBACA6891,r,m,size)==child_tls);
 assert(vx_import(0x2BE3E066,r,m,size)==1024);
 s->pc=UINT32_MAX;return 0;
}
static uint32_t prior_module_owner;
static int module_resume(vx_guest_state*s,uint8_t*m,size_t size,uint32_t budget){
 (void)budget;uint32_t r[16]={0};uint32_t owner=vx_import(0x0FB972F9,r,m,size);assert(owner!=prior_module_owner&&owner!=1);prior_module_owner=owner;
 uint32_t slot=tls(7,m,size);assert(!m[slot]);m[slot]=99;m[2000]++;
 r[0]=0;vx_import(0x0C8A38E1,r,m,size);s->services++;return 1;
}
int main(int argc,char**argv){assert(argc==2);uint8_t m[65536]={0};memcpy(m+32,"tls",4);memset(m+1024,0xa5,12);
 assert(!vx_runtime_mount(argv[1]));assert(!vx_runtime_set_heap(24576,16384));
 assert(vx_runtime_set_tls(4097,512,1024,12,160)==-1);
 assert(!vx_runtime_set_tls(4096,512,1024,12,160));vx_runtime_set_process_param(1024);
 vx_guest_state s={0};s.pc=0x100;s.r[13]=60000;assert(!vx_runtime_run(&s,m,sizeof m,resume));
 for(int i=0;i<2;i++){vx_guest_state module={0};module.pc=0x400;module.r[13]=60000;assert(!vx_runtime_run_module(&module,m,sizeof m,module_resume));uint32_t status;assert(vx_runtime_stop_requested(&status)==VX_STOP_THREAD&&status==0);vx_runtime_reset_stop();}
 assert(m[2000]==2);vx_runtime_shutdown();return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(source);(p/'save').mkdir()
            result=subprocess.run(['clang','-std=c11','-O1','-I',str(ROOT/'runtime'),str(p/'test.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(p/'test')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(p/'test'),str(p/'save')],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
