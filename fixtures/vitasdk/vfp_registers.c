/* Genuine SDK ABI regression: raw S/D aliasing and callee-save stack moves. */
#include <psp2/kernel/processmgr.h>
#include <psp2/io/fcntl.h>
static const unsigned input[4]={0x7f800001,0x80000000,0x12345678,0xffffffff};
static unsigned output[6];
static const char success[]="VitaSDK VFP registers PASS\n";
int module_start(unsigned argc,const void *argp){
 (void)argc;(void)argp;
 __asm__ volatile(
  "vpush {d8-d15}\n"
  "vldmia %0,{s16-s19}\n"
  "vpush {s16-s19}\n"
  "vmov.f32 s16,#1.0\n"
  "vpop {s16-s19}\n"
  "vstmia %1,{d8-d9}\n"
  "vpop {d8-d15}\n"
  : : "r"(input),"r"(output) : "memory");
 unsigned low,high;
 __asm__ volatile(
  "vmov d31,%2,%3\n"
  "vstr d31,[%4,#16]\n"
  "vldr d30,[%4,#16]\n"
  "vmov %0,%1,d30\n"
  : "=r"(low),"=r"(high) : "r"(input[0]),"r"(input[2]),"r"(output)
  : "memory","d30","d31");
 int status=output[0]!=input[0]||output[1]!=input[1]||
            output[2]!=input[2]||output[3]!=input[3]||low!=input[0]||high!=input[2];
 if(!status)sceIoWrite(1,success,sizeof(success)-1);
 sceKernelExitProcess(status);return 99;
}
