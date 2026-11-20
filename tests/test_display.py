"""Bounded SceDisplay ABI/high-address validation and actual GPU pixel tests."""
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(platform.system()=='Darwin' and shutil.which('clang'),'macOS Clang required')
class DisplayTests(unittest.TestCase):
    def probe(self,source):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'probe.c').write_text(source)
            command=['clang','-fobjc-arc','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),str(ROOT/'runtime/vita_metal.m'),str(ROOT/'runtime/vita_display.m'),str(ROOT/'runtime/vita_frame.c'),str(d/'probe.c'),'-framework','Foundation','-framework','Metal','-o',str(d/'probe')]
            subprocess.run(command,check=True,capture_output=True)
            return subprocess.run([str(d/'probe')],capture_output=True,text=True,timeout=15)

    def test_metadata_pointer_bounds_and_configuration(self):
        result=self.probe(r'''
#include "vita_display.h"
#include <assert.h>
#include <string.h>
static void word(uint8_t*p,uint32_t value){memcpy(p,&value,4);}
int main(void){
 uint8_t mem[1024]={0};uint32_t r[16]={0},out=99;const uint32_t base=0x81000000;
 assert(!vx_display_configure(120,60,3840,2160));
 assert(vx_display_configure(0,60,0,0)==-1);assert(vx_display_configure(60,60,3840,0)==-1);
 assert(vx_display_set_filter(2)==-1);assert(!vx_display_set_filter(1));
 assert(!vx_display_import(0xffffffff,r,mem,sizeof mem,base,&out)&&out==99);
 r[0]=base+1022;assert(vx_display_import(0xa08ca60d,r,mem,sizeof mem,base,&out)&&out==0x80290002);
 r[0]=base-1;assert(vx_display_import(0xa08ca60d,r,mem,sizeof mem,base,&out)&&out==0x80290002);
 r[0]=base+32;assert(vx_display_import(0xa08ca60d,r,mem,sizeof mem,base,&out)&&!out);
 float hz;memcpy(&hz,mem+32,4);assert(hz==120);
 r[0]=base+32;r[1]=base+36;assert(vx_display_import(0x8848addd,r,mem,sizeof mem,base,&out)&&!out);
 uint32_t value;memcpy(&value,mem+32,4);assert(value==960);memcpy(&value,mem+36,4);assert(value==544);
 uint32_t fb[]={24,base+128,2,0,2,2};memcpy(mem+32,fb,sizeof fb);r[0]=base+32;r[1]=2;
 assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&out)&&out==0x80290006);
 r[1]=0;word(mem+32,20);assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&out)&&out==0x80290001);
 word(mem+32,24);word(mem+44,1);assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&out)&&out==0x80290003);
 word(mem+44,0);word(mem+40,1);assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&out)&&out==0x80290004);
 word(mem+40,2);word(mem+36,base+1016);assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&out)&&out==0x80290002);
 r[0]=base+32;assert(vx_display_import(0x42ae6bbc,r,mem,sizeof mem,base,&out)&&out==0x80290007);
 vx_display_shutdown();return 0;
}''')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_framebuffer_pixels_and_filtering(self):
        result=self.probe(r'''
#include "vita_display.h"
#include <assert.h>
#include <string.h>
int main(void){
 uint8_t mem[1024]={0};uint32_t r[16]={0},out;const uint32_t base=0x81000000;
 uint32_t fb[]={24,base+128,2,0,2,2};memcpy(mem+32,fb,sizeof fb);
 uint8_t pixels[]={255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255};memcpy(mem+128,pixels,sizeof pixels);
 assert(!vx_display_configure(60,60,4,4));r[0]=base+32;
 assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&out));if(out==0x80290009)return 77;assert(!out);
 uint8_t rgba[64];assert(!vx_display_readback(rgba,sizeof rgba));assert(!memcmp(rgba,pixels,4));assert(!memcmp(rgba+60,pixels+12,4));
 r[0]=base+64;uint32_t size=24;memcpy(mem+64,&size,4);assert(vx_display_import(0x42ae6bbc,r,mem,sizeof mem,base,&out)&&!out);assert(!memcmp(mem+64,fb,24));
 assert(!vx_display_set_filter(1));r[0]=base+32;assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&out)&&!out);assert(!vx_display_readback(rgba,sizeof rgba));
 assert(rgba[20]>0&&rgba[21]>0&&rgba[22]>0); /* interpolation differs from nearest red */
 r[0]=0;assert(vx_display_import(0x7a410b64,r,mem,sizeof mem,base,&out)&&!out);assert(!vx_display_readback(rgba,sizeof rgba));assert(!rgba[0]&&!rgba[1]&&!rgba[2]&&rgba[3]==255);
 vx_display_shutdown();return 0;
}''')
        if result.returncode==77:self.skipTest('Metal unavailable in sandbox; run outside sandbox for pixel evidence')
        self.assertEqual(result.returncode,0,result.stderr)
