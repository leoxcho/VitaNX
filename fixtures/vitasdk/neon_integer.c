/* Genuine VitaSDK SIMD regression; no host-side substitute executes this code. */
#include <psp2/kernel/processmgr.h>
#include <psp2/io/fcntl.h>
static const unsigned input[8]={0xffffffff,0x80000000,0x12345678,0x7fffffff,
                               1,0xffffffff,0xabcdef01,2};
static unsigned output[20];
static const char success[]="VitaSDK NEON integer PASS\n";
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 unsigned *target=output;
 __asm__ volatile(
  "vldmia %1,{d2-d5}\n"
  "vand q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "vorr q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "veor q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "vadd.i32 q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  "vsub.i32 q0,q1,q2\n vstmia %0!,{d0-d1}\n"
  : "+r"(target) : "r"(input) : "memory","q0","q1","q2");
 int status=0;
 for(unsigned i=0;i<4;i++){
  unsigned a=input[i],b=input[i+4];
  if(output[i]!=(a&b)||output[i+4]!=(a|b)||output[i+8]!=(a^b)||
     output[i+12]!=a+b||output[i+16]!=a-b)status=1;
 }
 if(!status)sceIoWrite(1,success,sizeof(success)-1);
 sceKernelExitProcess(status);return 99;
}
