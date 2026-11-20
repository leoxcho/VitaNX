/* Genuine VitaSDK 3D cube: CPU transforms and painter sorting; guest GXM
   indexed draws use unchanged translated GXP assets. No depth-buffer support. */
#include <psp2/gxm.h>
#include <psp2/display.h>
#include <psp2/ctrl.h>
#include <psp2/io/fcntl.h>
#include <psp2/kernel/processmgr.h>
void *memset(void *destination,int value,unsigned n){volatile unsigned char *p=destination;for(unsigned i=0;i<n;i++)p[i]=(unsigned char)value;return destination;}
static unsigned vs[1024],fs[1024];
static unsigned char host[4096] __attribute__((aligned(4096)));
static unsigned char gpu[327680] __attribute__((aligned(4096)));
static const unsigned short faces[6][6]={
 {0,1,2,2,1,3},{4,6,5,5,6,7},{0,4,1,1,4,5},
 {2,3,6,6,3,7},{0,2,4,4,2,6},{1,5,3,3,5,7}};
static const float colors[6][4]={{1,.15f,.15f,1},{.1f,.8f,.25f,1},{.1f,.3f,1,1},
 {1,.8f,.1f,1},{.8f,.15f,.9f,1},{.1f,.85f,.9f,1}};
static const char pass[]="VitaSDK GXM 3D cube 180 frames / 1080 indexed draws PASS\n";
static int save(const char *path,const void *pixels){
 int fd=sceIoOpen(path,SCE_O_WRONLY|SCE_O_CREAT|SCE_O_TRUNC,0600);if(fd<0)return -1;
 int n=sceIoWrite(fd,pixels,320*240*4);sceIoClose(fd);return n==320*240*4?0:-1;
}
static int load(const char *path,void *p){int fd=sceIoOpen(path,SCE_O_RDONLY,0);if(fd<0)return fd;int n=sceIoRead(fd,p,4096);sceIoClose(fd);return n;}
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;int status=1;
 SceGxmContext *context=0;SceGxmShaderPatcher *patcher=0;SceGxmRenderTarget *target=0;
 SceGxmShaderPatcherId vi=0,fi=0;SceGxmVertexProgram *vp=0;SceGxmFragmentProgram *fp=0;
 SceGxmInitializeParams init={0};init.parameterBufferSize=0x40000;
 if(sceGxmInitialize(&init))goto done;
 if(sceGxmMapMemory(gpu,sizeof gpu,SCE_GXM_MEMORY_ATTRIB_RW))goto done;
 SceGxmContextParams cp={0};cp.hostMem=host;cp.hostMemSize=sizeof host;cp.vertexRingBufferMem=gpu+2048;cp.vertexRingBufferMemSize=1024;
 status=2;if(sceGxmCreateContext(&cp,&context))goto done;
 if(load("app0:/scene.vpo",vs)<156||load("app0:/scene.fpo",fs)<156)goto done;
 SceGxmShaderPatcherParams pp={0};status=3;
 if(sceGxmShaderPatcherCreate(&pp,&patcher)||sceGxmShaderPatcherRegisterProgram(patcher,(SceGxmProgram *)vs,&vi)||sceGxmShaderPatcherRegisterProgram(patcher,(SceGxmProgram *)fs,&fi))goto done;
 SceGxmVertexAttribute attr={0};attr.format=SCE_GXM_ATTRIBUTE_FORMAT_F32;attr.componentCount=4;
 const SceGxmProgramParameter *pos=sceGxmProgramFindParameterBySemantic((SceGxmProgram *)vs,SCE_GXM_PARAMETER_SEMANTIC_POSITION,0);
 if(!pos)goto done;attr.regIndex=sceGxmProgramParameterGetResourceIndex(pos);
 SceGxmVertexStream stream={16,SCE_GXM_INDEX_SOURCE_INDEX_16BIT};status=4;
 if(sceGxmShaderPatcherCreateVertexProgram(patcher,vi,&attr,1,&stream,1,&vp)||sceGxmShaderPatcherCreateFragmentProgram(patcher,fi,SCE_GXM_OUTPUT_REGISTER_FORMAT_UCHAR4,SCE_GXM_MULTISAMPLE_NONE,0,(SceGxmProgram *)vs,&fp))goto done;
 SceGxmRenderTargetParams rt={0};rt.width=320;rt.height=240;rt.scenesPerFrame=1;rt.driverMemBlock=-1;
 status=5;if(sceGxmCreateRenderTarget(&rt,&target))goto done;
 SceGxmColorSurface surface;
 if(sceGxmColorSurfaceInit(&surface,SCE_GXM_COLOR_FORMAT_U8U8U8U8_ABGR,SCE_GXM_COLOR_SURFACE_LINEAR,SCE_GXM_COLOR_SURFACE_SCALE_NONE,SCE_GXM_OUTPUT_REGISTER_SIZE_32BIT,320,240,320,gpu+4096))goto done;
 sceGxmSetVertexProgram(context,vp);sceGxmSetFragmentProgram(context,fp);
 status=6;if(sceGxmSetVertexStream(context,0,gpu))goto done;
 const SceGxmProgramParameter *uniform=sceGxmProgramFindParameterByName((SceGxmProgram *)vs,"gvColor");
 if(!uniform)goto done;
 SceDisplayFrameBuf fb={sizeof fb,gpu+4096,320,SCE_DISPLAY_PIXELFORMAT_A8B8G8R8,320,240};
 SceCtrlData pad;status=14;if(sceCtrlSetSamplingMode(SCE_CTRL_MODE_ANALOG)<0)goto done;
 float c=.93969262f,s=.34202014f;
 for(unsigned frame=0;frame<180;frame++){
  status=14;if(sceCtrlPeekBufferPositive(0,&pad,1)!=1)goto done;
  float direction=(pad.buttons&SCE_CTRL_LEFT)?-1.0f:1.0f;
  float depth[8];float *v=(float *)gpu;
  for(unsigned i=0;i<8;i++){
   float x=(i&1)?1.0f:-1.0f,y=(i&2)?1.0f:-1.0f,z=(i&4)?1.0f:-1.0f;
   float rx=x*c+z*s,rz=z*c-x*s;
   float ry=y*.8660254f-rz*.5f,w=y*.5f+rz*.8660254f+5.0f;
   v[i*4]=rx*2.1f;v[i*4+1]=ry*2.8f;v[i*4+2]=w*.5f;v[i*4+3]=w;depth[i]=w;
  }
  unsigned order[6];float distances[6];
  for(unsigned i=0;i<6;i++){order[i]=i;distances[i]=depth[faces[i][0]]+depth[faces[i][1]]+depth[faces[i][2]]+depth[faces[i][5]];}
  for(unsigned i=0;i<5;i++)for(unsigned j=i+1;j<6;j++)if(distances[order[j]]>distances[order[i]]){unsigned tmp=order[i];order[i]=order[j];order[j]=tmp;}
  unsigned *pixels=(unsigned *)(gpu+4096);
  status=17;if(sceGxmTransferFill(0xff18100c,SCE_GXM_TRANSFER_FORMAT_U8U8U8U8_ABGR,pixels,0,0,320,240,320*4,0,0,0))goto done;
  status=7;int begin=sceGxmBeginScene(context,0,target,0,0,0,&surface,0);
  if(begin){status=begin==(int)0x805b0017?77:7;goto done;}
  for(unsigned i=0;i<6;i++){
   unsigned face=order[i];void *buffer=0;
   status=15;if(sceGxmReserveVertexDefaultUniformBuffer(context,&buffer)||sceGxmSetUniformDataF(buffer,uniform,0,4,colors[face]))goto done;
   unsigned short *indices=(unsigned short *)(gpu+256);for(unsigned j=0;j<6;j++)indices[j]=faces[face][j];
   status=8;if(sceGxmDraw(context,SCE_GXM_PRIMITIVE_TRIANGLES,SCE_GXM_INDEX_FORMAT_U16,indices,6))goto done;
  }
  status=9;if(sceGxmEndScene(context,0,0))goto done;
  status=10;if(pixels[0]!=0xff18100c||pixels[120*320+160]==0xff18100c)goto done;
  status=13;if(sceDisplaySetFrameBuf(&fb,SCE_DISPLAY_SETBUF_NEXTFRAME))goto done;
  if(frame==0&&save("savedata0:/cube-first.rgba",pixels)){status=16;goto done;}
  if(frame==179&&save("savedata0:/cube-last.rgba",pixels)){status=16;goto done;}
  float next=c*.999390827f-s*.034899497f*direction;
  s=s*.999390827f+c*.034899497f*direction;c=next;
 }
 status=11;
 if(sceGxmShaderPatcherReleaseVertexProgram(patcher,vp)||sceGxmShaderPatcherReleaseFragmentProgram(patcher,fp)||sceGxmShaderPatcherUnregisterProgram(patcher,vi)||sceGxmShaderPatcherUnregisterProgram(patcher,fi)||sceGxmShaderPatcherDestroy(patcher)||sceGxmDestroyRenderTarget(target)||sceGxmDestroyContext(context)||sceGxmUnmapMemory(gpu)||sceGxmTerminate())goto done;
 status=0;sceIoWrite(1,pass,sizeof(pass)-1);
 done:sceKernelExitProcess(status);return 99;
}
