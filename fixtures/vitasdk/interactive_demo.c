/* Genuine VitaSDK interactive keyboard/controller demo. Press Enter/Start to
   finish successfully; otherwise bounded to 1800 software-vblank frames.
   Cross/Z changes the upper-left quadrant to yellow. This uses a software
   framebuffer and SceDisplay, not GXM/GXP command/shader translation. */
#include <psp2/display.h>
#include <psp2/ctrl.h>
#include <psp2/kernel/processmgr.h>
static unsigned pixels[4]={0xff0000ffu,0xff00ff00u,0xffff0000u,0xffffffffu};
static SceDisplayFrameBuf framebuffer={sizeof(framebuffer),pixels,2,SCE_DISPLAY_PIXELFORMAT_A8B8G8R8,2,2};
static SceCtrlData pad;
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 if(sceCtrlSetSamplingMode(SCE_CTRL_MODE_ANALOG)<0)return 1;
 for(unsigned frame=0;frame<1800;frame++){
  if(sceCtrlPeekBufferPositive(0,&pad,1)!=1)return 2;
  if(pad.buttons==SCE_CTRL_START)break;
  if(pad.buttons==SCE_CTRL_CROSS)pixels[0]=0xff00ffffu;
  else pixels[0]=0xff0000ffu;
  if(sceDisplaySetFrameBuf(&framebuffer,SCE_DISPLAY_SETBUF_NEXTFRAME)<0)return 3;
 }
 sceKernelExitProcess(0);return 99;
}
