/* Genuine VitaSDK guest scene ABI. Original GXP assets are loaded unchanged.
   Two indexed triangles, guest uniforms and framebuffer checks; no gameplay claim. */
#include <psp2/gxm.h>
#include <psp2/display.h>
#include <psp2/io/fcntl.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/kernel/threadmgr.h>
void *memset(void *destination,int value,unsigned n){volatile unsigned char *p=destination;for(unsigned i=0;i<n;i++)p[i]=(unsigned char)value;return destination;}
static unsigned vs[1024],fs[1024];
static unsigned char host[4096] __attribute__((aligned(4096)));
static unsigned char gpu[65536] __attribute__((aligned(4096)));
static const float vertices[12]={-.8f,-.8f,.5f,1,.8f,-.8f,.5f,1,0,.8f,.5f,1};
#ifdef VX_GXM_BINDINGS_ONLY
static const char pass[]="VitaSDK GXM context/shader/buffer/texture bindings PASS\n";
#else
static const char pass[]="VitaSDK GXM stencil overlap/compares/operations/masks/load/store PASS\n";
#endif
static int load(const char *path,void *p){int fd=sceIoOpen(path,SCE_O_RDONLY,0);if(fd<0)return fd;int n=sceIoRead(fd,p,4096);sceIoClose(fd);return n;}
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;int status=1;
 SceGxmContext *context=0;SceGxmShaderPatcher *patcher=0;SceGxmRenderTarget *target=0;
 SceGxmShaderPatcherId vi=0,fi=0;SceGxmVertexProgram *vp=0;SceGxmFragmentProgram *fp=0;
 SceGxmInitializeParams init={0};init.parameterBufferSize=0x40000;
 if(sceGxmInitialize(&init))goto done;
 if(sceGxmMapMemory(gpu,sizeof gpu,SCE_GXM_MEMORY_ATTRIB_RW))goto done;
 SceGxmContextParams cp={0};cp.hostMem=host;cp.hostMemSize=sizeof host;
 status=2;if(sceGxmCreateContext(&cp,&context))goto done;
 if(load("app0:/scene.vpo",vs)<156||load("app0:/scene.fpo",fs)<156)goto done;
 SceGxmShaderPatcherParams pp={0};status=3;
 if(sceGxmShaderPatcherCreate(&pp,&patcher)||sceGxmShaderPatcherRegisterProgram(patcher,(SceGxmProgram *)vs,&vi)||sceGxmShaderPatcherRegisterProgram(patcher,(SceGxmProgram *)fs,&fi))goto done;
 SceGxmVertexAttribute attr={0};attr.format=SCE_GXM_ATTRIBUTE_FORMAT_F32;attr.componentCount=4;
 const SceGxmProgramParameter *pos=sceGxmProgramFindParameterBySemantic((SceGxmProgram *)vs,SCE_GXM_PARAMETER_SEMANTIC_POSITION,0);
 if(!pos)goto done;attr.regIndex=sceGxmProgramParameterGetResourceIndex(pos);
 SceGxmVertexStream stream={16,SCE_GXM_INDEX_SOURCE_INDEX_16BIT};status=4;
 if(sceGxmShaderPatcherCreateVertexProgram(patcher,vi,&attr,1,&stream,1,&vp)||sceGxmShaderPatcherCreateFragmentProgram(patcher,fi,SCE_GXM_OUTPUT_REGISTER_FORMAT_UCHAR4,SCE_GXM_MULTISAMPLE_NONE,0,(SceGxmProgram *)vs,&fp))goto done;
 SceGxmRenderTargetParams rt={0};rt.width=64;rt.height=64;rt.scenesPerFrame=1;rt.driverMemBlock=-1;
 status=5;if(sceGxmCreateRenderTarget(&rt,&target))goto done;
 SceGxmColorSurface surface;
 if(sceGxmColorSurfaceInit(&surface,SCE_GXM_COLOR_FORMAT_U8U8U8U8_ABGR,SCE_GXM_COLOR_SURFACE_LINEAR,SCE_GXM_COLOR_SURFACE_SCALE_NONE,SCE_GXM_OUTPUT_REGISTER_SIZE_32BIT,64,64,64,gpu+4096))goto done;
 for(unsigned i=0;i<12;i++)((float *)gpu)[i]=vertices[i];
 ((unsigned short *)(gpu+128))[0]=2;((unsigned short *)(gpu+128))[1]=0;((unsigned short *)(gpu+128))[2]=1;
 float *color=(float *)(gpu+256);color[0]=1;color[1]=0;color[2]=0;color[3]=1;
 sceGxmSetVertexProgram(context,vp);sceGxmSetFragmentProgram(context,fp);
 status=6;if(sceGxmSetVertexStream(context,0,gpu)||sceGxmSetVertexDefaultUniformBuffer(context,color))goto done;
 #ifdef VX_GXM_BINDINGS_ONLY
 SceGxmTexture texture;status=12;
 if(sceGxmTextureInitLinear(&texture,gpu+512,SCE_GXM_TEXTURE_FORMAT_U8U8U8U8_ABGR,2,2,1)||
    sceGxmTextureSetUAddrMode(&texture,SCE_GXM_TEXTURE_ADDR_CLAMP)||sceGxmTextureSetVAddrMode(&texture,SCE_GXM_TEXTURE_ADDR_CLAMP)||
    sceGxmTextureSetMinFilter(&texture,SCE_GXM_TEXTURE_FILTER_LINEAR)||sceGxmTextureSetMagFilter(&texture,SCE_GXM_TEXTURE_FILTER_LINEAR)||
    sceGxmSetFragmentTexture(context,0,&texture))goto done;
