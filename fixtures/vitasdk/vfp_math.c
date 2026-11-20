/* Check non-fused VMLA rounding and native square root in a real SDK module. */
#include <psp2/kernel/processmgr.h>
#include <psp2/io/fcntl.h>
static const unsigned input[4]={0xbf800000,0x3f800001,0x3f7ffffe,0x40800000};
static unsigned output[2];
static const char success[]="VitaSDK VFP math PASS\n";
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 unsigned fpscr;
 __asm__ volatile(
  "vldmia %1,{s0-s3}\n"
  "vmla.f32 s0,s1,s2\n"
  "vstr s0,[%2]\n"
  "vsqrt.f32 s3,s3\n"
  "vstr s3,[%2,#4]\n"
  "vmrs %0,fpscr\n"
  : "=r"(fpscr) : "r"(input),"r"(output) : "memory","s0","s1","s2","s3");
 int status=output[0]!=0||output[1]!=0x40000000||fpscr!=16;
 if(!status)sceIoWrite(1,success,sizeof(success)-1);
 sceKernelExitProcess(status);return 99;
}
