"""Native host Metal integration. This does not exercise Vita GXM/GXP code."""
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(platform.system() == 'Darwin' and shutil.which('clang'), 'macOS Clang required')
class MetalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.path = Path(cls.temporary.name)
        cls.common = ['clang', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                      '-I', str(ROOT/'runtime'), str(ROOT/'runtime/vita_metal.m'),
                      '-framework', 'Foundation', '-framework', 'Metal']
        cls.probe = cls.path/'metal-probe'
        subprocess.run(cls.common + [str(ROOT/'runtime/metal_probe.m'), '-o', str(cls.probe)],
                       check=True, capture_output=True)

    def test_cpu_bounds_before_device_access(self):
        source = self.path/'bounds.m'
        source.write_text(r'''
#include "vita_metal.h"
#include <assert.h>
int main(void){
 vx_metal *out=(vx_metal*)1;
 assert(vx_metal_create(960,544,0)==VX_METAL_INVALID);
 assert(vx_metal_create(0,544,&out)==VX_METAL_INVALID);assert(!out);
 assert(vx_metal_create(4097,544,&out)==VX_METAL_INVALID);assert(!out);
 assert(vx_metal_create(960,4097,&out)==VX_METAL_INVALID);assert(!out);
 float clear[4]={0,0,1,1};uint8_t pixel[4];
 assert(vx_metal_draw(0,0,0,clear)==VX_METAL_INVALID);
 assert(vx_metal_readback(0,pixel,sizeof pixel)==VX_METAL_INVALID);
 vx_metal_destroy(0);return 0;
}
''')
        binary = self.path/'bounds'
        subprocess.run(self.common+[str(source),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)
        for args in [('0','544'),('4097','544'),('960','-1'),('abc','544')]:
            result = subprocess.run([str(self.probe),*args],capture_output=True,timeout=5)
            self.assertEqual(result.returncode,10)

    def test_native_and_double_resolution_readback(self):
        for width,height in [(64,64),(960,544),(1920,1088)]:
            with self.subTest(width=width,height=height):
                image = self.path/f'{width}x{height}.ppm'
                result = subprocess.run([str(self.probe),str(width),str(height),str(image)],
                                        capture_output=True,timeout=20)
                if result.returncode == 77:
                    self.skipTest('Metal device unavailable; compilation and CPU bounds checked separately')
                self.assertEqual(result.returncode,0,result.stderr.decode())
                self.assertIn(f'{width}x{height} RGBA8'.encode(), result.stdout)
                prefix = f'P6\n{width} {height}\n255\n'.encode()
                data = image.read_bytes()
                self.assertTrue(data.startswith(prefix))
                pixels = data[len(prefix):]
                self.assertEqual(len(pixels),width*height*3)
                center = ((height//2)*width+width//2)*3
                self.assertEqual(pixels[center:center+3],b'\xff\0\0')
                self.assertEqual(pixels[:3],b'\0\0\xff')
                # Existing exported evidence must never be overwritten.
                repeated = subprocess.run([str(self.probe),str(width),str(height),str(image)],
                                          capture_output=True,timeout=20)
                self.assertNotEqual(repeated.returncode,0)
                self.assertEqual(image.read_bytes(),data)

    def test_cpu_framebuffer_formats_and_bounds(self):
        source=self.path/'formats.m'
        source.write_text(r'''
#include "vita_metal.h"
#include <assert.h>
#include <string.h>
int main(void){
 size_t needed=0,output=0;
 assert(!vx_framebuffer_required(2,2,12,VX_PIXELS_RGBA8,&needed,&output));assert(needed==20&&output==16);
 assert(vx_framebuffer_required(2,2,7,VX_PIXELS_RGBA8,&needed,&output)==VX_METAL_INVALID);
 assert(vx_framebuffer_required(4097,2,16388,VX_PIXELS_RGBA8,&needed,&output)==VX_METAL_INVALID);
 assert(vx_framebuffer_required(2,2,8,3,&needed,&output)==VX_METAL_INVALID);
 assert(vx_framebuffer_required(2,2,8,0,0,&output)==VX_METAL_INVALID);
 const uint8_t expected[16]={255,0,0,255,0,255,0,127,0,0,255,255,255,255,255,0};
 uint8_t rgba[20]={255,0,0,255,0,255,0,127,9,9,9,9,0,0,255,255,255,255,255,0};
 uint8_t result[16]={0};
 assert(!vx_framebuffer_convert(2,2,12,VX_PIXELS_RGBA8,rgba,sizeof rgba,result,sizeof result));
 assert(!memcmp(result,expected,16));
 uint8_t bgra[20]={0,0,255,255,0,255,0,127,9,9,9,9,255,0,0,255,255,255,255,0};
 assert(!vx_framebuffer_convert(2,2,12,VX_PIXELS_BGRA8,bgra,sizeof bgra,result,sizeof result));assert(!memcmp(result,expected,16));
 uint8_t rgb565[10]={0,248,224,7,9,9,31,0,255,255};
 const uint8_t opaque[16]={255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255};
 assert(!vx_framebuffer_convert(2,2,6,VX_PIXELS_RGB565_LE,rgb565,sizeof rgb565,result,sizeof result));assert(!memcmp(result,opaque,16));
 assert(vx_framebuffer_convert(2,2,12,0,rgba,19,result,16)==VX_METAL_INVALID);
 assert(vx_framebuffer_convert(2,2,12,0,rgba,20,result,15)==VX_METAL_INVALID);
 assert(vx_framebuffer_convert(2,2,12,0,rgba,20,rgba,20)==VX_METAL_INVALID);
 assert(vx_framebuffer_convert(2,2,12,0,0,20,result,16)==VX_METAL_INVALID);
 assert(vx_metal_upload(0,rgba,20,12,0)==VX_METAL_INVALID);
 assert(vx_metal_resize(0,2,2)==VX_METAL_INVALID);
 uint32_t width,height;assert(vx_metal_size(0,&width,&height)==VX_METAL_INVALID);
 return 0;
}''')
        binary=self.path/'formats'
        subprocess.run(self.common+[str(source),'-o',str(binary)],check=True,capture_output=True)
        subprocess.run([str(binary)],check=True,capture_output=True,timeout=5)

    def test_gpu_framebuffer_upload_and_atomic_resize(self):
        source=self.path/'upload.m'
        source.write_text(r'''
#include "vita_metal.h"
#include <assert.h>
#include <string.h>
int main(void){
 vx_metal *ctx=0;int status=vx_metal_create(2,2,&ctx);if(status==77)return 77;assert(!status);
 const uint8_t bgra[16]={0,0,255,255,0,255,0,255,255,0,0,255,255,255,255,255};
 const uint8_t rgba[16]={255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255};
 uint8_t result[64];assert(!vx_metal_upload(ctx,bgra,16,8,VX_PIXELS_BGRA8));
 assert(!vx_metal_readback(ctx,result,sizeof result));assert(!memcmp(result,rgba,16));
 assert(vx_metal_resize(ctx,0,2)==VX_METAL_INVALID);
 assert(!vx_metal_readback(ctx,result,sizeof result));assert(!memcmp(result,rgba,16));
 assert(!vx_metal_resize(ctx,4,4));uint32_t width=0,height=0;assert(!vx_metal_size(ctx,&width,&height));assert(width==4&&height==4);
 assert(vx_metal_readback(ctx,result,sizeof result)==VX_METAL_INVALID);
 float clear[4]={0,0,1,1};assert(!vx_metal_draw(ctx,0,0,clear));assert(!vx_metal_readback(ctx,result,sizeof result));
 for(int i=0;i<16;i++)assert(result[i*4]==0&&result[i*4+1]==0&&result[i*4+2]==255&&result[i*4+3]==255);
 vx_metal_destroy(ctx);return 0;
}''')
        binary=self.path/'upload'
        subprocess.run(self.common+[str(source),'-o',str(binary)],check=True,capture_output=True)
        result=subprocess.run([str(binary)],capture_output=True,timeout=20)
        if result.returncode==77:self.skipTest('Metal unavailable; no upload/readback or resize GPU evidence')
        self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_gpu_texture_filter_shader_and_alpha(self):
        source=self.path/'filter.m'
        source.write_text(r'''#include "vita_metal.h"
#include <assert.h>
#include <stdlib.h>
int main(void){
 vx_metal *ctx=0;int status=vx_metal_create(4,1,&ctx);if(status==77)return 77;assert(!status);
 const uint8_t pixels[]={255,0,0,0,0,0,255,255};uint8_t out[16];
 assert(!vx_metal_present(ctx,pixels,8,2,1,8,VX_PIXELS_RGBA8));assert(!vx_metal_readback(ctx,out,16));
 for(int x=0;x<4;x++){assert(out[4*x]==(x<2?255:0));assert(out[4*x+2]==(x<2?0:255));assert(out[4*x+3]==(x<2?0:255));}
 assert(!vx_metal_set_filter(ctx,1));assert(vx_metal_set_filter(ctx,2)==VX_METAL_INVALID);
 assert(!vx_metal_present(ctx,pixels,8,2,1,8,VX_PIXELS_RGBA8));assert(!vx_metal_readback(ctx,out,16));
 const int red[]={255,191,64,0},blue[]={0,64,191,255};
 for(int x=0;x<4;x++){assert(abs(out[4*x]-red[x])<=1);assert(!out[4*x+1]);assert(abs(out[4*x+2]-blue[x])<=1);assert(abs(out[4*x+3]-blue[x])<=1);}
 vx_metal_destroy(ctx);return 0;
}''')
        binary=self.path/'filter'
        subprocess.run(self.common+[str(source),'-o',str(binary)],check=True,capture_output=True)
        result=subprocess.run([str(binary)],capture_output=True,timeout=15)
        if result.returncode==77:self.skipTest('Metal unavailable for filtering/shader validation')
        self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_gxp_depth_order_compare_write_and_scene_clear(self):
        """Synthetic host shaders/geometry: depth evidence, not guest evidence."""
        source=self.path/'depth.m'
        source.write_text(r'''#include "vita_metal.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
static const char *vs="#include <metal_stdlib>\nusing namespace metal;struct I{float4 p [[attribute(0)]];};struct O{float4 p [[position]];};vertex O vx_gxp_v(I i [[stage_in]]){return O{i.p};}";
static const char *fs="#include <metal_stdlib>\nusing namespace metal;fragment float4 vx_gxp_f(constant float4 &c [[buffer(1)]]){return c;}";
static const vx_gxp_attribute attr={4,0};
static void pipeline(vx_metal *c){char diagnostic[1024];int s=vx_metal_gxp_pipeline(c,vs,fs,&attr,1,16,0,4,0,diagnostic,sizeof diagnostic);if(s)fprintf(stderr,"%s\n",diagnostic);assert(!s);}
static void draw(vx_metal *c,float z,int green){float v[]={-.8f,-.8f,z,1,.8f,-.8f,z,1,0,.8f,z,1};const float color[]={green?0:1,green?1:0,0,1};assert(!vx_metal_gxp_draw_load(c,v,sizeof v,3,0,0,(const uint32_t *)color,4));}
static void check(vx_metal *c,int green){unsigned char pixels[64*64*4];assert(!vx_metal_readback(c,pixels,sizeof pixels));unsigned char *p=pixels+(32*64+32)*4;assert(p[0]==(green?0:255)&&p[1]==(green?255:0)&&p[2]==0&&p[3]==255);}
int main(void){
 assert(vx_metal_gxp_depth_begin(0,1,1)==VX_METAL_INVALID);assert(vx_metal_gxp_depth_state(0,1,1)==VX_METAL_INVALID);
 vx_metal *c=0;int status=vx_metal_create(64,64,&c);if(status==77)return 77;assert(!status);
 assert(vx_metal_gxp_depth_begin(c,2,1)==VX_METAL_INVALID);assert(vx_metal_gxp_depth_begin(c,1,NAN)==VX_METAL_INVALID);
 assert(vx_metal_gxp_depth_state(c,8,1)==VX_METAL_INVALID);assert(vx_metal_gxp_depth_state(c,1,2)==VX_METAL_INVALID);
 const float clear[]={0,0,0,1};assert(!vx_metal_draw(c,0,0,clear));
 assert(!vx_metal_gxp_depth_begin(c,1,1));assert(!vx_metal_gxp_depth_state(c,1,1));pipeline(c);
 for(int order=0;order<2;order++){
  assert(!vx_metal_gxp_depth_begin(c,1,1));
  draw(c,order?.2f:.8f,order);draw(c,order?.8f:.2f,!order);check(c,1);
  float z[4096];assert(vx_metal_gxp_depth_readback(c,z,4095)==VX_METAL_INVALID);
  assert(!vx_metal_gxp_depth_readback(c,z,4096));assert(fabsf(z[32*64+32]-.2f)<.00001f&&z[0]==1);
 }
 /* Exercise all eight compare mappings against a known stored value. */
 for(unsigned compare=0;compare<8;compare++)for(unsigned relation=0;relation<3;relation++){
  assert(!vx_metal_gxp_depth_begin(c,1,1));assert(!vx_metal_gxp_depth_state(c,7,1));draw(c,.5f,0);
  assert(!vx_metal_gxp_depth_state(c,compare,0));draw(c,relation==0?.25f:relation==1?.5f:.75f,1);
  int pass=compare==7||(compare==1&&relation==0)||(compare==2&&relation==1)||(compare==3&&relation<2)||(compare==4&&relation==2)||(compare==5&&relation!=1)||(compare==6&&relation>0);check(c,pass);
 }
 assert(!vx_metal_gxp_depth_begin(c,1,1));assert(!vx_metal_gxp_depth_state(c,1,0));draw(c,.2f,1);draw(c,.8f,0);check(c,0);
 float empty[4096];assert(!vx_metal_gxp_depth_begin(c,1,.5f));assert(!vx_metal_gxp_depth_readback(c,empty,4096));for(unsigned i=0;i<4096;i++)assert(empty[i]==.5f);
 /* Padded guest rows survive a fresh scene. Draws load imported values;
    an empty load/readback scene must preserve them too. */
 float padded[64*96];for(unsigned y=0;y<64;y++)for(unsigned x=0;x<96;x++)padded[y*96+x]=x<64?.25f:.9f;
 assert(!vx_metal_gxp_depth_begin(c,1,1));
 assert(vx_metal_gxp_depth_upload(c,(const uint8_t *)padded,63*384+255,384)==VX_METAL_INVALID);
 assert(vx_metal_gxp_depth_upload(c,(const uint8_t *)padded,sizeof padded,255)==VX_METAL_INVALID);
 assert(!vx_metal_gxp_depth_upload(c,(const uint8_t *)padded,sizeof padded,384));
 assert(!vx_metal_gxp_depth_readback(c,empty,4096));for(unsigned i=0;i<4096;i++)assert(empty[i]==.25f);
 assert(!vx_metal_gxp_depth_state(c,1,1));draw(c,.2f,1);draw(c,.8f,0);check(c,1);
 assert(!vx_metal_gxp_depth_readback(c,empty,4096));assert(empty[0]==.25f&&fabsf(empty[32*64+32]-.2f)<.00001f);
 assert(!vx_metal_gxp_depth_begin(c,1,1));
 assert(!vx_metal_gxp_depth_upload(c,(const uint8_t *)padded,sizeof padded,384));
 draw(c,.8f,0);check(c,1); /* far fragment fails against reloaded .25 */
 assert(!vx_metal_gxp_depth_begin(c,0,1));
 assert(vx_metal_gxp_depth_upload(c,(const uint8_t *)padded,sizeof padded,384)==VX_METAL_INVALID);
 assert(!vx_metal_gxp_depth_begin(c,0,1));pipeline(c);draw(c,.2f,1);draw(c,.8f,0);check(c,0);
 assert(!vx_metal_resize(c,64,64));assert(!vx_metal_draw(c,0,0,clear));
 assert(!vx_metal_gxp_depth_begin(c,1,1));assert(!vx_metal_gxp_depth_state(c,1,1));pipeline(c);draw(c,.2f,1);draw(c,.8f,0);check(c,1);
 vx_metal_destroy(c);puts("host Metal depth order/compare/write/clear PASS");return 0;
}''')
        binary=self.path/'depth'
        result=subprocess.run(self.common+[str(source),'-o',str(binary)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
        if result.returncode==77:self.skipTest('Metal unavailable; no depth pixel evidence')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('depth order/compare/write/clear PASS',result.stdout)

    def test_gxp_stencil_compare_operations_masks_and_storage(self):
        binary=self.path/'stencil'
        result=subprocess.run(self.common+[str(ROOT/'tests/metal_stencil_probe.m'),'-o',str(binary)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=45)
        if result.returncode==77:self.skipTest('Metal unavailable; no stencil pixel evidence')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('stencil compare/ops/masks/storage PASS',result.stdout)

    def test_stencil_bounds_without_device(self):
        binary=self.path/'stencil-bounds'
        result=subprocess.run(self.common+[str(ROOT/'tests/metal_stencil_probe.m'),'-o',str(binary)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        result=subprocess.run([str(binary),'bounds'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('stencil null bounds PASS',result.stdout)
