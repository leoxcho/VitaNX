"""Guest scene ABI regression with a recording backend. NOT GPU pixel evidence."""
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest
from vitaxnative.gxm_catalog import write_catalog

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('clang') and platform.system()=='Darwin','Clang required')
class SceneAbiTests(unittest.TestCase):
    def test_genuine_scene_imports_remain_launcher_conversion_candidates(self):
        from vitaxnative.workflow import compatibility
        for source in ('gxm-cube-sdk-fill-20261104','gxm-texture-sdk-20261104','gxm-depth-sdk-fill-20261104','gxm-depth-load-sdk-final-20261104','gxm-stencil-sdk-nojt-20261105'):
            report=compatibility(ROOT/'artifacts'/source/'homebrew.velf')
            self.assertTrue(report['conversion_candidate'],report)
            self.assertIn('gxm',report['required_features'])
            self.assertFalse(report['playable'])

    def test_guest_scene_commands_bounds_bindings_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            write_catalog(ROOT/'artifacts/gxm-scene-assets-20261101',d/'catalog.h')
            source=d/'probe.c';binary=d/'probe'
            source.write_text(r'''
#include "vita_gxm.h"
#include "vita_metal.h"
#include "catalog.h"
#include <assert.h>
#include <string.h>
static unsigned char mem[65536];static const unsigned base=0x81000000;
static int stencil_active,stencil_failure,stencil_uploads,stencil_states;
static int unavailable,draw_failure,read_failure,pipelines,draws,textures,depth_active,depth_failure,upload_failure,depth_uploads;
int vx_metal_create(uint32_t w,uint32_t h,vx_metal **out){assert(w==64&&h==64);if(unavailable)return 77;*out=(vx_metal *)1;return 0;}
int vx_metal_gxp_depth_begin(vx_metal *c,int enabled,float clear){assert(c&&clear==1);depth_active=enabled;return 0;}
int vx_metal_gxp_depth_upload(vx_metal *c,const uint8_t *p,size_t n,size_t stride){assert(c&&depth_active&&p==mem+32768&&n==16384&&stride==256);depth_uploads++;return upload_failure?-4:0;}
int vx_metal_gxp_depth_state(vx_metal *c,unsigned f,int w){assert(c&&depth_active&&f==1&&w==1);return 0;}
int vx_metal_gxp_depth_readback(vx_metal *c,float *p,size_t n){assert(c&&depth_active&&n==4096);for(size_t i=0;i<n;i++)p[i]=.25f;return depth_failure?-4:0;}
int vx_metal_gxp_stencil_begin(vx_metal *c,int enabled,unsigned clear){assert(c&&clear==0);stencil_active=enabled;return 0;}
int vx_metal_gxp_stencil_upload(vx_metal *c,const uint8_t *p,size_t n,size_t stride){assert(c&&stencil_active&&p==mem+49152&&n==4096&&stride==64);stencil_uploads++;return upload_failure?-4:0;}
int vx_metal_gxp_stencil_readback(vx_metal *c,uint8_t *p,size_t n){assert(c&&stencil_active&&n==4096);memset(p,0x66,n);return stencil_failure?-4:0;}
int vx_metal_gxp_stencil_face_state(vx_metal *c,unsigned face,unsigned f,unsigned fail,unsigned df,unsigned pass,unsigned rm,unsigned wm,unsigned ref){assert(c&&face<2&&f==face+1&&fail==2&&df==3&&pass==4&&rm==15&&wm==240&&ref==face+5);stencil_states++;return 0;}
void vx_metal_destroy(vx_metal *c){(void)c;}
int vx_metal_resize(vx_metal *c,uint32_t w,uint32_t h){assert(c&&w==64&&h==64);return 0;}
int vx_metal_upload(vx_metal *c,const uint8_t *p,size_t n,size_t s,uint32_t f){assert(c&&p==mem+16384&&n==16384&&s==256&&f==0);return 0;}
int vx_metal_gxp_pipeline(vx_metal *c,const char *v,const char *f,const vx_gxp_attribute *a,size_t n,size_t s,size_t vw,size_t fw,uint32_t mask,char *diag,size_t cap){
 (void)diag;(void)cap;assert(c&&strstr(v,"vx_gxp_v")&&strstr(f,"vx_gxp_f")&&a[0].components==4&&a[0].offset==0&&n==1&&s==16&&vw==4&&fw==0&&!mask);pipelines++;return 0;}
int vx_metal_gxp_upload_texture(vx_metal *c,const uint8_t *p,size_t n,uint32_t w,uint32_t h,size_t s,int linear){assert(c&&p==mem+32768&&n==16&&w==2&&h==2&&s==8&&!linear);textures++;return 0;}
int vx_metal_gxp_draw_load(vx_metal *c,const void *v,size_t bytes,size_t count,const uint32_t *vu,size_t vw,const uint32_t *fu,size_t fw){
 (void)fu;assert(c&&bytes==48&&count==3&&vw==4&&fw==0&&vu[0]==0x3f800000);const unsigned *p=v;assert(p[0]==3&&p[4]==1&&p[8]==2);draws++;return draw_failure?-4:0;}
int vx_metal_readback(vx_metal *c,uint8_t *p,size_t n){assert(c&&n==16384);memset(p,0x55,n);return read_failure?-4:0;}
int vx_metal_transfer_fill(vx_metal *c,uint32_t color,unsigned b,uint32_t w,uint32_t h,uint8_t *p,size_t n,size_t s){(void)c;(void)color;(void)b;(void)w;(void)h;(void)p;(void)n;(void)s;assert(0);return -1;}
int vx_metal_transfer_copy(vx_metal *c,unsigned b,uint32_t w,uint32_t h,const uint8_t *p,size_t pn,size_t ps,uint8_t *q,size_t qn,size_t qs){(void)c;(void)b;(void)w;(void)h;(void)p;(void)pn;(void)ps;(void)q;(void)qn;(void)qs;assert(0);return -1;}
static void word(unsigned offset,unsigned value){memcpy(mem+offset,&value,4);}
static unsigned get(unsigned offset){unsigned v;memcpy(&v,mem+offset,4);return v;}
static unsigned call(unsigned nid,unsigned *a,unsigned count){unsigned r[16]={0},out=0xdead;
 for(unsigned i=0;i<4&&i<count;i++)r[i]=a[i];r[13]=base+512;
 for(unsigned i=4;i<count;i++)word(512+(i-4)*4,a[i]);assert(vx_gxm_import(nid,r,mem,sizeof mem,base,&out));return out;}
#define CALL(n,...) call(n,(unsigned[]){__VA_ARGS__},sizeof((unsigned[]){__VA_ARGS__})/4)
int main(void){
 assert(!vx_install_gxm_catalog());word(80,0x40000);
 assert(CALL(0xe84ce5b4,base+128,base+200)==0x805b0000);
 assert(!CALL(0xb0f1e4ec,base+64));assert(vx_gxm_set_catalog(0,0)==-1);
 assert(!CALL(0xc61e34fc,base+4096,61440,3));
 word(128,base+12288);word(132,4096);word(144,base+8192);word(148,16);assert(!CALL(0xe84ce5b4,base+128,base+200));unsigned ctx=get(200);
 assert(CALL(0xe84ce5b4,base+128,base+200)==0x805b0009);
 assert(CALL(0x895df2e9,ctx,1,base+4096)==0x805b0009);
 assert(CALL(0x895df2e9,ctx+1,0,base+4096)==0x805b0004);
 assert(CALL(0x895df2e9,ctx,0,base+65536)==0x805b0004);
 assert(!CALL(0x895df2e9,ctx,0,base+4096));assert(!CALL(0xc697cae5,ctx,base+8192));word(8192,0x3f800000);
 word(304,1);assert(CALL(0x05032658,base+300,base+204)==0x805b0009);word(304,0);
 assert(!CALL(0x05032658,base+300,base+204));unsigned patch=get(204);
 const vx_gxm_shader *v=&vx_gxm_catalog[1],*f=&vx_gxm_catalog[0];
 memcpy(mem+1024,v->gxp,v->size);memcpy(mem+2048,f->gxp,f->size);
 mem[1024+64+get(1024+64)]^=1;assert(CALL(0x2b528462,patch,base+1024,base+208)==0x805b0009);mem[1024+64+get(1024+64)]^=1;
 assert(!CALL(0x2b528462,patch,base+1024,base+208));unsigned vi=get(208);
 assert(!CALL(0x2b528462,patch,base+2048,base+212));unsigned fi=get(212);
 mem[604]=9;mem[605]=4;word(608,16);
 assert(!CALL(0xb7bba6d5,patch,vi,base+600,1,base+608,1,base+216));unsigned vp=get(216);
 mem[604]=10;assert(CALL(0xb7bba6d5,patch,vi,base+600,1,base+608,1,base+216)==0x805b0009);mem[604]=9;
 assert(CALL(0x4ed2e49d,patch,vi,1,0,0,base+1024,base+220)==0x805b0003);
 assert(!CALL(0x4ed2e49d,patch,fi,1,0,0,base+1024,base+220));unsigned fp=get(220);
 assert(!CALL(0x31ff8abd,ctx,vp));assert(!CALL(0xad2f48d9,ctx,fp));
 word(704,64|(64<<16));word(708,1);word(716,0xffffffff);
 assert(!CALL(0x207af96b,base+700,base+224));unsigned target=get(224);
 assert(!CALL(0xed0f6e25,base+768,0,0,0,0,64,64,64,base+16384));
 assert(CALL(0xed0f6e25,base+768,0,0,0,0,64,64,63,base+16384)==0x805b0003);
 assert(CALL(0x97118913,ctx,base+228)==0x805b0003);
 assert(CALL(0xbc059afc,ctx,0,0,base+4200,3)==0x805b0003);
 unavailable=1;assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,0)==0x805b0017);
 unavailable=0;assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0009);
 assert(CALL(0xa41db0d6,base+65520)==0x805b0004);
 assert(CALL(0xa41db0d6,base+841)==0x805b0004);
 assert(CALL(0x082200e1,base+840)==0x805b0009);
 assert(!CALL(0xa41db0d6,base+840));assert(!CALL(0x082200e1,base+840));
 word(844,1);assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0009);word(844,0);
 assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+65520)==0x805b0004);
 assert(!CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840));
 assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,0)==0x805b0003);
 assert(!CALL(0x97118913,ctx,base+228));assert(get(228)==base+8192);
 word(228,0xdeadbeef);assert(CALL(0x97118913,ctx,base+228)==0x805b0002);assert(get(228)==0xdeadbeef);
 assert(CALL(0x7b1fabb6,ctx,base+228)==0x805b0002);
 assert(CALL(0x0733d8ae,ctx)==0x805b0003);
 assert(CALL(0xeddc5fb2,ctx)==0x805b0003);assert(CALL(0xac1ff2da,patch,vp)==0x805b0003);
 word(4096,1);word(4112,2);word(4128,3);mem[4200]=2;mem[4202]=0;mem[4204]=1;
 assert(CALL(0xbc059afc,ctx,0,0,base+65534,3)==0x805b0004);
 assert(CALL(0xbc059afc,ctx,0,0,base+4200,4)==0x805b0003);
 assert(CALL(0xbc059afc,ctx,0,0x01000000,base+4200,3)==0x805b0009);
 mem[4200]=255;mem[4201]=255;assert(CALL(0xbc059afc,ctx,0,0,base+4200,3)==0x805b0004);mem[4200]=2;mem[4201]=0;
 assert(!CALL(0xbc059afc,ctx,0,0,base+4200,3));assert(!CALL(0xbc059afc,ctx,0,0,base+4200,3));assert(pipelines==1&&draws==2);
 assert(CALL(0xfe300e2f,ctx,base+400,0)==0x805b0009);
 read_failure=1;assert(CALL(0xfe300e2f,ctx,0,0)==0x805b0017);assert(mem[16384]==0);
 read_failure=0;assert(!CALL(0xfe300e2f,ctx,0,0));assert(mem[16384]==0x55);assert(!CALL(0x0733d8ae,ctx));
 assert(CALL(0xfe300e2f,ctx,0,0)==0x805b0003);
 assert(CALL(0xca9d41d1,base+840,0x66000,0,64,base+32768,0)==0x805b0004);
 assert(CALL(0xca9d41d1,base+840,0x44000,0,63,base+32768,0)==0x805b0003);
 assert(CALL(0xca9d41d1,base+840,0x44000,0,64,base+65536,0)==0x805b0004);
 assert(!CALL(0xca9d41d1,base+840,0x44000,0,64,base+32768,0));assert(CALL(0x082200e1,base+840)==1);
 /* Only S0 carries background floats. Integer R1 is deliberately poison;
    invalid operations preserve both destination memory and all FP registers. */
 unsigned rr[16]={0},ff[64],oo=0;for(unsigned i=0;i<64;i++)ff[i]=0x12340000+i;
 rr[0]=base+840;rr[1]=0xdeadbeef;ff[0]=0x3f000000;
 assert(vx_gxm_float_import(0x32f280f0,rr,ff,mem,sizeof mem,base,&oo)&&!oo);assert(get(852)==0x3f000000);
 ff[0]=0;assert(vx_gxm_float_import(0x269b56be,rr,ff,mem,sizeof mem,base,&oo)&&!oo);assert(ff[0]==0x3f000000);
 for(unsigned i=1;i<64;i++)assert(ff[i]==0x12340000+i);
 const unsigned bad[]={0x7fc00000,0x7f800000,0xbf000000,0x3fc00000};
 for(unsigned i=0;i<4;i++){ff[0]=bad[i];assert(vx_gxm_float_import(0x32f280f0,rr,ff,mem,sizeof mem,base,&oo)&&oo==0x805b0003);assert(get(852)==0x3f000000&&ff[0]==bad[i]);}
 rr[0]=base+65520;ff[0]=0x12345678;assert(vx_gxm_float_import(0x269b56be,rr,ff,mem,sizeof mem,base,&oo)&&oo==0x805b0004&&ff[0]==0x12345678);
 rr[0]=base+840;ff[0]=0x3f800000;assert(vx_gxm_float_import(0x32f280f0,rr,ff,mem,sizeof mem,base,&oo)&&!oo);
 assert(CALL(0x14bd831f,ctx,1)==0x805b0003);assert(!CALL(0x14bd831f,ctx,0x400000));
 assert(CALL(0xf32cbf34,ctx,2)==0x805b0003);assert(!CALL(0xf32cbf34,ctx,0));
 word(848,32);assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0003);word(848,64);
 word(844,base+16384);assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0003);word(844,base+32768);
 assert(!CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840));
 assert(!CALL(0xbc059afc,ctx,0,0,base+4200,3));
 mem[16384]=0x33;depth_failure=1;assert(CALL(0xfe300e2f,ctx,0,0)==0x805b0017);assert(get(32768)==0);assert(mem[16384]==0x33);
 depth_failure=0;assert(!CALL(0xfe300e2f,ctx,0,0));assert(get(32768)==0x3e800000);

 /* Enabling/disabling force controls preserves independent bits. Failed load
    must not open a scene or change guest storage; retry then succeeds. */
 assert(!CALL(0x2f5cc20c,base+840));assert(!CALL(0x544aa05a,base+840));
 assert(CALL(0x0c44acd7,base+840,4)==0x805b0003);assert(get(856)==0);
 assert(!CALL(0x0c44acd7,base+840,2));assert(!CALL(0x12aaa7af,base+840,4));
 assert(CALL(0x2f5cc20c,base+840)==2);assert(CALL(0x544aa05a,base+840)==4);
 assert(!CALL(0x12aaa7af,base+840,0));assert(CALL(0x2f5cc20c,base+840)==2);
 upload_failure=1;mem[16384]=0x77;unsigned prior=get(32768);
 assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0017);
 assert(CALL(0xfe300e2f,ctx,0,0)==0x805b0003);assert(mem[16384]==0x77&&get(32768)==prior);
 upload_failure=0;assert(!CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840));
 assert(!CALL(0xfe300e2f,ctx,0,0));assert(depth_uploads==2);
 assert(!CALL(0x0c44acd7,base+840,0));assert(!CALL(0x2f5cc20c,base+840));
 /* Checked guest stencil state, disjoint spans and atomic third-read failure. */
 assert(CALL(0xb8645a9a,ctx,1,2,3,4,15,240)==0x805b0003);
 assert(CALL(0x8fa6fe44,ctx,256)==0x805b0003);
 assert(!CALL(0xb8645a9a,ctx,1u<<25,2,3,4,15,240));
 assert(!CALL(0x1a68c8d2,ctx,2u<<25,2,3,4,15,240));
 assert(!CALL(0x8fa6fe44,ctx,5));assert(!CALL(0x866a0517,ctx,6));
 assert(!CALL(0xca9d41d1,base+840,0x66000,0,64,base+32768,base+49152));
 assert(!CALL(0xf5d3f3e8,base+840,77));assert(CALL(0xaafc062b,base+840)==77);
 assert(!CALL(0xf5d3f3e8,base+840,0));
 word(856,base+32768);assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0003);
 word(856,base+16384);assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0003);
 word(856,base+65536);assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0004);
 word(856,base+49152);assert(!CALL(0x0c44acd7,base+840,2));
 upload_failure=1;assert(CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840)==0x805b0017);
 upload_failure=0;assert(!CALL(0x8734ff4e,ctx,0,target,0,0,0,base+768,base+840));
 assert(stencil_uploads==1);assert(!CALL(0xbc059afc,ctx,0,0,base+4200,3));assert(stencil_states==2);
 mem[16384]=0x12;mem[32768]=0x34;mem[49152]=0x56;stencil_failure=1;
 assert(CALL(0xfe300e2f,ctx,0,0)==0x805b0017);
 assert(mem[16384]==0x12&&mem[32768]==0x34&&mem[49152]==0x56);
 stencil_failure=0;assert(!CALL(0xfe300e2f,ctx,0,0));assert(mem[16384]==0x55&&get(32768)==0x3e800000&&mem[49152]==0x66);
 assert(!CALL(0x4811aecb,base+900,base+32768,0x0c000000,2,2,1));
 assert(CALL(0x4811aecb,base+900,base+32768,0x0c000000,2,2,2)==0x805b0009);
 assert(!CALL(0x29c34df5,ctx,0,base+900));assert(CALL(0x29c34df5,ctx,1,base+900)==0x805b0009);
 assert(!CALL(0xfa695fd7,base+900,1));assert(CALL(0x29c34df5,ctx,0,base+900)==0x805b0009);
 assert(!CALL(0x416764e3,base+900,1));assert(!CALL(0x29c34df5,ctx,0,base+900));
 assert(CALL(0x4281763e,base+900,0)==0x805b0009);
 assert(!CALL(0xac1ff2da,patch,vp));assert(!CALL(0xbe2743d1,patch,fp));assert(!CALL(0xf103af8a,patch,vi));assert(!CALL(0xf103af8a,patch,fi));
 assert(!CALL(0xeaa5b100,patch));assert(!CALL(0x0b94c50a,target));assert(!CALL(0xeddc5fb2,ctx));
 assert(CALL(0x895df2e9,ctx,0,base+4096)==0x805b0004);
 vx_gxm_stats stats;vx_gxm_get_stats(&stats);assert(stats.draws==4&&stats.scenes==4);
 assert(!CALL(0xb627de66,0));vx_gxm_shutdown();return 0;
}
''')
            result=subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-I',str(ROOT/'runtime'),'-I',str(d),str(source),str(ROOT/'runtime/vita_gxm.c'),'-o',str(binary)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            result=subprocess.run([binary],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
