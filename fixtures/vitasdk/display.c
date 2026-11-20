/* Original VitaSDK SceDisplay ABI/pacing fixture; no GXM rendering claim. */
#include <psp2/display.h>
#include <psp2/kernel/processmgr.h>
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 union {float value;unsigned bits;} rate={0};int width=0,height=0;
 if(sceDisplayGetRefreshRate(&rate.value)<0||rate.bits!=0x42f00000u)return 1;
 if(sceDisplayGetMaximumFrameBufResolution(&width,&height)<0||width!=960||height!=544)return 2;
 if(sceDisplaySetFrameBuf(0,SCE_DISPLAY_SETBUF_IMMEDIATE)<0)return 3;
 if(sceDisplayWaitVblankStart()<0)return 4;
 sceKernelExitProcess(0);return 99;
}
