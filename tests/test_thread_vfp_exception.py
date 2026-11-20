"""VitaSDK cumulative FPSCR flags, applied across cached native service yields."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ThreadVfpExceptionTests(unittest.TestCase):
    def test_native_yield_clear_set_preservation_and_errors(self):
        source = r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
static unsigned phase;
static int resume(vx_guest_state*s,uint8_t*m,size_t n,uint32_t budget){
 (void)budget;
 uint32_t local=s->fpscr;
 if(phase==0){
  assert(local==0xf940009f);s->r[0]=0x0800009f;s->r[1]=0;
  assert(vx_import(0xcc18fbae,s->r,m,n)==0);assert(s->r[1]==0);
 }else if(phase==1){
  assert(local==0xf1400000);s->r[0]=0x0800009f;s->r[1]=0x08000012;
  assert(vx_import(0xcc18fbae,s->r,m,n)==0);
 }else if(phase==2){
  assert(local==0xf9400012);s->r[0]=0;s->r[1]=0x100;
  assert(vx_import(0xcc18fbae,s->r,m,n)==0x80020005);
 }else{assert(local==0xf9400012);return 0;}
 /* Match generated code: FPSCR local overwrites state after vx_import. */
 s->fpscr=local;s->instructions++;s->services++;phase++;return 1;
}
int main(void){
 uint8_t m[2048];memset(m,0xa5,sizeof m);uint32_t r[16]={0};
 assert(vx_import(0xcc18fbae,r,m,sizeof m)==0x80010030);
 vx_guest_state s={0};s.fpscr=0xf940009f;s.f[17]=0x12345678;
 assert(vx_runtime_run(&s,m,sizeof m,resume)==0);
 assert(phase==3&&s.fpscr==0xf9400012&&s.f[17]==0x12345678);
 for(unsigned i=0;i<sizeof m;i++)assert(m[i]==0xa5);
 /* A second guest context starts with its own flags, no retained masks. */
 phase=0;s=(vx_guest_state){0};s.fpscr=0xf940009f;
 assert(vx_runtime_run(&s,m,sizeof m,resume)==0);assert(phase==3);
 vx_runtime_shutdown();return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'probe.c').write_text(source)
            c=subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(p/'probe')],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            result=subprocess.run([str(p/'probe')],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_simultaneous_guest_thread_isolation(self):
        source = r''' 
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
static unsigned root_phase,child_phase;
int vx_guest_target_valid(uint32_t pc){return pc==0x200;}
static uint32_t call(uint32_t nid,uint8_t*m,size_t n,uint32_t a,uint32_t b,uint32_t c,uint32_t d){
 uint32_t r[16]={a,b,c,d};r[13]=60000;return vx_import(nid,r,m,n);
}
static int resume(vx_guest_state*s,uint8_t*m,size_t n,uint32_t budget){
 (void)budget;
 if(s->pc==0x200){
  if(!child_phase++){
   assert(s->fpscr==0);s->fpscr=0x0800009f;
   assert(!call(0xcc18fbae,m,n,0x9f,0x2,0,0));return 1;
  }
  assert(s->fpscr==0x08000002);return 0;
 }
 if(!root_phase++){
  uint32_t uid=call(0xc5c11ee7,m,n,32,0x200,200,4096);assert((int32_t)uid>0);
  assert(!call(0xf08de149,m,n,uid,0,0,0));
  assert(!call(0xcc18fbae,m,n,0x0800009f,0x10,0,0));return 1;
 }
 assert(child_phase==2);assert(s->fpscr==0xf0000010);return 0;
}
int main(void){uint8_t m[65536]={0};strcpy((char*)m+32,"fpscr");
 uint32_t r[16]={0};vx_import(0x0fb972f9,r,m,sizeof m);
 assert(!vx_runtime_set_heap(8192,32768));vx_guest_state s={0};s.pc=0x100;s.fpscr=0xf800009f;
 assert(!vx_runtime_run(&s,m,sizeof m,resume));assert(root_phase==2&&child_phase==2);
 vx_runtime_shutdown();return 0;}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'probe.c').write_text(source)
            c=subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(p/'probe')],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            result=subprocess.run([str(p/'probe')],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_exact_qualified_binding(self):
        rows=json.loads((ROOT/'vitanx/runtime-nids.json').read_text())['bindings']
        found=[row for row in rows if (row['library_nid'],row['function_nid'])==('859a24b1','cc18fbae')]
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['name'],'sceKernelChangeThreadVfpException')
