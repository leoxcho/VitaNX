#include "vita_metal.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
static const char *vs="#include <metal_stdlib>\nusing namespace metal;struct I{float4 p [[attribute(0)]];};struct O{float4 p [[position]];};vertex O vx_gxp_v(I i [[stage_in]]){return O{i.p};}";
static const char *fs="#include <metal_stdlib>\nusing namespace metal;fragment float4 vx_gxp_f(constant float4 &c [[buffer(1)]]){return c;}";
static const vx_gxp_attribute attr={4,0};
static void pipeline(vx_metal *c){char diagnostic[1024];int s=vx_metal_gxp_pipeline(c,vs,fs,&attr,1,16,0,4,0,diagnostic,sizeof diagnostic);if(s)fprintf(stderr,"%s\n",diagnostic);assert(!s);}
static void draw(vx_metal *c,float z,int green){float v[]={-.8f,-.8f,z,1,.8f,-.8f,z,1,0,.8f,z,1};const float color[]={green?0:1,green?1:0,0,1};assert(!vx_metal_gxp_draw_load(c,v,sizeof v,3,0,0,(const uint32_t *)color,4));}
static void check(vx_metal *c,int green){unsigned char pixels[64*64*4];assert(!vx_metal_readback(c,pixels,sizeof pixels));unsigned char *p=pixels+(32*64+32)*4;assert(p[0]==(green?0:255)&&p[1]==(green?255:0)&&p[2]==0&&p[3]==255);}

#include <string.h>
static unsigned center(vx_metal *c){uint8_t values[4096];assert(!vx_metal_gxp_stencil_readback(c,values,sizeof values));return values[32*64+32];}
static void state(vx_metal *c,unsigned compare,unsigned fail,unsigned df,unsigned pass,unsigned mask,unsigned write,unsigned ref){assert(!vx_metal_gxp_stencil_state(c,compare,fail,df,pass,mask,write,ref));}
static void scene(vx_metal *c,unsigned value){assert(!vx_metal_gxp_stencil_begin(c,1,value));}
int main(int argc,char **argv){
 (void)argv;
 assert(vx_metal_gxp_stencil_begin(0,1,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_state(0,7,0,0,0,255,255,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_upload(0,0,0,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_readback(0,0,0)==VX_METAL_INVALID);
 if(argc>1){puts("stencil null bounds PASS");return 0;}
 vx_metal *c=0;int status=vx_metal_create(64,64,&c);if(status==77)return 77;assert(!status);
 assert(vx_metal_gxp_stencil_begin(c,2,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_begin(c,1,256)==VX_METAL_INVALID);
 const float clear[]={0,0,0,1};assert(!vx_metal_draw(c,0,0,clear));
 assert(!vx_metal_gxp_depth_begin(c,1,1));assert(!vx_metal_gxp_depth_state(c,7,0));
 scene(c,0);pipeline(c);
 for(unsigned cmp=0;cmp<8;cmp++)for(unsigned relation=0;relation<3;relation++){
  scene(c,128);state(c,cmp,0,0,2,255,255,relation==0?64:relation==1?128:192);
  draw(c,.5f,0); /* establish a red target even when this comparison fails */
  /* Reset red color independently, then repeat the stencil test in green. */
  assert(!vx_metal_draw(c,0,0,(const float[]){1,0,0,1}));scene(c,128);draw(c,.5f,1);
  int pass=cmp==7||(cmp==1&&relation==0)||(cmp==2&&relation==1)||(cmp==3&&relation<2)||(cmp==4&&relation==2)||(cmp==5&&relation!=1)||(cmp==6&&relation>0);
  check(c,pass);assert(center(c)==(pass?(relation==0?64:relation==1?128:192):128));
 }
 /* Exercise every operation on each outcome, including clamp/wrap boundaries. */
 for(unsigned outcome=0;outcome<3;outcome++)for(unsigned op=0;op<8;op++)for(unsigned i=0;i<3;i++){
  unsigned initial=i==0?0:i==1?128:255;
  scene(c,initial);assert(!vx_metal_gxp_depth_begin(c,1,1));assert(!vx_metal_gxp_depth_state(c,outcome==1?0:7,0));
  state(c,outcome==0?0:7,outcome==0?op:0,outcome==1?op:0,outcome==2?op:0,255,255,42);
  draw(c,.5f,1);
  unsigned expected=initial;
  switch(op){case 1:expected=0;break;case 2:expected=42;break;case 3:expected=initial==255?255:initial+1;break;case 4:expected=initial?initial-1:0;break;case 5:expected=initial^255;break;case 6:expected=(initial+1)&255;break;case 7:expected=(initial-1)&255;break;}
  assert(center(c)==expected);
 }
 assert(!vx_metal_gxp_depth_state(c,7,0));scene(c,0xa5);state(c,2,0,0,2,15,0xf0,0x35);draw(c,.5f,1);assert(center(c)==0x35);
 scene(c,0xa5);state(c,7,0,0,2,255,0,0);draw(c,.5f,1);assert(center(c)==0xa5);
 /* Invalid calls preserve state and attachment bytes. */
 assert(vx_metal_gxp_stencil_state(c,8,0,0,0,255,255,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_state(c,7,8,0,0,255,255,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_state(c,7,0,8,0,255,255,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_state(c,7,0,0,8,255,255,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_state(c,7,0,0,0,256,255,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_state(c,7,0,0,0,255,256,0)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_state(c,7,0,0,0,255,255,256)==VX_METAL_INVALID);
 draw(c,.5f,1);assert(center(c)==0xa5);
 uint8_t padded[64*96],out[4096];memset(padded,0x79,sizeof padded);
 assert(vx_metal_gxp_stencil_upload(c,padded,sizeof padded,63)==VX_METAL_INVALID);
 assert(vx_metal_gxp_stencil_upload(c,padded,63*96+63,96)==VX_METAL_INVALID);
 assert(!vx_metal_gxp_stencil_upload(c,padded,sizeof padded,96));assert(center(c)==0x79);
 memset(out,0x33,sizeof out);assert(vx_metal_gxp_stencil_readback(c,out,sizeof out-1)==VX_METAL_INVALID);assert(out[0]==0x33);
 assert(!vx_metal_gxp_stencil_readback(c,out,sizeof out));for(unsigned i=0;i<4096;i++)assert(out[i]==0x79);
 scene(c,19);assert(!vx_metal_gxp_stencil_readback(c,out,sizeof out));for(unsigned i=0;i<4096;i++)assert(out[i]==19);
 /* Stencil-only and depth-only transitions rebuild attachment formats. */
 assert(!vx_metal_gxp_depth_begin(c,0,1));pipeline(c);state(c,7,0,0,2,255,255,23);draw(c,.5f,1);assert(center(c)==23);
 assert(!vx_metal_gxp_stencil_begin(c,0,0));pipeline(c);draw(c,.5f,1);check(c,1);
 assert(vx_metal_gxp_stencil_readback(c,out,sizeof out)==VX_METAL_INVALID);
 assert(!vx_metal_resize(c,32,32));scene(c,11);assert(!vx_metal_gxp_stencil_readback(c,out,sizeof out));for(unsigned i=0;i<1024;i++)assert(out[i]==11);
 vx_metal_destroy(c);puts("host Metal stencil compare/ops/masks/storage PASS");return 0;
}