#else
 SceGxmDepthStencilSurface depth;
 unsigned char *st=gpu+49152;float *z=(float *)(gpu+24576);
 status=14;if(sceGxmDepthStencilSurfaceInit(&depth,SCE_GXM_DEPTH_STENCIL_FORMAT_DF32_S8,SCE_GXM_DEPTH_STENCIL_SURFACE_LINEAR,96,z,st))goto done;
 for(unsigned i=0;i<64*96;i++){st[i]=0xee;z[i]=.75f;}
 sceGxmSetFrontDepthFunc(context,SCE_GXM_DEPTH_FUNC_ALWAYS);
 sceGxmSetFrontDepthWriteEnable(context,SCE_GXM_DEPTH_WRITE_DISABLED);
 /* Masked first triangle, then smaller overlapping geometry constrained by stencil. */
 sceGxmDepthStencilSurfaceSetBackgroundStencil(&depth,0xa0);
 status=15;if(sceGxmDepthStencilSurfaceGetBackgroundStencil(&depth)!=0xa0)goto done;
 status=7;if(sceGxmBeginScene(context,0,target,0,0,0,&surface,&depth))goto done;
 sceGxmSetFrontStencilRef(context,0xa5);sceGxmSetBackStencilRef(context,0xa5);
 sceGxmSetFrontStencilFunc(context,SCE_GXM_STENCIL_FUNC_ALWAYS,SCE_GXM_STENCIL_OP_KEEP,SCE_GXM_STENCIL_OP_KEEP,SCE_GXM_STENCIL_OP_REPLACE,255,15);
 sceGxmSetBackStencilFunc(context,SCE_GXM_STENCIL_FUNC_ALWAYS,SCE_GXM_STENCIL_OP_KEEP,SCE_GXM_STENCIL_OP_KEEP,SCE_GXM_STENCIL_OP_REPLACE,255,15);
 status=8;if(sceGxmDraw(context,SCE_GXM_PRIMITIVE_TRIANGLES,SCE_GXM_INDEX_FORMAT_U16,gpu+128,3))goto done;
 for(unsigned i=0;i<3;i++){((float *)gpu)[i*4]*=.5f;((float *)gpu)[i*4+1]*=.5f;}
 color[0]=0;color[1]=1;
 sceGxmSetFrontStencilRef(context,5);sceGxmSetBackStencilRef(context,5);
 sceGxmSetFrontStencilFunc(context,SCE_GXM_STENCIL_FUNC_EQUAL,SCE_GXM_STENCIL_OP_KEEP,SCE_GXM_STENCIL_OP_KEEP,SCE_GXM_STENCIL_OP_INCR,15,255);
 sceGxmSetBackStencilFunc(context,SCE_GXM_STENCIL_FUNC_EQUAL,SCE_GXM_STENCIL_OP_KEEP,SCE_GXM_STENCIL_OP_KEEP,SCE_GXM_STENCIL_OP_INCR,15,255);
 if(sceGxmDraw(context,SCE_GXM_PRIMITIVE_TRIANGLES,SCE_GXM_INDEX_FORMAT_U16,gpu+128,3))goto done;
 status=9;if(sceGxmEndScene(context,0,0))goto done;
 unsigned red=0,green=0;
 for(unsigned y=0;y<64;y++)for(unsigned x=0;x<64;x++){
  unsigned char *px=gpu+4096+(y*64+x)*4;
  status=16;if(px[0]>253){if(st[y*96+x]!=0xa5)goto done;red++;}
  if(px[1]>253){if(st[y*96+x]!=0xa6)goto done;green++;}
 }
 if(!red||!green||st[32*96+32]!=0xa6||st[0]!=0xa0)goto done;
 /* All operations through genuine guest calls, independently on each outcome. */
 for(unsigned outcome=0;outcome<3;outcome++)for(unsigned op=0;op<8;op++){
  sceGxmDepthStencilSurfaceSetBackgroundStencil(&depth,5);
  sceGxmSetFrontDepthFunc(context,outcome==1?SCE_GXM_DEPTH_FUNC_NEVER:SCE_GXM_DEPTH_FUNC_ALWAYS);
  SceGxmStencilFunc cmp=outcome==0?SCE_GXM_STENCIL_FUNC_NEVER:SCE_GXM_STENCIL_FUNC_ALWAYS;
  sceGxmSetFrontStencilRef(context,3);sceGxmSetBackStencilRef(context,3);
  sceGxmSetFrontStencilFunc(context,cmp,outcome==0?op:0,outcome==1?op:0,outcome==2?op:0,255,255);
  sceGxmSetBackStencilFunc(context,cmp,outcome==0?op:0,outcome==1?op:0,outcome==2?op:0,255,255);
  status=20;if(sceGxmBeginScene(context,0,target,0,0,0,&surface,&depth))goto done;
  if(sceGxmDraw(context,SCE_GXM_PRIMITIVE_TRIANGLES,SCE_GXM_INDEX_FORMAT_U16,gpu+128,3)||sceGxmEndScene(context,0,0))goto done;
  unsigned expected=op==0?5:op==1?0:op==2?3:op==3?6:op==4?4:op==5?250:op==6?6:4;
  status=21;if(st[32*96+32]!=expected||st[0]!=5)goto done;
 }
 /* Eight compare enums; fail zero versus pass replace makes results observable. */
 sceGxmSetFrontDepthFunc(context,SCE_GXM_DEPTH_FUNC_ALWAYS);
 for(unsigned cmp=0;cmp<8;cmp++){
  sceGxmDepthStencilSurfaceSetBackgroundStencil(&depth,4);
  sceGxmSetFrontStencilFunc(context,(SceGxmStencilFunc)(cmp<<25),SCE_GXM_STENCIL_OP_ZERO,0,SCE_GXM_STENCIL_OP_REPLACE,255,255);
  sceGxmSetBackStencilFunc(context,(SceGxmStencilFunc)(cmp<<25),SCE_GXM_STENCIL_OP_ZERO,0,SCE_GXM_STENCIL_OP_REPLACE,255,255);
  status=22;if(sceGxmBeginScene(context,0,target,0,0,0,&surface,&depth)||sceGxmDraw(context,SCE_GXM_PRIMITIVE_TRIANGLES,SCE_GXM_INDEX_FORMAT_U16,gpu+128,3)||sceGxmEndScene(context,0,0))goto done;
  unsigned passes=cmp==1||cmp==3||cmp==5||cmp==7;
  if(st[32*96+32]!=(passes?3:0))goto done;
 }
 /* No-draw force load must round trip both attachments and preserve row padding. */
 sceGxmDepthStencilSurfaceSetForceLoadMode(&depth,SCE_GXM_DEPTH_STENCIL_FORCE_LOAD_ENABLED);
 status=23;if(sceGxmBeginScene(context,0,target,0,0,0,&surface,&depth)||sceGxmEndScene(context,0,0))goto done;
 if(st[32*96+32]!=3||st[0]!=4)goto done;
 for(unsigned y=0;y<64;y++)for(unsigned x=64;x<96;x++)if(st[y*96+x]!=0xee||z[y*96+x]!=.75f)goto done;
 /* S8-only clear exercises pipeline attachment transition and no-draw storage. */
 status=24;if(sceGxmDepthStencilSurfaceInit(&depth,SCE_GXM_DEPTH_STENCIL_FORMAT_S8,SCE_GXM_DEPTH_STENCIL_SURFACE_LINEAR,96,0,st))goto done;
 sceGxmDepthStencilSurfaceSetBackgroundStencil(&depth,77);
 if(sceGxmBeginScene(context,0,target,0,0,0,&surface,&depth)||sceGxmEndScene(context,0,0))goto done;
 if(st[0]!=77||st[32*96+32]!=77)goto done;

#endif
 status=11;
 if(sceGxmShaderPatcherReleaseVertexProgram(patcher,vp)||sceGxmShaderPatcherReleaseFragmentProgram(patcher,fp)||sceGxmShaderPatcherUnregisterProgram(patcher,vi)||sceGxmShaderPatcherUnregisterProgram(patcher,fi)||sceGxmShaderPatcherDestroy(patcher)||sceGxmDestroyRenderTarget(target)||sceGxmDestroyContext(context)||sceGxmUnmapMemory(gpu)||sceGxmTerminate())goto done;
 status=0;sceIoWrite(1,pass,sizeof(pass)-1);
 done:sceKernelExitProcess(status);return 99;
}
