/* Original genuine VitaSDK memory/semaphore ABI regression. No guest threads. */
#include <psp2/kernel/sysmem.h>
#include <psp2/kernel/threadmgr.h>
#include <psp2/kernel/processmgr.h>
static unsigned *storage;
static unsigned timeout;
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 SceUID block=sceKernelAllocMemBlock("native heap",SCE_KERNEL_MEMBLOCK_TYPE_USER_RW,4096,0);
 if(block<0)return 1;
 if(sceKernelGetMemBlockBase(block,(void**)&storage)<0)return 2;
 *storage=0x56495441u;
 if(*storage!=0x56495441u)return 3;
 if(sceKernelFindMemBlockByAddr(storage,4)!=block)return 4;
 SceUID semaphore=sceKernelCreateSema("native semaphore",0,1,2,0);
 if(semaphore<0)return 5;
 if(sceKernelPollSema(semaphore,1)<0)return 6;
 if(sceKernelWaitSema(semaphore,1,&timeout)!=(int)0x80028005u)return 11;
 if(sceKernelSignalSema(semaphore,1)<0)return 7;
 if(sceKernelWaitSema(semaphore,1,0)<0)return 8;
 if(sceKernelDeleteSema(semaphore)<0)return 9;
 if(sceKernelFreeMemBlock(block)<0)return 10;
 if(sceKernelGetMemBlockBase(block,(void**)&storage)>=0)return 12;
 block=sceKernelAllocMemBlock("reuse",SCE_KERNEL_MEMBLOCK_TYPE_USER_RW,4096,0);
 if(block<0)return 13;
 if(sceKernelGetMemBlockBase(block,(void**)&storage)<0)return 14;
 if(*storage)return 15;
 if(sceKernelFreeMemBlock(block)<0)return 16;
 sceKernelExitProcess(0);return 99;
}
