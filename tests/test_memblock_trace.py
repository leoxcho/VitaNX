"""Runtime import tracing retains why a guest allocation was rejected."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('clang'), 'Clang required')
class MemoryBlockImportTraceTests(unittest.TestCase):
    def test_rejected_guest_pointer_has_stable_reason(self):
        source = r'''
#include "vita_runtime.h"
#include "vita_memblock_diag.h"
#include <assert.h>
#include <string.h>
extern uint32_t vn_import(uint32_t,uint32_t *,uint8_t *,size_t);
extern size_t vn_import_trace_count(void);
extern uint32_t vn_import_trace_field(size_t,unsigned);
static uint8_t memory[65536];
int main(void){
 const uint32_t base=0x81000000u;
 uint32_t r[16]={base+12,0x0c20d060,4096,base+65532};
 strcpy((char*)memory+12,"trace");
 uint32_t len=64;memcpy(memory+65532,&len,4);
 vx_runtime_set_memory_base(base);
 assert(vx_runtime_set_heap(base+8192,32768)==0);
 assert(vn_import(0xB9D5EBDE,r,memory,sizeof memory)==0x80020006u);
 assert(vn_import_trace_count()==1);
 assert(vn_import_trace_field(0,0)==0xB9D5EBDEu);
 assert(vn_import_trace_field(0,5)==0x80020006u);
 assert(vn_import_trace_field(0,8)==VX_MEMBLOCK_BAD_OPTIONS_ADDRESS);
 /* The next valid request must not inherit the earlier failure reason. */
 r[0]=base+12;r[1]=0x0c20d060;r[2]=4096;r[3]=0;
 assert((int32_t)vn_import(0xB9D5EBDE,r,memory,sizeof memory)>0);
 assert(vn_import_trace_field(1,8)==VX_MEMBLOCK_OK);
 assert(vn_import_trace_field(0,8)==VX_MEMBLOCK_BAD_OPTIONS_ADDRESS);
 vx_runtime_shutdown();return 0;
}'''
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / 'probe.c').write_text(source)
            sources = [ROOT / 'runtime' / name for name in (
                'vita_runtime.c', 'vitanx_dynamic.c', 'vitanx_devices.c',
                'vitanx_format.c', 'vitanx_memory.c')]
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'runtime'), str(directory / 'probe.c'),
                            *map(str, sources), '-o', str(directory / 'probe')],
                           capture_output=True, text=True, check=True)
            subprocess.run([str(directory / 'probe')], capture_output=True,
                           text=True, check=True, timeout=5)
