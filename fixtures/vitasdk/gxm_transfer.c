/* Genuine VitaSDK GXM transfer program. No GXP shader substitute is used.
   GPU fill/copy results are checked before submission to SceDisplay. */
#include <psp2/gxm.h>
#include <psp2/display.h>
#include <psp2/kernel/sysmem.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/io/fcntl.h>
static SceGxmInitializeParams params={0,0,0,0,0x40000};
static void *memory;
static SceDisplayFrameBuf fb;
static const char good[]="VitaSDK GXM transfer pixels PASS\n";
static int test(void){
 if(sceGxmInitialize(&params)<0)return 1;
 SceUID uid=sceKernelAllocMemBlock("GXM transfer",SCE_KERNEL_MEMBLOCK_TYPE_USER_RW,32768,0);
 if(uid<0||sceKernelGetMemBlockBase(uid,&memory)<0)return 2;
 if(sceGxmMapMemory(memory,32768,SCE_GXM_MEMORY_ATTRIB_RW)<0)return 3;
 if(sceGxmTransferFill(0xff0000ff,SCE_GXM_TRANSFER_FORMAT_U8U8U8U8_ABGR,memory,0,0,32,64,256,0,0,0)<0)return 77;
 if(sceGxmTransferFill(0xff00ff00,SCE_GXM_TRANSFER_FORMAT_U8U8U8U8_ABGR,memory,32,0,32,64,256,0,0,0)<0)return 4;
 unsigned *dest=(unsigned *)memory+4096;
 if(sceGxmTransferCopy(64,64,0,0,SCE_GXM_TRANSFER_COLORKEY_NONE,SCE_GXM_TRANSFER_FORMAT_U8U8U8U8_ABGR,SCE_GXM_TRANSFER_LINEAR,memory,0,0,256,
    SCE_GXM_TRANSFER_FORMAT_U8U8U8U8_ABGR,SCE_GXM_TRANSFER_LINEAR,dest,0,0,256,0,0,0)<0)return 5;
 if(sceGxmTransferFinish()<0)return 6;
 if(dest[0]!=0xff0000ff||dest[31]!=0xff0000ff||dest[32]!=0xff00ff00||dest[4095]!=0xff00ff00)return 7;
 fb.size=sizeof(fb);fb.base=dest;fb.pitch=64;fb.pixelformat=SCE_DISPLAY_PIXELFORMAT_A8B8G8R8;fb.width=64;fb.height=64;
 if(sceDisplaySetFrameBuf(&fb,SCE_DISPLAY_SETBUF_IMMEDIATE)<0)return 8;
 for(unsigned i=0;i<60;i++)if(sceDisplayWaitVblankStart()<0)return 9;
 if(sceIoWrite(1,good,sizeof(good)-1)!=(int)sizeof(good)-1)return 10;
 if(sceGxmUnmapMemory(memory)<0||sceKernelFreeMemBlock(uid)<0||sceGxmTerminate()<0)return 11;
 return 0;
}
int module_start(unsigned argc,const void *argp){(void)argc;(void)argp;int status=test();sceKernelExitProcess(status);return 99;}
