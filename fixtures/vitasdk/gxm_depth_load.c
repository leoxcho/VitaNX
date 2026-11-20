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
static unsigned char gpu[49152] __attribute__((aligned(4096)));
static const float vertices[12]={-.8f,-.8f,.5f,1,.8f,-.8f,.5f,1,0,.8f,.5f,1};
#ifdef VX_GXM_BINDINGS_ONLY
static const char pass[]="VitaSDK GXM context/shader/buffer/texture bindings PASS\n";
#else
static const char pass[]="VitaSDK GXM DF32 depth load/store/background/padded rows PASS\n";
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
 status=14;if(sceGxmDepthStencilSurfaceInit(&depth,SCE_GXM_DEPTH_STENCIL_FORMAT_DF32,SCE_GXM_DEPTH_STENCIL_SURFACE_LINEAR,96,gpu+24576,0)||!sceGxmDepthStencilSurfaceIsEnabled(&depth))goto done;
 sceGxmSetFrontDepthFunc(context,SCE_GXM_DEPTH_FUNC_LESS);
 sceGxmSetFrontDepthWriteEnable(context,SCE_GXM_DEPTH_WRITE_ENABLED);
 status=18;
 if(sceGxmDepthStencilSurfaceGetForceLoadMode(&depth)!=SCE_GXM_DEPTH_STENCIL_FORCE_LOAD_DISABLED)goto done;
 sceGxmDepthStencilSurfaceSetForceStoreMode(&depth,SCE_GXM_DEPTH_STENCIL_FORCE_STORE_ENABLED);
 if(sceGxmDepthStencilSurfaceGetForceStoreMode(&depth)!=SCE_GXM_DEPTH_STENCIL_FORCE_STORE_ENABLED)goto done;
 /* Sentinel padding is never a depth pixel. */
 float *z=(float *)(gpu+24576);
 for(unsigned y=0;y<64;y++)for(unsigned x=64;x<96;x++)z[y*96+x]=.75f;
 for(unsigned frame=0;frame<5;frame++){
  sceGxmDepthStencilSurfaceSetForceLoadMode(&depth,(frame==1||frame==2)?SCE_GXM_DEPTH_STENCIL_FORCE_LOAD_ENABLED:SCE_GXM_DEPTH_STENCIL_FORCE_LOAD_DISABLED);
  status=19;if(sceGxmDepthStencilSurfaceGetForceLoadMode(&depth)!=((frame==1||frame==2)?2:0))goto done;
  if(frame==3)sceGxmDepthStencilSurfaceSetBackgroundDepth(&depth,.5f);
  status=20;if(sceGxmDepthStencilSurfaceGetBackgroundDepth(&depth)!=(frame>=3?.5f:1.0f))goto done;
  status=7;if(sceGxmBeginScene(context,0,target,0,0,0,&surface,&depth))goto done;
  /* Scene 1 draws only far red, which retained near depth must reject.
     Scenes 2/3 contain no draws: load then custom clear still store depth. */
  if(frame==0||frame==1||frame==4){
   float value=frame==0?.2f:frame==1?.8f:.4f;
   for(unsigned i=0;i<3;i++)((float *)gpu)[i*4+2]=value;
   color[0]=frame==1?1:0;color[1]=frame==1?0:1;
   status=8;if(sceGxmDraw(context,SCE_GXM_PRIMITIVE_TRIANGLES,SCE_GXM_INDEX_FORMAT_U16,gpu+128,3))goto done;
  }
  status=9;if(sceGxmEndScene(context,0,0))goto done;
  float expected=frame<3?.2f:frame==3?.5f:.4f;
  status=21;if(z[32*96+32]<expected-.00001f||z[32*96+32]>expected+.00001f||z[0]!=(frame<3?1:.5f))goto done;
  for(unsigned y=0;y<64;y++)for(unsigned x=64;x<96;x++)if(z[y*96+x]!=.75f)goto done;
  unsigned char *center=gpu+4096+(32*64+32)*4;
  status=10;if(center[0]>2||center[1]<253||center[2]>2||center[3]<253)goto done;
 }

#endif
 status=11;
 if(sceGxmShaderPatcherReleaseVertexProgram(patcher,vp)||sceGxmShaderPatcherReleaseFragmentProgram(patcher,fp)||sceGxmShaderPatcherUnregisterProgram(patcher,vi)||sceGxmShaderPatcherUnregisterProgram(patcher,fi)||sceGxmShaderPatcherDestroy(patcher)||sceGxmDestroyRenderTarget(target)||sceGxmDestroyContext(context)||sceGxmUnmapMemory(gpu)||sceGxmTerminate())goto done;
 status=0;sceIoWrite(1,pass,sizeof(pass)-1);
 done:sceKernelExitProcess(status);return 99;
}
