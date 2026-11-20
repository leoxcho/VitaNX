"""Native scheduler contention tests for the commercial lightweight-mutex path."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=r'''
#include "vita_runtime.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static uint32_t low,high,attr,order[2],used,mode;
static uint32_t get(uint8_t*m,unsigned a){uint32_t v;memcpy(&v,m+a,4);return v;}
static uint32_t call(uint32_t n,uint8_t*m,size_t size,uint32_t a,uint32_t b,uint32_t c,uint32_t d){uint32_t r[16]={a,b,c,d};r[13]=60000;return vx_import(n,r,m,size);}
int vx_guest_target_valid(uint32_t pc){return pc==0x200||pc==0x300;}
static uint32_t create(uint32_t pc,uint32_t priority,uint8_t*m,size_t z){uint32_t id=call(0xC5C11EE7,m,z,32,pc,priority,4096);assert((int32_t)id>0);return id;}
static void start(uint32_t id,uint8_t*m,size_t z){assert(!call(0xF08DE149,m,z,id,0,0,0));}
static int resume(vx_guest_state*s,uint8_t*m,size_t z,uint32_t budget){
 (void)budget;
 if(s->pc!=0x100){
  if(!s->r[4]){s->r[4]=1;s->r[0]=call(0x46E7BE7B,m,z,512,1,mode==1?2048:0,0);return 1;}
  if(mode){assert(s->r[0]==(mode==1?0x80028005:0x800281c2));used++;s->pc=UINT32_MAX;return 0;}
  assert(!s->r[0]);assert(get(m,512)==(s->pc==0x200?low:high));order[used++]=s->pc;
  assert(!call(0x91FA6614,m,z,512,1,0,0));s->pc=UINT32_MAX;return 0;
 }
 switch(s->r[4]++){
 case 0:
  assert(!call(0xDA6EC8EF,m,z,512,32,attr,2));assert(get(m,512)==1&&get(m,520)==2&&get(m,524)==attr);
  assert(!call(0xA6A2C915,m,z,512,1,0,0));assert(get(m,520)==3);
  assert(!call(0x91FA6614,m,z,512,1,0,0));
  assert(call(0x91FA6614,m,z,512,3,0,0)==0x80028184);assert(get(m,520)==2);
  low=create(0x200,400,m,z);high=create(0x300,300,m,z);start(low,m,z);break;
 case 1:start(high,m,z);break;
 case 2:
  if(mode==2){assert(!call(0x244E76D2,m,z,512,0,0,0));break;}
  assert(!call(0x91FA6614,m,z,512,1,0,0));assert(get(m,520)==1);
  assert(!call(0x91FA6614,m,z,512,1,0,0));break;
 case 3:
  assert(used==2);if(!mode){assert(order[0]==(attr&0x2000?0x300:0x200));assert(order[1]==(attr&0x2000?0x200:0x300));}
  if(mode!=2)assert(!get(m,512)&&!get(m,520));
  if(mode!=2)assert(!call(0x244E76D2,m,z,512,0,0,0));assert(call(0xA6A2C915,m,z,512,1,0,0)==0x80028181);
  assert(!call(0xDA6EC8EF,m,z,512,32,0,0));assert(!call(0x46E7BE7B,m,z,512,1,0,0));
  assert(call(0x46E7BE7B,m,z,512,1,0,0)==0x80028182);
  assert(!call(0x48C7EAE6,m,z,1024,32,0x2000,512));assert(get(m,1028)==get(m,528));
  assert(!call(0x721F6CB3,m,z,1024,0,0,0));
  s->pc=UINT32_MAX;return 0;
 }
 assert(!call(0x4B675D05,m,z,1000,0,0,0));return 1;
}
int main(int argc,char**argv){assert(argc==3);uint8_t m[65536]={0};memcpy(m+32,"lwmutex",8);attr=strtoul(argv[2],0,0);mode=attr>>16;attr&=0xffff;uint32_t timeout=100;memcpy(m+2048,&timeout,4);
 assert(!vx_runtime_mount(argv[1]));assert(!vx_runtime_set_heap(8192,32768));
 memset(m+512,0xa5,32);assert(call(0xDA6EC8EF,m,sizeof m,512,32,4,0)==0x8002000e);assert(m[512]==0xa5);
 assert(call(0xDA6EC8EF,m,sizeof m,65528,32,0x2002,0)==0x80020006);
 vx_guest_state s={0};s.pc=0x100;s.r[13]=60000;assert(!vx_runtime_run(&s,m,sizeof m,resume));vx_runtime_shutdown();return 0;}
'''
class LwMutexTests(unittest.TestCase):
    def test_priority_fifo_recursion_workarea_and_faults(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(SOURCE);(p/'save').mkdir()
            c=subprocess.run(['clang','-std=c11','-O1','-I',str(ROOT/'runtime'),str(p/'test.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(p/'native')],capture_output=True,text=True)
            self.assertEqual(c.returncode,0,c.stderr)
            for attr in ['0x2002','2','0x12002','0x22002']:
                r=subprocess.run([str(p/'native'),str(p/'save'),attr],capture_output=True,text=True,timeout=5)
                self.assertEqual(r.returncode,0,r.stderr)
