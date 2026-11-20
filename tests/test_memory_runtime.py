"""Native bounded Sysmem and single-thread semaphore behavior."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('clang'),'Clang required')
class MemoryRuntimeTests(unittest.TestCase):
    def test_large_allocation_alignment_options_and_failure_reasons(self):
        """VitaSDK HAS_ALIGNMENT and a 1.5MiB request in a bounded arena."""
        source=r'''
#include "vita_runtime.h"
#include "vita_memblock_diag.h"
#include <assert.h>
#include <stdint.h>
#include <string.h>
static uint8_t mem[4*1024*1024];
static uint32_t r[16];
static const uint32_t base=0x81000000u;
static void word(uint32_t off,uint32_t val){memcpy(mem+off,&val,sizeof val);}
static uint32_t word_at(uint32_t off){uint32_t val;memcpy(&val,mem+off,4);return val;}
static uint32_t call(uint32_t name,uint32_t type,uint32_t size,uint32_t options){
 r[0]=name;r[1]=type;r[2]=size;r[3]=options;
 return vx_import(0xB9D5EBDE,r,mem,sizeof mem);
}
static uint32_t getbase(uint32_t uid){
 r[0]=uid;r[1]=base+192;
 assert(vx_import(0xB8EF5818,r,mem,sizeof mem)==0);
 return word_at(192);
}
int main(void){
 vx_runtime_set_memory_base(base);
 assert(vx_runtime_set_heap(base+8192u,3*1024*1024u)==0);
 strcpy((char *)mem+32,"graphics backing");
 word(128,64);word(132,4);word(136,65536);
 uint32_t a=call(base+32,0x0c20d060,4096,0);
 assert((int32_t)a>0 && getbase(a)==base+8192u);
 uint32_t b=call(base+32,0x0c208060,1536*1024,base+128);
 assert((int32_t)b>0 && b!=a);
 assert(getbase(b)==base+65536u && getbase(b)%65536u==0);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_OK);
 assert(mem[65536]==0 && mem[65536+1536*1024-1]==0);
 word(136,6144);
 assert(call(base+32,0x0c208060,4096,base+128)==0x80020005u);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_BAD_ALIGNMENT);
 word(136,4096);word(132,0x14);
 assert(call(base+32,0x0c208060,4096,base+128)==0x80010030u);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_UNSUPPORTED_OPTIONS);
 word(132,4);word(128,64);
 word(sizeof mem-4,64);
 assert(call(base+32,0x0c208060,4096,base+sizeof mem-4)==0x80020006u);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_BAD_OPTIONS_ADDRESS);
 assert(call(base-4,0x0c208060,4096,0)==0x80020006u);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_BAD_NAME);
 memset(mem+320,'x',32);
 assert(call(base+320,0x0c208060,4096,0)==0x80020006u);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_NAME_UNTERMINATED);
 assert(call(base+32,0x09408060,4096,0)==0x8002000cu);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_UNSUPPORTED_TYPE);
 assert(call(base+32,0x0c20d060,0,0)==0x8002000bu);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_BAD_SIZE);
 assert(call(base+32,0x0c20d060,4096,0)==a+2);
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_OK);
 vx_runtime_shutdown();
 assert(vx_runtime_memblock_failure_reason()==VX_MEMBLOCK_OK);
 return 0;
}'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);(tmp/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),
                            str(tmp/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(tmp/'probe')],
                           check=True,capture_output=True)
            subprocess.run([str(tmp/'probe')],check=True,capture_output=True,timeout=5)

    def test_memory_blocks_and_single_thread_semaphores(self):
        source=r'''
#include "vita_runtime.h"
#include <assert.h>
#include <string.h>
static uint8_t memory[65536];
static uint32_t r[16];
static uint32_t call(uint32_t nid,uint32_t a,uint32_t b,uint32_t c,uint32_t d){
 r[0]=a;r[1]=b;r[2]=c;r[3]=d;return vx_import(nid,r,memory,sizeof memory);
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
