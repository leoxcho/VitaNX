"""Controller guest ABI tests using a deterministic host input provider."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('clang'),'Clang required')
class InputRuntimeTests(unittest.TestCase):
    def test_controller_bounds_layout_sampling_and_count(self):
        source=r'''
#include "vita_runtime.h"
#include "vita_display.h"
#include "vita_window.h"
#include <assert.h>
#include <string.h>
static uint8_t memory[256];static uint32_t r[16];static int close_requested;
int vx_display_input_state(vx_window_input *out){*out=(vx_window_input){.buttons=0x4110,.ext_buttons=0x402,.left_trigger=33,.lx=3,.ly=255,.rx=42,.ry=0,.connected=1,.close_requested=close_requested,.touch_x={1919,42},.touch_y={1087,77},.touch_down={1,1},.touch_id={17,4}};return 0;}
void vx_display_shutdown(void){}
int vx_display_import(uint32_t n,uint32_t *r,uint8_t *m,size_t s,uint32_t b,uint32_t *out){(void)n;(void)r;(void)m;(void)s;(void)b;(void)out;return 0;}
static uint32_t call(uint32_t nid,uint32_t a,uint32_t b,uint32_t c){r[0]=a;r[1]=b;r[2]=c;return vx_import(nid,r,memory,sizeof memory);}
int main(void){
 const uint32_t base=0x81000000u;vx_runtime_set_memory_base(base);
 size_t count=0;const vx_import_capability *caps=vx_runtime_import_capabilities(&count);
 assert(count>=42);unsigned window_count=0;uint32_t window_nids[]={VX_WINDOW_IMPORT_NIDS};
 for(size_t i=0;i<count;i++){
  assert(caps[i].name&&strcmp(caps[i].name,"unknown")&&caps[i].limits);
  if(!strcmp(caps[i].feature,"window")){
   int found=0;for(unsigned j=0;j<sizeof window_nids/sizeof *window_nids;j++)if(caps[i].nid==window_nids[j])found=1;
   assert(found);window_count++;
  }
 }
 assert(window_count==sizeof window_nids/sizeof *window_nids);
 assert(call(0xA9C3CED6,0,base+64,1)==1);
 assert(memory[72]==0x10&&memory[73]==0x41);assert(memory[76]==128&&memory[79]==128);
 assert(memory[80]==255&&memory[90]==255&&memory[91]==0);
 assert(call(0xA497B150,1,0,0)==0);
 assert(call(0xEC752AAF,base+32,0,0)==0&&memory[32]==1);
 assert(call(0xA9C3CED6,0,base+64,64)==1);
 assert(memory[76]==3&&memory[77]==255&&memory[78]==42&&memory[79]==0);
 assert(call(0xA9C3CED6,1,base+64,1)==0x80020005u);
 assert(call(0xA9C3CED6,0,base+64,65)==0x80020005u);
 assert(call(0xA9C3CED6,0,base+64,0)==0x80020005u);
 assert(call(0xA9C3CED6,0,base-1,1)==0x80020006u);
 assert(call(0xA9C3CED6,0,base+225,1)==0x80020006u);
 assert(call(0xEC752AAF,base+253,0,0)==0x80020006u);
 assert(call(0xA497B150,2,0,0)==1);
 assert(call(0xA497B150,3,0,0)==0x80020005u);
 assert(call(0x104ED1A7,0,base+64,1)==1&&memory[72]==0xef&&memory[73]==0xbe);
 assert(call(0xB1DC4378,2,0,0)==0);
 assert(call(0xBD27F830,base+32,0,0)==0&&memory[32]==2);
 assert(call(0x860BF292,0,base+64,1)==1);
 assert(memory[72]==0x12&&memory[73]==0x44&&memory[76]==3&&memory[84]==33);
 assert(call(0x15F81E8C,1,base+64,1)==0);
 assert(call(0x324F1B66,base+32,0,0)==0&&memory[32]==1&&memory[33]==0);
 assert(call(0x67E7AB83,0,base+64,1)==1);assert(call(0x67E7AB83,0,base+64,1)==1);
 assert(call(0xFF082DF0,0,base+64,1)==1&&memory[76]==0);
 assert(!call(0x1B9C5D14,0,1,0));assert(!call(0xB18370C2,0,0,0));
 assert(call(0xFF082DF0,0,base+64,1)==1&&memory[76]==1);
 assert(memory[80]==17&&memory[81]==128&&memory[82]==0x7f&&memory[83]==7&&memory[84]==0x3f&&memory[85]==4);
 assert(!call(0x1B9C5D14,1,1,0));assert(call(0xFF082DF0,1,base+64,64)==1);
 assert(memory[80]==4&&memory[81]==0&&memory[82]==42&&memory[84]==77);
 assert(!call(0x10A2CA25,0,base+16,0));assert(memory[20]==0x7f&&memory[21]==7&&memory[22]==0x3f&&memory[23]==4);
 assert(!call(0x26531526,1,base+32,0)&&memory[32]==1);
 assert(call(0xFF082DF0,2,base+64,1)==0x80350001u);
 assert(call(0xFF082DF0,0,base+113,1)==0x80350001u);
 assert(call(0xFF082DF0,0,base+64,0)==0x80350001u);
 assert(call(0x1B9C5D14,0,2,0)==0x80350001u);
 assert(call(0x26531526,0,base+253,0)==0x80350001u);
 close_requested=1;assert(call(0xA9C3CED6,0,base+64,1)==1);
 uint32_t status=99;assert(vx_runtime_stop_requested(&status)==VX_STOP_PROCESS&&status==0);
 vx_runtime_shutdown();assert(vx_runtime_stop_requested(&status)==VX_STOP_NONE);return 0;
}'''
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);(tmp/'probe.c').write_text(source)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-DVX_ENABLE_WINDOW','-DVX_ENABLE_DISPLAY',
                            '-I',str(ROOT/'runtime'),str(tmp/'probe.c'),str(ROOT/'runtime/vita_runtime.c'),'-o',str(tmp/'probe')],
                           check=True,capture_output=True)
            subprocess.run([str(tmp/'probe')],check=True,capture_output=True,timeout=5)
