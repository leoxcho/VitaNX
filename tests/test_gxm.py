"""Actual GXM transfer ABI tests; GPU pixels require a real Metal device."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest
import json
import os
import re

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(platform.system()=='Darwin' and shutil.which('clang'),'macOS Clang required')
class GxmTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.directory.cleanup)
        root=Path(cls.directory.name);source=root/'probe.c';cls.binary=root/'probe'
        source.write_text(r'''
#include "vita_gxm.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned char mem[16384];
static const unsigned base=0x81000000;
static void word(unsigned offset,unsigned v){for(int i=0;i<4;i++)mem[offset+i]=(unsigned char)(v>>(8*i));}
static unsigned call(unsigned nid,const unsigned *args,unsigned count){
 unsigned r[16]={0},out=0xfeed;for(unsigned i=0;i<count&&i<4;i++)r[i]=args[i];
 r[13]=base+256;for(unsigned i=4;i<count;i++)word(256+(i-4)*4,args[i]);
 assert(vx_gxm_import(nid,r,mem,sizeof mem,base,&out));return out;
}
static void init(void){unsigned a[]={base+64};word(80,0x40000);assert(!call(0xb0f1e4ec,a,1));}
static void map(unsigned addr,unsigned attr){unsigned a[]={base+addr,4096,attr};assert(!call(0xc61e34fc,a,3));}
int main(int argc,char **argv){
 unsigned a[20]={0};(void)argc;
 vx_gxm_readiness ready;vx_gxm_get_readiness(&ready);assert(!ready.initialize_calls&&!ready.initializations&&!ready.initialized&&!ready.registration_calls);
 /* Synthetic GXP metadata: only structural/API behavior, not a real shader. */
 memcpy(mem+1024,"GXP\0",4);mem[1028]=1;mem[1029]=4;
 word(1032,208);word(1044,1|8|16|32);word(1060,1);word(1064,136);
 word(1084,1);word(1088,96);word(1124,4);
 word(1200,16);memcpy(mem+1216,"position",9);
 a[0]=base+1024;
 assert(!call(0xed8b6c69,a,1));assert(call(0xbf5e2090,a,1)==208);
 assert(call(0x04bb3c59,a,1)==1&&call(0xd5d5fccd,a,1)==1);
 assert(call(0x8fa3f9c3,a,1)==4&&call(0x029b4f1c,a,1)==1);
 assert(call(0x89613ef2,a,1)==1&&call(0xe63c53d8,a,1)==1);
 word(1088,0xfffffff0);assert(call(0xed8b6c69,a,1)==0x805b0003);word(1088,96);
 word(1064,120);assert(call(0xed8b6c69,a,1)==0x805b0003);word(1064,136);
 word(1200,0x7fffffff);assert(call(0xed8b6c69,a,1)==0x805b0003);word(1200,16);
 mem[1029]=5;assert(!call(0xed8b6c69,a,1));mem[1029]=6;assert(call(0xed8b6c69,a,1)==0x805b0009);mem[1029]=4;
 word(1032,0x10000000);assert(call(0xed8b6c69,a,1)==0x805b0003);word(1032,208);
 a[0]=base+sizeof(mem)-4;assert(call(0xed8b6c69,a,1)==0x805b0004);

 unsigned r[16]={0},out=123;
 assert(!vx_gxm_import(0xdeadbeef,r,mem,sizeof mem,base,&out)&&out==123);
 assert(call(0x45229c39,a,0)==0x805b0000);
 a[0]=base+64;word(80,0x40000);word(72,base+123);
 assert(call(0xb0f1e4ec,a,1)==0x805b0003);word(72,0);init();
 assert(call(0xb0f1e4ec,a,1)==0x805b0001);
 vx_gxm_get_readiness(&ready);assert(ready.initialize_calls==3&&ready.initializations==1&&ready.initialized);
 assert(call(0x2b528462,a,1)==0x805b0004);
 vx_gxm_get_readiness(&ready);assert(ready.registration_calls==1);
 a[0]=base+4097;a[1]=4096;a[2]=3;assert(call(0xc61e34fc,a,3)==0x805b0005);
 a[0]=base+4096;a[2]=4;assert(call(0xc61e34fc,a,3)==0x805b0003);
 a[0]=base+16384;a[2]=3;assert(call(0xc61e34fc,a,3)==0x805b0004);
 map(4096,3);map(8192,3);
 a[0]=base+4096;assert(call(0xc61e34fc,a,3)==0x805b0003);
 unsigned fill[]={0x11223344,0x60000,base+4096,1,1,3,2,20,0,0,0};
 fill[9]=1;assert(call(0x69ddff5e,fill,11)==0x805b0009);fill[9]=0;
 fill[7]=0xffffffff;assert(call(0x69ddff5e,fill,11)==0x805b0003);fill[7]=20;
 fill[4]=0xffffffff;assert(call(0x69ddff5e,fill,11)==0x805b0004);fill[4]=1;
 fill[3]=4;assert(call(0x69ddff5e,fill,11)==0x805b0003);fill[3]=1;
 fill[2]=base+12280;assert(call(0x69ddff5e,fill,11)==0x805b0004);fill[2]=base+4096;
 r[13]=base+sizeof(mem)-4;assert(vx_gxm_import(0x69ddff5e,r,mem,sizeof mem,base,&out)&&out==0x805b0004);
 unsigned copy[]={3,2,0,0,0,0x60000,0,base+4096,1,1,20,0x60000,0,base+4096,1,1,20,0,0,0};
 assert(call(0x62312bf8,copy,20)==0x805b0009);copy[13]=base+8192;
 copy[12]=0x800000;assert(call(0x62312bf8,copy,20)==0x805b0009);copy[12]=0;
 a[0]=base+8192;assert(!call(0x828c68e8,a,1));map(8192,1);
 assert(call(0x62312bf8,copy,20)==0x805b0004);
 assert(!call(0x828c68e8,a,1));map(8192,3);
 if(!strcmp(argv[1],"gpu")){
  memset(mem+4096,0xa5,8192);
  unsigned result=call(0x69ddff5e,fill,11);
  if(result){vx_gxm_stats stats;vx_gxm_get_stats(&stats);assert(result==0x805b0017&&stats.metal_status==77);
   for(unsigned i=4096;i<12288;i++)assert(mem[i]==0xa5);vx_gxm_shutdown();return 77;}
  for(unsigned y=0;y<4;y++)for(unsigned x=0;x<20;x++){
   unsigned expected=(y>=1&&y<3&&x>=4&&x<16)?(0x11223344u>>((x%4)*8))&255:0xa5;
   assert(mem[4096+y*20+x]==expected);
  }
  copy[14]=2;copy[16]=28;assert(!call(0x62312bf8,copy,20));
  for(unsigned y=0;y<4;y++)for(unsigned x=0;x<28;x++){
   unsigned expected=(y>=1&&y<3&&x>=8&&x<20)?(0x11223344u>>((x%4)*8))&255:0xa5;
   assert(mem[8192+y*28+x]==expected);
  }
  for(unsigned bpp=1;bpp<=4;bpp*=2){
   fill[1]=bpp==1?0:bpp==2?0xf0000:0x110000;fill[3]=0;fill[4]=0;fill[5]=3;fill[6]=2;fill[7]=4*bpp;
   assert(!call(0x69ddff5e,fill,11));
   for(unsigned y=0;y<2;y++)for(unsigned x=0;x<3*bpp;x++)assert(mem[4096+y*4*bpp+x]==((0x11223344u>>((x%bpp)*8))&255));
  }
  vx_gxm_stats stats;vx_gxm_get_stats(&stats);assert(stats.fills==4&&stats.copies==1&&stats.metal_status==0);
 }
 assert(!call(0x45229c39,a,0));assert(!call(0xb627de66,a,0));
 assert(call(0x828c68e8,a,1)==0x805b0000);
 vx_gxm_get_readiness(&ready);assert(ready.initializations==1&&!ready.initialized);
 vx_gxm_shutdown();vx_gxm_get_readiness(&ready);assert(!ready.initialize_calls&&!ready.registration_calls);return 0;
}''')
        command=['clang','-Wall','-Wextra','-Werror','-fobjc-arc','-I',str(ROOT/'runtime'),
                 str(source),str(ROOT/'runtime/vita_gxm.c'),str(ROOT/'runtime/vita_metal.m'),
                 '-framework','Foundation','-framework','Metal','-o',str(cls.binary)]
        subprocess.run(command,check=True,capture_output=True)

    def test_initialization_mappings_abi_bounds_and_fail_closed_features(self):
        result=subprocess.run([self.binary,'validation'],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_gpu_fill_copy_and_guest_memory_readback(self):
        result=subprocess.run([self.binary,'gpu'],capture_output=True,timeout=15)
        if result.returncode==77:self.skipTest('Metal device unavailable; no GXM rendering evidence')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_metal_transfer_shader_compiles_offline(self):
        source=(ROOT/'runtime/vita_metal.m').read_text().split('NSString *code=',1)[1].split('NSError *error=',1)[0]
        shader=''.join(json.loads(literal.lstrip('@')) for literal in re.findall(r'@?"(?:[^"\\]|\\.)*"',source))
        path=Path(self.directory.name)/'transfer.metal';path.write_text(shader)
        result=subprocess.run(([os.environ['VX_METAL_COMPILER']] if os.environ.get('VX_METAL_COMPILER') else ['xcrun','metal'])+['-std=macos-metal2.0','-c',str(path),'-o',str(path.with_suffix('.air'))],capture_output=True,text=True,timeout=30)
        if result.returncode and ('missing Metal Toolchain' in result.stderr or 'cannot execute tool' in result.stderr):
            self.skipTest(result.stderr.strip())
        self.assertEqual(result.returncode,0,result.stderr)
