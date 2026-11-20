/* Original CPU framebuffer fixture; Metal presentation, no GXM/GXP shaders. */
#include <psp2/display.h>
#include <psp2/kernel/processmgr.h>
static unsigned pixels[4]={0xff0000ffu,0xff00ff00u,0xffff0000u,0xffffffffu};
static SceDisplayFrameBuf fb={sizeof(fb),pixels,2,SCE_DISPLAY_PIXELFORMAT_A8B8G8R8,2,2};
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 if(sceDisplaySetFrameBuf(&fb,SCE_DISPLAY_SETBUF_IMMEDIATE)<0)return 1;
 sceKernelExitProcess(0);return 99;
}
