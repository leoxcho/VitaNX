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
        self._run_probe(source)

    def test_display_queue_fifo_backpressure_and_sync_lifetime(self):
        source=r'''
#include "vita_runtime.h"
#include "vita_gxm.h"
#include "vita_display.h"
#include <assert.h>
#include <string.h>
static unsigned char mem[262144];
static const uint32_t base=0x81000000;
static unsigned root_phase,callbacks;
static uint32_t first,second;
static int metal_ready;
static void put(unsigned off,uint32_t v){memcpy(mem+off,&v,4);}
static uint32_t get(unsigned off){uint32_t v;memcpy(&v,mem+off,4);return v;}
int vx_guest_target_valid(uint32_t pc){return pc==0x810067d9;}
static uint32_t call(uint32_t nid,uint32_t a,uint32_t b,uint32_t c){
 uint32_t r[16]={a,b,c};r[13]=base+4096;
 return vx_import(nid,r,mem,sizeof mem);
}
static void prepare_frame(void){
 uint32_t host=base+8000,texture=base+196608;
 put(512,host);put(516,2048);
 assert(!call(0xe84ce5b4,base+512,base+576,0));
 put(604,(4<<16)|4);put(608,1);put(616,UINT32_MAX);
 assert(!call(0x207af96b,base+600,base+624,0));
 assert(!call(0xc61e34fc,texture,4096,3));
 for(unsigned i=0;i<16;i++)put(196608+i*4,0xff563412);
 uint32_t r[16]={base+640,0,0,0};r[13]=base+4096;
 put(4096,0);put(4100,4);put(4104,4);put(4108,4);put(4112,texture);
 assert(!vx_import(0xed0f6e25,r,mem,sizeof mem));
 r[0]=get(576);r[2]=get(624);
 put(4096,0);put(4100,second);put(4104,base+640);put(4108,0);
 uint32_t result=vx_import(0x8734ff4e,r,mem,sizeof mem);
 if(result==0x805b0017)return; /* No usable Metal device in the test process. */
 assert(!result);
 assert(call(0x889ae88c,second,0,0)==0x805b0003);
 put(752,24);put(756,texture);put(760,4);put(768,4);put(772,4);
 metal_ready=1;
}
static int resume(vx_guest_state *s,uint8_t *m,size_t n,uint32_t budget){
 (void)m;(void)n;(void)budget;
 if(s->pc==0x810067d9){
  unsigned data=s->r[0]-base;
  assert(s->r[0]==s->r[13]&&!(s->r[13]&7)&&s->r[14]==UINT32_MAX);
  assert(callbacks<4&&get(data)==41+callbacks&&get(data+12)==81+callbacks);
  assert(call(0x889ae88c,second,0,0)==0x805b0003);
  if(callbacks==0&&metal_ready){
   assert(!call(0x7a410b64,base+752,0,0));
   vx_display_stats stats;vx_display_get_stats(&stats);
   assert(stats.frames_presented==1);
   uint8_t rgba[64];assert(!vx_display_readback(rgba,sizeof rgba));
   assert(rgba[0]==0x12&&rgba[1]==0x34&&rgba[2]==0x56&&rgba[3]==0xff);
  }
  if(callbacks==1)put(144,7);
  callbacks++;
  return 0;
 }
 assert(s->pc==0x100);
 switch(root_phase++){
 case 0:
  put(68,2);put(72,0x810067d9);put(76,16);put(80,0x40000);
  assert(!call(0xb0f1e4ec,base+64,0,0));
  assert(!call(0x6a6013e1,base+96,0,0));
  assert(!call(0x6a6013e1,base+100,0,0));
  first=get(96);second=get(100);
  assert(first&&second&&first!=second);
  prepare_frame();
  assert(call(0xec5c26b5,first,second,base+sizeof mem-4)==0x805b0004);
  put(112,41);put(124,81);
  assert(!call(0xec5c26b5,first,second,base+112));
  if(metal_ready)return 1;
  root_phase++;
  /* Fall through when GPU execution is unavailable. */
 case 1:
  assert(callbacks==0);
  if(metal_ready){
   put(704,base+720);put(708,0xfeed);
   assert(!call(0xfe300e2f,get(576),0,base+704));
   assert(get(720)==0xfeed);
  }
  put(112,42);put(124,82);
  assert(!call(0xec5c26b5,second,second,base+112));
  assert(call(0xb627de66,0,0,0)==0x805b0003);
  put(112,43);put(124,83);
  assert(!call(0xec5c26b5,first,second,base+112)); /* Sleeps until a slot is free. */
  return 1;
 case 2:
  assert(!s->r[0]&&callbacks>=2);
  put(136,base+144);put(140,7);
  assert(!call(0x9f448e79,base+136,0,0));
  put(112,44);put(124,84);
  assert(!call(0xec5c26b5,first,second,base+112));
  assert(!call(0xb98c5b0d,0,0,0)); /* Sleeps until the last callback returns. */
  return 1;
 default:
  assert(!s->r[0]&&callbacks==4);
  assert(!call(0x889ae88c,first,0,0));
  assert(!call(0x889ae88c,second,0,0));
  assert(!call(0xb627de66,0,0,0));
  return 0;
 }
}
int main(void){
 vx_runtime_set_memory_base(base);
 assert(!vx_runtime_set_heap(base+8192,131072));
 vx_guest_state s={0};s.pc=0x100;
 assert(!vx_runtime_run(&s,mem,sizeof mem,resume));
 vx_kernel_stats stats;vx_runtime_kernel_stats(&stats);
 assert(root_phase==4&&callbacks==4&&stats.waits==2);
 vx_runtime_shutdown();return 0;
}
'''
        self._run_probe(source,display=True)

    def test_deferred_uniform_allocator_returns_to_guest_import(self):
        source=r'''
#include "vita_runtime.h"
#include "vita_gxm.h"
#include <assert.h>
#include <string.h>
static uint8_t mem[16384];
static const uint32_t base=0x81000000,entry=0x81000601;
static uint32_t deferred;
static unsigned phase,allocations,vdm_allocations;
static void put(unsigned off,uint32_t v){memcpy(mem+off,&v,4);}
static uint32_t get(unsigned off){uint32_t v;memcpy(&v,mem+off,4);return v;}
int vx_guest_target_valid(uint32_t pc){return pc==entry;}
static uint32_t call(uint32_t nid,uint32_t a,uint32_t b,uint32_t c){
 uint32_t r[16]={a,b,c};r[13]=base+4096;
 return vx_import(nid,r,mem,sizeof mem);
}
static int resume(vx_guest_state *s,uint8_t *m,size_t n,uint32_t budget){
 (void)m;(void)n;(void)budget;
 if(s->pc==entry){
  assert(s->r[0]==42&&s->r[2]==s->r[13]&&!(s->r[13]&7));
  if(s->r[1]==1024){
   put(s->r[2]-base,1024);
   s->r[0]=base+9216;
   vdm_allocations++;
   return 0;
  }
  assert(s->r[1]==16);
  put(s->r[2]-base,allocations?8:32);
  s->r[0]=base+8192;
  allocations++;
  return 0;
 }
 assert(s->pc==0x100);
 switch(phase++){
 case 0:{
  put(80,0x40000);assert(!call(0xb0f1e4ec,base+64,0,0));
  assert(!call(0xc61e34fc,base+8192,4096,1));
  assert(!call(0x05032658,base+128,base+208,0));
  uint32_t patcher=get(208);
  assert(!call(0x2b528462,patcher,base+512,base+212));
  put(4104,base+216);
  assert(!call(0x4ed2e49d,patcher,get(212),0));
  put(1024,base+12288);put(1028,2048);put(1032,entry);put(1040,entry);put(1044,42);
  assert(!call(0x249d5b00,base+1024,base+220,0));
  deferred=get(220);
  assert(!call(0x944d3f83,deferred,0,0));
  return 1;
 }
 case 1:
  assert(!s->r[0]&&vdm_allocations==1);
  assert(!call(0xad2f48d9,deferred,get(216),0));
  assert(!call(0x7b1fabb6,deferred,base+224,0));
  assert(!get(224));
  return 1;
 case 2:
  assert(!s->r[0]&&allocations==1&&get(224)==base+8192);
  assert(!call(0x7b1fabb6,deferred,base+228,0));
  assert(get(228)==base+8208);
  assert(!call(0x7b1fabb6,deferred,base+232,0));
  return 1;
 default:
  assert(s->r[0]==0x805b000b&&allocations==2&&!get(232));
  assert(!call(0x36d85916,deferred,base+256,0));
  return 0;
 }
}
int main(void){
 memcpy(mem+512,"GXP",3);mem[516]=1;mem[517]=5;
 put(520,164);put(532,1);put(572,1);put(576,156-64);
 const vx_gxm_shader shader={.gxp=mem+512,.size=164,.msl="fixture",.stage=1,.uniform_words=4};
 assert(!vx_gxm_set_catalog(&shader,1));
 vx_runtime_set_memory_base(base);
 vx_guest_state state={0};state.pc=0x100;state.r[13]=base+4096;
 assert(!vx_runtime_run(&state,mem,sizeof mem,resume));
 assert(phase==4&&allocations==2&&vdm_allocations==1);
 vx_runtime_shutdown();
 return 0;
}
'''
        self._run_probe(source)

    def _run_probe(self,source,display=False):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'probe.c').write_text(source)
            display_args=['-DVX_ENABLE_DISPLAY',str(ROOT/'runtime/vita_display.m'),
                          str(ROOT/'runtime/vita_frame.c')] if display else []
            result=subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DVX_ENABLE_GXM','-fobjc-arc','-I',str(ROOT/'runtime'),str(p/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),str(ROOT/'runtime/vita_gxm.c'),str(ROOT/'runtime/vita_metal.m'),*display_args,'-framework','Foundation','-framework','Metal','-o',str(p/'probe')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([str(p/'probe')],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
