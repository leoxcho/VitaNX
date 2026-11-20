"""Validated GXM display queue setup against the real guest scheduler/allocator."""
from pathlib import Path
import platform,shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(platform.system()=='Darwin' and shutil.which('clang'),'macOS Clang required')
class GxmInitializationTests(unittest.TestCase):
    def test_real_queue_worker_storage_validation_and_cleanup(self):
        source=r'''
#include "vita_runtime.h"
#include "vita_gxm.h"
#include <assert.h>
#include <string.h>
static unsigned char mem[262144];
static const unsigned base=0x81000000;
static void word(unsigned off,unsigned v){memcpy(mem+off,&v,4);}
int vx_guest_target_valid(uint32_t pc){return pc==0x810067d9;}
static uint32_t call(unsigned nid,unsigned a,unsigned b,unsigned c,unsigned d){
 uint32_t r[16]={a,b,c,d};r[13]=base+4096;return vx_import(nid,r,mem,sizeof mem);
}
static void params(void){word(64,0);word(68,2);word(72,0x810067d9);word(76,16);word(80,0x1000000);}
static int resume(vx_guest_state*s,uint8_t*m,size_t n,uint32_t budget){
 (void)m;(void)n;(void)budget;assert(s->pc==0x100); /* Worker must remain dormant. */
 vx_gxm_initialize_state state;params();
 /* Resource failure must not commit initialized state or leak a guest block. */
 assert(call(0xb0f1e4ec,base+64,0,0,0)==0x805b0002);
 assert(vx_gxm_get_initialize_state(&state)==-1);
 assert(!vx_runtime_set_heap(base+8192,131072));
 word(68,17);assert(call(0xb0f1e4ec,base+64,0,0,0)==0x805b0003);params();
 word(76,0xffffffff);assert(call(0xb0f1e4ec,base+64,0,0,0)==0x805b0003);params();
 word(80,0x40001);assert(call(0xb0f1e4ec,base+64,0,0,0)==0x805b0003);params();
 word(72,0x810067d8);assert(call(0xb0f1e4ec,base+64,0,0,0)==0x805b0004);params();
 assert(vx_gxm_get_initialize_state(&state)==-1);
 unsigned char before[4096];memcpy(before,mem,sizeof before);
 assert(call(0xb0f1e4ec,base+64,0,0,0)==0);
 assert(!memcmp(before,mem,sizeof before));
 assert(!vx_gxm_get_initialize_state(&state));
 assert(state.flags==0&&state.max_pending==2&&state.callback==0x810067d9&&state.data_size==16&&state.parameter_size==0x1000000&&state.worker);
 vx_kernel_stats ks;vx_runtime_kernel_stats(&ks);assert(ks.threads_created==1);
 vx_gxm_stats gs;vx_gxm_get_stats(&gs);assert(gs.metal_status==0&&!gs.draws&&!gs.scenes);
 /* Guest mutating its parameter struct cannot mutate retained configuration. */
 word(72,0);assert(!vx_gxm_get_initialize_state(&state)&&state.callback==0x810067d9);
 assert(call(0xb0f1e4ec,base+64,0,0,0)==0x805b0001);
 /* Real reserved worker stack cannot overlap the next guest allocation. */
 strcpy((char*)mem+512,"check");
 unsigned allocation=call(0xb9d5ebde,base+512,0x0c20d060,65536,0);assert((int)allocation>0);
 assert(!call(0xb8ef5818,allocation,base+516,0,0));
 unsigned address;memcpy(&address,mem+516,4);assert(address==base+8192+65536);
 assert(!call(0xa91e15ee,allocation,0,0,0));
 unsigned worker=state.worker;assert(!call(0xb627de66,0,0,0,0));
 assert(vx_gxm_get_initialize_state(&state)==-1);
 assert(call(0x1bbde3d9,worker,0,0,0)==0x80028021);
 assert(call(0xa33b99d1,base+8192,65536,0,0)==0x80024501);
 /* Reinitialize, then shutdown: both lifecycle paths release the reservation. */
 params();assert(!call(0xb0f1e4ec,base+64,0,0,0));vx_gxm_shutdown();
 assert(call(0xa33b99d1,base+8192,65536,0,0)==0x80024501);
 return 0;
}
int main(void){
 vx_runtime_set_memory_base(base);assert(!vx_runtime_set_heap(base+8192,4096));params();
 assert(call(0xb0f1e4ec,base+64,0,0,0)==0x805b0017); /* No active guest scheduler. */
 vx_guest_state s={0};s.pc=0x100;s.fpscr=0x0800009f;
 assert(!vx_runtime_run(&s,mem,sizeof mem,resume));assert(s.fpscr==0x0800009f);
 vx_runtime_shutdown();return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'probe.c').write_text(source)
            result=subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DVX_ENABLE_GXM','-fobjc-arc','-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),str(ROOT/'runtime/vita_gxm.c'),str(ROOT/'runtime/vita_metal.m'),'-framework','Foundation','-framework','Metal','-o',str(p/'probe')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(p/'probe')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
