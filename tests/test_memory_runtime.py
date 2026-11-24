"""Native bounded Sysmem and single-thread semaphore behavior."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('clang'),'Clang required')
class MemoryRuntimeTests(unittest.TestCase):
    def test_memory_blocks_and_single_thread_semaphores(self):
        source=r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
static uint8_t memory[0x181000];
static uint32_t r[16];
static size_t backing_size=65536;
static uint32_t call(uint32_t nid,uint32_t a,uint32_t b,uint32_t c,uint32_t d){
 r[0]=a;r[1]=b;r[2]=c;r[3]=d;return vx_import(nid,r,memory,backing_size);
}
static uint32_t word(unsigned offset){uint32_t result;memcpy(&result,memory+offset,4);return result;}
int main(void){
 size_t capability_count=0;const vx_import_capability *caps=vx_runtime_import_capabilities(&capability_count);
 assert(capability_count>=30&&vx_runtime_import_capabilities(0)==caps);
 for(size_t i=0;i<capability_count;i++)assert(!strcmp(caps[i].feature,"core")&&strcmp(caps[i].name,"unknown"));
 const uint32_t base=0x81000000u;
 vx_runtime_set_memory_base(base);strcpy((char*)memory+32,"test allocation");
 assert(vx_runtime_set_heap(base+4097,8192)==-1);
 assert(vx_runtime_set_heap(0xfffff000u,8192)==-1);
 assert(!vx_runtime_set_heap(0xffffe000u,4096));
 assert(call(0xB9D5EBDE,base+32,0x0c20d060,4096,0)==0x8002710bu);
 assert(!vx_runtime_set_heap(base-4096,4096));
 assert(call(0xB9D5EBDE,base+32,0x0c20d060,4096,0)==0x8002710bu);
 assert(!vx_runtime_set_heap(base+65536,4096));
 assert(call(0xB9D5EBDE,base+32,0x0c20d060,4096,0)==0x8002710bu);
 assert(!vx_runtime_set_heap(base+4096,8192));
 uint32_t first=call(0xB9D5EBDE,base+32,0x0c20d060,4096,0);assert(first<0x80000000u);
 assert(vx_runtime_set_heap(base+4096,8192)==-1);
 assert(!call(0xB8EF5818,first,base+128,0,0));assert(word(128)==base+4096);
 memset(memory+4096,0x5a,4096);
 assert(call(0xA33B99D1,base+4096,4096,0,0)==first);
 assert(call(0xA33B99D1,base+4096,4097,0,0)==0x80024501u);
 assert(call(0xA33B99D1,0xffffffffu,2,0,0)==0x80020005u);
 uint32_t second=call(0xB9D5EBDE,base+32,0x0c208060,4096,0);assert(second!=first&&second<0x80000000u);
 assert(call(0xB9D5EBDE,base+32,0x0c20d060,4096,0)==0x8002710bu);
 assert(!call(0xA91E15EE,first,0,0,0));assert(call(0xA91E15EE,first,0,0,0)==0x80024501u);
 uint32_t third=call(0xB9D5EBDE,base+32,0x0c20d060,4096,0);assert(third!=first&&third!=second);
 assert(memory[4096]==0&&memory[8191]==0);
 assert(!call(0xB8EF5818,third,base+128,0,0));assert(word(128)==base+4096);
 assert(call(0xB8EF5818,third,base-1,0,0)==0x80020006u);
 assert(call(0xB8EF5818,third,base+65534,0,0)==0x80020006u);
 assert(call(0xB9D5EBDE,base-1,0x0c20d060,4096,0)==0x80020006u);
 assert(call(0xB9D5EBDE,base+32,0x0c20d060,1,0)==0x8002000bu);
 assert(call(0xB9D5EBDE,base+32,1,4096,0)==0x8002000cu);
 assert(call(0xB9D5EBDE,base+32,0x0c20d060,4096,base+65535)==0x80020006u);
 r[13]=base+65534;assert(call(0x1BD67366,base+32,0,1,2)==0x80020006u);
 r[13]=base+512;
 assert(call(0x1BD67366,base+32,0,3,2)==0x80020005u);
 assert(call(0x1BD67366,base+32,0,0xffffffffu,2)==0x80020005u);
 assert(call(0x1BD67366,base+32,1,1,2)==0x80010030u);
 uint32_t sema=call(0x1BD67366,base+32,0,1,2);assert(sema<0x80000000u);
 assert(!call(0x866EF048,sema,1,0,0));assert(call(0x866EF048,sema,1,0,0)==0x80028102u);
 assert(call(0x0C7B834B,sema,1,base+600,0)==0x80028005u);
 assert(call(0x0C7B834B,sema,1,0,0)==0x80010030u); /* unsupported blocking wait */
 assert(call(0x0C7B834B,sema,1,base+65534,0)==0x80020006u);
 assert(call(0xE6B761D1,sema,0xffffffffu,0,0)==0x80020005u);
 assert(!call(0xE6B761D1,sema,2,0,0));assert(call(0xE6B761D1,sema,1,0,0)==0x80028103u);
 assert(!call(0x0C7B834B,sema,1,0,0));assert(!call(0x866EF048,sema,1,0,0));
 assert(call(0x866EF048,sema,0,0,0)==0x80020005u);
 assert(!call(0xDB32948A,sema,0,0,0));assert(call(0x866EF048,sema,1,0,0)==0x80024501u);
 vx_runtime_shutdown();vx_runtime_set_memory_base(base);
 backing_size=sizeof memory;
 assert(!vx_runtime_set_heap(base+4096,0x180000));
 strcpy((char*)memory+32,"Sgx::CDevice Fragment Ring Buffer");
 uint32_t ring=call(0xB9D5EBDE,base+32,0x0c208060,0x180000,0);
 assert(ring<0x80000000u);
 assert(!call(0xB8EF5818,ring,base+128,0,0));assert(word(128)==base+4096);
 assert(call(0xA33B99D1,base+4096,0x180000,0,0)==ring);
 assert(!call(0xA91E15EE,ring,0,0,0));
 const uint32_t last=sizeof memory-1;
 memory[last]='x';
 assert(call(0xB9D5EBDE,base+last,0x0c208060,4096,0)==0x80020006u);
 memory[last]=0;
 assert(call(0xB9D5EBDE,base+last,0x0c208060,4096,0)<0x80000000u);
 vx_runtime_shutdown();vx_runtime_set_memory_base(base);
 assert(call(0xB9D5EBDE,base+32,0x0c20d060,4096,0)==0x8002710bu);
 assert(call(0xB8EF5818,third,base+128,0,0)==0x80024501u);
 return 0;
}'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);(tmp/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),
                            str(tmp/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(tmp/'probe')],
                           check=True,capture_output=True)
            subprocess.run([str(tmp/'probe')],check=True,capture_output=True,timeout=5)
