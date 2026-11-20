/* Genuine VitaSDK guest scene ABI. Original GXP assets are loaded unchanged.
   Two indexed triangles, guest uniforms and framebuffer checks; no gameplay claim. */
#include <psp2/gxm.h>
#include <psp2/display.h>
#include <psp2/io/fcntl.h>
#include <psp2/kernel/processmgr.h>
void *memset(void *destination,int value,unsigned n){volatile unsigned char *p=destination;for(unsigned i=0;i<n;i++)p[i]=(unsigned char)value;return destination;}
static unsigned vs[1024],fs[1024];
static unsigned char host[4096] __attribute__((aligned(4096)));
static unsigned char gpu[24576] __attribute__((aligned(4096)));
static const float vertices[12]={-.8f,-.8f,.5f,1,.8f,-.8f,.5f,1,0,.8f,.5f,1};
static const char pass[]="VitaSDK GXM texture point/linear + U32 index pixels PASS\n";
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
 SceGxmVertexAttribute attr[2]={{0},{0}};attr[0].format=SCE_GXM_ATTRIBUTE_FORMAT_F32;attr[0].componentCount=4;attr[1].format=SCE_GXM_ATTRIBUTE_FORMAT_F32;attr[1].componentCount=4;attr[1].offset=16;
 const SceGxmProgramParameter *pos=sceGxmProgramFindParameterBySemantic((SceGxmProgram *)vs,SCE_GXM_PARAMETER_SEMANTIC_POSITION,0);
 if(!pos)goto done;attr[0].regIndex=sceGxmProgramParameterGetResourceIndex(pos);
 const SceGxmProgramParameter *uv=sceGxmProgramFindParameterBySemantic((SceGxmProgram *)vs,SCE_GXM_PARAMETER_SEMANTIC_TEXCOORD,0);
 if(!uv)goto done;attr[1].regIndex=sceGxmProgramParameterGetResourceIndex(uv);
 SceGxmVertexStream stream={32,SCE_GXM_INDEX_SOURCE_INDEX_32BIT};status=4;
 if(sceGxmShaderPatcherCreateVertexProgram(patcher,vi,attr,2,&stream,1,&vp)||sceGxmShaderPatcherCreateFragmentProgram(patcher,fi,SCE_GXM_OUTPUT_REGISTER_FORMAT_UCHAR4,SCE_GXM_MULTISAMPLE_NONE,0,(SceGxmProgram *)vs,&fp))goto done;
 SceGxmRenderTargetParams rt={0};rt.width=64;rt.height=64;rt.scenesPerFrame=1;rt.driverMemBlock=-1;
 status=5;if(sceGxmCreateRenderTarget(&rt,&target))goto done;
 SceGxmColorSurface surface;
 if(sceGxmColorSurfaceInit(&surface,SCE_GXM_COLOR_FORMAT_U8U8U8U8_ABGR,SCE_GXM_COLOR_SURFACE_LINEAR,SCE_GXM_COLOR_SURFACE_SCALE_NONE,SCE_GXM_OUTPUT_REGISTER_SIZE_32BIT,64,64,64,gpu+4096))goto done;
 for(unsigned i=0;i<3;i++)for(unsigned j=0;j<4;j++)((float *)gpu)[i*8+j]=vertices[i*4+j];
 ((unsigned *)(gpu+128))[0]=2;((unsigned *)(gpu+128))[1]=0;((unsigned *)(gpu+128))[2]=1;
 float *color=(float *)(gpu+256);color[0]=0;color[1]=0;color[2]=0;color[3]=0;
 unsigned *texels=(unsigned *)(gpu+512);texels[0]=0xff0000ff;texels[1]=0xff00ff00;texels[2]=0xffff0000;texels[3]=0xffffffff;
 SceGxmTexture texture;
 status=12;if(sceGxmTextureInitLinear(&texture,texels,SCE_GXM_TEXTURE_FORMAT_U8U8U8U8_ABGR,2,2,1))goto done;
 sceGxmSetVertexProgram(context,vp);sceGxmSetFragmentProgram(context,fp);
 status=6;if(sceGxmSetVertexStream(context,0,gpu)||sceGxmSetVertexDefaultUniformBuffer(context,color))goto done;
 for(unsigned frame=0;frame<3;frame++){
  if(frame==2&&(sceGxmTextureSetMinFilter(&texture,SCE_GXM_TEXTURE_FILTER_LINEAR)||sceGxmTextureSetMagFilter(&texture,SCE_GXM_TEXTURE_FILTER_LINEAR))){status=12;goto done;}
  status=12;if(sceGxmSetFragmentTexture(context,0,&texture))goto done;
  for(unsigned i=0;i<3;i++){((float *)gpu)[i*8+4]=frame==2?.5f:frame?.75f:.25f;((float *)gpu)[i*8+5]=.25f;((float *)gpu)[i*8+6]=0;((float *)gpu)[i*8+7]=1;}
  status=7;int begin=sceGxmBeginScene(context,0,target,0,0,0,&surface,0);
  if(begin){status=begin==(int)0x805b0017?77:7;goto done;}
  status=8;if(sceGxmDraw(context,SCE_GXM_PRIMITIVE_TRIANGLES,SCE_GXM_INDEX_FORMAT_U32,gpu+128,3))goto done;
  status=9;if(sceGxmEndScene(context,0,0))goto done;
  unsigned char *center=gpu+4096+(32*64+32)*4;
  status=10;
  if(frame==0&&(center[0]<253||center[1]>2||center[2]>2||center[3]<253))goto done;
  if(frame==1&&(center[1]<253||center[0]>2||center[2]>2||center[3]<253))goto done;
  if(frame==2&&(center[0]<126||center[0]>129||center[1]<126||center[1]>129||center[2]>2||center[3]<253))goto done;
 }
 status=11;
 if(sceGxmShaderPatcherReleaseVertexProgram(patcher,vp)||sceGxmShaderPatcherReleaseFragmentProgram(patcher,fp)||sceGxmShaderPatcherUnregisterProgram(patcher,vi)||sceGxmShaderPatcherUnregisterProgram(patcher,fi)||sceGxmShaderPatcherDestroy(patcher)||sceGxmDestroyRenderTarget(target)||sceGxmDestroyContext(context)||sceGxmUnmapMemory(gpu)||sceGxmTerminate())goto done;
 status=0;sceIoWrite(1,pass,sizeof(pass)-1);
 done:sceKernelExitProcess(status);return 99;
}
