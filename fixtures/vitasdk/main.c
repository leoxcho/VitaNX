/* Genuine VitaSDK application with an explicit, supported module entry.
   No newlib/CRT dependency: loader initializes .data/.bss; only Vita SDK APIs used. */
#include <psp2/types.h>
#include <psp2/io/fcntl.h>
#include <psp2/kernel/processmgr.h>
#include <psp2/kernel/threadmgr.h>
#include <psp2/kernel/clib.h>
#include <psp2common/kernel/iofilemgr.h>
static const char begin[]="VitaSDK module initialized\n";
static const char success[]="VitaSDK native: imports, assets, saves, seek, sync PASS\n";
static const SceUInt32 expected=0x41544956;
static SceUInt32 loaded, saved;
static int check(void) {
 SceUID out=sceKernelGetStdout();
 if(sceIoWrite(out,begin,sizeof(begin)-1)!=(int)sizeof(begin)-1)return 1;
 SceUID fd=sceIoOpen("app0:/data/payload.bin",SCE_O_RDONLY,0);
 if(fd<0)return 2;
 if(sceIoRead(fd,&loaded,sizeof(loaded))!=sizeof(loaded))return 3;
 if(sceIoClose(fd)<0||loaded!=expected)return 4;
 fd=sceIoOpen("savedata0:/vitasdk-save.bin",SCE_O_WRONLY|SCE_O_CREAT|SCE_O_TRUNC,0600);
 if(fd<0)return 5;
 if(sceIoWrite(fd,&loaded,sizeof(loaded))!=sizeof(loaded))return 6;
 if(sceIoSyncByFd(fd,0)<0||sceIoClose(fd)<0)return 7;
 fd=sceIoOpen("savedata0:/vitasdk-save.bin",SCE_O_RDONLY,0);
 if(fd<0)return 8;
 if(sceIoLseek32(fd,0,SCE_SEEK_END)!=4)return 9;
 if(sceIoLseek32(fd,0,SCE_SEEK_SET)!=0)return 10;
 if(sceIoRead(fd,&saved,sizeof(saved))!=sizeof(saved))return 11;
 if(sceIoClose(fd)<0||saved!=expected)return 12;
 if(sceIoWrite(out,success,sizeof(success)-1)!=(int)sizeof(success)-1)return 13;
 return 0;
}
int module_start(SceSize argc,const void *argp) {
 (void)argc;(void)argp;
 int status=check();
 sceKernelExitProcess(status);
 /* Correct native termination must stop dispatch before this unreachable code. */
 return 99;
}
