/* Lane overflow must wrap within 8/16/64-bit elements, never their neighbors. */
#include <psp2/kernel/processmgr.h>
#include <psp2/io/fcntl.h>
static const unsigned input[8]={~0u,~0u,~0u,~0u,1,1,1,1};
static unsigned output[24];
static const unsigned expected[24]={
 0xffffff00,0xffffff00,0xffffff00,0xffffff00,
 0xfffffffe,0xfffffffe,0xfffffffe,0xfffffffe,
 0xffff0000,0xffff0000,0xffff0000,0xffff0000,
 0xfffffffe,0xfffffffe,0xfffffffe,0xfffffffe,
 0,1,0,1,
 0xfffffffe,0xfffffffe,0xfffffffe,0xfffffffe};
static const char success[]="VitaSDK NEON widths PASS\n";
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 unsigned *target=output;
 __asm__ volatile(
  "vldmia %1,{d2-d5}\n"
  "vadd.i8 q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "vsub.i8 q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "vadd.i16 q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "vsub.i16 q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "vadd.i64 q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "vsub.i64 q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  : "+r"(target) : "r"(input) : "memory","q0","q1","q2");
 int status=0;
 for(unsigned i=0;i<24;i++)if(output[i]!=expected[i])status=1;
 if(!status)sceIoWrite(1,success,sizeof(success)-1);
 sceKernelExitProcess(status);return 99;
}
